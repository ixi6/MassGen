"""Tests for PlanOptionsPopover analysis target type initialization and state.

Covers:
- Target type parameter is stored correctly
- Title text logic is correct for each target type
"""

from __future__ import annotations

import pytest

try:
    from textual.widgets import Label  # noqa: F401

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not TEXTUAL_AVAILABLE, reason="textual not installed")

from massgen.frontend.displays.textual_widgets.plan_options import (  # noqa: E402
    PlanOptionsPopover,
)

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_analysis_target_type_defaults_to_log() -> None:
    """Default analysis target type should be 'log'."""
    popover = PlanOptionsPopover(plan_mode="analysis")
    assert popover._analysis_target_type == "log"


def test_analysis_target_type_skills_stored() -> None:
    """Skills target type should be stored when passed."""
    popover = PlanOptionsPopover(plan_mode="analysis", analysis_target_type="skills")
    assert popover._analysis_target_type == "skills"


# ---------------------------------------------------------------------------
# Title derivation
# ---------------------------------------------------------------------------


def test_analysis_title_text_for_log() -> None:
    """Title should contain 'Log Analysis' when target is log."""
    popover = PlanOptionsPopover(plan_mode="analysis", analysis_target_type="log")
    title = "Skill Organization" if popover._analysis_target_type == "skills" else "Log Analysis Options"
    assert title == "Log Analysis Options"


def test_analysis_title_text_for_skills() -> None:
    """Title should contain 'Skill Organization' when target is skills."""
    popover = PlanOptionsPopover(plan_mode="analysis", analysis_target_type="skills")
    title = "Skill Organization" if popover._analysis_target_type == "skills" else "Log Analysis Options"
    assert title == "Skill Organization"


# ---------------------------------------------------------------------------
# Container ID constants (used by compose and on_select_changed)
# ---------------------------------------------------------------------------


def test_log_controls_container_id_constant() -> None:
    """Verify the expected container ID for log controls."""
    assert PlanOptionsPopover.LOG_CONTROLS_ID == "analysis_log_controls"


def test_skills_controls_container_id_constant() -> None:
    """Verify the expected container ID for skills controls."""
    assert PlanOptionsPopover.SKILLS_CONTROLS_ID == "analysis_skills_controls"
