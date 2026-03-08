"""Unit tests for changedoc utility module.

Tests cover:
- Reading tasks/changedoc.md from agent workspace
- Handling missing/empty changedoc files
"""

from pathlib import Path

import pytest

from massgen.changedoc import read_changedoc_from_workspace


@pytest.fixture()
def tasks_dir(tmp_path: Path) -> Path:
    """Create tasks/ subdirectory in workspace."""
    d = tmp_path / "tasks"
    d.mkdir()
    return d


class TestReadChangedocFromWorkspace:
    """Tests for read_changedoc_from_workspace()."""

    def test_reads_changedoc_when_present(self, tmp_path: Path, tasks_dir: Path):
        """Returns content when tasks/changedoc.md exists with content."""
        changedoc_content = "# Change Document\n\n## Summary\nChose caching for performance."
        (tasks_dir / "changedoc.md").write_text(changedoc_content)

        result = read_changedoc_from_workspace(tmp_path)
        assert result == changedoc_content

    def test_returns_none_when_file_missing(self, tmp_path: Path):
        """Returns None when tasks/changedoc.md does not exist."""
        result = read_changedoc_from_workspace(tmp_path)
        assert result is None

    def test_returns_none_when_file_empty(self, tmp_path: Path, tasks_dir: Path):
        """Returns None when tasks/changedoc.md exists but is empty."""
        (tasks_dir / "changedoc.md").write_text("")
        result = read_changedoc_from_workspace(tmp_path)
        assert result is None

    def test_returns_none_when_file_whitespace_only(self, tmp_path: Path, tasks_dir: Path):
        """Returns None when tasks/changedoc.md contains only whitespace."""
        (tasks_dir / "changedoc.md").write_text("   \n\n  ")
        result = read_changedoc_from_workspace(tmp_path)
        assert result is None

    def test_preserves_content_exactly(self, tmp_path: Path, tasks_dir: Path):
        """Content is returned stripped but otherwise preserved."""
        content = "# Change Document\n\n## Decisions\n### DEC-001: Use Redis\n**Why:** Fast lookups"
        (tasks_dir / "changedoc.md").write_text(f"  {content}  \n")

        result = read_changedoc_from_workspace(tmp_path)
        assert result == content

    def test_handles_nonexistent_workspace(self):
        """Returns None when workspace path doesn't exist."""
        result = read_changedoc_from_workspace(Path("/nonexistent/workspace"))
        assert result is None
