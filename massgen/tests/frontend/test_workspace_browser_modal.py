"""Unit tests for workspace-browser scanning safeguards."""

from massgen.frontend.displays.textual.widgets.modals.browser_modals import (
    WorkspaceBrowserModal,
)


class _ScrollStub:
    def __init__(self) -> None:
        self.children = []

    def remove_children(self) -> None:
        self.children = []

    def mount(self, widget, *args, **kwargs) -> None:  # noqa: ANN001 - test stub API
        self.children.append(widget)


def _render_widget_text(widget) -> str:  # noqa: ANN001 - test helper
    try:
        rendered = widget.render()
        return getattr(rendered, "plain", str(rendered))
    except Exception:
        return str(widget)


def _make_modal() -> WorkspaceBrowserModal:
    return WorkspaceBrowserModal(
        answers=[],
        agent_ids=["agent_a"],
        default_agent="agent_a",
    )


def test_workspace_browser_scan_limits_file_count(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    modal = _make_modal()
    max_files = modal._MAX_SCAN_FILES

    for idx in range(max_files + 50):
        (workspace / f"file_{idx:04d}.txt").write_text("x", encoding="utf-8")

    files, truncated = modal._scan_workspace_files(str(workspace))

    assert truncated is True
    assert len(files) == max_files


def test_workspace_browser_scan_limits_depth(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    modal = _make_modal()

    deep_dir = workspace
    for level in range(modal._MAX_SCAN_DEPTH + 2):
        deep_dir = deep_dir / f"lvl_{level}"
        deep_dir.mkdir()

    shallow_file = workspace / "top.txt"
    deep_file = deep_dir / "too_deep.txt"
    shallow_file.write_text("top", encoding="utf-8")
    deep_file.write_text("deep", encoding="utf-8")

    files, _ = modal._scan_workspace_files(str(workspace))
    rel_paths = {item["rel_path"] for item in files}

    assert "top.txt" in rel_paths
    assert deep_file.relative_to(workspace).as_posix() not in rel_paths


def test_workspace_browser_resets_preview_on_workspace_switch(monkeypatch, tmp_path):
    workspace_a = tmp_path / "workspace_a"
    workspace_b = tmp_path / "workspace_b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    (workspace_a / "first.txt").write_text("a", encoding="utf-8")
    (workspace_b / "second.txt").write_text("b", encoding="utf-8")

    modal = WorkspaceBrowserModal(
        answers=[
            {"agent_id": "agent_a", "workspace_path": str(workspace_a)},
            {"agent_id": "agent_a", "workspace_path": str(workspace_b)},
        ],
        agent_ids=["agent_a"],
        default_agent="agent_a",
    )

    file_list = _ScrollStub()
    preview = _ScrollStub()

    def fake_query_one(selector: str, _widget_type=None):  # noqa: ANN001 - monkeypatch target signature
        if selector == "#workspace_file_list":
            return file_list
        if selector == "#workspace_preview":
            return preview
        raise AssertionError(f"Unexpected selector: {selector}")

    monkeypatch.setattr(modal, "query_one", fake_query_one, raising=False)

    # Simulate a previously previewed file from another workspace.
    preview.mount("stale preview")
    modal._load_workspace_files(1)

    assert len(preview.children) == 1
    assert "Select a file to preview" in _render_widget_text(preview.children[0])
