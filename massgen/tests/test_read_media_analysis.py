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
