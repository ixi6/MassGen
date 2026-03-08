#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modal app entrypoint for MassGen cloud jobs."""

import base64
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
from pathlib import Path
from typing import Dict, List

import modal

APP_NAME = "massgen-cloud-job"
RESULT_MARKER = "__MASSGEN_CLOUD_JOB_RESULT__"


def parse_automation_value(label: str, text: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(label)}:\s*(.+)$", re.MULTILINE)
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def make_tar_gz_b64(source_dir: Path) -> str:
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


@app.function(image=image, timeout=60 * 60, volumes={CONTEXT_MOUNT_PATH: context_vol})
def run_massgen_job(payload_b64: str) -> dict:
    """Local entrypoint for Modal job."""
    payload: Dict[str, object] = json.loads(base64.b64decode(payload_b64).decode("utf-8"))

    prompt = str(payload["prompt"])
    config_yaml = str(payload["config_yaml"])
    output_filename = str(payload.get("output_filename", "final_answer.txt"))
    forwarded_env = payload.get("env", {}) or {}

    for key, value in forwarded_env.items():
        os.environ[str(key)] = str(value)
    # Note: A better way to handle is using Modal secrets
    # But this requires user to run
    # `modal secret create massgen-env --from-dotenv .env`

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
    stdout_lines: List[str] = []
    stderr_lines: List[str] = []

    def _drain_stderr():
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    assert proc.stdout is not None
    for line in proc.stdout:
        stdout_lines.append(line)
        print(line, end="", flush=True)

    proc.wait()
    stderr_thread.join(timeout=5)

    stdout_text = "".join(stdout_lines)
    stderr_text = "".join(stderr_lines)
    returncode = proc.returncode

    artifact_root = workspace / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)

    (artifact_root / "stdout.log").write_text(stdout_text, encoding="utf-8")
    (artifact_root / "stderr.log").write_text(stderr_text, encoding="utf-8")
    (artifact_root / "events.jsonl").write_text(stdout_text, encoding="utf-8")

    log_dir = parse_automation_value("LOG_DIR", stderr_text)
    if log_dir:
        src_log_dir = Path(log_dir)
        if src_log_dir.exists():
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
    print(f"{RESULT_MARKER}{json.dumps(result)}")
    return result
