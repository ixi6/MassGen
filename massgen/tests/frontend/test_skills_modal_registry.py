"""Tests for SkillsModal registry content parameter.

Covers:
- Modal accepts and stores registry_content parameter
- Modal has no registry content when not provided
"""

from __future__ import annotations

from typing import Any

import pytest

try:
    from textual.widgets import Static  # noqa: F401

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not TEXTUAL_AVAILABLE, reason="textual not installed")

from massgen.frontend.displays.textual.widgets.modals.skills_modals import (  # noqa: E402
    SkillsModal,
)

SAMPLE_SKILLS: dict[str, list[dict[str, Any]]] = {
    "builtin": [{"name": "pdf", "description": "PDF toolkit"}],
    "project": [{"name": "xlsx", "description": "Excel toolkit"}],
    "user": [],
    "previous_session": [],
}

REGISTRY_CONTENT = """# Skill Registry

## Document Tools (2)
- **pdf**: Generate and manipulate PDF documents
- **xlsx**: Create and edit Excel spreadsheets
"""


# ---------------------------------------------------------------------------
# Registry content parameter
# ---------------------------------------------------------------------------


def test_registry_content_stored_when_provided() -> None:
    """Modal should store registry_content when provided."""
    modal = SkillsModal(
        skills_by_location=SAMPLE_SKILLS,
        enabled_skill_names=None,
        include_previous_session_skills=False,
        registry_content=REGISTRY_CONTENT,
    )
    assert modal._registry_content == REGISTRY_CONTENT


def test_registry_content_none_by_default() -> None:
    """Modal should have None registry_content when not provided."""
    modal = SkillsModal(
        skills_by_location=SAMPLE_SKILLS,
        enabled_skill_names=None,
        include_previous_session_skills=False,
    )
    assert modal._registry_content is None


def test_registry_content_empty_string() -> None:
    """Modal should store empty string as-is."""
    modal = SkillsModal(
        skills_by_location=SAMPLE_SKILLS,
        enabled_skill_names=None,
        include_previous_session_skills=False,
        registry_content="",
    )
    assert modal._registry_content == ""
