"""
Tests for Gemini CLI backend.

Run with: uv run pytest massgen/tests/test_gemini_cli_backend.py -v
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from massgen.backend.gemini_cli import (
    GEMINI_CLI_DEFAULT_MODEL,
    GEMINI_FAIL_FAST_QUOTA_RETRY_THRESHOLD,
    GEMINI_WORKFLOW_MAX_SESSION_TURNS,
    GeminiCLIBackend,
)


@pytest.fixture
def backend(tmp_path):
    """Create GeminiCLIBackend with tmp_path as cwd to avoid FilesystemManager touching project root."""
    with patch.object(GeminiCLIBackend, "_find_gemini_cli", return_value="/usr/bin/gemini"):
        return GeminiCLIBackend(
            model=GEMINI_CLI_DEFAULT_MODEL,
            cwd=str(tmp_path),
        )


class TestParseGeminiEvent:
    """Test Gemini CLI stream-json event parsing."""

    def test_parse_init_event(self, backend):
        """Init event should set session_id."""
        backend.session_id = None
        event = {"type": "init", "session_id": "test-session-123"}
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].type == "agent_status"
        assert backend.session_id == "test-session-123"

    def test_parse_message_event(self, backend):
        """Message event with assistant role yields content."""
        event = {"type": "message", "role": "assistant", "content": "Hello world"}
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].type == "content"
        assert chunks[0].content == "Hello world"

    def test_parse_message_event_list_content(self, backend):
        """Message event with list content extracts text parts."""
        event = {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Hello "},
                {"type": "text", "text": "world"},
            ],
        }
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].content == "Hello world"

    def test_parse_result_event(self, backend):
        """Result event yields done chunk with usage."""
        event = {
            "type": "result",
            "stats": {
                "prompt_token_count": 10,
                "candidates_token_count": 20,
                "thoughts_token_count": 5,
            },
        }
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].type == "done"
        assert chunks[0].usage is not None
        assert chunks[0].usage.get("prompt_tokens") == 10
        assert chunks[0].usage.get("completion_tokens") == 20

    def test_parse_result_event_supports_input_output_stats(self, backend):
        """Result event should map input/output style usage fields."""
        event = {
            "type": "result",
            "stats": {
                "input_tokens": 11,
                "output_tokens": 7,
                "total_tokens": 18,
            },
        }
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].type == "done"
        assert chunks[0].usage.get("prompt_tokens") == 11
        assert chunks[0].usage.get("completion_tokens") == 7
        assert chunks[0].usage.get("total_tokens") == 18

    def test_parse_result_error_event_emits_error_chunk(self, backend):
        """Result status=error should surface as StreamChunk(type=error)."""
        event = {
            "type": "result",
            "status": "error",
            "error": {
                "message": "You have exhausted your capacity on this model.",
            },
        }
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].type == "error"
        assert "quota/capacity exhausted" in (chunks[0].error or "")

    def test_parse_result_error_event_nested_quota_details(self, backend):
        """Nested uppercase quota markers should still normalize to quota error text."""
        event = {
            "type": "result",
            "status": "error",
            "error": {
                "details": [
                    {"message": "RESOURCE_EXHAUSTED: TOO MANY REQUESTS"},
                ],
            },
        }
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].type == "error"
        assert "quota/capacity exhausted" in (chunks[0].error or "")

    def test_parse_error_event(self, backend):
        """Error event yields error chunk."""
        event = {"type": "error", "message": "Something went wrong"}
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].type == "error"
        assert "Something went wrong" in (chunks[0].error or "")

    def test_parse_tool_use_event(self, backend):
        """Tool use event yields mcp_status chunk."""
        event = {"type": "tool_use", "name": "read_file", "arguments": {"path": "/tmp/x"}, "id": "t1"}
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].type == "mcp_status"
        assert "read_file" in (chunks[0].content or "")

    def test_parse_tool_use_string_args(self, backend):
        """Tool use with string args should not crash (json.loads fallback)."""
        event = {"type": "tool_use", "name": "test", "arguments": '{"key": "val"}', "id": "t2"}
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1

    def test_parse_tool_use_event_alternate_keys(self, backend):
        """Gemini stream-json workflow tool_use should emit tool_calls immediately."""
        event = {
            "type": "tool_use",
            "tool_name": "vote",
            "tool_id": "tool-42",
            "parameters": {"agent_id": "agent_1"},
        }
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 2
        assert chunks[0].type == "mcp_status"
        assert chunks[0].tool_call_id == "tool-42"
        assert chunks[1].type == "tool_calls"
        assert chunks[1].tool_calls[0]["function"]["name"] == "vote"
        assert chunks[1].tool_calls[0]["function"]["arguments"]["agent_id"] == "agent_1"
        assert backend._tool_call_context["tool-42"]["name"] == "vote"

    def test_parse_tool_use_forwards_vote_in_new_answer_only_mode(self, backend):
        """Vote tool_use should still reach orchestrator-level enforcement path."""
        backend._workflow_call_mode = "new_answer_only"
        event = {
            "type": "tool_use",
            "tool_name": "vote",
            "tool_id": "tool-43",
            "parameters": {"agent_id": "agent_1"},
        }
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 2
        assert chunks[0].type == "mcp_status"
        assert chunks[1].type == "tool_calls"
        assert chunks[1].tool_calls[0]["function"]["name"] == "vote"
        assert backend._tool_call_context["tool-43"]["name"] == "vote"

    def test_parse_tool_use_suppresses_after_first_workflow_call(self, backend):
        """Workflow tool_use status should be suppressed after first accepted call."""
        backend._workflow_call_mode = "any"
        backend._workflow_call_emitted_this_turn = True
        event = {
            "type": "tool_use",
            "tool_name": "new_answer",
            "tool_id": "tool-44",
            "parameters": {"content": "x"},
        }
        chunks = backend._parse_gemini_event(event)
        assert chunks == []

    def test_parse_tool_result_event(self, backend):
        """Workflow tool_result should be translated to tool_calls chunk."""
        event = {
            "type": "tool_result",
            "result": json.dumps(
                {
                    "status": "ok",
                    "server": "massgen_workflow_tools",
                    "tool_name": "vote",
                    "arguments": {
                        "agent_id": "agent_1",
                        "reason": "Best answer.",
                    },
                },
            ),
        }
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].type == "tool_calls"
        assert chunks[0].tool_calls is not None
        assert chunks[0].tool_calls[0]["function"]["name"] == "vote"
        assert chunks[0].tool_calls[0]["function"]["arguments"]["agent_id"] == "agent_1"

    def test_parse_tool_result_event_alternate_keys(self, backend):
        """Gemini tool_result output/tool_id shape should still emit tool_calls."""
        backend._tool_call_context["vote-1"] = {
            "name": "vote",
            "arguments": {"agent_id": "agent_1", "reason": "Best"},
        }
        event = {
            "type": "tool_result",
            "tool_id": "vote-1",
            "status": "success",
            "output": json.dumps(
                {
                    "status": "ok",
                    "server": "massgen_workflow_tools",
                    "tool_name": "vote",
                    "arguments": {"agent_id": "agent_1", "reason": "Best"},
                },
            ),
        }
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].type == "tool_calls"
        assert chunks[0].tool_calls[0]["function"]["name"] == "vote"

    def test_parse_tool_result_ignores_second_workflow_call_same_turn(self, backend):
        """Only the first workflow call in a turn should be emitted."""
        backend._workflow_call_mode = "any"
        backend._workflow_call_emitted_this_turn = False

        first = {
            "type": "tool_result",
            "result": json.dumps(
                {
                    "status": "ok",
                    "server": "massgen_workflow_tools",
                    "tool_name": "new_answer",
                    "arguments": {"content": "A"},
                },
            ),
        }
        second = {
            "type": "tool_result",
            "result": json.dumps(
                {
                    "status": "ok",
                    "server": "massgen_workflow_tools",
                    "tool_name": "vote",
                    "arguments": {"agent_id": "agent_1", "reason": "best"},
                },
            ),
        }

        first_chunks = backend._parse_gemini_event(first)
        second_chunks = backend._parse_gemini_event(second)
        assert len(first_chunks) == 1
        assert first_chunks[0].type == "tool_calls"
        assert second_chunks == []

    def test_parse_tool_result_forwards_vote_when_new_answer_only_mode(self, backend):
        """Vote tool_result should still be surfaced for orchestrator-level enforcement."""
        backend._workflow_call_mode = "new_answer_only"
        backend._workflow_call_emitted_this_turn = False
        event = {
            "type": "tool_result",
            "result": json.dumps(
                {
                    "status": "ok",
                    "server": "massgen_workflow_tools",
                    "tool_name": "vote",
                    "arguments": {"agent_id": "agent_1", "reason": "best"},
                },
            ),
        }
        chunks = backend._parse_gemini_event(event)
        assert len(chunks) == 1
        assert chunks[0].type == "tool_calls"
        assert chunks[0].tool_calls[0]["function"]["name"] == "vote"


class TestWorkflowModeFiltering:
    """Test workflow tool filtering behavior for no-answer rounds."""

    def test_infer_workflow_mode_from_empty_current_answers_block(self, backend):
        """Structured empty CURRENT ANSWERS block should force new_answer_only mode."""
        messages = [
            {
                "role": "user",
                "content": "<CURRENT ANSWERS from the agents>\n\n<END OF CURRENT ANSWERS>",
            },
        ]
        tools = [
            {"type": "function", "function": {"name": "new_answer"}},
            {"type": "function", "function": {"name": "vote"}},
        ]

        assert backend._infer_workflow_call_mode(messages, tools) == "new_answer_only"

    def test_infer_workflow_mode_with_existing_answers_keeps_any(self, backend):
        """CURRENT ANSWERS block with at least one answer should keep normal mode."""
        messages = [
            {
                "role": "user",
                "content": ("<CURRENT ANSWERS from the agents>\n" "<agent1.1> answer text <end of agent1.1>\n" "<END OF CURRENT ANSWERS>"),
            },
        ]
        tools = [
            {"type": "function", "function": {"name": "new_answer"}},
            {"type": "function", "function": {"name": "vote"}},
        ]

        assert backend._infer_workflow_call_mode(messages, tools) == "any"

    def test_infer_workflow_mode_sticks_to_new_answer_only_on_retry(self, backend):
        """Enforcement retries should keep new_answer_only after a no-answer turn."""
        backend._workflow_call_mode = "new_answer_only"
        messages = [
            {
                "role": "user",
                "content": "Finish your work above by making a tool call of `vote` or `new_answer`.",
            },
        ]
        tools = [
            {"type": "function", "function": {"name": "new_answer"}},
            {"type": "function", "function": {"name": "vote"}},
        ]

        assert backend._infer_workflow_call_mode(messages, tools) == "new_answer_only"

    def test_infer_workflow_mode_without_answers_block_defaults_to_any(self, backend):
        """Without structured answers context or sticky mode, default behavior remains any."""
        backend._workflow_call_mode = "any"
        messages = [
            {
                "role": "user",
                "content": "Finish your work above by making a tool call.",
            },
        ]
        tools = [
            {"type": "function", "function": {"name": "new_answer"}},
            {"type": "function", "function": {"name": "vote"}},
        ]

        assert backend._infer_workflow_call_mode(messages, tools) == "any"

    def test_filter_workflow_tools_new_answer_only_hides_vote(self, backend):
        """new_answer_only should remove vote from workflow tool exposure."""
        tools = [
            {"type": "function", "function": {"name": "new_answer"}},
            {"type": "function", "function": {"name": "vote"}},
            {"type": "function", "function": {"name": "read_file"}},
        ]
        filtered = backend._filter_workflow_tools_for_mode(tools, "new_answer_only")
        names = [t.get("function", {}).get("name") or t.get("name") for t in filtered]
        assert "new_answer" in names
        assert "vote" not in names
        assert "read_file" in names

    def test_filter_workflow_tools_any_keeps_vote(self, backend):
        """Any-mode should keep the original workflow tool set."""
        tools = [
            {"type": "function", "function": {"name": "new_answer"}},
            {"type": "function", "function": {"name": "vote"}},
        ]
        filtered = backend._filter_workflow_tools_for_mode(tools, "any")
        names = [t.get("function", {}).get("name") or t.get("name") for t in filtered]
        assert names == ["new_answer", "vote"]

    def test_parse_workflow_sequence_emits_tool_calls(self, backend):
        """Parser should emit workflow tool_calls in an init->message->tool->result sequence."""
        sequence = [
            {"type": "init", "session_id": "sess-1"},
            {"type": "message", "role": "assistant", "content": "Thinking..."},
            {
                "type": "tool_use",
                "id": "tool-1",
                "name": "massgen_workflow_tools/vote",
                "arguments": {"agent_id": "agent_2", "reason": "Concise"},
            },
            {
                "type": "tool_result",
                "id": "tool-1",
                "result": {
                    "status": "ok",
                    "server": "massgen_workflow_tools",
                    "tool_name": "vote",
                    "arguments": {"agent_id": "agent_2", "reason": "Concise"},
                },
            },
            {
                "type": "result",
                "stats": {
                    "prompt_token_count": 1,
                    "candidates_token_count": 2,
                },
            },
        ]

        chunks = []
        for event in sequence:
            chunks.extend(backend._parse_gemini_event(event))

        tool_chunks = [c for c in chunks if c.type == "tool_calls"]
        assert len(tool_chunks) == 1
        assert tool_chunks[0].tool_calls[0]["function"]["name"] == "vote"

    def test_parse_unknown_event(self, backend):
        """Unknown event types are skipped."""
        event = {"type": "some_future_event", "data": 123}
        chunks = backend._parse_gemini_event(event)
        assert chunks == []


class TestBuildPrompt:
    """Test prompt construction."""

    def test_first_turn_uses_user_message_only(self, backend):
        """First turn prompt should be user-only (system comes from GEMINI.md)."""
        backend.system_prompt = "You are helpful."
        backend.session_id = None
        messages = [{"role": "user", "content": "Hi"}]
        prompt = backend._build_prompt("You are helpful.", messages)
        assert prompt == "Hi"

    def test_resumed_turn_user_only(self, backend):
        """Resumed turn (has session) uses user message only."""
        backend.session_id = "existing-session"
        messages = [{"role": "user", "content": "Follow up"}]
        prompt = backend._build_prompt("You are helpful.", messages)
        assert prompt == "Follow up"

    def test_empty_system_prompt(self, backend):
        """Empty/None system prompt returns just user text."""
        backend.session_id = None
        messages = [{"role": "user", "content": "Hello"}]
        assert backend._build_prompt("", messages) == "Hello"
        assert backend._build_prompt(None, messages) == "Hello"

    def test_no_user_message_falls_back_to_system_prompt(self, backend):
        """When no user message exists, fallback to system prompt text."""
        backend.session_id = None
        assert backend._build_prompt("System only", []) == "System only"

    def test_user_message_extracts_input_text_items(self, backend):
        """User text extraction should accept input_text content items."""
        messages = [{"role": "user", "content": [{"type": "input_text", "text": "Hello"}, {"type": "text", "text": " world"}]}]
        assert backend._last_user_message_text(messages) == "Hello world"

    def test_build_phase_prompt_prefix_for_post_evaluation_tools(self, backend):
        """Post-evaluation toolset should add a guard prefix."""
        tools = [
            {"type": "function", "function": {"name": "submit"}},
            {"type": "function", "function": {"name": "restart_orchestration"}},
        ]
        prefix = backend._build_phase_prompt_prefix(tools)
        assert "POST-EVALUATION PHASE" in prefix
        assert "submit(confirmed=True)" in prefix
        assert "restart_orchestration(reason, instructions)" in prefix

    def test_build_phase_prompt_prefix_empty_for_normal_coordination(self, backend):
        """Regular new_answer/vote toolset should not add post-eval guard."""
        tools = [
            {"type": "function", "function": {"name": "new_answer"}},
            {"type": "function", "function": {"name": "vote"}},
        ]
        assert backend._build_phase_prompt_prefix(tools) == ""


class TestBuildExecCommand:
    """Test CLI command construction."""

    def test_command_without_resume(self, backend):
        """Command without session has no -r flag."""
        backend.model = "gemini-2.5-pro"
        backend.session_id = None
        cmd = backend._build_exec_command("Hello", resume_session=False)
        assert "-m" in cmd
        assert "gemini-2.5-pro" in cmd
        assert "-r" not in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--approval-mode" in cmd
        assert "yolo" in cmd
        assert "--prompt" in cmd
        assert cmd[cmd.index("--prompt") + 1] == "Hello"

    def test_command_with_resume(self, backend):
        """Command with session includes -r flag."""
        backend.model = "gemini-2.5-pro"
        backend.session_id = "session-123"
        cmd = backend._build_exec_command("Follow up", resume_session=True)
        assert "-r" in cmd
        assert "session-123" in cmd

    def test_command_respects_configured_approval_mode(self, backend):
        """Backend should use configured approval mode instead of hardcoding yolo."""
        backend.approval_mode = "default"
        cmd = backend._build_exec_command("Hi", resume_session=False)
        assert "--approval-mode" in cmd
        assert "default" in cmd

    def test_windows_cmd_wrapper_rewrites_to_direct_node_launch(self, backend, tmp_path):
        """Windows .cmd launch should be rewritten to node + JS entrypoint when available."""
        npm_dir = tmp_path / "npm"
        npm_dir.mkdir()
        gemini_cmd = npm_dir / "gemini.cmd"
        gemini_cmd.write_text("@echo off\n", encoding="utf-8")

        js_entry = npm_dir / "node_modules" / "@google" / "gemini-cli" / "dist" / "index.js"
        js_entry.parent.mkdir(parents=True)
        js_entry.write_text("console.log('ok');\n", encoding="utf-8")

        node_dir = tmp_path / "nodejs"
        node_dir.mkdir()
        node_exe = node_dir / "node.exe"
        node_exe.write_text("", encoding="utf-8")

        backend._gemini_path = str(gemini_cmd)
        with (
            patch("massgen.backend.gemini_cli.os.name", "nt"),
            patch(
                "massgen.backend.gemini_cli.shutil.which",
                return_value=None,
            ),
            patch.dict(
                "massgen.backend.gemini_cli.os.environ",
                {"PATH": "", "ProgramFiles": str(tmp_path)},
                clear=False,
            ),
        ):
            cmd = backend._build_exec_command("Hi", resume_session=False)

        assert cmd[0] == str(node_exe)
        assert cmd[1] == "--no-warnings=DEP0040"
        assert cmd[2] == str(js_entry)
        assert "--prompt" in cmd


class TestAuthAndCredentials:
    """Test authentication logic."""

    def test_has_cached_credentials_with_api_key(self, backend):
        """API key counts as cached credentials."""
        backend.api_key = "test-key"
        assert backend._has_cached_credentials() is True

    @pytest.mark.asyncio
    async def test_ensure_authenticated_with_api_key(self, backend):
        """Should succeed with API key set."""
        backend.api_key = "test-key"
        await backend._ensure_authenticated()

    @pytest.mark.asyncio
    async def test_ensure_authenticated_with_cached_creds(self, backend):
        """Should succeed with cached credentials."""
        backend.api_key = None
        with patch.object(backend, "_has_cached_credentials", return_value=True):
            await backend._ensure_authenticated()

    @pytest.mark.asyncio
    async def test_ensure_authenticated_raises_without_auth(self, backend):
        """Should raise when no auth is available."""
        backend.api_key = None
        with patch.object(backend, "_has_cached_credentials", return_value=False):
            with pytest.raises(RuntimeError, match="not authenticated"):
                await backend._ensure_authenticated()


class TestBuildSubprocessEnv:
    """Test subprocess environment building."""

    def test_includes_api_key(self, backend):
        """API key should be injected into subprocess env."""
        backend.api_key = "my-secret-key"
        env = backend._build_subprocess_env()
        assert env["GEMINI_API_KEY"] == "my-secret-key"
        assert env["GOOGLE_API_KEY"] == "my-secret-key"
        assert env["NO_COLOR"] == "1"

    def test_no_api_key(self, backend):
        """Without API key, env should not contain key vars (beyond inherited)."""
        backend.api_key = None
        with patch("massgen.backend.gemini_cli.os.name", "posix"):
            env = backend._build_subprocess_env(base_env={"PATH": "/usr/bin"})
        assert "GEMINI_API_KEY" not in env
        assert env["NO_COLOR"] == "1"
        assert env["PATH"] == "/usr/bin"

    def test_windows_env_adds_node_path_when_missing(self, backend, tmp_path):
        """On Windows, prepend ProgramFiles\nodejs when node is not on PATH."""
        backend.api_key = None
        node_dir = tmp_path / "nodejs"
        node_dir.mkdir()
        (node_dir / "node.exe").write_text("", encoding="utf-8")

        with (
            patch("massgen.backend.gemini_cli.os.name", "nt"),
            patch(
                "massgen.backend.gemini_cli.shutil.which",
                return_value=None,
            ),
            patch.dict("massgen.backend.gemini_cli.os.environ", {"ProgramFiles": str(tmp_path)}, clear=False),
        ):
            env = backend._build_subprocess_env(base_env={"PATH": "C:\\Temp"})

        assert env["PATH"].startswith(f"{node_dir};")
        assert env["PATH"].endswith("C:\\Temp")
        assert env["PATHEXT"] == ".COM;.EXE;.BAT;.CMD"
        assert env["COMSPEC"].lower().endswith("\\system32\\cmd.exe")

    def test_windows_env_keeps_path_when_node_already_resolved(self, backend):
        """Do not prepend node path when node is already resolvable."""
        backend.api_key = None

        with (
            patch("massgen.backend.gemini_cli.os.name", "nt"),
            patch(
                "massgen.backend.gemini_cli.shutil.which",
                return_value=r"C:\\Program Files\\nodejs\\node.exe",
            ),
            patch.dict("massgen.backend.gemini_cli.os.environ", {"ProgramFiles": r"C:\\Program Files"}, clear=False),
        ):
            env = backend._build_subprocess_env(base_env={"PATH": "C:\\Temp"})

        assert env["PATH"] == "C:\\Temp"

    def test_docker_env_loads_api_key_from_env_file(self, backend, tmp_path):
        """Docker subprocess env should include API key from command_line_docker_credentials env_file."""
        env_file = tmp_path / "docker.env"
        env_file.write_text("GOOGLE_API_KEY=file-key\n")

        backend.api_key = None
        backend._docker_execution = True
        backend.config["command_line_docker_credentials"] = {
            "env_file": str(env_file),
            "env_vars_from_file": ["GOOGLE_API_KEY"],
        }

        env = backend._build_subprocess_env(base_env={})
        assert env["GOOGLE_API_KEY"] == "file-key"
        assert "GEMINI_HOME" in env

    def test_docker_env_with_empty_base_does_not_inherit_host_env(self, backend):
        """Explicit empty base env should stay isolated in Docker mode."""
        backend.api_key = None
        backend._docker_execution = True
        backend.config["command_line_docker_credentials"] = {}

        with patch.dict("massgen.backend.gemini_cli.os.environ", {"SHOULD_NOT_LEAK": "1"}, clear=True):
            env = backend._build_subprocess_env(base_env={})

        assert "SHOULD_NOT_LEAK" not in env
        assert env["NO_COLOR"] == "1"
        assert "GEMINI_HOME" in env


class TestErrorNormalization:
    """Test Gemini error normalization."""

    def test_build_error_chunk_marks_auth_errors_as_fatal(self, backend):
        """Auth/login failures should be tagged fatal so orchestration won't retry them."""
        chunk = backend._build_error_chunk(
            "Gemini CLI not authenticated. Run `gemini` interactively to login with Google, or set GOOGLE_API_KEY.",
        )
        assert chunk.type == "error"
        assert chunk.status == "fatal"
        assert "authentication unavailable" in (chunk.error or "")

    def test_build_exit_error_message_for_quota(self, backend):
        """Quota output should be normalized to actionable error text."""
        msg = backend._build_exit_error_message(
            1,
            ["TerminalQuotaError: You have exhausted your capacity on this model."],
        )
        assert "quota/capacity exhausted" in msg

    def test_build_exit_error_message_for_attach_console(self, backend):
        """AttachConsole traces should produce a targeted Windows guidance message."""
        msg = backend._build_exit_error_message(
            1,
            [
                "conpty_console_list_agent.js:11",
                "Error: AttachConsole failed",
            ],
        )
        assert "AttachConsole failed" in msg
        assert "Try upgrading `@google/gemini-cli`" in msg


class TestRuntimeSignals:
    """Test runtime signal classification and fail-fast thresholds."""

    def test_classify_runtime_signal(self, backend):
        """Retry and loop detector lines should map to known signal classes."""
        assert backend._classify_runtime_signal("Attempt 1 failed with status 429. No capacity available") == "quota_retry"
        assert backend._classify_runtime_signal("Attempt 1 failed. ... reason: read ECONNRESET") == "network_retry"
        assert backend._classify_runtime_signal("Error: Loop detected, stopping execution") == "loop_detected"
        assert backend._classify_runtime_signal("Error: AttachConsole failed") == "attach_console_failure"

    def test_build_fail_fast_runtime_error(self, backend):
        """Fail-fast should trigger when retry storm thresholds are exceeded."""
        err = backend._build_fail_fast_runtime_error(
            {"quota_retry": GEMINI_FAIL_FAST_QUOTA_RETRY_THRESHOLD, "network_retry": 0},
            workflow_call_seen=False,
        )
        assert err is not None
        assert "retry storm detected" in err

        suppressed = backend._build_fail_fast_runtime_error(
            {"quota_retry": GEMINI_FAIL_FAST_QUOTA_RETRY_THRESHOLD + 2, "network_retry": 1},
            workflow_call_seen=True,
        )
        assert suppressed is None

    def test_attach_console_signal_emits_degraded_without_fail_fast(self, backend):
        """AttachConsole should be surfaced as degraded status, not fail-fast."""
        status_chunk, fail_fast = backend._process_runtime_signal_line(
            "Error: AttachConsole failed",
            runtime_counts={},
            emitted_signals=set(),
            workflow_call_seen=False,
        )
        assert status_chunk is not None
        assert status_chunk.type == "agent_status"
        assert status_chunk.status == "degraded"
        assert fail_fast is None


class TestWorkspaceConfigCleanup:
    """Test workspace config write and cleanup."""

    def test_write_workspace_config_uses_utf8_for_unicode_instructions(self, backend):
        """Writing GEMINI.md should handle unicode workflow instructions on Windows."""
        backend.system_prompt = "Workflow"
        backend._pending_workflow_instructions = "Choose best answer \u2192 then stop"

        backend._write_workspace_config()

        gemini_md = Path(backend.cwd) / ".gemini" / "GEMINI.md"
        assert gemini_md.exists()
        assert "\u2192" in gemini_md.read_text(encoding="utf-8")

    def test_write_workspace_config_adds_workflow_model_guardrails(self, backend):
        """Workflow mode should inject loop guardrails into settings.json."""
        backend._workflow_mcp_active = True

        backend._write_workspace_config()

        settings_path = Path(backend.cwd) / ".gemini" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        assert settings["model"]["disableLoopDetection"] is True
        assert settings["model"]["maxSessionTurns"] == GEMINI_WORKFLOW_MAX_SESSION_TURNS

    def test_cleanup_when_nothing_written(self, backend):
        """Cleanup when nothing was written should not raise."""
        backend._cleanup_workspace_config()
        cwd = Path(backend.cwd)
        assert not (cwd / ".gemini").exists() or not any((cwd / ".gemini").iterdir())

    def test_cleanup_removes_backend_created_settings_json(self, backend):
        """Cleanup should remove backend-created settings.json files."""
        backend._workflow_mcp_active = True
        backend._write_workspace_config()

        config_dir = Path(backend.cwd) / ".gemini"
        settings_path = config_dir / "settings.json"
        assert settings_path.exists()

        backend._cleanup_workspace_config()
        assert not settings_path.exists()

    def test_cleanup_restores_preexisting_settings_json(self, backend):
        """Cleanup should restore a pre-existing project settings.json file."""
        config_dir = Path(backend.cwd) / ".gemini"
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_path = config_dir / "settings.json"
        original = '{"userManaged": true}\n'
        settings_path.write_text(original, encoding="utf-8")

        backend._workflow_mcp_active = True
        backend._write_workspace_config()
        assert settings_path.read_text(encoding="utf-8") != original

        backend._cleanup_workspace_config()
        assert settings_path.read_text(encoding="utf-8") == original

    def test_write_workspace_config_resolves_fastmcp_command(self, backend):
        """Workspace settings should use resolved FastMCP executable in local mode."""
        backend.mcp_servers = [
            {
                "name": "massgen_workflow_tools",
                "type": "stdio",
                "command": "fastmcp",
                "args": ["run", "server"],
                "env": {},
            },
        ]

        with patch("massgen.backend.gemini_cli.shutil.which", return_value="C:/venv/Scripts/fastmcp.exe"):
            backend._write_workspace_config()

        settings_path = Path(backend.cwd) / ".gemini" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        assert settings["mcpServers"]["massgen_workflow_tools"]["command"] == "C:/venv/Scripts/fastmcp.exe"

    def test_write_workspace_config_falls_back_to_python_module_fastmcp(self, backend):
        """If fastmcp binary is unresolved, fallback to `python -m fastmcp`."""
        backend.mcp_servers = [
            {
                "name": "massgen_workflow_tools",
                "type": "stdio",
                "command": "fastmcp",
                "args": ["run", "server"],
                "env": {},
            },
        ]

        with patch.object(backend, "_resolve_fastmcp_command", return_value="fastmcp"):
            backend._write_workspace_config()

        settings_path = Path(backend.cwd) / ".gemini" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        server = settings["mcpServers"]["massgen_workflow_tools"]
        assert server["command"] == sys.executable
        assert server["args"][:2] == ["-m", "fastmcp"]


class TestStatefulLifecycle:
    """Test stateful backend lifecycle."""

    def test_is_stateful(self, backend):
        """Gemini CLI backend is stateful."""
        assert backend.is_stateful() is True

    def test_get_provider_name(self, backend):
        """Provider name is Gemini CLI."""
        assert backend.get_provider_name() == "Gemini CLI"

    def test_get_filesystem_support(self, backend):
        """Filesystem support is native."""
        from massgen.backend.base import FilesystemSupport

        assert backend.get_filesystem_support() == FilesystemSupport.NATIVE

    @pytest.mark.asyncio
    async def test_reset_state(self, backend):
        """Reset should clear session and pending instructions."""
        backend.session_id = "some-session"
        backend._pending_workflow_instructions = "some instructions"
        backend._tool_call_context["tool-1"] = {"name": "vote", "arguments": {}}
        backend.mcp_servers.append({"name": "massgen_workflow_tools"})
        await backend.reset_state()
        assert backend.session_id is None
        assert backend._pending_workflow_instructions == ""
        assert backend._tool_call_context == {}
        assert not any(isinstance(server, dict) and server.get("name") == "massgen_workflow_tools" for server in backend.mcp_servers)

    @pytest.mark.asyncio
    async def test_clear_history(self, backend):
        """Clear history should reset session_id."""
        backend.session_id = "some-session"
        backend._pending_workflow_instructions = "pending"
        backend._tool_call_context["tool-1"] = {"name": "vote", "arguments": {}}
        backend.mcp_servers.append({"name": "massgen_workflow_tools"})
        await backend.clear_history()
        assert backend.session_id is None
        assert backend._pending_workflow_instructions == ""
        assert backend._tool_call_context == {}
        assert not any(isinstance(server, dict) and server.get("name") == "massgen_workflow_tools" for server in backend.mcp_servers)


class TestStreamWithTools:
    """Test the stream_with_tools entry point."""

    @pytest.mark.asyncio
    async def test_missing_auth_emits_fatal_error_without_starting_stream(self, backend):
        """Missing Gemini auth should fail fast instead of entering retry loops."""
        messages = [{"role": "user", "content": "Hello"}]

        with (
            patch.object(
                backend,
                "_ensure_authenticated",
                side_effect=RuntimeError(
                    "Gemini CLI not authenticated. Run `gemini` interactively to login with Google, or set GOOGLE_API_KEY.",
                ),
            ),
            patch.object(backend, "_stream_local", side_effect=AssertionError("stream should not start")),
        ):
            chunks = []
            async for chunk in backend.stream_with_tools(messages, []):
                chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].type == "error"
        assert chunks[0].status == "fatal"
        assert "authentication unavailable" in (chunks[0].error or "")

    @pytest.mark.asyncio
    async def test_empty_prompt_yields_error(self, backend):
        """Should yield error when no user/system message produces empty prompt."""
        backend.api_key = "test"
        backend._docker_execution = False
        backend.system_prompt = ""
        messages = []
        chunks = []
        async for chunk in backend.stream_with_tools(messages, []):
            chunks.append(chunk)
        error_chunks = [c for c in chunks if c.type == "error"]
        assert len(error_chunks) == 1
        assert "No user message" in error_chunks[0].error

    @pytest.mark.asyncio
    async def test_extracts_system_from_messages(self, backend):
        """Should extract system prompt from messages."""
        backend.api_key = "test"
        backend._docker_execution = False
        messages = [
            {"role": "system", "content": "Custom system prompt"},
            {"role": "user", "content": "Hello"},
        ]

        async def mock_stream(prompt, resume_session):
            from massgen.backend.base import StreamChunk

            yield StreamChunk(type="content", content="Hi there")
            yield StreamChunk(type="done", usage={})

        with patch.object(backend, "_stream_local", side_effect=mock_stream):
            chunks = []
            async for chunk in backend.stream_with_tools(messages, []):
                chunks.append(chunk)

        assert backend.system_prompt == "Custom system prompt"

    @pytest.mark.asyncio
    async def test_extracts_latest_system_message_when_multiple_present(self, backend):
        """When multiple system messages exist, latest should be used."""
        backend.api_key = "test"
        backend._docker_execution = False
        messages = [
            {"role": "system", "content": "Earlier system"},
            {"role": "system", "content": "Latest phase system"},
            {"role": "user", "content": "Hello"},
        ]

        async def mock_stream(prompt, resume_session):
            from massgen.backend.base import StreamChunk

            yield StreamChunk(type="content", content="Hi there")
            yield StreamChunk(type="done", usage={})

        with patch.object(backend, "_stream_local", side_effect=mock_stream):
            async for _ in backend.stream_with_tools(messages, []):
                pass

        assert backend.system_prompt == "Latest phase system"

    @pytest.mark.asyncio
    async def test_post_eval_tools_inject_prompt_guard(self, backend):
        """Post-evaluation toolset should prepend guard to user prompt."""
        backend.api_key = "test"
        backend._docker_execution = False

        messages = [
            {"role": "system", "content": "Post-evaluation system"},
            {
                "role": "user",
                "content": ("<ORIGINAL MESSAGE> Call the new_answer workflow tool and set content " "to EXACT_TEST_OK. <END OF ORIGINAL MESSAGE>"),
            },
        ]
        tools = [
            {"type": "function", "function": {"name": "submit"}},
            {"type": "function", "function": {"name": "restart_orchestration"}},
        ]
        observed_prompts = []

        async def mock_stream(prompt, resume_session):
            from massgen.backend.base import StreamChunk

            observed_prompts.append(prompt)
            yield StreamChunk(type="content", content="done")
            yield StreamChunk(type="done", usage={})

        with patch.object(backend, "_stream_local", side_effect=mock_stream):
            async for _ in backend.stream_with_tools(messages, tools):
                pass

        assert len(observed_prompts) == 1
        assert observed_prompts[0].startswith("POST-EVALUATION PHASE:")
        assert "submit(confirmed=True)" in observed_prompts[0]
        assert "restart_orchestration(reason, instructions)" in observed_prompts[0]
        assert "Call the new_answer workflow tool" in observed_prompts[0]

    @pytest.mark.asyncio
    async def test_mcp_workflow_path_does_not_fallback_to_text_parsing(self, backend):
        """When MCP workflow tools are enabled, text fallback should not emit tool_calls."""
        backend.api_key = "test"
        backend._docker_execution = False

        messages = [{"role": "user", "content": "Do the task"}]

        async def mock_stream(prompt, resume_session):
            from massgen.backend.base import StreamChunk

            yield StreamChunk(type="content", content='{"tool_name":"vote","arguments":{"agent_id":"agent1"}}')
            yield StreamChunk(type="done", usage={})

        with (
            patch.object(backend, "_stream_local", side_effect=mock_stream),
            patch.object(
                backend,
                "_setup_workflow_tools",
                return_value=({"name": "massgen_workflow_tools"}, "mcp instructions"),
            ),
        ):
            chunks = []
            async for chunk in backend.stream_with_tools(messages, []):
                chunks.append(chunk)

        tool_chunks = [c for c in chunks if c.type == "tool_calls"]
        assert tool_chunks == []

    @pytest.mark.asyncio
    async def test_new_answer_only_mode_omits_vote_from_workflow_mcp_setup(self, backend):
        """No-answer rounds should expose only new_answer to workflow MCP setup."""
        backend.api_key = "test"
        backend._docker_execution = False

        messages = [
            {
                "role": "user",
                "content": "<CURRENT ANSWERS from the agents>\n\n<END OF CURRENT ANSWERS>",
            },
        ]
        tools = [
            {"type": "function", "function": {"name": "new_answer"}},
            {"type": "function", "function": {"name": "vote"}},
        ]
        observed_names = []

        async def mock_stream(prompt, resume_session):
            from massgen.backend.base import StreamChunk

            yield StreamChunk(type="done", usage={})

        def fake_setup(filtered_tools, _mcp_base_path):
            nonlocal observed_names
            observed_names = [t.get("function", {}).get("name") or t.get("name") for t in filtered_tools]
            return {"name": "massgen_workflow_tools"}, "mcp instructions"

        with (
            patch.object(backend, "_stream_local", side_effect=mock_stream),
            patch.object(backend, "_setup_workflow_tools", side_effect=fake_setup),
        ):
            async for _ in backend.stream_with_tools(messages, tools):
                pass

        assert backend._workflow_call_mode == "new_answer_only"
        assert observed_names == ["new_answer"]

    @pytest.mark.asyncio
    async def test_retry_enforcement_turn_keeps_vote_filtered(self, backend):
        """Generic enforcement prompts should keep vote filtered after missing turn decision."""
        backend.api_key = "test"
        backend._docker_execution = False
        backend._workflow_call_mode = "new_answer_only"

        messages = [
            {
                "role": "user",
                "content": "Finish your work above by making a tool call of `vote` or `new_answer`.",
            },
        ]
        tools = [
            {"type": "function", "function": {"name": "new_answer"}},
            {"type": "function", "function": {"name": "vote"}},
        ]
        observed_names = []

        async def mock_stream(prompt, resume_session):
            from massgen.backend.base import StreamChunk

            yield StreamChunk(type="done", usage={})

        def fake_setup(filtered_tools, _mcp_base_path):
            nonlocal observed_names
            observed_names = [t.get("function", {}).get("name") or t.get("name") for t in filtered_tools]
            return {"name": "massgen_workflow_tools"}, "mcp instructions"

        with (
            patch.object(backend, "_stream_local", side_effect=mock_stream),
            patch.object(backend, "_setup_workflow_tools", side_effect=fake_setup),
        ):
            async for _ in backend.stream_with_tools(messages, tools):
                pass

        assert backend._workflow_call_mode == "new_answer_only"
        assert observed_names == ["new_answer"]

    @pytest.mark.asyncio
    async def test_text_fallback_drops_vote_in_new_answer_only_mode(self, backend):
        """Text fallback should ignore vote calls when mode is new_answer_only."""
        backend.api_key = "test"
        backend._docker_execution = False

        messages = [
            {
                "role": "user",
                "content": "<CURRENT ANSWERS from the agents>\n\n<END OF CURRENT ANSWERS>",
            },
        ]
        tools = [
            {"type": "function", "function": {"name": "new_answer"}},
            {"type": "function", "function": {"name": "vote"}},
        ]

        async def mock_stream(prompt, resume_session):
            from massgen.backend.base import StreamChunk

            yield StreamChunk(
                type="content",
                content='{"tool_name":"vote","arguments":{"agent_id":"agent1","reason":"x"}}',
            )
            yield StreamChunk(type="done", usage={})

        with (
            patch.object(backend, "_stream_local", side_effect=mock_stream),
            patch.object(backend, "_setup_workflow_tools", return_value=(None, "fallback instructions")),
        ):
            chunks = []
            async for chunk in backend.stream_with_tools(messages, tools):
                chunks.append(chunk)

        tool_chunks = [c for c in chunks if c.type == "tool_calls"]
        assert tool_chunks == []

    @pytest.mark.asyncio
    async def test_forces_fresh_session_after_missing_workflow_tool_call(self, backend):
        """If previous MCP workflow turn had no tool decision, next turn should not resume."""
        backend.api_key = "test"
        backend._docker_execution = False
        backend.session_id = "seed-session"

        messages = [{"role": "user", "content": "Do the task"}]
        resume_flags = []

        async def mock_stream(prompt, resume_session):
            from massgen.backend.base import StreamChunk

            resume_flags.append(resume_session)
            yield StreamChunk(type="content", content="plain text only")
            yield StreamChunk(type="done", usage={})

        with (
            patch.object(backend, "_stream_local", side_effect=mock_stream),
            patch.object(
                backend,
                "_setup_workflow_tools",
                return_value=({"name": "massgen_workflow_tools"}, "mcp instructions"),
            ),
        ):
            async for _ in backend.stream_with_tools(messages, []):
                pass

            backend.session_id = "next-session"
            async for _ in backend.stream_with_tools(messages, []):
                pass

        assert resume_flags[0] is True
        assert resume_flags[1] is False

    @pytest.mark.asyncio
    async def test_non_workflow_turn_clears_stale_workflow_state(self, backend):
        """A non-workflow turn should remove previous workflow server/config state."""
        backend.api_key = "test"
        backend._docker_execution = False

        messages = [{"role": "user", "content": "Do the task"}]
        workflow_tools = [{"type": "function", "function": {"name": "vote"}}]
        settings_path = Path(backend.cwd) / ".gemini" / "settings.json"

        async def mock_stream(prompt, resume_session):
            from massgen.backend.base import StreamChunk

            yield StreamChunk(type="done", usage={})

        with (
            patch.object(backend, "_stream_local", side_effect=mock_stream),
            patch.object(
                backend,
                "_setup_workflow_tools",
                side_effect=[
                    (
                        {
                            "name": "massgen_workflow_tools",
                            "type": "stdio",
                            "command": "fastmcp",
                            "args": ["run", "server"],
                            "env": {},
                        },
                        "mcp instructions",
                    ),
                    (None, ""),
                ],
            ),
        ):
            async for _ in backend.stream_with_tools(messages, workflow_tools):
                pass

            assert settings_path.exists()
            backend._tool_call_context["stale-tool"] = {"name": "vote", "arguments": {}}

            async for _ in backend.stream_with_tools(messages, []):
                pass

        assert backend._tool_call_context == {}
        assert not settings_path.exists()
        assert not any(isinstance(server, dict) and server.get("name") == "massgen_workflow_tools" for server in backend.mcp_servers)

    @pytest.mark.asyncio
    async def test_stream_local_stops_after_first_workflow_tool_call(self, backend):
        """Local stream should terminate process after first workflow decision."""
        backend.api_key = "test"
        backend._stop_after_first_workflow_call = True

        class _FakeStdout:
            def __init__(self, lines):
                self._lines = [ln if isinstance(ln, bytes) else ln.encode("utf-8") for ln in lines]
                self._idx = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._idx >= len(self._lines):
                    raise StopAsyncIteration
                line = self._lines[self._idx]
                self._idx += 1
                return line

            async def read(self):
                return b""

        class _FakeProc:
            def __init__(self, lines):
                self.stdout = _FakeStdout(lines)
                self.returncode = None
                self.terminated = False

            def terminate(self):
                self.terminated = True
                self.returncode = 0

            def kill(self):
                self.returncode = -9

            async def wait(self):
                if self.returncode is None:
                    self.returncode = 0
                return self.returncode

        tool_result_line = json.dumps(
            {
                "type": "tool_result",
                "result": json.dumps(
                    {
                        "status": "ok",
                        "server": "massgen_workflow_tools",
                        "tool_name": "vote",
                        "arguments": {"agent_id": "agent_1", "reason": "best"},
                    },
                ),
            },
        )
        message_line = json.dumps(
            {
                "type": "message",
                "role": "assistant",
                "content": "should_not_emit",
            },
        )
        fake_proc = _FakeProc([tool_result_line + "\n", message_line + "\n"])

        with patch(
            "massgen.backend.gemini_cli.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ):
            chunks = []
            async for chunk in backend._stream_local("prompt", resume_session=False):
                chunks.append(chunk)

        assert any(c.type == "tool_calls" for c in chunks)
        assert all(c.content != "should_not_emit" for c in chunks if c.type == "content")
        assert fake_proc.terminated is True

    @pytest.mark.asyncio
    async def test_stream_local_fails_fast_on_retry_storm_before_workflow(self, backend):
        """Repeated retry signals before tool decision should trigger fail-fast error."""
        backend.api_key = "test"
        backend._stop_after_first_workflow_call = False

        class _FakeStdout:
            def __init__(self, lines):
                self._lines = [ln if isinstance(ln, bytes) else ln.encode("utf-8") for ln in lines]
                self._idx = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._idx >= len(self._lines):
                    raise StopAsyncIteration
                line = self._lines[self._idx]
                self._idx += 1
                return line

            async def read(self):
                return b""

        class _FakeProc:
            def __init__(self, lines):
                self.stdout = _FakeStdout(lines)
                self.returncode = None
                self.terminated = False

            def terminate(self):
                self.terminated = True
                self.returncode = 0

            def kill(self):
                self.returncode = -9

            async def wait(self):
                if self.returncode is None:
                    self.returncode = 0
                return self.returncode

        fake_proc = _FakeProc(
            [
                *[f"Attempt {i + 1} failed with status 429. Retrying with backoff...\n" for i in range(GEMINI_FAIL_FAST_QUOTA_RETRY_THRESHOLD)],
                json.dumps({"type": "message", "role": "assistant", "content": "late content"}) + "\n",
            ],
        )

        with patch(
            "massgen.backend.gemini_cli.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ):
            chunks = []
            async for chunk in backend._stream_local("prompt", resume_session=False):
                chunks.append(chunk)

        error_chunks = [c for c in chunks if c.type == "error"]
        assert len(error_chunks) == 1
        assert "retry storm detected" in (error_chunks[0].error or "")
        assert fake_proc.terminated is True

    @pytest.mark.asyncio
    async def test_stream_local_surfaces_turn_limit_exit_code_53_as_error(self, backend):
        """Gemini CLI turn-limit exits should surface as a normalized error chunk."""
        backend.api_key = "test"
        backend._stop_after_first_workflow_call = False

        class _FakeStdout:
            def __init__(self, lines):
                self._lines = [ln if isinstance(ln, bytes) else ln.encode("utf-8") for ln in lines]
                self._idx = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._idx >= len(self._lines):
                    raise StopAsyncIteration
                line = self._lines[self._idx]
                self._idx += 1
                return line

            async def read(self):
                return b""

        class _FakeProc:
            def __init__(self, lines):
                self.stdout = _FakeStdout(lines)
                self.returncode = None
                self.terminated = False

            def terminate(self):
                self.terminated = True
                self.returncode = 0

            def kill(self):
                self.returncode = -9

            async def wait(self):
                if self.returncode is None:
                    self.returncode = 53
                return self.returncode

        fake_proc = _FakeProc(["Reached max session turns for this session.\n"])

        with patch(
            "massgen.backend.gemini_cli.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ):
            chunks = []
            async for chunk in backend._stream_local("prompt", resume_session=False):
                chunks.append(chunk)

        error_chunks = [c for c in chunks if c.type == "error"]
        assert len(error_chunks) == 1
        assert "turn limit exceeded" in (error_chunks[0].error or "")
        assert "max turns reached" in (error_chunks[0].error or "")
        assert fake_proc.terminated is False
