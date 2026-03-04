"""Tests for read_media structured analysis improvements.

Covers:
- Part 1: Always-on vision system prompt + better default prompt
- Part 2: Feedback-to-action pipeline (evidence-based findings, foundation warning,
          multimodal-aware diagnostic report gate)
"""

# ===========================================================================
# Part 1: Vision System Prompt and Default Prompt
# ===========================================================================


class TestVisionSystemPrompt:
    """The vision system prompt exists, is general, and contains key elements."""

    def test_system_prompt_exists(self):
        from massgen.tool._multimodal_tools.analysis_prompts import (
            VISION_SYSTEM_PROMPT,
        )

        assert isinstance(VISION_SYSTEM_PROMPT, str)
        assert len(VISION_SYSTEM_PROMPT) > 30

    def test_system_prompt_mentions_critical(self):
        """Should instruct the model to be critical/honest."""
        from massgen.tool._multimodal_tools.analysis_prompts import (
            VISION_SYSTEM_PROMPT,
        )

        prompt_lower = VISION_SYSTEM_PROMPT.lower()
        assert "critical" in prompt_lower or "honest" in prompt_lower

    def test_system_prompt_distinguishes_severity(self):
        """Should distinguish fundamental issues from surface fixes."""
        from massgen.tool._multimodal_tools.analysis_prompts import (
            VISION_SYSTEM_PROMPT,
        )

        prompt_lower = VISION_SYSTEM_PROMPT.lower()
        assert "fundamental" in prompt_lower or "foundation" in prompt_lower

    def test_system_prompt_is_domain_agnostic(self):
        """Must NOT contain domain-specific language."""
        from massgen.tool._multimodal_tools.analysis_prompts import (
            VISION_SYSTEM_PROMPT,
        )

        prompt_lower = VISION_SYSTEM_PROMPT.lower()
        assert "website" not in prompt_lower
        assert "typography" not in prompt_lower
        assert "css" not in prompt_lower
        assert "html" not in prompt_lower
        assert "color palette" not in prompt_lower


class TestImprovedDefaultPrompt:
    """The default prompt is critical, not descriptive."""

    def test_default_prompt_exists(self):
        from massgen.tool._multimodal_tools.analysis_prompts import (
            DEFAULT_MEDIA_PROMPT_TEMPLATE,
        )

        assert isinstance(DEFAULT_MEDIA_PROMPT_TEMPLATE, str)

    def test_default_prompt_is_critical(self):
        """Default prompt should ask for critical analysis, not just description."""
        from massgen.tool._multimodal_tools.analysis_prompts import (
            DEFAULT_MEDIA_PROMPT_TEMPLATE,
        )

        prompt = DEFAULT_MEDIA_PROMPT_TEMPLATE.format(media_type="image")
        prompt_lower = prompt.lower()
        assert "describe its contents" not in prompt_lower
        assert "critical" in prompt_lower or "demanding" in prompt_lower

    def test_default_prompt_uses_media_type(self):
        from massgen.tool._multimodal_tools.analysis_prompts import (
            DEFAULT_MEDIA_PROMPT_TEMPLATE,
        )

        assert "{media_type}" in DEFAULT_MEDIA_PROMPT_TEMPLATE


# ===========================================================================
# Part 1: Backend system_prompt parameter
# ===========================================================================


class TestBackendSystemPromptParam:
    """All call_* functions in image_backends.py accept system_prompt."""

    def test_call_openai_accepts_system_prompt(self):
        import inspect

        from massgen.tool._multimodal_tools.image_backends import call_openai

        sig = inspect.signature(call_openai)
        assert "system_prompt" in sig.parameters

    def test_call_claude_accepts_system_prompt(self):
        import inspect

        from massgen.tool._multimodal_tools.image_backends import call_claude

        sig = inspect.signature(call_claude)
        assert "system_prompt" in sig.parameters

    def test_call_gemini_accepts_system_prompt(self):
        import inspect

        from massgen.tool._multimodal_tools.image_backends import call_gemini

        sig = inspect.signature(call_gemini)
        assert "system_prompt" in sig.parameters

    def test_call_grok_accepts_system_prompt(self):
        import inspect

        from massgen.tool._multimodal_tools.image_backends import call_grok

        sig = inspect.signature(call_grok)
        assert "system_prompt" in sig.parameters

    def test_call_claude_code_accepts_system_prompt(self):
        import inspect

        from massgen.tool._multimodal_tools.image_backends import call_claude_code

        sig = inspect.signature(call_claude_code)
        assert "system_prompt" in sig.parameters

    def test_call_codex_accepts_system_prompt(self):
        import inspect

        from massgen.tool._multimodal_tools.image_backends import call_codex

        sig = inspect.signature(call_codex)
        assert "system_prompt" in sig.parameters


# ===========================================================================
# Part 1: Severity parsing and foundation warning
# ===========================================================================


class TestSeverityParsing:
    """read_media best-effort parses severity from vision model responses."""

    def test_parse_valid_severity_json(self):
        from massgen.tool._multimodal_tools.read_media import (
            _parse_severity_summary,
        )

        response = "Analysis here...\n" '```json\n{"foundation_issues": 1, "structural_issues": 2, ' '"surface_issues": 3, "foundation_sound": false}\n```'
        result = _parse_severity_summary(response)
        assert result is not None
        assert result["foundation_sound"] is False

    def test_parse_missing_json_returns_none(self):
        from massgen.tool._multimodal_tools.read_media import (
            _parse_severity_summary,
        )

        result = _parse_severity_summary("Analysis with no JSON block at all.")
        assert result is None

    def test_parse_malformed_json_returns_none(self):
        from massgen.tool._multimodal_tools.read_media import (
            _parse_severity_summary,
        )

        result = _parse_severity_summary('```json\n{"bad": }\n```')
        assert result is None

    def test_parse_json_without_code_fence(self):
        from massgen.tool._multimodal_tools.read_media import (
            _parse_severity_summary,
        )

        response = "Analysis...\n" '{"foundation_issues": 0, "structural_issues": 1, ' '"surface_issues": 2, "foundation_sound": true}'
        result = _parse_severity_summary(response)
        assert result is not None
        assert result["foundation_sound"] is True


class TestFoundationWarning:
    """Foundation warning is added to results when foundation is unsound."""

    def test_warning_added_when_foundation_unsound(self):
        from massgen.tool._multimodal_tools.read_media import (
            _maybe_add_severity_fields,
        )

        result = {"response": "text"}
        severity = {"foundation_sound": False, "foundation_issues": 2}
        _maybe_add_severity_fields(result, severity)
        assert "foundation_warning" in result

    def test_no_warning_when_foundation_sound(self):
        from massgen.tool._multimodal_tools.read_media import (
            _maybe_add_severity_fields,
        )

        result = {"response": "text"}
        severity = {"foundation_sound": True, "foundation_issues": 0}
        _maybe_add_severity_fields(result, severity)
        assert "foundation_warning" not in result

    def test_severity_summary_added_to_result(self):
        from massgen.tool._multimodal_tools.read_media import (
            _maybe_add_severity_fields,
        )

        result = {"response": "text"}
        severity = {"foundation_sound": False, "foundation_issues": 1}
        _maybe_add_severity_fields(result, severity)
        assert result["severity_summary"] == severity


# ===========================================================================
# Part 2: Feedback-to-Action Pipeline
# ===========================================================================


class TestEvidenceBasedFindings:
    """GEPA sections instruct agents to include read_media findings."""

    def test_checklist_analysis_has_evidence_instruction(self):
        from massgen.system_prompt_sections import _build_checklist_analysis

        content = _build_checklist_analysis()
        assert "Evidence-Based Findings" in content

    def test_changedoc_analysis_has_evidence_instruction(self):
        from massgen.system_prompt_sections import (
            _build_changedoc_checklist_analysis,
        )

        content = _build_changedoc_checklist_analysis()
        assert "Evidence-Based Findings" in content

    def test_evidence_instruction_mentions_read_media(self):
        from massgen.system_prompt_sections import _build_checklist_analysis

        content = _build_checklist_analysis()
        assert "read_media" in content

    def test_evidence_instruction_mentions_foundation(self):
        """Should mention foundation-level issues from read_media."""
        from massgen.system_prompt_sections import _build_checklist_analysis

        content = _build_checklist_analysis().lower()
        assert "foundation" in content


class TestMultimodalToolsSectionUpdated:
    """MultimodalToolsSection has updated guidance."""

    def test_mentions_foundation_issues(self):
        from massgen.system_prompt_sections import MultimodalToolsSection

        section = MultimodalToolsSection()
        content = section.build_content().lower()
        assert "foundation" in content or "fundamental" in content

    def test_has_domain_prompt_examples(self):
        """Should include examples of good prompts for different domains."""
        from massgen.system_prompt_sections import MultimodalToolsSection

        section = MultimodalToolsSection()
        content = section.build_content().lower()
        assert "example" in content or "e.g." in content


class TestMultimodalDiagnosticReportGate:
    """Diagnostic report has higher quality bar when multimodal tools available."""

    def test_higher_min_length_with_multimodal(self, tmp_path):
        from massgen.mcp_tools.checklist_tools_server import _evaluate_gap_report

        report = tmp_path / "diagnostic.md"
        report.write_text("x" * 150)  # >100 but <300

        state = {
            "require_diagnostic_report": True,
            "has_multimodal_tools": True,
            "workspace_path": str(tmp_path),
        }
        result = _evaluate_gap_report(str(report), state)
        assert result["passed"] is False

    def test_normal_min_length_without_multimodal(self, tmp_path):
        from massgen.mcp_tools.checklist_tools_server import _evaluate_gap_report

        report = tmp_path / "diagnostic.md"
        report.write_text("x" * 150)

        state = {
            "require_diagnostic_report": True,
            "has_multimodal_tools": False,
            "workspace_path": str(tmp_path),
        }
        result = _evaluate_gap_report(str(report), state)
        assert result["passed"] is True


# ===========================================================================
# Video System Prompt Parity
# ===========================================================================


class TestVideoSystemPromptParity:
    """Video analysis gets the same critical framing as image analysis."""

    def test_understand_video_accepts_system_prompt(self):
        """understand_video() must accept a system_prompt parameter."""
        import inspect

        from massgen.tool._multimodal_tools.understand_video import (
            understand_video,
        )

        sig = inspect.signature(understand_video)
        assert "system_prompt" in sig.parameters

    def test_video_default_model_is_pro(self):
        """Gemini default for video should be gemini-3.1-pro-preview (not flash)."""
        from massgen.tool._multimodal_tools.backend_selector import GEMINI_VIDEO

        assert GEMINI_VIDEO.model == "gemini-3.1-pro-preview"

    def test_video_gets_same_system_prompt_as_image(self, tmp_path):
        """read_media passes VISION_SYSTEM_PROMPT to understand_video."""
        import asyncio
        import json
        from unittest.mock import AsyncMock, patch

        from massgen.tool._multimodal_tools.analysis_prompts import (
            VISION_SYSTEM_PROMPT,
        )
        from massgen.tool._multimodal_tools.read_media import read_media

        # Create a fake .mp4 file and CONTEXT.md
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 100)
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text("Test context for video analysis")

        # Mock understand_video to capture kwargs
        mock_result_data = json.dumps(
            {
                "success": True,
                "operation": "understand_video",
                "response": "mock analysis",
            },
        )
        from massgen.tool._result import ExecutionResult, TextContent

        mock_result = ExecutionResult(
            output_blocks=[TextContent(data=mock_result_data)],
        )
        mock_uv = AsyncMock(return_value=mock_result)

        with patch(
            "massgen.tool._multimodal_tools.understand_video.understand_video",
            mock_uv,
        ):
            asyncio.run(
                read_media(
                    file_path="test.mp4",
                    agent_cwd=str(tmp_path),
                    task_context="Test context for video analysis",
                ),
            )

        mock_uv.assert_called_once()
        call_kwargs = mock_uv.call_args
        assert call_kwargs.kwargs.get("system_prompt") == VISION_SYSTEM_PROMPT

    def test_video_default_prompt_is_critical(self, tmp_path):
        """Video should use DEFAULT_MEDIA_PROMPT_TEMPLATE (not the old descriptive default)."""
        import asyncio
        import json
        from unittest.mock import AsyncMock, patch

        from massgen.tool._multimodal_tools.analysis_prompts import (
            DEFAULT_MEDIA_PROMPT_TEMPLATE,
        )
        from massgen.tool._multimodal_tools.read_media import read_media

        # Create a fake .mp4 file and CONTEXT.md
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 100)
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text("Test context for video analysis")

        mock_result_data = json.dumps(
            {
                "success": True,
                "operation": "understand_video",
                "response": "mock analysis",
            },
        )
        from massgen.tool._result import ExecutionResult, TextContent

        mock_result = ExecutionResult(
            output_blocks=[TextContent(data=mock_result_data)],
        )
        mock_uv = AsyncMock(return_value=mock_result)

        with patch(
            "massgen.tool._multimodal_tools.understand_video.understand_video",
            mock_uv,
        ):
            asyncio.run(
                read_media(
                    file_path="test.mp4",
                    agent_cwd=str(tmp_path),
                    task_context="Test context for video analysis",
                ),
            )

        mock_uv.assert_called_once()
        call_kwargs = mock_uv.call_args
        expected_prompt = DEFAULT_MEDIA_PROMPT_TEMPLATE.format(media_type="video")
        assert call_kwargs.kwargs.get("prompt") == expected_prompt

    def test_video_backend_functions_accept_system_prompt(self):
        """All _process_with_* video backend functions accept system_prompt."""
        import inspect

        from massgen.tool._multimodal_tools.understand_video import (
            _process_with_anthropic,
            _process_with_gemini,
            _process_with_grok,
            _process_with_openai,
            _process_with_openrouter,
        )

        for fn in [
            _process_with_gemini,
            _process_with_openai,
            _process_with_anthropic,
            _process_with_grok,
            _process_with_openrouter,
        ]:
            sig = inspect.signature(fn)
            assert "system_prompt" in sig.parameters, f"{fn.__name__} missing system_prompt parameter"


class TestReadMediaStringifiedJsonNormalization:
    """read_media must tolerate `inputs` passed as a stringified JSON list.

    Models (especially via MCP) sometimes serialize list arguments as JSON
    strings rather than native lists. The tool must detect and parse this
    rather than returning a Pydantic validation error.
    """

    def test_stringified_inputs_returns_error_not_type_error(self, tmp_path):
        """Stringified JSON `inputs` should not raise a Pydantic list_type error.

        It should either successfully process or return a meaningful domain
        error (e.g. file not found) — not a Pydantic schema validation failure.
        """
        import asyncio
        import json

        from massgen.tool._multimodal_tools.read_media import read_media

        fake_path = str(tmp_path / "nonexistent.png")
        inputs_as_string = json.dumps(
            [
                {"files": {"agent1": fake_path}, "prompt": "Compare"},
            ],
        )

        result = asyncio.run(
            read_media(inputs=inputs_as_string),  # type: ignore[arg-type]
        )

        output = result.output_blocks[0].data
        # Must NOT be a Pydantic type error
        assert "list_type" not in output
        assert "Input should be a valid list" not in output
        # Should be a domain error (file not found) or success
        assert "success" in output

    def test_stringified_inputs_with_valid_structure_is_normalized(self, tmp_path):
        """Stringified JSON inputs with correct structure should parse cleanly.

        After normalization the tool validates the `files` key normally, so
        a missing-file error is acceptable — it means parsing succeeded.
        """
        import asyncio
        import json

        from massgen.tool._multimodal_tools.read_media import read_media

        fake_path = str(tmp_path / "img.png")
        inputs_as_string = json.dumps(
            [
                {"files": {"a": fake_path, "b": fake_path}, "prompt": "Compare"},
            ],
        )

        result = asyncio.run(
            read_media(inputs=inputs_as_string),  # type: ignore[arg-type]
        )
        output = result.output_blocks[0].data
        # Pydantic list_type error must not appear
        assert "list_type" not in output
        assert "Input should be a valid list" not in output

    def test_mcp_handler_list_params_accept_string(self):
        """_json_schema_to_python_type for array schema should allow strings
        through the MCP registration layer so FastMCP does not reject them."""
        from massgen.mcp_tools.custom_tools_server import _json_schema_to_python_type

        array_schema = {"anyOf": [{"type": "array"}, {"type": "null"}]}
        py_type = _json_schema_to_python_type(array_schema)
        # After fix: should accept str in addition to list (via Any or Union)
        # We verify by checking the type allows str values at runtime
        import typing

        # The type should either be Any or include str in its args
        is_any = py_type is typing.Any
        allows_str = False
        if hasattr(py_type, "__args__"):
            allows_str = str in py_type.__args__ or type(None) not in py_type.__args__
        assert is_any or allows_str, f"Expected list-type schema to allow string normalization, got {py_type}"


class TestReadMediaFilePathsAlias:
    """read_media should accept `file_paths` (list) as an alias for `files` (dict).

    Models sometimes use `file_paths` (plural of the top-level `file_path`)
    instead of the correct `files` dict. Normalizing this silently avoids the
    'inputs[0] missing required files key' error.
    """

    def test_file_paths_list_is_normalized_to_files_dict(self, tmp_path):
        """inputs[i]['file_paths'] as a list should be converted to 'files' dict."""
        import asyncio

        from massgen.tool._multimodal_tools.read_media import read_media

        fake_a = str(tmp_path / "a.png")
        fake_b = str(tmp_path / "b.png")

        result = asyncio.run(
            read_media(inputs=[{"file_paths": [fake_a, fake_b], "prompt": "Compare"}]),
        )
        output = result.output_blocks[0].data
        # Must NOT return the "missing required 'files' key" error
        assert "missing required 'files' key" not in output

    def test_file_paths_alias_produces_named_files(self, tmp_path):
        """After normalization, each path in file_paths becomes a named entry."""

        from massgen.tool._multimodal_tools.read_media import _normalize_inputs_aliases

        fake_a = str(tmp_path / "a.png")
        fake_b = str(tmp_path / "b.png")

        inputs = [{"file_paths": [fake_a, fake_b], "prompt": "Compare"}]
        normalized = _normalize_inputs_aliases(inputs)

        assert "files" in normalized[0]
        assert "file_paths" not in normalized[0]
        files = normalized[0]["files"]
        assert isinstance(files, dict)
        assert set(files.values()) == {fake_a, fake_b}

    def test_files_key_takes_precedence_over_file_paths(self, tmp_path):
        """If both 'files' and 'file_paths' present, 'files' wins."""

        from massgen.tool._multimodal_tools.read_media import _normalize_inputs_aliases

        real = str(tmp_path / "real.png")
        other = str(tmp_path / "other.png")

        inputs = [{"files": {"main": real}, "file_paths": [other], "prompt": "x"}]
        normalized = _normalize_inputs_aliases(inputs)

        assert normalized[0]["files"] == {"main": real}

    def test_non_list_file_paths_is_not_normalized(self, tmp_path):
        """file_paths that is not a list is left alone (will fail validation normally)."""
        from massgen.tool._multimodal_tools.read_media import _normalize_inputs_aliases

        inputs = [{"file_paths": "not_a_list.png", "prompt": "x"}]
        normalized = _normalize_inputs_aliases(inputs)

        # Should not have been converted (will hit normal validation error)
        assert "files" not in normalized[0]
