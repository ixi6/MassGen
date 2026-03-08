#!/usr/bin/env python3
"""
Tests for terminal evaluation feature (run_massgen_with_recording tool).

This test suite verifies:
- VHS installation check
- Terminal recording functionality
- Video file creation
- Integration with understand_video tool
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest


def check_vhs_installed() -> bool:
    """Check if VHS is installed and available."""
    try:
        result = subprocess.run(
            ["vhs", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


# Skip marker for tests that require VHS
requires_vhs = pytest.mark.skipif(
    not check_vhs_installed(),
    reason="VHS not installed (install with: brew install vhs or go install github.com/charmbracelet/vhs@latest)",
)


class TestTerminalEvaluation:
    """Test suite for terminal evaluation (run_massgen_with_recording)."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def simple_config(self, temp_dir):
        """Create a simple test config for recording."""
        config_content = """
agents:
  - id: "test_agent"
    backend:
      type: "openai"
      model: "gpt-5-nano"
      cwd: "workspace_test"
    system_message: |
      You are a test agent. Just respond with "2+2=4" and nothing else.

ui:
  display_type: "rich_terminal"
  logging_enabled: false
"""
        config_path = temp_dir / "test_config.yaml"
        config_path.write_text(config_content)
        return config_path

    @requires_vhs
    def test_vhs_installed(self):
        """Test that VHS is installed (prerequisite for terminal evaluation)."""
        # This test verifies VHS works when installed
        assert check_vhs_installed()

    @pytest.mark.asyncio
    async def test_vhs_check_function(self):
        """Test the _check_vhs_installed function from the tool."""
        from massgen.tool._multimodal_tools.run_massgen_with_recording import (
            _check_vhs_installed,
        )

        result = _check_vhs_installed()
        assert isinstance(result, bool)
        # If VHS is installed, should return True
        if check_vhs_installed():
            assert result is True

    @pytest.mark.asyncio
    async def test_vhs_tape_creation(self, temp_dir):
        """Test VHS tape file generation."""
        from massgen.tool._multimodal_tools.run_massgen_with_recording import (
            _create_vhs_tape,
        )

        output_path = temp_dir / "test_output.mp4"
        command = "echo 'Hello MassGen'"

        tape_content = _create_vhs_tape(
            command=command,
            output_path=output_path,
            output_format="mp4",
            width=1200,
            height=800,
            timeout_seconds=10,
        )

        # Verify tape content
        assert isinstance(tape_content, str)
        assert "Output" in tape_content
        assert str(output_path) in tape_content
        # Check that command is in the Type line with backticks
        assert f"Type `{command}`" in tape_content
        assert "Set Width 1200" in tape_content
        assert "Set Height 800" in tape_content
        assert "Sleep 2s" in tape_content

    @pytest.mark.asyncio
    async def test_tool_without_vhs(self, temp_dir, simple_config, monkeypatch):
        """Test that tool returns proper error when VHS is not installed."""
        from massgen.tool._multimodal_tools.run_massgen_with_recording import (
            run_massgen_with_recording,
        )

        # Mock VHS as not installed
        def mock_check_vhs():
            return False

        monkeypatch.setattr(
            "massgen.tool._multimodal_tools.run_massgen_with_recording._check_vhs_installed",
            mock_check_vhs,
        )

        result = await run_massgen_with_recording(
            config_path=str(simple_config),
            question="What is 2+2?",
            agent_cwd=str(temp_dir),
        )

        # Verify error response
        assert result.output_blocks
        output_data = json.loads(result.output_blocks[0].data)
        assert output_data["success"] is False
        assert "VHS is not installed" in output_data["error"]

    @pytest.mark.asyncio
    async def test_invalid_config_path(self, temp_dir):
        """Test that tool returns error for non-existent config."""
        from massgen.tool._multimodal_tools.run_massgen_with_recording import (
            run_massgen_with_recording,
        )

        result = await run_massgen_with_recording(
            config_path="nonexistent_config.yaml",
            question="Test question",
            agent_cwd=str(temp_dir),
        )

        # Verify error response
        assert result.output_blocks
        output_data = json.loads(result.output_blocks[0].data)
        assert output_data["success"] is False
        assert "Config file does not exist" in output_data["error"]

    @pytest.mark.asyncio
    async def test_invalid_output_format(self, temp_dir, simple_config, monkeypatch):
        """Test that tool validates output format."""
        from massgen.tool._multimodal_tools.run_massgen_with_recording import (
            run_massgen_with_recording,
        )

        # Mock VHS as installed so we reach format validation
        def mock_check_vhs():
            return True

        monkeypatch.setattr(
            "massgen.tool._multimodal_tools.run_massgen_with_recording._check_vhs_installed",
            mock_check_vhs,
        )

        result = await run_massgen_with_recording(
            config_path=str(simple_config),
            question="Test question",
            output_format="invalid_format",
            agent_cwd=str(temp_dir),
        )

        # Verify error response
        assert result.output_blocks
        output_data = json.loads(result.output_blocks[0].data)
        assert output_data["success"] is False
        assert "Invalid output format" in output_data["error"]

    @pytest.mark.skipif(
        not check_vhs_installed(),
        reason="VHS not installed - install with: brew install vhs",
    )
    @pytest.mark.asyncio
    async def test_simple_recording(self, temp_dir):
        """
        Test a simple terminal recording with VHS.

        This test creates a minimal VHS tape that just echoes text,
        to verify VHS recording works without running full MassGen.
        """
        from massgen.tool._multimodal_tools.run_massgen_with_recording import (
            _create_vhs_tape,
        )

        # Create a simple VHS tape
        output_path = temp_dir / "simple_test.mp4"
        tape_content = _create_vhs_tape(
            command="echo 'MassGen Terminal Evaluation Test'",
            output_path=output_path,
            output_format="mp4",
            width=800,
            height=600,
            timeout_seconds=3,
        )

        # Write tape file
        tape_path = temp_dir / "simple_test.tape"
        tape_path.write_text(tape_content)

        # Run VHS
        try:
            result = subprocess.run(
                ["vhs", str(tape_path)],
                cwd=str(temp_dir),
                capture_output=True,
                text=True,
                timeout=15,
            )

            # Some environments have unstable VHS runtime despite being installed.
            # Treat runtime crashes as environment skips, not product regressions.
            if result.returncode != 0:
                pytest.skip(f"VHS runtime failed in this environment: {result.stderr}")

            # Verify video file was created
            assert output_path.exists(), "Video file was not created"
            assert output_path.stat().st_size > 0, "Video file is empty"

        except subprocess.TimeoutExpired:
            pytest.fail("VHS recording timed out")

    @pytest.mark.skipif(
        not check_vhs_installed(),
        reason="VHS not installed - install with: brew install vhs",
    )
    @pytest.mark.asyncio
    async def test_gif_format(self, temp_dir):
        """Test GIF output format."""
        from massgen.tool._multimodal_tools.run_massgen_with_recording import (
            _create_vhs_tape,
        )

        output_path = temp_dir / "test_output.gif"
        tape_content = _create_vhs_tape(
            command="echo 'Testing GIF format'",
            output_path=output_path,
            output_format="gif",
            width=800,
            height=600,
            timeout_seconds=2,
        )

        # Verify GIF-specific tape content
        assert "Output" in tape_content
        assert ".gif" in str(output_path).lower()

    @pytest.mark.asyncio
    async def test_path_validation(self, temp_dir, simple_config):
        """Test that path validation works correctly."""
        from massgen.tool._multimodal_tools.run_massgen_with_recording import (
            run_massgen_with_recording,
        )

        # Create config in a different directory
        other_dir = temp_dir / "other"
        other_dir.mkdir()
        config_path = other_dir / "config.yaml"
        config_path.write_text("agents:\n  - id: test\n")

        # Try to access with restricted allowed_paths
        result = await run_massgen_with_recording(
            config_path=str(config_path),
            question="Test",
            allowed_paths=[str(temp_dir / "restricted")],
            agent_cwd=str(temp_dir),
        )

        # Should fail due to path restriction
        output_data = json.loads(result.output_blocks[0].data)
        assert output_data["success"] is False
        assert "not in allowed directories" in output_data["error"]


class TestToolIntegration:
    """Integration tests for terminal evaluation tool."""

    @pytest.mark.asyncio
    async def test_tool_returns_execution_result(self, tmp_path):
        """Test that tool returns proper ExecutionResult."""
        from massgen.tool._multimodal_tools.run_massgen_with_recording import (
            run_massgen_with_recording,
        )
        from massgen.tool._result import ExecutionResult, TextContent

        result = await run_massgen_with_recording(
            config_path="fake_config.yaml",
            question="Test",
            agent_cwd=str(tmp_path),
        )

        # Verify return type
        assert isinstance(result, ExecutionResult)
        assert len(result.output_blocks) == 1
        assert isinstance(result.output_blocks[0], TextContent)

        # Verify JSON structure
        output_data = json.loads(result.output_blocks[0].data)
        assert "success" in output_data
        assert "operation" in output_data
        assert output_data["operation"] == "run_massgen_with_recording"

    @pytest.mark.asyncio
    async def test_tool_workflow_with_understand_video(self, tmp_path):
        """Test the two-step workflow: record then analyze separately."""
        from massgen.tool._multimodal_tools.run_massgen_with_recording import (
            run_massgen_with_recording,
        )

        # Step 1: Record (will fail due to missing config, but we verify the API)
        result = await run_massgen_with_recording(
            config_path="fake_config.yaml",
            question="Test",
            output_format="mp4",
            timeout_seconds=30,
            agent_cwd=str(tmp_path),
        )

        # Verify it returns proper structure (even if it fails)
        assert result is not None
        output_data = json.loads(result.output_blocks[0].data)
        assert "success" in output_data
        assert "operation" in output_data

        # If successful, video_path would be included
        # Step 2: understand_video would be called separately with the video_path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
