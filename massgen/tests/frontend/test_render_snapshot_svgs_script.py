"""Tests for scripts/render_snapshot_svgs.py."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.snapshot


def _load_script_module():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "render_snapshot_svgs.py"
    spec = importlib.util.spec_from_file_location("render_snapshot_svgs_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discover_svgs_filters_real_tui(tmp_path):
    module = _load_script_module()
    (tmp_path / "a.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "b_real_tui_round.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "c_real_tui_final.svg").write_text("<svg/>", encoding="utf-8")

    all_names = [path.name for path in module.discover_svgs(tmp_path)]
    real_tui_names = [path.name for path in module.discover_svgs(tmp_path, real_tui_only=True)]

    assert all_names == ["a.svg", "b_real_tui_round.svg", "c_real_tui_final.svg"]
    assert real_tui_names == ["b_real_tui_round.svg", "c_real_tui_final.svg"]


def test_render_svg_invokes_playwright(tmp_path, monkeypatch):
    module = _load_script_module()
    svg_path = tmp_path / "snapshot.svg"
    svg_path.write_text("<svg/>", encoding="utf-8")
    out_dir = tmp_path / "pngs"
    out_dir.mkdir()

    captured = {}

    def _fake_run(cmd, capture_output, text, check):  # noqa: ANN001 - subprocess signature
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["check"] = check
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    code, output = module.render_svg(svg_path, out_dir, "Desktop Chrome")
    assert code == 0
    assert output == "ok"
    assert captured["cmd"][0:3] == ["npx", "playwright", "screenshot"]
    assert captured["cmd"][3] == "--device=Desktop Chrome"
    assert captured["cmd"][4] == svg_path.resolve().as_uri()
    assert captured["cmd"][5] == str(out_dir / "snapshot.png")
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["check"] is False


def test_main_returns_error_when_no_matching_svgs(tmp_path, capsys):
    module = _load_script_module()
    (tmp_path / "regular.svg").write_text("<svg/>", encoding="utf-8")

    rc = module.main(
        [
            "--input-dir",
            str(tmp_path),
            "--real-tui-only",
        ],
    )
    err = capsys.readouterr().err
    assert rc == 1
    assert "No real_tui snapshots found" in err


def test_main_renders_all_svgs(tmp_path, monkeypatch, capsys):
    module = _load_script_module()
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    (in_dir / "a.svg").write_text("<svg/>", encoding="utf-8")
    (in_dir / "b.svg").write_text("<svg/>", encoding="utf-8")

    rendered = []

    def _fake_render(svg_path, output_dir, device):  # noqa: ANN001 - helper signature
        rendered.append((svg_path.name, output_dir, device))
        return 0, ""

    monkeypatch.setattr(module, "render_svg", _fake_render)

    rc = module.main(
        [
            "--input-dir",
            str(in_dir),
            "--output-dir",
            str(out_dir),
            "--device",
            "Desktop Chrome",
        ],
    )

    output = capsys.readouterr().out
    assert rc == 0
    assert out_dir.exists()
    assert rendered == [
        ("a.svg", out_dir, "Desktop Chrome"),
        ("b.svg", out_dir, "Desktop Chrome"),
    ]
    assert "All snapshots rendered successfully." in output
