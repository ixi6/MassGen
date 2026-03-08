"""Unit tests for skills modal helper behavior."""

from massgen.frontend.displays.textual.widgets.modals.skills_modals import SkillsModal


def test_build_tags_marks_custom_and_evolving() -> None:
    tags = SkillsModal._build_tags({"is_custom": True, "is_evolving": True}, "project")
    assert "project" in tags[0]
    assert "custom" in tags
    assert "evolving" in tags


def test_build_tags_marks_previous_session_as_evolving() -> None:
    tags = SkillsModal._build_tags({}, "previous_session")
    assert "previous session" in tags[0]
    assert "evolving" in tags


def test_build_detail_combines_description_and_origin() -> None:
    detail = SkillsModal._build_detail({"description": "Useful workflow", "origin": "analysis-turn-3"})
    assert "Useful workflow" in detail
    assert "analysis-turn-3" in detail
