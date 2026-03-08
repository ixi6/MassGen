"""Tests for CLI @reference parsing toggle in prompt context injection."""

from __future__ import annotations

import pytest

from massgen.cli import ConfigurationError, inject_prompt_context_paths


def test_inject_prompt_context_paths_can_be_disabled() -> None:
    """When disabled, @tokens in prompt text are treated as plain text."""
    prompt = "Use CSS @import for fonts."
    config = {"orchestrator": {"context_paths": []}}

    cleaned, updated = inject_prompt_context_paths(
        prompt,
        config,
        parse_at_references=False,
    )

    assert cleaned == prompt
    assert updated["orchestrator"]["context_paths"] == []


def test_inject_prompt_context_paths_still_parses_when_enabled() -> None:
    """Enabled parsing keeps existing behavior (missing paths raise config errors)."""
    prompt = "Use CSS @import for fonts."

    with pytest.raises(ConfigurationError, match="Context paths not found"):
        inject_prompt_context_paths(prompt, {}, parse_at_references=True)
