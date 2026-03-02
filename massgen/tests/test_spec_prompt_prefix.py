"""Unit tests for spec creation prompt prefix."""

from massgen.cli import get_spec_creation_prompt_prefix


class TestSpecCreationPromptPrefix:
    """Test spec mode prompt prefix generation."""

    def test_default_broadcast_uses_scope_analysis(self):
        prefix = get_spec_creation_prompt_prefix()
        assert "Scope Analysis" in prefix
        assert "Scope Confirmation" not in prefix

    def test_instructs_project_spec_json_output(self):
        prefix = get_spec_creation_prompt_prefix()
        assert "project_spec.json" in prefix
        assert "project_plan.json" not in prefix

    def test_includes_ears_notation_guidance(self):
        prefix = get_spec_creation_prompt_prefix()
        assert "EARS" in prefix or "ears" in prefix
        assert "WHEN" in prefix
        assert "SHALL" in prefix

    def test_includes_requirement_schema(self):
        prefix = get_spec_creation_prompt_prefix()
        assert "REQ-" in prefix
        assert '"id"' in prefix
        assert '"ears"' in prefix
        assert '"verification"' in prefix
        assert '"priority"' in prefix

    def test_includes_chunking_rules(self):
        prefix = get_spec_creation_prompt_prefix()
        assert "chunk" in prefix.lower()
        assert "C01_" in prefix or "c01_" in prefix.lower()

    def test_includes_do_not_build_constraint(self):
        prefix = get_spec_creation_prompt_prefix()
        assert "DO NOT" in prefix
        assert "deliverable" in prefix.lower() or "EXECUTOR" in prefix

    def test_broadcast_human_includes_scope_confirmation(self):
        prefix = get_spec_creation_prompt_prefix(broadcast_mode="human")
        assert "Scope Confirmation" in prefix or "scope" in prefix.lower()
        assert "ask_others" in prefix or "human" in prefix.lower()

    def test_broadcast_false_omits_human_ask(self):
        prefix = get_spec_creation_prompt_prefix(broadcast_mode=False)
        # Should use autonomous scope analysis, not human verification
        assert "Scope Analysis" in prefix or "consensus" in prefix.lower()

    def test_ends_with_user_request_marker(self):
        prefix = get_spec_creation_prompt_prefix()
        assert "USER'S REQUEST:" in prefix

    def test_spec_mode_header(self):
        prefix = get_spec_creation_prompt_prefix()
        assert "SPEC" in prefix.upper()
