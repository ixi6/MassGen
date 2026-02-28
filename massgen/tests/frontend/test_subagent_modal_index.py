"""Tests for subagent modal index selection when multiple subagents share an ID.

Bug: Clicking a subagent opens the wrong modal because the modal/screen
constructor searches by `sa.id == subagent.id` and always matches the first
occurrence. Fix: pass the index from the click site through to the modal.
"""

from massgen.subagent.models import SubagentDisplayData


def _make_subagent(
    subagent_id: str = "researcher",
    task: str = "test task",
    status: str = "completed",
) -> SubagentDisplayData:
    return SubagentDisplayData(
        id=subagent_id,
        task=task,
        status=status,
        progress_percent=100 if status == "completed" else 50,
        elapsed_seconds=10.0,
        timeout_seconds=300.0,
        workspace_path="",
        workspace_file_count=0,
        last_log_line="",
        error=None,
        answer_preview="answer" if status == "completed" else None,
        log_path=None,
    )


# =============================================================================
# SubagentView index selection
# =============================================================================


class TestSubagentViewIndexSelection:
    """SubagentView must use the passed index, not search by ID."""

    def test_duplicate_ids_with_explicit_index(self):
        """Passing subagent_index selects the correct subagent even with duplicate IDs."""
        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        sa0 = _make_subagent("researcher", task="task A")
        sa1 = _make_subagent("researcher", task="task B")
        sa2 = _make_subagent("researcher", task="task C")
        all_subagents = [sa0, sa1, sa2]

        view = SubagentView.__new__(SubagentView)
        view.__init__(subagent=sa2, all_subagents=all_subagents, subagent_index=2)
        assert view._current_index == 2

    def test_duplicate_ids_middle_index(self):
        """Middle subagent with duplicate ID is found correctly."""
        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        sa0 = _make_subagent("researcher", task="task A")
        sa1 = _make_subagent("researcher", task="task B")
        sa2 = _make_subagent("researcher", task="task C")
        all_subagents = [sa0, sa1, sa2]

        view = SubagentView.__new__(SubagentView)
        view.__init__(subagent=sa1, all_subagents=all_subagents, subagent_index=1)
        assert view._current_index == 1

    def test_fallback_uses_identity_when_index_is_none(self):
        """Without subagent_index, falls back to object identity match."""
        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        sa0 = _make_subagent("researcher", task="task A")
        sa1 = _make_subagent("researcher", task="task B")
        all_subagents = [sa0, sa1]

        view = SubagentView.__new__(SubagentView)
        view.__init__(subagent=sa1, all_subagents=all_subagents, subagent_index=None)
        assert view._current_index == 1

    def test_unique_ids_with_explicit_index(self):
        """Unique IDs still work correctly with explicit index."""
        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        sa0 = _make_subagent("alpha")
        sa1 = _make_subagent("beta")
        sa2 = _make_subagent("gamma")
        all_subagents = [sa0, sa1, sa2]

        view = SubagentView.__new__(SubagentView)
        view.__init__(subagent=sa2, all_subagents=all_subagents, subagent_index=2)
        assert view._current_index == 2


# =============================================================================
# SubagentModal index selection
# =============================================================================


class TestSubagentModalIndexSelection:
    """SubagentModal must use the passed index, not search by ID."""

    def test_duplicate_ids_with_explicit_index(self):
        from massgen.frontend.displays.textual_widgets.subagent_modal import (
            SubagentModal,
        )

        sa0 = _make_subagent("researcher", task="task A")
        sa1 = _make_subagent("researcher", task="task B")
        sa2 = _make_subagent("researcher", task="task C")
        all_subagents = [sa0, sa1, sa2]

        modal = SubagentModal(subagent=sa2, all_subagents=all_subagents, subagent_index=2)
        assert modal._current_index == 2

    def test_fallback_uses_identity_when_index_is_none(self):
        from massgen.frontend.displays.textual_widgets.subagent_modal import (
            SubagentModal,
        )

        sa0 = _make_subagent("researcher", task="task A")
        sa1 = _make_subagent("researcher", task="task B")
        all_subagents = [sa0, sa1]

        modal = SubagentModal(subagent=sa1, all_subagents=all_subagents, subagent_index=None)
        assert modal._current_index == 1


# =============================================================================
# SubagentTuiModal index selection
# =============================================================================


class TestSubagentTuiModalIndexSelection:
    """SubagentTuiModal must use the passed index, not search by ID."""

    def test_duplicate_ids_with_explicit_index(self):
        from massgen.frontend.displays.textual_widgets.subagent_tui_modal import (
            SubagentTuiModal,
        )

        sa0 = _make_subagent("researcher", task="task A")
        sa1 = _make_subagent("researcher", task="task B")
        sa2 = _make_subagent("researcher", task="task C")
        all_subagents = [sa0, sa1, sa2]

        modal = SubagentTuiModal(subagent=sa1, all_subagents=all_subagents, subagent_index=1)
        assert modal._current_index == 1

    def test_fallback_uses_identity_when_index_is_none(self):
        from massgen.frontend.displays.textual_widgets.subagent_tui_modal import (
            SubagentTuiModal,
        )

        sa0 = _make_subagent("researcher", task="task A")
        sa1 = _make_subagent("researcher", task="task B")
        all_subagents = [sa0, sa1]

        modal = SubagentTuiModal(subagent=sa1, all_subagents=all_subagents, subagent_index=None)
        assert modal._current_index == 1


# =============================================================================
# OpenModal message carries index
# =============================================================================


class TestOpenModalCarriesIndex:
    """SubagentCard.OpenModal must carry the subagent_index field."""

    def test_open_modal_stores_subagent_index(self):
        from massgen.frontend.displays.textual_widgets.subagent_card import (
            SubagentCard,
        )

        sa = _make_subagent()
        msg = SubagentCard.OpenModal(sa, [sa], subagent_index=2)
        assert msg.subagent_index == 2

    def test_open_modal_defaults_index_to_none(self):
        from massgen.frontend.displays.textual_widgets.subagent_card import (
            SubagentCard,
        )

        sa = _make_subagent()
        msg = SubagentCard.OpenModal(sa, [sa])
        assert msg.subagent_index is None


# =============================================================================
# SubagentColumn passes index on click
# =============================================================================


class TestSubagentColumnPassesIndex:
    """SubagentColumn must pass its index to the open callback."""

    def test_column_passes_index_to_callback(self):
        from massgen.frontend.displays.textual_widgets.subagent_card import (
            SubagentColumn,
        )

        sa = _make_subagent()
        captured = {}

        def _callback(subagent, all_subagents, index):
            captured["subagent"] = subagent
            captured["index"] = index

        col = SubagentColumn(
            subagent=sa,
            all_subagents=[sa],
            summary="test",
            tools=[],
            open_callback=_callback,
            index=3,
        )
        col.on_click()
        assert captured["index"] == 3
        assert captured["subagent"] is sa
