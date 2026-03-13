"""Verify which MCP tools Codex can discover from MassGen custom-tool wiring."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from massgen.backend.codex import CodexBackend
from massgen.mcp_tools.custom_tools_server import (
    BACKGROUND_TOOL_CANCEL_NAME,
    BACKGROUND_TOOL_LIST_NAME,
    BACKGROUND_TOOL_RESULT_NAME,
    BACKGROUND_TOOL_START_NAME,
    BACKGROUND_TOOL_STATUS_NAME,
    BACKGROUND_TOOL_WAIT_NAME,
    create_server,
)


@pytest.fixture(autouse=True)
def _mock_codex_cli(monkeypatch):
    """Avoid requiring a real Codex CLI install in tests."""
    monkeypatch.setattr(CodexBackend, "_find_codex_cli", lambda self: "/usr/bin/codex")
    monkeypatch.setattr(CodexBackend, "_has_cached_credentials", lambda self: True)


@pytest.mark.asyncio
async def test_codex_custom_tools_mcp_exposes_multimodal_and_background_tools(
    tmp_path: Path,
    monkeypatch,
):
    """Codex custom-tools MCP must expose media tools plus lifecycle management tools."""
    backend = CodexBackend(
        cwd=str(tmp_path),
        enable_multimodal_tools=True,
    )
    backend._write_workspace_config()

    specs_path = tmp_path / ".codex" / "custom_tool_specs.json"
    assert specs_path.exists()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "custom_tools_server",
            "--tool-specs",
            str(specs_path),
            "--agent-id",
            "codex",
            "--allowed-paths",
            str(tmp_path),
        ],
    )

    mcp = await create_server()
    available_tools = {tool.name for tool in mcp._tool_manager._tools.values()}

    expected_tools = {
        "custom_tool__read_media",
        "custom_tool__generate_media",
        BACKGROUND_TOOL_START_NAME,
        BACKGROUND_TOOL_STATUS_NAME,
        BACKGROUND_TOOL_RESULT_NAME,
        BACKGROUND_TOOL_CANCEL_NAME,
        BACKGROUND_TOOL_LIST_NAME,
        BACKGROUND_TOOL_WAIT_NAME,
    }
    missing_tools = expected_tools - available_tools
    assert not missing_tools, f"Missing expected MCP tools: {sorted(missing_tools)}. " f"Available: {sorted(available_tools)}"
    assert "custom_tool__list_available_tools" not in available_tools


def test_codex_custom_tools_mcp_config_includes_wait_interrupt_file(tmp_path: Path):
    """Codex custom-tools MCP server config should pass wait interrupt file path."""
    backend = CodexBackend(cwd=str(tmp_path))
    backend._write_workspace_config()

    server_cfg = next(server for server in backend.mcp_servers if isinstance(server, dict) and server.get("name") == "massgen_custom_tools")
    args = server_cfg.get("args", [])

    assert "--wait-interrupt-file" in args
    index = args.index("--wait-interrupt-file")
    assert args[index + 1] == str(tmp_path / ".codex" / "background_wait_interrupt.json")


def test_codex_custom_tools_mcp_env_sets_claude_config_dir_for_docker_mount(tmp_path: Path):
    """Docker-mode Codex should expose CLAUDE_CONFIG_DIR when claude_config is mounted."""
    backend = CodexBackend(
        cwd=str(tmp_path),
        command_line_execution_mode="docker",
        command_line_docker_credentials={"mount": ["claude_config"]},
    )

    env = backend._build_custom_tools_mcp_env()

    assert env["CLAUDE_CONFIG_DIR"] == "/home/massgen/.claude"


@pytest.mark.asyncio
async def test_codex_background_mcp_client_uses_orchestrator_servers(
    tmp_path: Path,
    monkeypatch,
):
    """Codex should expose a host-side MCP client for orchestrator-managed subagent calls."""
    from massgen.backend import codex as codex_mod

    backend = CodexBackend(
        cwd=str(tmp_path),
        agent_id="agent_a",
    )
    backend.config["type"] = "codex"
    backend.config["mcp_servers"] = {
        "subagent_agent_a": {
            "type": "stdio",
            "command": "fastmcp",
            "args": ["run", "dummy"],
            "tool_timeout_sec": 2040,
        },
        "massgen_custom_tools": {
            "type": "stdio",
            "command": "fastmcp",
            "args": ["run", "ignored"],
        },
    }

    fake_client = object()
    setup_calls: list[dict] = []

    async def fake_setup_mcp_client(**kwargs):
        setup_calls.append(kwargs)
        return fake_client

    monkeypatch.setattr(
        codex_mod,
        "MCPResourceManager",
        SimpleNamespace(setup_mcp_client=fake_setup_mcp_client),
        raising=False,
    )

    client = await backend._get_background_mcp_client()

    assert client is fake_client
    assert len(setup_calls) == 1
    assert [server["name"] for server in setup_calls[0]["servers"]] == ["subagent_agent_a"]
    assert setup_calls[0]["timeout_seconds"] == 2100
    assert setup_calls[0]["backend_name"] == "codex"
    assert setup_calls[0]["agent_id"] == "agent_a"

    cached_client = await backend._get_background_mcp_client()

    assert cached_client is fake_client
    assert len(setup_calls) == 1


@pytest.mark.asyncio
async def test_codex_background_mcp_client_rewrites_delegated_subagent_runtime_mode_for_host(
    tmp_path: Path,
    monkeypatch,
):
    """Host-side background MCP clients must not keep delegated subagent runtime mode."""
    from massgen.backend import codex as codex_mod

    backend = CodexBackend(
        cwd=str(tmp_path),
        agent_id="agent_a",
    )
    backend.config["type"] = "codex"
    backend.config["mcp_servers"] = {
        "subagent_agent_a": {
            "type": "stdio",
            "command": "fastmcp",
            "args": [
                "run",
                "dummy",
                "--",
                "--runtime-mode",
                "delegated",
                "--runtime-fallback-mode",
                "",
                "--delegation-directory",
                str(tmp_path / "delegation"),
            ],
            "tool_timeout_sec": 2040,
        },
    }

    fake_client = object()
    setup_calls: list[dict] = []

    async def fake_setup_mcp_client(**kwargs):
        setup_calls.append(kwargs)
        return fake_client

    monkeypatch.setattr(
        codex_mod,
        "MCPResourceManager",
        SimpleNamespace(setup_mcp_client=fake_setup_mcp_client),
        raising=False,
    )

    client = await backend._get_background_mcp_client()

    assert client is fake_client
    assert len(setup_calls) == 1

    server = setup_calls[0]["servers"][0]
    args = server["args"]
    runtime_mode_index = args.index("--runtime-mode")
    assert args[runtime_mode_index + 1] == "isolated"

    original_args = backend.config["mcp_servers"]["subagent_agent_a"]["args"]
    original_runtime_mode_index = original_args.index("--runtime-mode")
    assert original_args[original_runtime_mode_index + 1] == "delegated"


class TestCodexMcpEnvFileMultiLocation:
    """Env file resolution should search multiple locations like DockerManager."""

    @pytest.fixture()
    def _fake_home(self, tmp_path, monkeypatch):
        """Set up a fake home with ~/.massgen/.env containing a home key."""
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        massgen_dir = fake_home / ".massgen"
        massgen_dir.mkdir()
        (massgen_dir / ".env").write_text("OPENAI_API_KEY=sk-from-home\n")
        monkeypatch.setattr(
            "massgen.backend.codex.Path.home",
            staticmethod(lambda: fake_home),
        )
        return fake_home

    def test_finds_home_env_when_local_missing(self, tmp_path, monkeypatch, _fake_home):
        """When CWD has no .env, fall back to ~/.massgen/.env."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.chdir(workspace)

        backend = CodexBackend(
            cwd=str(workspace),
            command_line_docker_credentials={
                "env_file": ".env",
                "env_vars_from_file": ["OPENAI_API_KEY"],
            },
        )

        env = backend._build_custom_tools_mcp_env()
        assert env.get("OPENAI_API_KEY") == "sk-from-home"

    def test_provided_path_overrides_home(self, tmp_path, monkeypatch, _fake_home):
        """An absolute env_file path should take priority over ~/.massgen/.env."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".env").write_text("OPENAI_API_KEY=sk-from-project\n")

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.chdir(workspace)

        backend = CodexBackend(
            cwd=str(workspace),
            command_line_docker_credentials={
                "env_file": str(project_root / ".env"),
                "env_vars_from_file": ["OPENAI_API_KEY"],
            },
        )

        env = backend._build_custom_tools_mcp_env()
        assert env.get("OPENAI_API_KEY") == "sk-from-project"

    def test_no_env_file_anywhere_logs_warning(self, tmp_path, monkeypatch, caplog):
        """Should warn when no .env found in any candidate location."""
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        (fake_home / ".massgen").mkdir()
        # No .env anywhere under fake_home
        monkeypatch.setattr(
            "massgen.backend.codex.Path.home",
            staticmethod(lambda: fake_home),
        )

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.chdir(workspace)

        backend = CodexBackend(
            cwd=str(workspace),
            command_line_docker_credentials={
                "env_file": ".env",
                "env_vars_from_file": ["OPENAI_API_KEY"],
            },
        )

        env = backend._build_custom_tools_mcp_env()

        assert "OPENAI_API_KEY" not in env

    def test_strips_surrounding_quotes_from_env_values(self, tmp_path, monkeypatch):
        """Quoted values in .env should have quotes stripped (like DockerManager)."""
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        massgen_dir = fake_home / ".massgen"
        massgen_dir.mkdir()
        (massgen_dir / ".env").write_text(
            'OPENAI_API_KEY="sk-proj-quoted"\n' "GEMINI_API_KEY='AIza-single-quoted'\n" "XAI_API_KEY=no-quotes\n",
        )
        monkeypatch.setattr(
            "massgen.backend.codex.Path.home",
            staticmethod(lambda: fake_home),
        )

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.chdir(workspace)

        backend = CodexBackend(
            cwd=str(workspace),
            command_line_docker_credentials={
                "env_file": ".env",
                "env_vars_from_file": ["OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"],
            },
        )

        env = backend._build_custom_tools_mcp_env()
        assert env["OPENAI_API_KEY"] == "sk-proj-quoted"
        assert env["GEMINI_API_KEY"] == "AIza-single-quoted"
        assert env["XAI_API_KEY"] == "no-quotes"


class TestCodexParseItemMcpNoStreamChunkDuplication:
    """Verify _parse_item emits events but NOT mcp_status StreamChunks for MCP tool calls.

    The event emitter (emit_tool_start/emit_tool_complete) is the canonical path
    for TUI rendering. Returning mcp_status StreamChunks too causes the TUI to
    display each tool call twice — once from events, once from stream chunks.
    """

    @pytest.fixture()
    def backend(self, tmp_path):
        return CodexBackend(cwd=str(tmp_path))

    def test_mcp_tool_started_returns_no_stream_chunks(self, backend):
        """item.started for MCP tool must NOT return mcp_status StreamChunks."""
        item = {
            "id": "item_42",
            "type": "mcp_tool_call",
            "server": "massgen_custom_tools",
            "tool": "custom_tool__generate_media",
            "arguments": {"mode": "image", "prompt": "a goat"},
            "status": "in_progress",
        }
        chunks = backend._parse_item("mcp_tool_call", item, is_completed=False)
        mcp_chunks = [c for c in chunks if c.type == "mcp_status"]
        assert mcp_chunks == [], f"Expected no mcp_status StreamChunks for tool start, got {len(mcp_chunks)}"

    def test_mcp_tool_completed_returns_no_stream_chunks(self, backend):
        """item.completed for MCP tool must NOT return mcp_status StreamChunks."""
        # Seed the start time so elapsed calculation works
        backend._tool_start_times["item_42"] = 1000.0
        backend._tool_id_to_name["item_42"] = "massgen_custom_tools/custom_tool__generate_media"
        item = {
            "id": "item_42",
            "type": "mcp_tool_call",
            "server": "massgen_custom_tools",
            "tool": "custom_tool__generate_media",
            "arguments": {"mode": "image", "prompt": "a goat"},
            "result": '{"success": true}',
        }
        chunks = backend._parse_item("mcp_tool_call", item, is_completed=True)
        mcp_chunks = [c for c in chunks if c.type == "mcp_status"]
        assert mcp_chunks == [], f"Expected no mcp_status StreamChunks for tool complete, got {len(mcp_chunks)}"

    def test_mcp_tool_started_emits_tool_start_event(self, backend, monkeypatch):
        """item.started must still fire emit_tool_start via the event emitter."""
        from massgen.backend import codex as codex_mod

        calls = []

        class FakeEmitter:
            def emit_tool_start(self, **kwargs):
                calls.append(("tool_start", kwargs))

        monkeypatch.setattr(codex_mod, "get_event_emitter", lambda: FakeEmitter())

        item = {
            "id": "item_99",
            "type": "mcp_tool_call",
            "server": "massgen_custom_tools",
            "tool": "custom_tool__read_media",
            "arguments": {"file_path": "/tmp/img.png"},
            "status": "in_progress",
        }
        backend._parse_item("mcp_tool_call", item, is_completed=False)
        assert len(calls) == 1, f"Expected 1 emit_tool_start call, got {len(calls)}"
        assert calls[0][1]["tool_name"] == "massgen_custom_tools/custom_tool__read_media"

    def test_mcp_tool_completed_emits_tool_complete_event(self, backend, monkeypatch):
        """item.completed must still fire emit_tool_complete via the event emitter."""
        from massgen.backend import codex as codex_mod

        calls = []

        class FakeEmitter:
            def emit_tool_complete(self, **kwargs):
                calls.append(("tool_complete", kwargs))

        monkeypatch.setattr(codex_mod, "get_event_emitter", lambda: FakeEmitter())
        backend._tool_start_times["item_99"] = 1000.0
        backend._tool_id_to_name["item_99"] = "massgen_custom_tools/custom_tool__read_media"

        item = {
            "id": "item_99",
            "type": "mcp_tool_call",
            "server": "massgen_custom_tools",
            "tool": "custom_tool__read_media",
            "result": '{"success": true}',
        }
        backend._parse_item("mcp_tool_call", item, is_completed=True)
        assert len(calls) == 1, f"Expected 1 emit_tool_complete call, got {len(calls)}"
        assert calls[0][1]["tool_name"] == "massgen_custom_tools/custom_tool__read_media"

    @pytest.mark.asyncio
    async def test_wait_start_signals_interrupt_when_runtime_payload_available(self, backend, monkeypatch):
        """If runtime input was queued before wait became active, wait start should still signal interrupt."""
        captured_payloads = []
        monkeypatch.setattr(
            backend,
            "notify_background_wait_interrupt",
            lambda payload: captured_payloads.append(payload) or True,
        )
        backend.set_background_wait_interrupt_provider(
            lambda _agent_id: {
                "interrupt_reason": "runtime_injection_available",
                "injected_content": "[Human Input]: and bob dylan",
            },
        )

        item = {
            "id": "item_wait",
            "type": "mcp_tool_call",
            "server": "massgen_custom_tools",
            "tool": "custom_tool__wait_for_background_tool",
            "arguments": {"timeout_seconds": "120"},
            "status": "in_progress",
        }
        backend._parse_item("mcp_tool_call", item, is_completed=False)
        await asyncio.sleep(0)

        assert backend.is_background_wait_active() is True
        assert captured_payloads
        assert captured_payloads[0]["interrupt_reason"] == "runtime_injection_available"
        assert "bob dylan" in str(captured_payloads[0]["injected_content"])

    @pytest.mark.asyncio
    async def test_wait_start_skips_interrupt_signal_when_provider_has_no_payload(self, backend, monkeypatch):
        """No interrupt signal should be emitted when provider returns None."""
        notify_calls = {"count": 0}
        monkeypatch.setattr(
            backend,
            "notify_background_wait_interrupt",
            lambda payload: notify_calls.__setitem__("count", notify_calls["count"] + 1) or True,
        )
        backend.set_background_wait_interrupt_provider(lambda _agent_id: None)

        item = {
            "id": "item_wait_none",
            "type": "mcp_tool_call",
            "server": "massgen_custom_tools",
            "tool": "custom_tool__wait_for_background_tool",
            "arguments": {"timeout_seconds": "120"},
            "status": "in_progress",
        }
        backend._parse_item("mcp_tool_call", item, is_completed=False)
        await asyncio.sleep(0)

        assert backend.is_background_wait_active() is True
        assert notify_calls["count"] == 0
