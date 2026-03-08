"""Shared fixtures for frontend tests."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_frontend_logs_to_tmp_path(monkeypatch, tmp_path):
    """Keep frontend tests from writing log sessions into repo-local .massgen/."""
    import massgen.logger_config as logger_config

    monkeypatch.setattr(logger_config, "_LOG_BASE_SESSION_DIR", None)
    monkeypatch.setattr(logger_config, "_LOG_SESSION_DIR", None)
    monkeypatch.setattr(logger_config, "_CURRENT_TURN", None)
    monkeypatch.setattr(logger_config, "_CURRENT_ATTEMPT", None)
    logger_config.set_log_base_session_dir_absolute(tmp_path / "massgen_logs")
