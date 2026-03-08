"""File explorer side panel for the final answer card.

Shows workspace file changes (new/modified) in a tree with click-to-preview.
Falls back to scanning the workspace directory when no explicit context_paths are provided.
"""

import os
import time
from pathlib import Path

from textual.containers import Vertical
from textual.widgets import Static, Tree

from ..shared.tui_debug import tui_debug_enabled, tui_log


class FileExplorerPanel(Vertical):
    """Side panel showing workspace file changes with click-to-preview.

    Displays a tree of new/modified files and a preview pane for the selected file.
    When context_paths is empty, scans workspace_path for all files instead.
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(
        self,
        context_paths: dict[str, list[str]] | None = None,
        workspace_path: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id or "file_explorer_panel")
        self.context_paths = context_paths or {}
        self.workspace_path = workspace_path
        self._all_paths: dict[str, str] = {}  # display path -> status ("new"/"modified"/"workspace")
        self._path_lookup: dict[str, str] = {}  # display path -> absolute path
        self._timing_debug = tui_debug_enabled() and os.environ.get("MASSGEN_TUI_TIMING_DEBUG", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        # Populate from explicit context_paths first, but cap entries for responsiveness.
        context_entries: list[tuple[str, str]] = []
        context_entries.extend((path, "new") for path in self.context_paths.get("new", []))
        context_entries.extend((path, "modified") for path in self.context_paths.get("modified", []))
        if context_entries:
            max_entries = self._MAX_FILES
            for display_path, status in context_entries[:max_entries]:
                self._add_path(display_path, status)
            remaining = len(context_entries) - max_entries
            if remaining > 0:
                self._add_path(f"... ({remaining} more files)", "workspace", absolute_path="")

    def _add_path(self, display_path: str, status: str, absolute_path: str | None = None) -> None:
        """Track a path for display and lookup."""
        self._all_paths[display_path] = status
        self._path_lookup[display_path] = absolute_path or display_path

    def _clear_workspace_entries(self) -> None:
        """Remove previously scanned workspace entries to allow refresh."""
        to_remove = [p for p, status in self._all_paths.items() if status == "workspace"]
        for display_path in to_remove:
            self._all_paths.pop(display_path, None)
            self._path_lookup.pop(display_path, None)

    # Directories to skip when scanning workspace
    _SKIP_DIRS = frozenset(
        {
            ".git",
            ".env",
            ".massgen",
            "massgen_logs",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".tox",
            ".nox",
            ".cache",
            ".next",
            ".nuxt",
            "dist",
            "build",
            "target",
            ".pnpm",
            ".pnpm-store",
            "vendor",
        },
    )
    _MAX_DEPTH = 3
    _MAX_FILES = 50
    _MAX_PREVIEW_LINES = 100
    _MAX_PREVIEW_CHARS = 100_000
    _BINARY_CHECK_BYTES = 2048

    def _scan_workspace(self) -> None:
        """Scan workspace directory and populate _all_paths with found files."""
        started = time.perf_counter()
        ws = Path(self.workspace_path)
        if not ws.exists() or not ws.is_dir():
            return
        self._clear_workspace_entries()
        added = 0
        truncated = False
        try:
            # Use os.walk with pruning so large ignored dirs don't block the TUI.
            for root, dirs, files in os.walk(ws, topdown=True):
                root_path = Path(root)
                try:
                    rel_root = root_path.relative_to(ws)
                except ValueError:
                    continue

                root_depth = 0 if str(rel_root) == "." else len(rel_root.parts)

                # Prune ignored and over-depth directories before descending.
                dirs[:] = [d for d in dirs if d not in self._SKIP_DIRS and root_depth < self._MAX_DEPTH]

                if root_depth >= self._MAX_DEPTH:
                    files = []

                for filename in files:
                    if added >= self._MAX_FILES:
                        truncated = True
                        break

                    file_path = root_path / filename
                    rel_file = file_path.relative_to(ws)
                    if len(rel_file.parts) > self._MAX_DEPTH:
                        continue

                    display_path = str(rel_file)
                    self._add_path(display_path, "workspace", absolute_path=str(file_path))
                    added += 1

                if truncated:
                    break
            if truncated:
                self._add_path("... (more files)", "workspace", absolute_path="")
        except Exception:
            pass
        finally:
            if self._timing_debug:
                tui_log(
                    "[TIMING] FileExplorerPanel._scan_workspace " f"{(time.perf_counter() - started) * 1000.0:.1f}ms " f"files={added} truncated={truncated} root={ws}",
                )

    @classmethod
    def _is_binary_file(cls, filepath: Path) -> bool:
        """Return True when a file looks binary based on an initial byte sample."""
        try:
            with filepath.open("rb") as f:
                sample = f.read(cls._BINARY_CHECK_BYTES)
            return b"\x00" in sample
        except Exception:
            return False

    @classmethod
    def _read_preview_content(cls, filepath: Path) -> str:
        """Read a bounded text preview without scanning the entire file."""
        with filepath.open("rb") as f:
            raw = f.read(cls._MAX_PREVIEW_CHARS + 1)
        truncated = len(raw) > cls._MAX_PREVIEW_CHARS
        if truncated:
            raw = raw[: cls._MAX_PREVIEW_CHARS]

        content = raw.decode("utf-8", errors="replace")
        lines = content.splitlines()
        if len(lines) > cls._MAX_PREVIEW_LINES:
            lines = lines[: cls._MAX_PREVIEW_LINES]
            truncated = True
        if truncated:
            lines.append("")
            lines.append("... (preview truncated)")

        return "\n".join(lines)

    def has_files(self) -> bool:
        """Return True if there are any files to display."""
        return bool(self._all_paths)

    def compose(self):
        from textual.widgets import Label

        has_context = bool(self.context_paths.get("new") or self.context_paths.get("modified"))
        header_text = "📂 Workspace Changes" if has_context else "📂 Workspace"
        yield Label(header_text, id="file_tree_header")

        tree: Tree[str] = Tree("files", id="file_tree")
        tree.root.expand()
        tree.show_root = False

        # Build directory structure
        dirs: dict[str, any] = {}
        for display_path, status in sorted(self._all_paths.items()):
            parts = Path(display_path).parts
            # Add directory nodes
            current = tree.root
            for i, part in enumerate(parts[:-1]):
                key = "/".join(parts[: i + 1])
                if key not in dirs:
                    node = current.add(f"▾ {part}/", data=None)
                    node.expand()
                    dirs[key] = node
                current = dirs[key]

            # Add file leaf with status icon
            if status == "new":
                icon = "✚"
            elif status == "modified":
                icon = "✎"
            else:
                icon = "·"
            filename = parts[-1] if parts else display_path
            data_path = self._path_lookup.get(display_path, display_path)
            current.add_leaf(f"{icon} {filename}", data=data_path)

        yield tree
        yield Label("", id="file_preview_header")
        yield Static("Select a file to preview", id="file_preview")

    def rebuild_tree(self) -> None:
        """Rebuild the tree widget in-place from current _all_paths."""
        try:
            tree = self.query_one("#file_tree", Tree)
        except Exception:
            return
        tree.clear()
        dirs: dict[str, any] = {}
        for display_path, status in sorted(self._all_paths.items()):
            parts = Path(display_path).parts
            current = tree.root
            for i, part in enumerate(parts[:-1]):
                key = "/".join(parts[: i + 1])
                if key not in dirs:
                    node = current.add(f"▾ {part}/", data=None)
                    node.expand()
                    dirs[key] = node
                current = dirs[key]
            if status == "new":
                icon = "✚"
            elif status == "modified":
                icon = "✎"
            else:
                icon = "·"
            filename = parts[-1] if parts else display_path
            data_path = self._path_lookup.get(display_path, display_path)
            current.add_leaf(f"{icon} {filename}", data=data_path)
        tree.root.expand()

    def auto_preview(self, answer_text: str) -> None:
        """Auto-select the first file whose name appears in answer_text."""
        if not answer_text or not self._all_paths:
            return
        answer_lower = answer_text.lower()
        for display_path in sorted(self._all_paths.keys()):
            filename = Path(display_path).name.lower()
            if filename != "..." and filename in answer_lower:
                self._show_preview(self._path_lookup.get(display_path, display_path))
                return
        # Single file — just show it
        if len(self._all_paths) == 1:
            display_path = next(iter(self._all_paths))
            self._show_preview(self._path_lookup.get(display_path, display_path))

    def _show_preview(self, filepath: str) -> None:
        """Load a file into the preview pane."""
        from textual.widgets import Label

        if not filepath:
            return
        try:
            preview_header = self.query_one("#file_preview_header", Label)
            preview_widget = self.query_one("#file_preview", Static)
            p = Path(filepath)
            preview_header.update(f"── {p.name} ──")
            if p.exists() and p.is_file():
                try:
                    if self._is_binary_file(p):
                        preview_widget.update("(binary file preview unavailable)")
                    else:
                        preview_widget.update(self._read_preview_content(p))
                except Exception:
                    preview_widget.update(f"(unable to read {filepath})")
            else:
                preview_widget.update(f"(file not found: {filepath})")
        except Exception:
            pass

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Load preview when a file is clicked."""
        if event.node.data:
            self._show_preview(event.node.data)
