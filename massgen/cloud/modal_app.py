#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modal app entrypoint for MassGen cloud jobs."""

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict

import modal

from .cloud_job import CloudJobLauncher
from .utils import make_tar_gz_b64, parse_automation_value

APP_NAME = "massgen-cloud-job"
RESULT_MARKER = CloudJobLauncher.RESULT_MARKER

app = modal.App(APP_NAME)
image = modal.Image.debian_slim(python_version="3.11").pip_install("massgen")


@app.function(image=image, timeout=60 * 60)
def run_massgen_job(payload_b64: str) -> dict:
    """Run massgen automation in Modal and print a parseable result marker."""
    payload: Dict[str, object] = json.loads(base64.b64decode(payload_b64).decode("utf-8"))

    prompt = str(payload["prompt"])
    config_yaml = str(payload["config_yaml"])
    timeout_seconds = int(payload.get("timeout_seconds", 1800))
    output_filename = str(payload.get("output_filename", "final_answer.txt"))
    forwarded_env = payload.get("env", {}) or {}

    for key, value in forwarded_env.items():
        os.environ[str(key)] = str(value)

    workspace = Path("/tmp/massgen_cloud_job")
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    config_path = workspace / "config.yaml"
    config_path.write_text(config_yaml, encoding="utf-8")

    output_file = workspace / output_filename
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

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        result = {
            "status": "error",
            "timed_out": True,
            "error": f"massgen timed out after {timeout_seconds}s",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
        print(f"{RESULT_MARKER}{json.dumps(result)}")
        return result

    artifact_root = workspace / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)

    (artifact_root / "stdout.log").write_text(proc.stdout, encoding="utf-8")
    (artifact_root / "stderr.log").write_text(proc.stderr, encoding="utf-8")
    (artifact_root / "events.jsonl").write_text(proc.stdout, encoding="utf-8")

    log_dir = parse_automation_value("LOG_DIR", proc.stderr)
    if log_dir:
        src_log_dir = Path(log_dir)
        if src_log_dir.exists():
            shutil.copytree(src_log_dir, artifact_root / "log_dir", dirs_exist_ok=True)

    final_answer = output_file.read_text(encoding="utf-8") if output_file.exists() else ""
    if final_answer:
        (artifact_root / "final_answer.txt").write_text(final_answer, encoding="utf-8")

    result = {
        "status": "ok" if proc.returncode == 0 else "error",
        "timed_out": False,
        "error": None if proc.returncode == 0 else f"massgen exited with code {proc.returncode}",
        "final_answer": final_answer,
        "remote_log_dir": log_dir,
        "artifacts_tar_gz_b64": make_tar_gz_b64(artifact_root),
    }
    print(f"{RESULT_MARKER}{json.dumps(result)}")
    return result
