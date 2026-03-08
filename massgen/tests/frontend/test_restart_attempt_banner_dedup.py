"""Regression tests for restart attempt banner deduplication in TUI panels."""

from __future__ import annotations

from massgen.frontend.displays.textual_terminal_display import AgentPanel


class _DummyDisplay:
    def __init__(self):
        self.enable_syntax_highlighting = False
        self._dom_id_mapping = {}

    @staticmethod
    def _get_icon(value: str) -> str:
        return value


class _FakeTimeline:
    def __init__(self):
        self.attempt_calls = []
        self.round_separators = []
        self._round_1_shown = False

    def set_viewed_round(self, round_number: int) -> None:
        self.viewed_round = round_number

    def clear_tools_tracking(self) -> None:
        self.cleared = True

    def add_attempt_banner(
        self,
        attempt: int,
        reason: str,
        instructions: str,
        round_number: int,
    ) -> None:
        self.attempt_calls.append((attempt, reason, instructions, round_number))

    def add_separator(self, label: str, round_number: int = 1) -> None:
        self.round_separators.append((label, round_number))


def test_show_restart_separator_deduplicates_identical_attempt(monkeypatch):
    panel = AgentPanel(agent_id="agent_a", display=_DummyDisplay(), key_index=1)
    timeline = _FakeTimeline()

    monkeypatch.setattr(panel, "query_one", lambda *_args, **_kwargs: timeline)
    monkeypatch.setattr(panel, "_hide_completion_footer", lambda: None)

    panel.show_restart_separator(
        attempt=2,
        reason="The answer omitted required details.",
        instructions="Add both required profiles.",
    )
    panel.show_restart_separator(
        attempt=2,
        reason="The answer omitted required details.",
        instructions="Add both required profiles.",
    )

    assert len(timeline.attempt_calls) == 1
    assert timeline.attempt_calls[0][0] == 2
