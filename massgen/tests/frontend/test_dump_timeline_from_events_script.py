"""Tests for scripts/dump_timeline_from_events.py mode selection and filtering."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from massgen.events import MassGenEvent


def _load_script_module():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "dump_timeline_from_events.py"
    spec = importlib.util.spec_from_file_location("dump_timeline_from_events_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_events_file(path: Path) -> None:
    payload = {
        "timestamp": "2026-02-08T00:00:00Z",
        "event_type": "text",
        "agent_id": "agent_a",
        "round_number": 1,
        "data": {"content": "synthetic replay"},
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_parse_mode_flags_defaults_to_text():
    module = _load_script_module()
    mode, args = module.parse_mode_flags(["events.jsonl"])
    assert mode == "text"
    assert args == ["events.jsonl"]


def test_parse_mode_flags_rejects_conflicting_modes():
    module = _load_script_module()
    with pytest.raises(ValueError, match="either --tui or --tui-real"):
        module.parse_mode_flags(["--tui", "--tui-real", "events.jsonl"])


def test_filter_replay_events_applies_expected_skips():
    module = _load_script_module()
    events = [
        MassGenEvent.create("timeline_entry", agent_id="agent_a", line="legacy"),
        MassGenEvent.create("stream_chunk", agent_id="agent_a", content="chunk"),
        MassGenEvent.create("text", agent_id="agent_a", content="keep this"),
        MassGenEvent.create("text", agent_id="agent_b", content="drop this"),
        MassGenEvent.create("orchestrator_timeout", timeout_seconds=10),
    ]

    filtered = module.filter_replay_events(events, {"agent_a"})
    assert [event.event_type for event in filtered] == ["text", "orchestrator_timeout"]


def test_main_dispatches_to_real_tui_mode(tmp_path, monkeypatch):
    module = _load_script_module()
    events_path = tmp_path / "events.jsonl"
    _write_events_file(events_path)

    called = {}

    def _fake_run_tui_real(events, agent_ids):
        called["events"] = events
        called["agent_ids"] = agent_ids
        return 77

    monkeypatch.setattr(module, "run_tui_real", _fake_run_tui_real)
    monkeypatch.setattr(module, "run_tui", lambda *_args, **_kwargs: pytest.fail("unexpected --tui dispatch"))
    monkeypatch.setattr(module, "run_text", lambda *_args, **_kwargs: pytest.fail("unexpected text dispatch"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["dump_timeline_from_events.py", "--tui-real", str(events_path), "agent_a"],
    )

    result = module.main()
    assert result == 77
    assert called["agent_ids"] == {"agent_a"}
    assert len(called["events"]) == 1


def test_main_prints_usage_for_conflicting_mode_flags(monkeypatch, capsys):
    module = _load_script_module()
    monkeypatch.setattr(sys, "argv", ["dump_timeline_from_events.py", "--tui", "--tui-real"])

    result = module.main()
    assert result == 1
    err = capsys.readouterr().err
    assert "Use either --tui or --tui-real, not both." in err
    assert module.USAGE in err
