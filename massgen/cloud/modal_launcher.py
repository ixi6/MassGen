#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modal-backed cloud job launcher for MassGen automation runs."""

import base64
import json
import secrets
import subprocess
from pathlib import Path
from typing import Optional

from .cloud_job import CloudJobError, CloudJobLauncher, CloudJobRequest, CloudJobResult
from .utils import extract_artifacts


class ModalCloudJobLauncher(CloudJobLauncher):
    """Launch MassGen jobs in Modal and materialize outputs locally."""

    def __init__(self, workspace_root: Optional[Path] = None):
        super().__init__(workspace_root)

    def launch(self, request: CloudJobRequest) -> CloudJobResult:
        """Run cloud job through `modal run` and return extracted artifacts."""
        payload = {
            "prompt": request.prompt,
            "config_yaml": request.config_yaml,
            "timeout_seconds": request.timeout_seconds,
            "output_filename": request.output_filename,
            "env": request.env,
        }
        payload_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

        cmd = [
            "modal",
            "run",
            "massgen/cloud/modal_app.py::run_massgen_job",
            "--payload-b64",
            payload_b64,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        marker_payload = self._extract_marker_payload(proc.stdout)

        if marker_payload is None:
            if proc.returncode != 0:
                raise CloudJobError(
                    f"Cloud job startup failure: modal exited with code {proc.returncode}. stderr={proc.stderr.strip()}",
                )
            raise CloudJobError("Cloud job failed: no result marker returned from Modal job")

        if marker_payload.get("status") != "ok":
            reason = marker_payload.get("error") or "unknown cloud failure"
            if marker_payload.get("timed_out"):
                raise CloudJobError(f"Cloud job timeout: {reason}")
            raise CloudJobError(f"Cloud job execution failure: {reason}")

        job_dir = self.workspace_root / f"job_{secrets.token_hex(6)}"
        job_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir = job_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        tar_b64 = marker_payload.get("artifacts_tar_gz_b64")
        if tar_b64:
            extract_artifacts(tar_b64, artifacts_dir)

        local_log_dir = artifacts_dir / "log_dir"
        if not local_log_dir.exists():
            local_log_dir = None
        local_events = artifacts_dir / "events.jsonl"
        if not local_events.exists():
            local_events = None

        return CloudJobResult(
            final_answer=marker_payload.get("final_answer", ""),
            artifacts_dir=artifacts_dir,
            local_log_dir=local_log_dir,
            local_events_path=local_events,
            remote_log_dir=marker_payload.get("remote_log_dir"),
            raw_stdout=proc.stdout,
            raw_stderr=proc.stderr,
        )
