#!/usr/bin/env python3
"""Tests for Modal cloud launcher MVP and utils."""

import base64
import io
import json
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

from massgen.cloud.modal_launcher import CloudJobRequest, ModalCloudJobLauncher
from massgen.cloud.utils import process_context_paths


def _make_artifact_payload() -> str:
    """Build a tiny tar.gz payload encoded as base64."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"hello from cloud"
        info = tarfile.TarInfo(name="events.jsonl")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _make_mock_popen(stdout_lines: list[str], stderr_lines: list[str], returncode: int):
    """Create a mock Popen object that yields lines from stdout/stderr."""
    mock_proc = MagicMock()
    mock_proc.stdout = iter(stdout_lines)
    mock_proc.stderr = iter(stderr_lines)
    mock_proc.returncode = returncode
    mock_proc.wait.return_value = returncode
    return mock_proc


def test_modal_launcher_extracts_result_and_artifacts(tmp_path: Path, monkeypatch):
    """Launcher should parse result marker and extract artifact archive."""
    cloud_job_id = "test_job_123"
    launcher = ModalCloudJobLauncher(workspace_root=tmp_path)
    marker_payload = {
        "status": "ok",
        "final_answer": "Cloud answer",
        "artifacts_tar_gz_b64": _make_artifact_payload(),
        "remote_log_dir": "/tmp/logs",
    }
    stdout_lines = [
        "some logs\n",
        f"{ModalCloudJobLauncher.RESULT_MARKER}{cloud_job_id}_{json.dumps(marker_payload)}\n",
    ]
    print(stdout_lines)
    mock_proc = _make_mock_popen(stdout_lines, [], returncode=0)
    monkeypatch.setattr(
        "massgen.cloud.modal_launcher.subprocess.Popen",
        lambda *a, **k: mock_proc,
    )

    result = launcher.launch(
        CloudJobRequest(
            prompt="solve fizzbuzz",
            config_yaml="agent: {}",
            timeout_seconds=60,
            cloud_job_id=cloud_job_id,
        ),
    )

    assert result.final_answer == "Cloud answer"
    assert result.artifacts_dir.exists()
    assert (result.artifacts_dir / "events.jsonl").read_text(encoding="utf-8") == "hello from cloud"
    assert result.artifacts_dir.parent.name == f"job_{cloud_job_id}"


def test_modal_launcher_streams_progress(tmp_path: Path, monkeypatch, capsys):
    cloud_job_id = "test_job_123"
    launcher = ModalCloudJobLauncher(workspace_root=tmp_path)
    marker_payload = {
        "status": "ok",
        "final_answer": "done",
        "remote_log_dir": None,
    }
    stdout_lines = [
        "Setting up workspace...\n",
        "Running agent...\n",
        f"{ModalCloudJobLauncher.RESULT_MARKER}{cloud_job_id}_{json.dumps(marker_payload)}\n",
    ]
    mock_proc = _make_mock_popen(stdout_lines, [], returncode=0)
    monkeypatch.setattr(
        "massgen.cloud.modal_launcher.subprocess.Popen",
        lambda *a, **k: mock_proc,
    )

    result = launcher.launch(
        CloudJobRequest(
            prompt="hello",
            config_yaml="agent: {}",
            timeout_seconds=60,
            cloud_job_id=cloud_job_id,
        ),
    )

    assert result.final_answer == "done"
    captured = capsys.readouterr()
    assert "[cloud] Setting up workspace..." in captured.out
    assert "[cloud] Running agent..." in captured.out
    # The result marker line should NOT be printed as progress
    assert "RESULT" not in captured.out


def test_process_context_paths_files_and_directories(tmp_path, monkeypatch):
    """process_context_paths should accurately upload inputs and rewrite paths."""
    mock_volume = MagicMock()
    mock_batch = MagicMock()
    mock_volume.batch_upload.return_value.__enter__.return_value = mock_batch

    class FakeVolume:
        @classmethod
        def from_name(cls, name, create_if_missing=False):
            return mock_volume

    fake_modal = type("FakeModal", (), {"Volume": FakeVolume})

    import sys

    monkeypatch.setitem(sys.modules, "modal", fake_modal)

    file1 = tmp_path / "file1.txt"
    file1.write_text("file1_test")

    dir1 = tmp_path / "dir1"
    dir1.mkdir()

    context_paths = [
        {"path": str(file1), "permission": "read"},
        {"path": str(dir1), "protected_paths": ["protect/path1", "protect/path2"]},
    ]

    job_id = "job-456"

    rewritten = process_context_paths(context_paths, cloud_job_id=job_id)

    assert len(rewritten) == 2

    # Verify Volume writes
    mock_batch.put_file.assert_called_with(str(file1), f"{job_id}/0/file1.txt")
    mock_batch.put_directory.assert_called_with(str(dir1), f"{job_id}/1")

    # Verify rewritten content
    assert rewritten[0]["path"] == f"/context/{job_id}/0/file1.txt"
    assert rewritten[0]["permission"] == "read"
    assert "protected_paths" not in rewritten[0]

    assert rewritten[1]["path"] == f"/context/{job_id}/1"
    assert rewritten[1]["permission"] == "read"
    assert rewritten[1]["protected_paths"] == ["protect/path1", "protect/path2"]
