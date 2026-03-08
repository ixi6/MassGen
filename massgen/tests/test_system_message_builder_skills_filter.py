"""Tests for runtime skill filtering in SystemMessageBuilder."""

from massgen.system_message_builder import SystemMessageBuilder

SKILLS = [
    {"name": "alpha", "location": "builtin", "description": ""},
    {"name": "beta", "location": "project", "description": ""},
    {"name": "gamma", "location": "previous_session", "description": ""},
]


def test_skill_filter_none_keeps_all() -> None:
    """None allowlist should keep all discovered skills."""
    filtered = SystemMessageBuilder._filter_skills_by_enabled_names(SKILLS, None)

    assert filtered == SKILLS


def test_skill_filter_matches_case_insensitively() -> None:
    """Runtime allowlist should filter by name case-insensitively."""
    filtered = SystemMessageBuilder._filter_skills_by_enabled_names(SKILLS, ["BETA", "gamma"])

    assert [s["name"] for s in filtered] == ["beta", "gamma"]


def test_skill_filter_empty_allowlist_returns_empty() -> None:
    """Empty allowlist means no skills are exposed."""
    filtered = SystemMessageBuilder._filter_skills_by_enabled_names(SKILLS, [])

    assert filtered == []
