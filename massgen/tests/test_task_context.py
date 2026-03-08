from __future__ import annotations

from pathlib import Path

import pytest


def test_load_task_context_success_does_not_emit_info_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Successful context loads should not spam INFO logs."""
    from massgen.context import task_context as task_context_module

    (tmp_path / "CONTEXT.md").write_text("Website task context\n", encoding="utf-8")

    def _fail_if_called(*args, **kwargs):  # type: ignore[no-untyped-def]
        message = "logger.info should not be called for successful context loads: " f"args={args}, kwargs={kwargs}"
        raise AssertionError(message)

    monkeypatch.setattr(task_context_module.logger, "info", _fail_if_called)

    content = task_context_module.load_task_context(str(tmp_path), required=True)
    assert content == "Website task context"
