from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.usefixtures("_isolate_test_logs")
def test_get_log_session_dir_respects_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import massgen.logger_config as logger_config

    custom_root = tmp_path / "custom_logs"
    monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(custom_root))
    logger_config.reset_logging_session()

    log_dir = logger_config.get_log_session_dir()
    session_root = logger_config.get_log_session_root()

    assert session_root.parent == custom_root
    assert session_root.name.startswith("log_")
    assert log_dir == session_root / "turn_1" / "attempt_1"


@pytest.mark.usefixtures("_isolate_test_logs")
def test_set_log_base_session_dir_uses_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import massgen.logger_config as logger_config

    custom_root = tmp_path / "custom_logs"
    monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(custom_root))
    logger_config.reset_logging_session()

    logger_config.set_log_base_session_dir("log_existing")
    log_dir = logger_config.get_log_session_dir()
    session_root = logger_config.get_log_session_root()

    assert session_root == custom_root / "log_existing"
    assert log_dir == custom_root / "log_existing" / "turn_1" / "attempt_1"
