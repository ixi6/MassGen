"""Tests for Codex reasoning effort config mapping."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib

from massgen import logger_config
from massgen.agent_config import AgentConfig
from massgen.backend.codex import CodexBackend
from massgen.orchestrator import Orchestrator


@pytest.fixture(autouse=True)
def _mock_codex_cli(monkeypatch):
    """Avoid requiring a real Codex CLI install in tests."""
    monkeypatch.setattr(CodexBackend, "_find_codex_cli", lambda self: "/usr/bin/codex")
    monkeypatch.setattr(CodexBackend, "_has_cached_credentials", lambda self: True)


def _read_workspace_codex_config(workspace: Path) -> dict:
    config_path = workspace / ".codex" / "config.toml"
    return tomllib.loads(config_path.read_text())


def test_codex_accepts_openai_style_reasoning_effort(tmp_path: Path):
    backend = CodexBackend(
        cwd=str(tmp_path),
        reasoning={"effort": "high", "summary": "auto"},
    )
    backend._write_workspace_config()

    config = _read_workspace_codex_config(tmp_path)
    assert config["model_reasoning_effort"] == "high"


def test_codex_model_reasoning_effort_takes_precedence(tmp_path: Path):
    backend = CodexBackend(
        cwd=str(tmp_path),
        model_reasoning_effort="xhigh",
        reasoning={"effort": "low", "summary": "auto"},
    )
    backend._write_workspace_config()

    config = _read_workspace_codex_config(tmp_path)
    assert config["model_reasoning_effort"] == "xhigh"


def test_codex_skips_reasoning_effort_when_not_provided(tmp_path: Path):
    backend = CodexBackend(
        cwd=str(tmp_path),
        reasoning={"summary": "auto"},
    )
    backend._write_workspace_config()

    config = _read_workspace_codex_config(tmp_path)
    assert "model_reasoning_effort" not in config


def test_codex_disables_view_image_tool_in_workspace_config(tmp_path: Path):
    backend = CodexBackend(cwd=str(tmp_path))
    backend._write_workspace_config()

    config = _read_workspace_codex_config(tmp_path)
    assert config["tools"]["view_image"] is False


def test_codex_writes_instructions_file_under_codex_home(tmp_path: Path):
    backend = CodexBackend(cwd=str(tmp_path))
    backend.system_prompt = "system instructions"
    backend._write_workspace_config()

    config = _read_workspace_codex_config(tmp_path)
    instructions_path = tmp_path / ".codex" / "AGENTS.md"
    assert config["model_instructions_file"] == str(instructions_path)
    content = instructions_path.read_text()
    assert content.startswith("system instructions")
    assert "[Human Input]:" in content
    assert not (tmp_path / "AGENTS.md").exists()


def test_codex_appends_runtime_input_priority_guidance(tmp_path: Path):
    backend = CodexBackend(cwd=str(tmp_path))
    backend.system_prompt = "system instructions"
    backend._write_workspace_config()

    instructions_path = tmp_path / ".codex" / "AGENTS.md"
    content = instructions_path.read_text()
    assert "system instructions" in content
    assert "[Human Input]:" in content
    assert "high-priority runtime instruction" in content


def test_codex_mirrors_local_skills_into_codex_home(tmp_path: Path):
    backend = CodexBackend(cwd=str(tmp_path))

    project_skills = tmp_path / ".agent" / "skills"
    project_skill = project_skills / "demo-skill"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text("# Demo Skill\n")

    backend.filesystem_manager = SimpleNamespace(
        local_skills_directory=project_skills,
        docker_manager=None,
        get_current_workspace=lambda: tmp_path,
    )
    assert backend._resolve_codex_skills_source() == project_skills
    backend._sync_skills_into_codex_home(tmp_path / ".codex")

    mirrored_skill = tmp_path / ".codex" / "skills" / "demo-skill" / "SKILL.md"
    assert mirrored_skill.exists()
    assert mirrored_skill.read_text() == "# Demo Skill\n"


def test_codex_always_registers_massgen_custom_tools_server(tmp_path: Path):
    """Codex should expose the MassGen custom tools server even without user tools."""
    backend = CodexBackend(cwd=str(tmp_path))
    server_names = [s.get("name") for s in backend.mcp_servers if isinstance(s, dict)]
    assert "massgen_custom_tools" in server_names


def test_codex_writes_background_mcp_targets_into_custom_tool_specs(tmp_path: Path):
    """Specs should include MCP targets that background manager may execute."""
    backend = CodexBackend(
        cwd=str(tmp_path),
        mcp_servers=[
            {
                "name": "command_line",
                "type": "stdio",
                "command": "fastmcp",
                "args": ["run", "massgen/filesystem_manager/_code_execution_server.py:create_server"],
            },
        ],
    )
    backend._write_workspace_config()

    specs_path = tmp_path / ".codex" / "custom_tool_specs.json"
    specs = json.loads(specs_path.read_text())

    background_names = {server["name"] for server in specs.get("background_mcp_servers", []) if isinstance(server, dict) and "name" in server}
    assert "command_line" in background_names
    assert "massgen_custom_tools" not in background_names


def test_codex_writes_execution_trace_markdown(tmp_path: Path):
    backend = CodexBackend(
        cwd=str(tmp_path),
        agent_id="agent_a",
    )

    backend._clear_streaming_buffer(agent_id="agent_a")

    backend._parse_item(
        "reasoning",
        {
            "id": "reason_1",
            "text": "Need to inspect the workspace first.",
        },
        is_completed=True,
    )
    backend._parse_item(
        "agent_message",
        {
            "id": "msg_1",
            "text": "I found the root cause and prepared a fix.",
        },
        is_completed=True,
    )
    backend._parse_item(
        "mcp_tool_call",
        {
            "id": "tool_1",
            "server": "massgen_custom_tools",
            "tool": "custom_tool__read_media",
            "arguments": {"file_path": "artifact.png"},
        },
        is_completed=False,
    )
    backend._parse_item(
        "mcp_tool_call",
        {
            "id": "tool_1",
            "server": "massgen_custom_tools",
            "tool": "custom_tool__read_media",
            "result": "read ok",
        },
        is_completed=True,
    )

    snapshot_dir = tmp_path / "trace_snapshot"
    trace_path = backend._save_execution_trace(snapshot_dir)

    assert trace_path == snapshot_dir / "execution_trace.md"
    assert trace_path is not None
    trace_text = trace_path.read_text()
    assert "# Execution Trace: agent_a" in trace_text
    assert "### Reasoning" in trace_text
    assert "Need to inspect the workspace first." in trace_text
    assert "### Content" in trace_text
    assert "I found the root cause and prepared a fix." in trace_text
    assert "### Tool Call: massgen_custom_tools/custom_tool__read_media" in trace_text
    assert "### Tool Result: massgen_custom_tools/custom_tool__read_media" in trace_text


def test_codex_turn_completed_usage_preserves_cached_input_tokens(tmp_path: Path):
    backend = CodexBackend(cwd=str(tmp_path))

    chunks = backend._parse_codex_event(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 200,
                "total_tokens": 1200,
                "cached_input_tokens": 800,
            },
        },
    )

    assert len(chunks) == 1
    assert chunks[0].type == "done"
    assert chunks[0].usage == {
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "total_tokens": 1200,
        "cached_input_tokens": 800,
    }


def test_codex_usage_chain_tracks_cached_input_tokens(tmp_path: Path):
    backend = CodexBackend(cwd=str(tmp_path))

    chunks = backend._parse_codex_event(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 200,
                "total_tokens": 1200,
                "cached_input_tokens": 800,
            },
        },
    )
    done_chunk = chunks[0]
    backend._update_token_usage_from_api_response(done_chunk.usage, backend.model)

    assert backend.token_usage.input_tokens == 1000
    assert backend.token_usage.output_tokens == 200
    assert backend.token_usage.cached_input_tokens == 800


@pytest.mark.asyncio
async def test_codex_execution_trace_saved_via_orchestrator_snapshot(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(logger_config, "_LOG_BASE_SESSION_DIR", None)
    monkeypatch.setattr(logger_config, "_LOG_SESSION_DIR", None)
    monkeypatch.setattr(logger_config, "_CURRENT_TURN", None)
    monkeypatch.setattr(logger_config, "_CURRENT_ATTEMPT", None)
    logger_config.set_log_base_session_dir_absolute(tmp_path / "logs")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    temp_parent = tmp_path / "temp_workspaces"
    temp_parent.mkdir()
    snapshot_storage = tmp_path / "snapshots"

    backend = CodexBackend(
        cwd=str(workspace),
        agent_id="agent_a",
        agent_temporary_workspace=str(temp_parent),
    )
    backend._clear_streaming_buffer(agent_id="agent_a")
    backend._parse_item(
        "agent_message",
        {"id": "msg_1", "text": "Snapshot trace content"},
        is_completed=True,
    )

    agent = SimpleNamespace(agent_id="agent_a", backend=backend)
    orchestrator = Orchestrator(
        agents={"agent_a": agent},
        config=AgentConfig(),
        snapshot_storage=str(snapshot_storage),
        agent_temporary_workspace=str(temp_parent),
    )

    await orchestrator._save_agent_snapshot(
        "agent_a",
        answer_content="answer",
        context_data=None,
        is_final=False,
    )

    trace_path = backend.filesystem_manager.snapshot_storage / "execution_trace.md"
    assert trace_path.exists()
    assert "Snapshot trace content" in trace_path.read_text()
