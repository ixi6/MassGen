#!/usr/bin/env python3
"""
Standalone test app for the GitDiffReviewModal.

Run with:
    uv run python scripts/test_review_modal.py

Or via textual-serve for browser-based dev:
    uv run textual-serve scripts/test_review_modal.py

This creates a simple Textual app with a button that opens the review modal
with realistic mock data. Use this to iterate on the modal design without
running full MassGen.

Press 't' to toggle between dark and light themes.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Center, Vertical  # noqa: E402
from textual.widgets import Button, Footer, Header, Label, Static  # noqa: E402

# Import the modal and its dependencies
from massgen.filesystem_manager import ReviewResult  # noqa: E402
from massgen.frontend.displays.textual.widgets.modals.review_modal import (  # noqa: E402
    GitDiffReviewModal,
)

# ── Mock data ──────────────────────────────────────────────────────────────

SAMPLE_DIFF_SINGLE_FILE = """\
diff --git a/ROCK_OPERA.md b/ROCK_OPERA.md
new file mode 100644
index 0000000..a1b2c3d
--- /dev/null
+++ b/ROCK_OPERA.md
@@ -0,0 +1,25 @@
+# The MassGen Rock Opera
+
+## Act I: The Awakening
+
+In the depths of silicon dreams,
+Where parallel thoughts ignite,
+The agents gather, form their teams,
+And code through endless night.
+
+## Act II: The Coordination
+
+They vote, they share, they disagree,
+Through rounds of fierce debate,
+Until consensus sets them free,
+And answers resonate.
+
+## Act III: The Presentation
+
+One voice emerges from the choir,
+The chosen one steps forth,
+With answers forged in digital fire,
+To prove what they are worth.
+
+---
+*Written by the agents, for the humans.*
"""

SAMPLE_DIFF_MODIFIED = """\
diff --git a/src/config.py b/src/config.py
index abc1234..def5678 100644
--- a/src/config.py
+++ b/src/config.py
@@ -10,7 +10,9 @@ class Config:
     def __init__(self):
         self.debug = False
         self.verbose = False
-        self.max_retries = 3
+        self.max_retries = 5
+        self.timeout = 30
+        self.cache_enabled = True

     def load(self, path: str):
         \"\"\"Load configuration from file.\"\"\"
@@ -25,6 +27,10 @@ class Config:
         with open(path) as f:
             data = json.load(f)
             self._apply(data)
+
+    def validate(self):
+        \"\"\"Validate configuration values.\"\"\"
+        if self.max_retries < 0:
+            raise ValueError("max_retries must be non-negative")

     def _apply(self, data: dict):
         for key, value in data.items():
"""

SAMPLE_DIFF_DELETED = """\
diff --git a/old_module.py b/old_module.py
deleted file mode 100644
index 1234567..0000000
--- a/old_module.py
+++ /dev/null
@@ -1,15 +0,0 @@
-# Old module - no longer needed
-
-def deprecated_function():
-    \"\"\"This function is deprecated.\"\"\"
-    pass
-
-def another_old_function():
-    \"\"\"Also deprecated.\"\"\"
-    return None
-
-class OldClass:
-    def __init__(self):
-        self.value = 42
-    def method(self):
-        return self.value
"""

# Combine into a realistic multi-file diff
COMBINED_DIFF = SAMPLE_DIFF_SINGLE_FILE + "\n" + SAMPLE_DIFF_MODIFIED + "\n" + SAMPLE_DIFF_DELETED

# Single context with multiple files
MOCK_CHANGES_MULTI = [
    {
        "original_path": "/Users/ncrispin/GitHubProjects/MassGenMore",
        "isolated_path": "/workspace/.worktree/ctx_1",
        "changes": [
            {"status": "?", "path": "ROCK_OPERA.md"},
            {"status": "M", "path": "src/config.py"},
            {"status": "D", "path": "old_module.py"},
        ],
        "diff": COMBINED_DIFF,
    },
]

# Single file (minimal case)
MOCK_CHANGES_SINGLE = [
    {
        "original_path": "/Users/ncrispin/GitHubProjects/MassGenMore",
        "isolated_path": "/workspace/.worktree/ctx_1",
        "changes": [
            {"status": "?", "path": "ROCK_OPERA.md"},
        ],
        "diff": SAMPLE_DIFF_SINGLE_FILE,
    },
]

# Multiple contexts
MOCK_CHANGES_MULTI_CTX = [
    {
        "original_path": "/Users/ncrispin/GitHubProjects/MassGenMore",
        "isolated_path": "/workspace/.worktree/ctx_1",
        "changes": [
            {"status": "?", "path": "ROCK_OPERA.md"},
            {"status": "M", "path": "src/config.py"},
        ],
        "diff": SAMPLE_DIFF_SINGLE_FILE + "\n" + SAMPLE_DIFF_MODIFIED,
    },
    {
        "original_path": "/Users/ncrispin/GitHubProjects/OtherProject",
        "isolated_path": "/workspace/.worktree/ctx_2",
        "changes": [
            {"status": "D", "path": "old_module.py"},
            {"status": "A", "path": "new_feature.py"},
        ],
        "diff": SAMPLE_DIFF_DELETED,
    },
]


# ── CSS Builder ───────────────────────────────────────────────────────────

THEME_DIR = Path(__file__).parent.parent / "massgen" / "frontend" / "displays" / "textual_themes"
PALETTE_DIR = THEME_DIR / "palettes"


def _build_combined_css(theme: str = "dark") -> Path:
    """Build a combined CSS file from palette + modal_base + base, matching the real app.

    Always writes to the same fixed path so the stylesheet can be re-read on theme toggle.
    """
    import tempfile

    from massgen.frontend.displays.textual.widgets.modal_base import MODAL_BASE_CSS

    palette_map = {"dark": "_dark.tcss", "light": "_light.tcss"}
    palette_file = palette_map.get(theme, "_dark.tcss")
    palette_css = (PALETTE_DIR / palette_file).read_text()
    base_css = (THEME_DIR / "base.tcss").read_text()

    # Split palette into variables (top) and component overrides (bottom)
    palette_lines = palette_css.split("\n")
    palette_vars = []
    palette_overrides = []
    in_overrides = False
    for line in palette_lines:
        if "Component Overrides" in line:
            in_overrides = True
        if in_overrides:
            palette_overrides.append(line)
        else:
            palette_vars.append(line)

    # Order: palette vars → modal base CSS → base.tcss → palette overrides
    combined = "\n".join(palette_vars) + "\n\n"
    combined += "/* Modal base styles */\n" + MODAL_BASE_CSS + "\n\n"
    combined += base_css
    if palette_overrides:
        combined += "\n\n" + "\n".join(palette_overrides)

    cache_dir = Path(tempfile.gettempdir()) / "massgen_themes"
    cache_dir.mkdir(exist_ok=True)
    # Always write to the same file so stylesheet.read() replaces the source
    combined_path = cache_dir / "test_modal_combined.tcss"
    combined_path.write_text(combined)
    return combined_path


# ── Test App ───────────────────────────────────────────────────────────────

# Pre-build dark theme CSS
_CSS_PATH = _build_combined_css("dark")


class ReviewModalTestApp(App):
    """Test app for iterating on the ReviewModal design."""

    CSS_PATH = [str(_CSS_PATH)]

    DEFAULT_CSS = """
    #main_content {
        width: auto;
        height: auto;
        padding: 2 4;
    }
    #main_content Button {
        margin: 1 0;
        width: 50;
    }
    #result_label {
        margin-top: 1;
        height: auto;
    }
    #theme_label {
        margin-top: 1;
        height: auto;
        color: #8b949e;
    }
    """

    BINDINGS = [
        ("1", "show_single", "Single File"),
        ("2", "show_multi", "Multi File"),
        ("3", "show_multi_ctx", "Multi Context"),
        ("t", "toggle_theme", "Toggle Theme"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self._current_theme = "dark"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Center():
            with Vertical(id="main_content"):
                yield Static(
                    "[bold]Review Modal Test Harness[/]\n\n" "Press a button or use keyboard shortcuts to open\n" "the review modal with different mock data sets.\n",
                    markup=True,
                )
                yield Button("1: Single File (new)", id="btn_single", variant="primary")
                yield Button("2: Multi File (new + modified + deleted)", id="btn_multi", variant="success")
                yield Button("3: Multi Context (2 projects)", id="btn_multi_ctx", variant="warning")
                yield Label("", id="result_label")
                yield Label(f"Theme: {self._current_theme} (press 't' to toggle)", id="theme_label")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_single":
            self._open_modal(MOCK_CHANGES_SINGLE)
        elif event.button.id == "btn_multi":
            self._open_modal(MOCK_CHANGES_MULTI)
        elif event.button.id == "btn_multi_ctx":
            self._open_modal(MOCK_CHANGES_MULTI_CTX)

    def action_show_single(self) -> None:
        self._open_modal(MOCK_CHANGES_SINGLE)

    def action_show_multi(self) -> None:
        self._open_modal(MOCK_CHANGES_MULTI)

    def action_show_multi_ctx(self) -> None:
        self._open_modal(MOCK_CHANGES_MULTI_CTX)

    def action_toggle_theme(self) -> None:
        """Toggle between dark and light themes by rebuilding CSS and re-reading."""
        self._current_theme = "light" if self._current_theme == "dark" else "dark"
        # Rebuild the combined CSS file (overwrites same path)
        css_path = _build_combined_css(self._current_theme)
        # Re-read from disk (replaces the source keyed by this path)
        self.stylesheet.read(str(css_path))
        # refresh_css() calls set_variables + reparse + update on all nodes
        self.refresh_css()
        try:
            label = self.query_one("#theme_label", Label)
            label.update(f"Theme: {self._current_theme} (press 't' to toggle)")
        except Exception:
            pass

    def _open_modal(self, changes):
        modal = GitDiffReviewModal(changes=changes)
        self.push_screen(modal, self._handle_result)

    def _handle_result(self, result: ReviewResult) -> None:
        label = self.query_one("#result_label", Label)
        if result is None:
            label.update("[dim]Modal dismissed with no result[/]")
        elif result.approved:
            files = result.approved_files
            if files is None:
                label.update("[green bold]APPROVED ALL[/]")
            else:
                label.update(f"[green]APPROVED {len(files)} file(s):[/] {', '.join(files)}")
        else:
            mode = result.metadata.get("selection_mode", "unknown") if result.metadata else "unknown"
            label.update(f"[red bold]REJECTED[/] (mode: {mode})")


if __name__ == "__main__":
    app = ReviewModalTestApp()
    app.run()
