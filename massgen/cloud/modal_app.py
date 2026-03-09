#!/usr/bin/env python3
"""Modal app entrypoint for MassGen cloud jobs."""

import base64
import io
import json
import shutil
import subprocess
import tarfile
import threading
from pathlib import Path

import modal

APP_NAME = "massgen-cloud-job"


def make_tar_gz_b64(source_dir: Path) -> str:
    """Create a base64-encoded tar.gz archive of a directory.

    Args:
        source_dir: The directory to archive.

    Returns:
        A base64-encoded string of the gzipped tar archive.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in source_dir.rglob("*"):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(source_dir)))
    return base64.b64encode(buf.getvalue()).decode("utf-8")


CONTEXT_VOLUME_NAME = "massgen-context"
CONTEXT_MOUNT_PATH = "/context"

app = modal.App(APP_NAME)
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "massgen",
        "fastmcp",
        "uv",
    )
    .apt_install(
        "nodejs",
        "npm",
        "curl",
        "wget",
        "git",
        "build-essential",
    )
)
context_vol = modal.Volume.from_name(CONTEXT_VOLUME_NAME, create_if_missing=True)


@app.function(
    image=image,
    timeout=60 * 60,
    volumes={CONTEXT_MOUNT_PATH: context_vol},
    secrets=[modal.Secret.from_name("massgen-env")],
)
def run_massgen_job(payload_b64: str) -> dict:
    """Local entrypoint for Modal job."""
    payload: dict[str, object] = json.loads(base64.b64decode(payload_b64).decode("utf-8"))

    prompt = str(payload["prompt"])
    config_yaml = str(payload["config_yaml"])
    cloud_job_id = str(payload.get("cloud_job_id", ""))
    output_filename = "final_answer.txt"

    workspace = Path("/tmp/massgen_cloud_job")
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    config_path = workspace / "config.yaml"
    config_path.write_text(config_yaml, encoding="utf-8")

    # Make context volume contents visible (uploaded by the launcher before this runs)
    context_vol.reload()

    output_file = workspace / output_filename
    print(f"Running massgen with config: {config_path}")
    cmd = [
        "massgen",
        "--automation",
        "--stream-events",
        "--config",
        str(config_path),
        "--output-file",
        str(output_file),
        prompt,
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    # Stream stdout line-by-line so `modal run` can forward it in real time.
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    event_lines: list[str] = []

    def _drain_stderr():
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            print(f"[stderr] {line}", end="", flush=True)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    assert proc.stdout is not None
    for line in proc.stdout:
        stdout_lines.append(line)
        print(line, end="", flush=True)
        line_stripped = line.strip()
        if not line_stripped:
            continue
        try:
            parsed = json.loads(line_stripped)
            if isinstance(parsed, dict):
                event_lines.append(line)
        except json.JSONDecodeError:
            pass

    proc.wait()
    stderr_thread.join(timeout=5)

    stdout_text = "".join(stdout_lines)
    stderr_text = "".join(stderr_lines)
    events_text = "".join(event_lines)
    returncode = proc.returncode

    artifact_root = workspace / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)

    (artifact_root / "stdout.log").write_text(stdout_text, encoding="utf-8")
    (artifact_root / "stderr.log").write_text(stderr_text, encoding="utf-8")
    (artifact_root / "events.jsonl").write_text(events_text, encoding="utf-8")

    log_dir = None
    logs_base = workspace / ".massgen" / "massgen_logs"
    if logs_base.exists():
        log_dirs = [d for d in logs_base.iterdir() if d.is_dir() and d.name.startswith("log_")]
        if log_dirs:
            src_log_dir = max(log_dirs, key=lambda d: d.stat().st_mtime)
            log_dir = str(src_log_dir.relative_to(workspace))
            shutil.copytree(src_log_dir, artifact_root / "log_dir", dirs_exist_ok=True)

    final_answer = output_file.read_text(encoding="utf-8") if output_file.exists() else ""
    if final_answer:
        (artifact_root / "final_answer.txt").write_text(final_answer, encoding="utf-8")

    result = {
        "status": "ok" if returncode == 0 else "error",
        "timed_out": False,
        "error": None if returncode == 0 else f"massgen exited with code {returncode}",
        "final_answer": final_answer,
        "remote_log_dir": log_dir,
        "artifacts_tar_gz_b64": make_tar_gz_b64(artifact_root),
    }
    result_marker = f"__MASSGEN_CLOUD_JOB_RESULT__{cloud_job_id}_"
    print(f"{result_marker}{json.dumps(result)}")
    return result
