"""Integration test: validate that _direct_spawn_subagents generates configs
that pass CLI context-path validation.

This test exercises the REAL workspace/path logic (no mocking of paths or
SubagentManager config generation) — only the actual subprocess execution
is skipped.  It catches exactly the class of bug where unit tests pass but
the subprocess dies with "Configuration error: Context paths not found".
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_orchestrator(*, enable_trace_analyzer: bool = False):
    """Build a real Orchestrator wired to the test_trace_analyzer_side_by_side
    config shape, but using mock backends so no API calls are made."""
    from massgen.agent_config import AgentConfig, CoordinationConfig
    from massgen.chat_agent import SingleAgent
    from massgen.orchestrator import Orchestrator
    from massgen.tests.conftest import MockLLMBackend

    coord = CoordinationConfig(
        orchestrator_managed_round_evaluator=True,
        enable_execution_trace_analyzer=enable_trace_analyzer,
        enable_subagents=True,
        subagent_types=["round_evaluator", "execution_trace_analyzer"],
        round_evaluator_before_checklist=True,
        round_evaluator_refine=False,
        round_evaluator_transformation_pressure="balanced",
        subagent_orchestrator={
            "enabled": True,
            "agents": [
                {"id": "eval_codex", "backend": {"type": "codex", "model": "gpt-5.4"}},
                {"id": "eval_claude", "backend": {"type": "claude_code", "model": "claude-sonnet-4-6"}},
            ],
        },
    )
    config = AgentConfig(
        coordination_config=coord,
        voting_sensitivity="checklist_gated",
    )

    backend = MockLLMBackend(responses=["mock answer"])
    agent = SingleAgent(backend=backend, agent_id="agent_a", system_message="test")
    agents = {"agent_a": agent}

    orch = Orchestrator(agents=agents, config=config)
    return orch


# ---------------------------------------------------------------------------
# The actual test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_spawn_generates_valid_subprocess_configs(tmp_path, monkeypatch):
    """_direct_spawn_subagents must produce subagent YAML configs whose
    context_paths all exist on disk — otherwise the subprocess CLI rejects
    them immediately with 'Configuration error: Context paths not found'.

    This test intercepts at create_subprocess_exec (the lowest possible point)
    so ALL real config generation, path resolution, and file writing runs.
    """
    from massgen.cli import validate_context_paths

    orch = _build_orchestrator(enable_trace_analyzer=True)

    # The mock backend has no filesystem_manager, so direct spawn uses
    # the fallback path under .massgen/workspaces/direct_spawn_*.

    # Intercept subprocess launch — let all config generation run, but
    # don't actually start processes.
    launched_commands: list[list[str]] = []

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        """Record the command and return a fake process that exits immediately."""
        launched_commands.append(list(cmd))
        kwargs.get("cwd", ".")

        # Write a fake answer file so SubagentManager thinks it succeeded.
        answer_file = None
        for i, c in enumerate(cmd):
            if c == "--output-file" and i + 1 < len(cmd):
                answer_file = cmd[i + 1]
                break
        if answer_file:
            Path(answer_file).write_text("fake subagent answer", encoding="utf-8")

        proc = MagicMock()
        proc.returncode = 0
        proc.pid = 12345

        async def fake_communicate():
            return (b"", b"")

        proc.communicate = fake_communicate

        async def fake_wait():
            return 0

        proc.wait = fake_wait
        return proc

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    # Build tasks the same way _run_round_evaluator_pre_round_if_needed does.
    parent_agent_id = "agent_a"
    answers = {parent_agent_id: "def is_prime(n): ..."}

    spawn_task = orch._build_round_evaluator_task(parent_agent_id, answers)
    spawn_context_paths = orch._get_round_evaluator_context_paths(parent_agent_id)

    task_payload = {
        "subagent_id": "round_eval_r2",
        "task": spawn_task,
        "subagent_type": "round_evaluator",
        "context_paths": spawn_context_paths,
    }
    trace_task_payload = {
        "subagent_id": "trace_analyzer_r2",
        "task": "Analyze execution trace for round 2.",
        "subagent_type": "execution_trace_analyzer",
        "context_paths": spawn_context_paths,
    }

    combined_tasks = [task_payload, trace_task_payload]

    # Run the direct spawn (subprocess is intercepted above).
    # The spawn may report failure because we fake the subprocess, but
    # we only care about validating the generated configs.
    try:
        await orch._direct_spawn_subagents(
            parent_agent_id=parent_agent_id,
            tasks=combined_tasks,
            refine=False,
        )
    except Exception:
        pass  # Config generation is what we're testing, not execution.

    # Find all generated subagent config files.
    # Fallback workspaces go under .massgen/workspaces/direct_spawn_*
    # Only search direct_spawn_* dirs to avoid picking up stale configs from previous runs.
    workspaces_base = Path(".massgen") / "workspaces"
    generated_configs = []
    for spawn_dir in workspaces_base.glob("direct_spawn_*/"):
        generated_configs.extend(spawn_dir.rglob("subagent_config_*.yaml"))

    assert len(generated_configs) >= 2, f"Expected at least 2 subagent configs, got {len(generated_configs)}: " f"{[str(p) for p in generated_configs]}"

    # --- Validate every generated config ---
    for config_path in generated_configs:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        # 1. The CLI validation must not raise.
        try:
            validate_context_paths(raw)
        except Exception as exc:
            pytest.fail(
                f"Config {config_path.name} failed CLI context-path validation: {exc}\n" f"Full config:\n{yaml.dump(raw, default_flow_style=False)}",
            )

        # 2. Every context_path entry must point to an existing path.
        orch_cfg = raw.get("orchestrator", {})
        for ctx in orch_cfg.get("context_paths", []):
            p = ctx.get("path") if isinstance(ctx, dict) else ctx
            assert Path(p).exists(), f"Context path does not exist: {p}\n" f"Config: {config_path.name}\n" f"Full config:\n{yaml.dump(raw, default_flow_style=False)}"

        # 3. Agent CWD directories must exist.
        for agent_cfg in raw.get("agents", []):
            cwd = agent_cfg.get("backend", {}).get("cwd")
            if cwd:
                assert Path(cwd).exists(), f"Agent CWD does not exist: {cwd}\n" f"Config: {config_path.name}"

    # 4. Configs were generated (the important part).
    # Spawn result may fail because we fake the subprocess — that's OK.

    # Clean up the direct_spawn_* workspace directories we created.
    import shutil

    for cfg_path in generated_configs:
        # Walk up to the direct_spawn_agent_a_XXXX directory
        spawn_dir = cfg_path
        while spawn_dir.parent != workspaces_base and spawn_dir != spawn_dir.parent:
            spawn_dir = spawn_dir.parent
        if spawn_dir.exists():
            shutil.rmtree(spawn_dir, ignore_errors=True)
