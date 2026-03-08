"""Tests for subagent context path display: modal and display data labeling."""

from massgen.subagent.models import SubagentDisplayData


def _make_subagent(subagent_id: str, **kwargs) -> SubagentDisplayData:
    defaults = {
        "id": subagent_id,
        "task": "check output",
        "status": "running",
        "progress_percent": 0,
        "elapsed_seconds": 0.0,
        "timeout_seconds": 300.0,
        "workspace_path": "",
        "workspace_file_count": 0,
        "last_log_line": "",
        "error": None,
        "answer_preview": None,
        "log_path": None,
    }
    defaults.update(kwargs)
    return SubagentDisplayData(**defaults)


# =============================================================================
# SubagentDisplayData.context_paths_labeled serialization
# =============================================================================


class TestSubagentDisplayDataLabeledPaths:
    """context_paths_labeled field on SubagentDisplayData."""

    def test_labeled_paths_serialized_in_to_dict(self):
        """context_paths_labeled should be included in to_dict() output."""
        subagent = _make_subagent("sub_1")
        subagent.context_paths_labeled = [
            {"path": "/workspace/project", "label": "Parent CWD", "permission": "read"},
            {"path": "/tmp/temp_ws", "label": "Temp Workspace", "permission": "read"},
        ]

        d = subagent.to_dict()
        assert "context_paths_labeled" in d
        assert len(d["context_paths_labeled"]) == 2
        assert d["context_paths_labeled"][0]["label"] == "Parent CWD"
        assert d["context_paths_labeled"][1]["label"] == "Temp Workspace"

    def test_empty_labeled_paths_is_empty_list(self):
        """Default context_paths_labeled is an empty list."""
        subagent = _make_subagent("sub_2")
        d = subagent.to_dict()
        assert d["context_paths_labeled"] == []

    def test_labeled_paths_are_deep_copied(self):
        """to_dict() should deep-copy labeled paths to prevent mutation."""
        labeled = [{"path": "/ws", "label": "WS", "permission": "read"}]
        subagent = _make_subagent("sub_3", context_paths_labeled=labeled)

        d = subagent.to_dict()
        d["context_paths_labeled"][0]["label"] = "MUTATED"
        assert subagent.context_paths_labeled[0]["label"] == "WS"


# =============================================================================
# _build_context_paths_labeled helper
# =============================================================================


class TestBuildContextPathsLabeled:
    """Tests for the display data label builder."""

    def test_parent_cwd_labeled(self):
        """Path matching workspace_path gets 'Parent CWD' label."""
        from massgen.frontend.displays.textual_terminal_display import (
            _build_context_paths_labeled,
        )

        result = _build_context_paths_labeled(
            context_paths=["/workspace/project"],
            workspace_path="/workspace/project",
            sa_data={},
            existing=None,
        )
        assert len(result) == 1
        assert result[0]["label"] == "Parent CWD"
        assert result[0]["permission"] == "read"

    def test_temp_workspace_labeled(self):
        """Path containing 'temp_workspace' gets 'Temp Workspace' label."""
        from massgen.frontend.displays.textual_terminal_display import (
            _build_context_paths_labeled,
        )

        result = _build_context_paths_labeled(
            context_paths=["/tmp/temp_workspace_agent_a"],
            workspace_path="/workspace",
            sa_data={},
            existing=None,
        )
        assert result[0]["label"] == "Temp Workspace"

    def test_other_path_uses_basename(self):
        """Other paths use their basename as label."""
        from massgen.frontend.displays.textual_terminal_display import (
            _build_context_paths_labeled,
        )

        result = _build_context_paths_labeled(
            context_paths=["/some/shared/docs"],
            workspace_path="/workspace",
            sa_data={},
            existing=None,
        )
        assert result[0]["label"] == "docs"

    def test_empty_paths_returns_empty(self):
        """No context paths returns empty list."""
        from massgen.frontend.displays.textual_terminal_display import (
            _build_context_paths_labeled,
        )

        result = _build_context_paths_labeled([], "", {}, None)
        assert result == []

    def test_existing_labeled_paths_preserved_when_no_new_paths(self):
        """When context_paths is empty but existing has labels, keep them."""
        from massgen.frontend.displays.textual_terminal_display import (
            _build_context_paths_labeled,
        )

        existing = _make_subagent(
            "sub_1",
            context_paths_labeled=[
                {"path": "/ws", "label": "Parent CWD", "permission": "read"},
            ],
        )
        result = _build_context_paths_labeled([], "", {}, existing)
        assert len(result) == 1
        assert result[0]["label"] == "Parent CWD"


# =============================================================================
# SubagentContextModal rendering
# =============================================================================


class TestSubagentContextModal:
    """Tests for the read-only SubagentContextModal."""

    async def test_modal_renders_all_paths_with_read_badge(self):
        """Modal should render each labeled path with a Read badge."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        from massgen.frontend.displays.textual.widgets.modals.content_modals import (
            SubagentContextModal,
        )

        labeled = [
            {"path": "/workspace", "label": "Parent CWD", "permission": "read"},
            {"path": "/tmp/temp_ws", "label": "Temp Workspace", "permission": "read"},
        ]

        class ModalApp(App[None]):
            def compose(self) -> ComposeResult:
                yield Static("placeholder")

        app = ModalApp()
        async with app.run_test(headless=True, size=(120, 40)) as pilot:
            modal = SubagentContextModal(context_paths_labeled=labeled)
            app.push_screen(modal)
            await pilot.pause()

            # Should have 2 path rows
            path_rows = modal.query(".context-path-row")
            assert len(path_rows) == 2

            # Read badges should be disabled
            badges = modal.query(".perm-badge")
            assert all(b.disabled for b in badges)

    async def test_modal_renders_empty_state(self):
        """Modal with no paths should show 'No context paths' message."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        from massgen.frontend.displays.textual.widgets.modals.content_modals import (
            SubagentContextModal,
        )

        class ModalApp(App[None]):
            def compose(self) -> ComposeResult:
                yield Static("placeholder")

        app = ModalApp()
        async with app.run_test(headless=True, size=(120, 40)) as pilot:
            modal = SubagentContextModal(context_paths_labeled=[])
            app.push_screen(modal)
            await pilot.pause()

            # Should have no path rows
            path_rows = modal.query(".context-path-row")
            assert len(path_rows) == 0


# =============================================================================
# SubagentHeader simplified (no more inline context buttons)
# =============================================================================


class TestSubagentHeaderSimplified:
    """SubagentHeader should no longer render inline context path buttons."""

    async def test_header_has_no_context_path_buttons(self):
        """Simplified header should not render context-path-btn elements."""
        from textual.app import App, ComposeResult
        from textual.widgets import Button

        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentHeader,
        )

        subagent = _make_subagent("sub_1")
        subagent.context_paths = ["/some/path", "/other/path"]

        class HeaderApp(App[None]):
            def compose(self) -> ComposeResult:
                yield SubagentHeader(subagent, id="test-header")

        app = HeaderApp()
        async with app.run_test(headless=True, size=(120, 10)):
            context_buttons = [b for b in app.query(Button) if b.has_class("context-path-btn")]
            assert len(context_buttons) == 0

    async def test_header_has_back_button_and_title(self):
        """Header should still have back button and title."""
        from textual.app import App, ComposeResult
        from textual.widgets import Button, Static

        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentHeader,
        )

        subagent = _make_subagent("sub_test")

        class HeaderApp(App[None]):
            def compose(self) -> ComposeResult:
                yield SubagentHeader(subagent, id="test-header")

        app = HeaderApp()
        async with app.run_test(headless=True, size=(120, 10)):
            back_btn = app.query_one("#back_btn", Button)
            assert back_btn is not None

            title = app.query_one("#header_title", Static)
            assert "sub_test" in title.render().plain
