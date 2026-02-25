"""
Tests for native backend routing in multimodal tools (MAS-300).

Verifies that read_media -> understand_image routes image analysis
to the agent's own backend instead of always using OpenAI.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Capability tests
# ---------------------------------------------------------------------------


class TestCapabilities:
    """Verify capabilities registry has image_understanding for expected backends."""

    def test_claude_has_image_understanding(self):
        from massgen.backend.capabilities import has_capability

        assert has_capability("claude", "image_understanding")

    def test_openai_has_image_understanding(self):
        from massgen.backend.capabilities import has_capability

        assert has_capability("openai", "image_understanding")

    def test_gemini_has_image_understanding(self):
        from massgen.backend.capabilities import has_capability

        assert has_capability("gemini", "image_understanding")

    def test_grok_has_image_understanding(self):
        from massgen.backend.capabilities import has_capability

        assert has_capability("grok", "image_understanding")

    def test_claude_code_has_image_understanding(self):
        from massgen.backend.capabilities import has_capability

        assert has_capability("claude_code", "image_understanding")

    def test_codex_has_image_understanding(self):
        from massgen.backend.capabilities import has_capability

        assert has_capability("codex", "image_understanding")

    def test_lmstudio_no_image_understanding(self):
        from massgen.backend.capabilities import has_capability

        assert not has_capability("lmstudio", "image_understanding")


# ---------------------------------------------------------------------------
# Routing tests - verify understand_image dispatches to correct backend
# ---------------------------------------------------------------------------


def _make_loaded_image(name: str = "test.png"):
    """Create a fake LoadedImage for testing."""
    from massgen.tool._multimodal_tools.understand_image import LoadedImage

    return LoadedImage(
        path=Path(f"/tmp/{name}"),
        base64_data="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        mime_type="image/png",
        name=name,
    )


@pytest.fixture
def fake_image(tmp_path):
    """Create a minimal valid PNG file for testing."""
    import base64

    # 1x1 red PNG
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/58BAwAI/AL+hc2rNAAAAABJRU5ErkJggg==",
    )
    img_path = tmp_path / "test.png"
    img_path.write_bytes(png_data)
    return img_path


class TestUnderstandImageRouting:
    """Test that understand_image routes to the correct backend."""

    @pytest.mark.asyncio
    async def test_routes_to_claude(self, fake_image):
        """When backend_type='claude', call_claude should be called."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_claude", new_callable=AsyncMock) as mock_claude,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_load.return_value = _make_loaded_image()
            mock_claude.return_value = ("This is a test image", None)

            result = await understand_image(
                image_path=str(fake_image),
                prompt="describe",
                backend_type="claude",
                model="claude-sonnet-4-5",
            )

            mock_claude.assert_called_once()
            data = json.loads(result.output_blocks[0].data)
            assert data["success"]
            assert data["response"] == "This is a test image"

    @pytest.mark.asyncio
    async def test_routes_to_gemini(self, fake_image):
        """When backend_type='gemini', call_gemini should be called."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_gemini", new_callable=AsyncMock) as mock_gemini,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_load.return_value = _make_loaded_image()
            mock_gemini.return_value = ("Gemini analysis", None)

            result = await understand_image(
                image_path=str(fake_image),
                prompt="describe",
                backend_type="gemini",
                model="gemini-3-flash-preview",
            )

            mock_gemini.assert_called_once()
            data = json.loads(result.output_blocks[0].data)
            assert data["success"]

    @pytest.mark.asyncio
    async def test_routes_to_grok(self, fake_image):
        """When backend_type='grok', call_grok should be called."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_grok", new_callable=AsyncMock) as mock_grok,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_load.return_value = _make_loaded_image()
            mock_grok.return_value = ("Grok analysis", None)

            result = await understand_image(
                image_path=str(fake_image),
                prompt="describe",
                backend_type="grok",
                model="grok-4",
            )

            mock_grok.assert_called_once()
            data = json.loads(result.output_blocks[0].data)
            assert data["success"]

    @pytest.mark.asyncio
    async def test_routes_to_openai(self, fake_image):
        """When backend_type='openai', call_openai should be called."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_openai", new_callable=AsyncMock) as mock_openai,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_load.return_value = _make_loaded_image()
            mock_openai.return_value = ("OpenAI analysis", "resp_123")

            result = await understand_image(
                image_path=str(fake_image),
                prompt="describe",
                backend_type="openai",
                model="gpt-5.2",
            )

            mock_openai.assert_called_once()
            data = json.loads(result.output_blocks[0].data)
            assert data["success"]

    @pytest.mark.asyncio
    async def test_routes_to_claude_code(self, fake_image):
        """When backend_type='claude_code', call_claude_code should be called."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_claude_code", new_callable=AsyncMock) as mock_cc,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_load.return_value = _make_loaded_image()
            mock_cc.return_value = ("Claude Code analysis", None)

            result = await understand_image(
                image_path=str(fake_image),
                prompt="describe",
                backend_type="claude_code",
                model="claude-sonnet-4-5",
                agent_cwd="/tmp",
            )

            mock_cc.assert_called_once()
            data = json.loads(result.output_blocks[0].data)
            assert data["success"]

    @pytest.mark.asyncio
    async def test_routes_to_codex(self, fake_image):
        """When backend_type='codex', call_codex should be called."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_codex", new_callable=AsyncMock) as mock_codex,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_load.return_value = _make_loaded_image()
            mock_codex.return_value = ("Codex analysis", None)

            result = await understand_image(
                image_path=str(fake_image),
                prompt="describe",
                backend_type="codex",
                agent_cwd="/tmp",
            )

            mock_codex.assert_called_once()
            data = json.loads(result.output_blocks[0].data)
            assert data["success"]

    @pytest.mark.asyncio
    async def test_falls_back_when_no_capability(self, fake_image):
        """Backend with no image_understanding capability falls back to OpenAI."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_openai", new_callable=AsyncMock) as mock_openai,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_load.return_value = _make_loaded_image()
            mock_openai.return_value = ("OpenAI fallback", "resp_fb")

            await understand_image(
                image_path=str(fake_image),
                prompt="describe",
                backend_type="lmstudio",
                model="some-model",
            )

            mock_openai.assert_called_once()
            # Fallback uses gpt-5.2
            call_args = mock_openai.call_args
            # Positional args: (loaded_images, prompt, model)
            assert call_args[0][2] == "gpt-5.2"

    @pytest.mark.asyncio
    async def test_falls_back_when_backend_type_none(self, fake_image):
        """When backend_type is None, falls back to OpenAI."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_openai", new_callable=AsyncMock) as mock_openai,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_load.return_value = _make_loaded_image()
            mock_openai.return_value = ("OpenAI default", "resp_def")

            await understand_image(
                image_path=str(fake_image),
                prompt="describe",
                backend_type=None,
            )

            mock_openai.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_openai_on_native_error(self, fake_image):
        """If native backend raises an error, falls back to OpenAI gpt-5.2."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_claude", new_callable=AsyncMock) as mock_claude,
            patch("massgen.tool._multimodal_tools.understand_image.call_openai", new_callable=AsyncMock) as mock_openai,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_load.return_value = _make_loaded_image()
            mock_claude.side_effect = Exception("Model does not support image input")
            mock_openai.return_value = ("OpenAI fallback after error", "resp_err")

            result = await understand_image(
                image_path=str(fake_image),
                prompt="describe",
                backend_type="claude",
                model="claude-haiku-3",
            )

            # Native backend was attempted
            mock_claude.assert_called_once()
            # Fell back to OpenAI
            mock_openai.assert_called_once()
            call_args = mock_openai.call_args
            assert call_args[0][2] == "gpt-5.2"
            # Result should still be successful
            data = json.loads(result.output_blocks[0].data)
            assert data["success"]
            assert data["response"] == "OpenAI fallback after error"


# ---------------------------------------------------------------------------
# Wiring tests - verify read_media passes backend_type to understand_image
# ---------------------------------------------------------------------------


class TestReadMediaWiring:
    """Test that read_media passes backend_type and model to understand_image."""

    @pytest.mark.asyncio
    async def test_single_file_passes_backend_type(self, fake_image):
        """read_media single-file mode passes backend_type to understand_image."""
        from massgen.tool._multimodal_tools.read_media import read_media

        with (
            patch("massgen.context.task_context.load_task_context_with_warning") as mock_ctx,
            patch("massgen.tool._multimodal_tools.understand_image.call_openai", new_callable=AsyncMock) as mock_openai,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_ctx.return_value = ("some context", None)
            mock_load.return_value = _make_loaded_image()
            mock_openai.return_value = ("analysis", "resp_an")

            result = await read_media(
                file_path=str(fake_image),
                prompt="describe",
                backend_type="openai",
                model="gpt-5.2",
                agent_cwd=str(fake_image.parent),
            )

            data = json.loads(result.output_blocks[0].data)
            assert data["success"]
            mock_openai.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_file_passes_claude_backend(self, fake_image):
        """read_media with backend_type=claude routes to call_claude."""
        from massgen.tool._multimodal_tools.read_media import read_media

        with (
            patch("massgen.context.task_context.load_task_context_with_warning") as mock_ctx,
            patch("massgen.tool._multimodal_tools.understand_image.call_claude", new_callable=AsyncMock) as mock_claude,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_ctx.return_value = ("some context", None)
            mock_load.return_value = _make_loaded_image()
            mock_claude.return_value = ("claude analysis", None)

            result = await read_media(
                file_path=str(fake_image),
                prompt="describe",
                backend_type="claude",
                model="claude-sonnet-4-5",
                agent_cwd=str(fake_image.parent),
            )

            data = json.loads(result.output_blocks[0].data)
            assert data["success"]
            mock_claude.assert_called_once()

    @pytest.mark.asyncio
    async def test_config_model_overrides_agent_model(self, fake_image):
        """multimodal_config image model overrides the agent's model."""
        from massgen.tool._multimodal_tools.read_media import read_media

        with (
            patch("massgen.context.task_context.load_task_context_with_warning") as mock_ctx,
            patch("massgen.tool._multimodal_tools.understand_image.call_openai", new_callable=AsyncMock) as mock_openai,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_ctx.return_value = ("some context", None)
            mock_load.return_value = _make_loaded_image()
            mock_openai.return_value = ("analysis", "resp_an")

            await read_media(
                file_path=str(fake_image),
                prompt="describe",
                backend_type="openai",
                model="gpt-5.2",
                multimodal_config={"image": {"model": "gpt-4.1"}},
                agent_cwd=str(fake_image.parent),
            )

            # The config model override should be passed
            call_args = mock_openai.call_args
            # Positional args: (loaded_images, prompt, model)
            assert call_args[0][2] == "gpt-4.1"

    @pytest.mark.asyncio
    async def test_batch_passes_backend_type(self, fake_image):
        """read_media batch mode passes backend_type to understand_image."""
        from massgen.tool._multimodal_tools.read_media import read_media

        with (
            patch("massgen.context.task_context.load_task_context_with_warning") as mock_ctx,
            patch("massgen.tool._multimodal_tools.understand_image.call_claude", new_callable=AsyncMock) as mock_claude,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
        ):
            mock_ctx.return_value = ("some context", None)
            mock_load.return_value = _make_loaded_image()
            mock_claude.return_value = ("batch analysis", None)

            result = await read_media(
                inputs=[{"files": {"img": str(fake_image)}, "prompt": "describe"}],
                backend_type="claude",
                model="claude-sonnet-4-5",
                agent_cwd=str(fake_image.parent),
            )

            data = json.loads(result.output_blocks[0].data)
            assert data["success"]
            mock_claude.assert_called_once()


# ---------------------------------------------------------------------------
# Video routing tests
# ---------------------------------------------------------------------------


class TestVideoRouting:
    """Test that understand_video prefers agent backend when capable."""

    @pytest.mark.asyncio
    async def test_prefers_agent_backend_when_capable(self, tmp_path):
        """When backend_type has video_understanding, skip backend_selector.

        Claude has video_understanding in capabilities, so it should be used directly.
        """
        from massgen.tool._multimodal_tools.understand_video import understand_video

        # Create a dummy video file
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 100)

        with (
            patch("massgen.tool._multimodal_tools.understand_video._process_with_anthropic", new_callable=AsyncMock) as mock_claude,
            patch("massgen.tool._multimodal_tools.understand_video.get_backend") as mock_selector,
            patch("massgen.tool._multimodal_tools.understand_video.extract_frames") as mock_extract,
        ):
            mock_claude.return_value = "claude video analysis"
            mock_selector.return_value = None
            mock_extract.return_value = ["fake_frame_base64"]

            result = await understand_video(
                video_path=str(video_file),
                prompt="describe",
                backend_type="claude",
                model="claude-sonnet-4-5",
            )

            data = json.loads(result.output_blocks[0].data)
            assert data["success"]
            assert data["backend"] == "claude"
            # backend_selector should NOT have been called
            mock_selector.assert_not_called()
            mock_claude.assert_called_once()


# ---------------------------------------------------------------------------
# Image backend function unit tests (mocked API clients)
# ---------------------------------------------------------------------------


class TestImageBackendFunctions:
    """Unit tests for individual backend calling functions."""

    @pytest.mark.asyncio
    async def test_call_openai_constructs_correct_payload(self):
        """call_openai sends correct content format to OpenAI Responses API."""
        loaded = _make_loaded_image()

        with patch("massgen.tool._multimodal_tools.image_backends.os.getenv", return_value="fake-key"):
            with patch("openai.AsyncOpenAI") as MockClient:
                mock_response = MagicMock()
                mock_response.output_text = "OpenAI response"
                mock_client = MockClient.return_value
                mock_client.responses = MagicMock()
                mock_client.responses.create = AsyncMock(return_value=mock_response)

                from massgen.tool._multimodal_tools.image_backends import call_openai

                result = await call_openai([loaded], "describe", "gpt-5.2")

                assert result[0] == "OpenAI response"
                mock_client.responses.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_claude_constructs_correct_payload(self):
        """call_claude sends correct content blocks to Anthropic API."""
        loaded = _make_loaded_image()

        with patch("massgen.tool._multimodal_tools.image_backends.os.getenv", return_value="fake-key"):
            with patch("anthropic.AsyncAnthropic") as MockClient:
                mock_response = MagicMock()
                mock_response.content = [MagicMock(text="Claude response")]
                mock_client = MockClient.return_value
                mock_client.messages = MagicMock()
                mock_client.messages.create = AsyncMock(return_value=mock_response)

                from massgen.tool._multimodal_tools.image_backends import call_claude

                result = await call_claude([loaded], "describe", "claude-sonnet-4-5")

                assert result[0] == "Claude response"
                mock_client.messages.create.assert_called_once()
                call_kwargs = mock_client.messages.create.call_args[1]
                assert call_kwargs["model"] == "claude-sonnet-4-5"
                # Verify content has image block + text block
                content = call_kwargs["messages"][0]["content"]
                assert content[0]["type"] == "image"
                assert content[-1]["type"] == "text"

    @pytest.mark.asyncio
    async def test_call_gemini_constructs_correct_payload(self):
        """call_gemini sends correct Part format to Gemini API."""
        loaded = _make_loaded_image()

        with patch("massgen.tool._multimodal_tools.image_backends.os.getenv", return_value="fake-key"):
            with patch("google.genai.Client") as MockClient:
                mock_response = MagicMock()
                mock_response.text = "Gemini response"
                mock_client = MockClient.return_value
                mock_client.models = MagicMock()
                mock_client.models.generate_content = MagicMock(return_value=mock_response)

                with patch("google.genai.types.Part.from_bytes") as mock_from_bytes:
                    mock_from_bytes.return_value = MagicMock()

                    from massgen.tool._multimodal_tools.image_backends import (
                        call_gemini,
                    )

                    result = await call_gemini([loaded], "describe", "gemini-3-flash-preview")

                    assert result[0] == "Gemini response"
                    mock_client.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_grok_constructs_correct_payload(self):
        """call_grok sends correct OpenAI-compatible format to Grok."""
        loaded = _make_loaded_image()

        with patch("massgen.tool._multimodal_tools.image_backends.os.getenv", return_value="fake-key"):
            with patch("openai.AsyncOpenAI") as MockClient:
                mock_response = MagicMock()
                mock_response.choices = [MagicMock(message=MagicMock(content="Grok response"))]
                mock_client = MockClient.return_value
                mock_client.chat = MagicMock()
                mock_client.chat.completions = MagicMock()
                mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

                from massgen.tool._multimodal_tools.image_backends import call_grok

                result = await call_grok([loaded], "describe", "grok-4")

                assert result[0] == "Grok response"
                MockClient.assert_called_once()
                call_kwargs = MockClient.call_args[1]
                assert "x.ai" in call_kwargs["base_url"]


# ---------------------------------------------------------------------------
# Sandbox security tests
# ---------------------------------------------------------------------------


class TestSandboxSecurity:
    """Verify that Claude Code and Codex backends are properly sandboxed."""

    @pytest.mark.asyncio
    async def test_claude_code_only_allows_read_tool(self):
        """Claude Code SDK options must restrict allowed_tools to ['Read'] only."""
        loaded = _make_loaded_image()
        captured_options = {}

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.query = AsyncMock()

        # Mock ResultMessage class for isinstance checks
        class FakeResultMessage:
            pass

        async def fake_receive():
            yield FakeResultMessage()

        mock_client.receive_response = fake_receive

        def make_options(**kwargs):
            captured_options["kwargs"] = dict(kwargs)
            opts = MagicMock()
            for k, v in kwargs.items():
                setattr(opts, k, v)
            return opts

        def capture_client(options):
            return mock_client

        # Patch at the import source since imports are lazy (inside function body)
        with (
            patch("claude_agent_sdk.ClaudeSDKClient", side_effect=capture_client),
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=make_options),
            patch("claude_agent_sdk.ResultMessage", FakeResultMessage),
            patch("claude_agent_sdk.AssistantMessage", MagicMock),
            patch("claude_agent_sdk.UserMessage", MagicMock),
            patch("claude_agent_sdk.TextBlock", MagicMock),
            patch("massgen.tool._multimodal_tools.image_backends.shutil.copy2"),
        ):
            from massgen.tool._multimodal_tools.image_backends import call_claude_code

            await call_claude_code([loaded], "describe", model=None, agent_cwd="/tmp")

        assert captured_options["kwargs"]["allowed_tools"] == ["Read"]
        assert "max_turns" not in captured_options["kwargs"]

    @pytest.mark.asyncio
    async def test_claude_code_uses_temp_dir_not_agent_cwd(self):
        """Claude Code cwd should be a temp dir, not the agent's working directory."""
        loaded = _make_loaded_image()
        captured_cwd = {}

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.query = AsyncMock()

        class FakeResultMessage:
            pass

        async def fake_receive():
            yield FakeResultMessage()

        mock_client.receive_response = fake_receive

        def capture_client(options):
            captured_cwd["cwd"] = options.cwd
            return mock_client

        with (
            patch("claude_agent_sdk.ClaudeSDKClient", side_effect=capture_client),
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=lambda **kw: MagicMock(**kw)),
            patch("claude_agent_sdk.ResultMessage", FakeResultMessage),
            patch("claude_agent_sdk.AssistantMessage", MagicMock),
            patch("claude_agent_sdk.UserMessage", MagicMock),
            patch("claude_agent_sdk.TextBlock", MagicMock),
            patch("massgen.tool._multimodal_tools.image_backends.shutil.copy2"),
        ):
            from massgen.tool._multimodal_tools.image_backends import call_claude_code

            await call_claude_code([loaded], "describe", model=None, agent_cwd="/home/user/project")

        # cwd should NOT be the agent's working directory
        assert captured_cwd["cwd"] != "/home/user/project"
        assert captured_cwd["cwd"] is not None

    @pytest.mark.asyncio
    async def test_codex_command_has_sandbox_flags(self):
        """Codex CLI command must include --skip-git-repo-check, --disable shell_tool, and web_search disabled."""
        loaded = _make_loaded_image()
        captured = {}

        def fake_subprocess_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = kwargs.get("env")
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "Codex response"
            mock_result.stderr = ""
            return mock_result

        with (
            patch("massgen.tool._multimodal_tools.image_backends.subprocess.run", side_effect=fake_subprocess_run),
            patch("massgen.tool._multimodal_tools.image_backends.shutil.copy2"),
            patch("massgen.tool._multimodal_tools.image_backends.Path.home", return_value=Path("/fake/home")),
        ):
            from massgen.tool._multimodal_tools.image_backends import call_codex

            await call_codex([loaded], "describe", agent_cwd="/home/user/project")

        cmd = captured["cmd"]
        assert "--skip-git-repo-check" in cmd, "Missing --skip-git-repo-check"
        assert "--disable" in cmd, "Missing --disable flag"
        # --disable should be followed by shell_tool
        disable_idx = cmd.index("--disable")
        assert cmd[disable_idx + 1] == "shell_tool", f"--disable should disable shell_tool, got: {cmd[disable_idx + 1]}"
        assert "--full-auto" in cmd, "Missing --full-auto"
        # web_search should be disabled via -c flag
        assert "-c" in cmd, "Missing -c flag for web_search"
        c_idx = cmd.index("-c")
        assert "web_search" in cmd[c_idx + 1] and "disabled" in cmd[c_idx + 1], f"web_search not disabled in -c arg: {cmd[c_idx + 1]}"

    @pytest.mark.asyncio
    async def test_codex_sets_codex_home_env(self):
        """Codex subprocess must have CODEX_HOME pointing to .codex inside temp dir."""
        loaded = _make_loaded_image()
        captured = {}

        def fake_subprocess_run(cmd, **kwargs):
            captured["env"] = kwargs.get("env")
            captured["cwd"] = kwargs.get("cwd")
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "response"
            mock_result.stderr = ""
            return mock_result

        with (
            patch("massgen.tool._multimodal_tools.image_backends.subprocess.run", side_effect=fake_subprocess_run),
            patch("massgen.tool._multimodal_tools.image_backends.shutil.copy2"),
            patch("massgen.tool._multimodal_tools.image_backends.Path.home", return_value=Path("/fake/home")),
        ):
            from massgen.tool._multimodal_tools.image_backends import call_codex

            await call_codex([loaded], "describe", agent_cwd="/home/user/project")

        env = captured["env"]
        assert "CODEX_HOME" in env, "CODEX_HOME not set in subprocess env"
        # CODEX_HOME should be .codex inside temp dir (not agent cwd or ~/.codex)
        assert env["CODEX_HOME"].endswith(".codex")
        assert "/home/user/project" not in env["CODEX_HOME"]

    @pytest.mark.asyncio
    async def test_codex_uses_temp_dir_not_agent_cwd(self):
        """Codex cwd should be a temp dir, not the agent's working directory."""
        loaded = _make_loaded_image()
        captured_cwd = {}

        def fake_subprocess_run(cmd, **kwargs):
            captured_cwd["cwd"] = kwargs.get("cwd")
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "response"
            mock_result.stderr = ""
            return mock_result

        with (
            patch("massgen.tool._multimodal_tools.image_backends.subprocess.run", side_effect=fake_subprocess_run),
            patch("massgen.tool._multimodal_tools.image_backends.shutil.copy2"),
            patch("massgen.tool._multimodal_tools.image_backends.Path.home", return_value=Path("/fake/home")),
        ):
            from massgen.tool._multimodal_tools.image_backends import call_codex

            await call_codex([loaded], "describe", agent_cwd="/home/user/project")

        assert captured_cwd["cwd"] != "/home/user/project"
        assert captured_cwd["cwd"] is not None


# ---------------------------------------------------------------------------
# Live API tests (opt-in, expensive)
# ---------------------------------------------------------------------------

TEST_IMAGE_PATH = Path(__file__).parent.parent / "configs" / "resources" / "v0.0.27-example" / "multimodality.jpg"


@pytest.mark.live_api
@pytest.mark.expensive
class TestLiveAPICalls:
    """Live API tests for image understanding backends.

    Run with: uv run pytest -m "live_api and expensive" -v
    """

    @pytest.mark.asyncio
    async def test_call_openai_live(self):
        import os

        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

        from massgen.tool._multimodal_tools.image_backends import call_openai
        from massgen.tool._multimodal_tools.understand_image import (
            _load_and_process_image,
        )

        loaded = _load_and_process_image(str(TEST_IMAGE_PATH), TEST_IMAGE_PATH.parent)
        result = await call_openai([loaded], "Describe this image briefly.", "gpt-4.1")
        print(f"\n{'='*60}")
        print("OPENAI (gpt-4.1) response:")
        print(f"{'='*60}")
        print(result)
        print(f"{'='*60}\n")
        assert isinstance(result, str)
        assert len(result) > 10

    @pytest.mark.asyncio
    async def test_call_claude_live(self):
        import os

        if not os.getenv("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set")

        from massgen.tool._multimodal_tools.image_backends import call_claude
        from massgen.tool._multimodal_tools.understand_image import (
            _load_and_process_image,
        )

        loaded = _load_and_process_image(str(TEST_IMAGE_PATH), TEST_IMAGE_PATH.parent)
        result = await call_claude([loaded], "Describe this image briefly.", "claude-sonnet-4-5")
        print(f"\n{'='*60}")
        print("CLAUDE (claude-sonnet-4-5) response:")
        print(f"{'='*60}")
        print(result)
        print(f"{'='*60}\n")
        assert isinstance(result, str)
        assert len(result) > 10

    @pytest.mark.asyncio
    async def test_call_gemini_live(self):
        import os

        if not os.getenv("GOOGLE_API_KEY") and not os.getenv("GEMINI_API_KEY"):
            pytest.skip("GOOGLE_API_KEY/GEMINI_API_KEY not set")

        from massgen.tool._multimodal_tools.image_backends import call_gemini
        from massgen.tool._multimodal_tools.understand_image import (
            _load_and_process_image,
        )

        loaded = _load_and_process_image(str(TEST_IMAGE_PATH), TEST_IMAGE_PATH.parent)
        result = await call_gemini([loaded], "Describe this image briefly.", "gemini-3-flash-preview")
        print(f"\n{'='*60}")
        print("GEMINI (gemini-3-flash-preview) response:")
        print(f"{'='*60}")
        print(result)
        print(f"{'='*60}\n")
        assert isinstance(result, str)
        assert len(result) > 10

    @pytest.mark.asyncio
    async def test_call_grok_live(self):
        import os

        if not os.getenv("XAI_API_KEY"):
            pytest.skip("XAI_API_KEY not set")

        from massgen.tool._multimodal_tools.image_backends import call_grok
        from massgen.tool._multimodal_tools.understand_image import (
            _load_and_process_image,
        )

        loaded = _load_and_process_image(str(TEST_IMAGE_PATH), TEST_IMAGE_PATH.parent)
        result = await call_grok([loaded], "Describe this image briefly.", "grok-4")
        print(f"\n{'='*60}")
        print("GROK (grok-4) response:")
        print(f"{'='*60}")
        print(result)
        print(f"{'='*60}\n")
        assert isinstance(result, str)
        assert len(result) > 10

    @pytest.mark.asyncio
    async def test_call_claude_code_live(self):
        """Live test for Claude Code SDK image understanding.

        Requires: claude CLI installed and authenticated (`claude login`),
        or ANTHROPIC_API_KEY / CLAUDE_CODE_API_KEY set.
        """
        import logging
        import shutil

        if not shutil.which("claude"):
            pytest.skip("claude CLI not installed (run: npm install -g @anthropic-ai/claude-code)")

        # Enable debug logging so we see SDK message types
        logging.getLogger("massgen").setLevel(logging.DEBUG)

        from claude_agent_sdk import (
            ClaudeAgentOptions,
            ClaudeSDKClient,
            ResultMessage,
            TextBlock,
        )

        from massgen.tool._multimodal_tools.understand_image import (
            _load_and_process_image,
        )

        loaded = _load_and_process_image(str(TEST_IMAGE_PATH), TEST_IMAGE_PATH.parent)

        # Run the SDK directly so we can inspect every message
        import tempfile

        tmpdir = tempfile.mkdtemp()
        dest = Path(tmpdir) / loaded.path.name
        shutil.copy2(loaded.path, dest)

        options = ClaudeAgentOptions(
            allowed_tools=["Read"],
            cwd=tmpdir,
            env={"CLAUDECODE": ""},
        )
        client = ClaudeSDKClient(options)

        print(f"\n{'='*60}")
        print("CLAUDE CODE SDK - raw message dump")
        print(f"{'='*60}")

        try:
            await client.connect()
            await client.query(
                f"Read and analyze the image(s) in this directory: {dest.name}\n\nDescribe this image briefly.",
            )

            response_text = ""
            msg_count = 0
            async for msg in client.receive_response():
                msg_count += 1
                msg_type = type(msg).__name__
                has_content = hasattr(msg, "content")
                print(f"\n--- Message #{msg_count}: {msg_type} (has content={has_content}) ---")

                if has_content and msg.content:
                    for i, block in enumerate(msg.content):
                        block_type = type(block).__name__
                        has_text = hasattr(block, "text")
                        is_textblock = isinstance(block, TextBlock)
                        text_preview = ""
                        if has_text and block.text:
                            text_preview = block.text[:200]
                        print(
                            f"  block[{i}]: {block_type}, " f"isinstance(TextBlock)={is_textblock}, " f"has .text={has_text}, " f"text={text_preview!r}",
                        )
                        # Dump all attributes for tool blocks
                        if block_type in ("ToolUseBlock", "ToolResultBlock"):
                            for attr in ("name", "input", "tool_use_id", "content", "is_error", "type"):
                                if hasattr(block, attr):
                                    val = getattr(block, attr)
                                    val_str = str(val)[:300] if val else str(val)
                                    print(f"    .{attr} = {val_str}")
                        if isinstance(block, TextBlock) and block.text:
                            response_text += block.text
                elif has_content:
                    print("  content is empty/None")

                if hasattr(msg, "usage") and msg.usage:
                    print(f"  usage: {msg.usage}")

                if isinstance(msg, ResultMessage):
                    print("  -> ResultMessage, breaking")
                    break
        finally:
            await client.disconnect()

        print(f"\n{'='*60}")
        print(f"Total messages: {msg_count}")
        print(f"Collected response length: {len(response_text)}")
        print(f"Response text: {response_text[:500]!r}")
        print(f"{'='*60}\n")

        assert isinstance(response_text, str)
        assert len(response_text) > 10, f"Expected response text > 10 chars, got {len(response_text)}: {response_text!r}"

    @pytest.mark.asyncio
    async def test_call_codex_live(self):
        """Live test for Codex CLI image understanding.

        Requires: codex CLI installed (`npm install -g @openai/codex`)
        and authenticated (`codex login` or OPENAI_API_KEY set).
        """
        import shutil
        import subprocess

        if not shutil.which("codex"):
            pytest.skip("codex CLI not installed (run: npm install -g @openai/codex)")

        from massgen.tool._multimodal_tools.understand_image import (
            _load_and_process_image,
        )

        loaded = _load_and_process_image(str(TEST_IMAGE_PATH), TEST_IMAGE_PATH.parent)

        # Use the image in-place (no temp dir) to test without isolation
        image_path = str(loaded.path)
        work_dir = str(TEST_IMAGE_PATH.parent)

        prompt = "Describe this image briefly."
        cmd = [
            "codex",
            "exec",
            prompt,
            "--full-auto",
            "--skip-git-repo-check",
            "--disable",
            "shell_tool",
            "-c",
            "web_search=disabled",
            "--image",
            image_path,
        ]

        env = {**os.environ, "NO_COLOR": "1"}

        print(f"\n{'='*60}")
        print("CODEX CLI - debug info (no temp dir)")
        print(f"{'='*60}")
        print(f"image_path: {image_path}")
        print(f"image exists: {Path(image_path).exists()} ({Path(image_path).stat().st_size} bytes)")
        print(f"work_dir: {work_dir}")
        print(f"cmd: {cmd}")
        print(f"{'='*60}")

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=work_dir,
            env=env,
            timeout=120,
        )

        print(f"\nreturncode: {proc.returncode}")
        print(f"stdout length: {len(proc.stdout)}")
        print(f"stdout: {proc.stdout[:1000]!r}")
        print(f"stderr length: {len(proc.stderr)}")
        print(f"stderr: {proc.stderr[:1000]!r}")
        print(f"{'='*60}\n")

        assert proc.returncode == 0, f"Codex CLI failed (exit {proc.returncode}): {proc.stderr}"
        assert isinstance(proc.stdout, str)
        assert len(proc.stdout) > 10
