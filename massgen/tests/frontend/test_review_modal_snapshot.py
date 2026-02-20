"""Snapshot tests for the GitDiffReviewModal to visually verify the change review experience."""

from pathlib import Path

import pytest

try:
    from textual.app import App, ComposeResult
    from textual.widgets import Static

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from massgen.frontend.displays.textual.widgets.modal_base import MODAL_BASE_CSS
from massgen.frontend.displays.textual.widgets.modals.review_modal import (
    GitDiffReviewModal,
)

pytestmark = pytest.mark.snapshot

SAMPLE_DIFF = """\
diff --git a/src/app.py b/src/app.py
index abc1234..def5678 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 import os
+import sys

 def main():
     pass
@@ -10,3 +11,3 @@ def helper():
-    return False
+    return True
     # end
"""

MULTI_FILE_DIFF = SAMPLE_DIFF + """\

diff --git a/new_feature.py b/new_feature.py
new file mode 100644
--- /dev/null
+++ b/new_feature.py
@@ -0,0 +1,8 @@
+\"\"\"New feature module.\"\"\"
+
+
+def process(data):
+    result = []
+    for item in data:
+        result.append(item * 2)
+    return result
"""


def _make_review_changes():
    return [
        {
            "original_path": "/home/user/project",
            "isolated_path": "/tmp/massgen_worktree",
            "changes": [
                {"status": "M", "path": "src/app.py"},
                {"status": "A", "path": "new_feature.py"},
                {"status": "D", "path": "deprecated.py"},
            ],
            "diff": MULTI_FILE_DIFF,
        },
    ]


def _make_multi_context_changes():
    return [
        {
            "original_path": "/home/user/frontend",
            "isolated_path": "/tmp/worktree_fe",
            "changes": [
                {"status": "M", "path": "src/App.tsx"},
                {"status": "A", "path": "src/hooks/useAuth.ts"},
            ],
            "diff": SAMPLE_DIFF.replace("src/app.py", "src/App.tsx"),
        },
        {
            "original_path": "/home/user/backend",
            "isolated_path": "/tmp/worktree_be",
            "changes": [
                {"status": "M", "path": "api/auth.py"},
            ],
            "diff": SAMPLE_DIFF.replace("src/app.py", "api/auth.py"),
        },
    ]


# Load MassGen's theme CSS matching the real app loading order:
# palette variables → MODAL_BASE_CSS → base.tcss
_THEMES_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "displays" / "textual_themes"
_PALETTE_CSS = (_THEMES_DIR / "palettes" / "_dark.tcss").read_text()
_BASE_CSS = (_THEMES_DIR / "base.tcss").read_text()


class ReviewModalApp(App):
    """Minimal app that mounts the review modal for snapshot testing.

    Loads MassGen's dark palette + modal base + base theme CSS for accurate rendering.
    """

    CSS = _PALETTE_CSS + "\n" + MODAL_BASE_CSS + "\n" + _BASE_CSS

    def __init__(self, changes, **kwargs):
        super().__init__(**kwargs)
        self._changes = changes

    def compose(self) -> ComposeResult:
        yield Static("")

    def on_mount(self) -> None:
        modal = GitDiffReviewModal(changes=self._changes)
        self.push_screen(modal)


@pytest.mark.skipif(not TEXTUAL_AVAILABLE, reason="textual not installed")
class TestReviewModalSnapshot:
    def test_review_modal_multi_file(self, snap_compare):
        """Snapshot: review modal with 3 files (modified, added, deleted)."""

        def _build():
            return ReviewModalApp(changes=_make_review_changes())

        assert snap_compare(
            _build(),
            terminal_size=(120, 35),
        )

    def test_review_modal_multi_context(self, snap_compare):
        """Snapshot: review modal with multiple context paths."""

        def _build():
            return ReviewModalApp(changes=_make_multi_context_changes())

        assert snap_compare(
            _build(),
            terminal_size=(120, 35),
        )

    def test_review_modal_widescreen(self, snap_compare):
        """Snapshot: review modal at wider terminal size (140x40)."""

        def _build():
            return ReviewModalApp(changes=_make_review_changes())

        assert snap_compare(
            _build(),
            terminal_size=(140, 40),
        )
