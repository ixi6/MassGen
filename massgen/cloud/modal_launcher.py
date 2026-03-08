#!/usr/bin/env python3
"""Modal-backed cloud job launcher for MassGen automation runs."""

import base64
import json
import subprocess
import threading
from pathlib import Path

from .cloud_job import CloudJobError, CloudJobLauncher, CloudJobRequest, CloudJobResult
from .utils import extract_artifacts


class ModalCloudJobLauncher(CloudJobLauncher):
    """Launch MassGen jobs in Modal and materialize outputs locally."""

    def __init__(self, workspace_root: Path | None = None):
        super().__init__(workspace_root)

    def launch(self, request: CloudJobRequest) -> CloudJobResult:
        """Run cloud job through `modal run` and return extracted artifacts."""
        print(f"Launching cloud job {request.cloud_job_id}")

        payload = {
            "prompt": request.prompt,
            "config_yaml": request.config_yaml,
            "timeout_seconds": request.timeout_seconds,
            "cloud_job_id": request.cloud_job_id,
        }
        payload_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

        modal_entrypoint = Path(__file__).parent / "modal_app.py"
        cmd = [
            "modal",
            "run",
            f"{modal_entrypoint}::run_massgen_job",
            "--payload-b64",
            payload_b64,
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        # Drain stderr in a background thread to avoid pipe deadlock.
        stderr_lines: list[str] = []

        def _drain_stderr():
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_lines.append(line)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        # Stream stdout
        stdout_lines: list[str] = []
        marker_payload = None
        assert proc.stdout is not None
        result_marker = f"__MASSGEN_CLOUD_JOB_RESULT_{request.cloud_job_id}__"
        for line in proc.stdout:
            stdout_lines.append(line)
            stripped = line.strip()
            if stripped.startswith(result_marker):
                raw = stripped[len(result_marker) :]
                try:
                    marker_payload = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise CloudJobError(f"Failed to parse cloud job result JSON: {raw}") from e
            else:
                print(f"[cloud] {line}", end="")

        proc.wait()
        stderr_thread.join(timeout=5)

        if marker_payload is None:
            if proc.returncode != 0:
                full_stderr = "".join(stderr_lines)
                raise CloudJobError(
                    f"Cloud job startup failure: modal exited with code {proc.returncode}. " f"stderr={full_stderr.strip()}",
                )
            raise CloudJobError("Cloud job failed: no result marker returned from Modal job")

        if marker_payload.get("status") != "ok":
            reason = marker_payload.get("error") or "unknown cloud failure"
            if marker_payload.get("timed_out"):
                raise CloudJobError(f"Cloud job timeout: {reason}")
            raise CloudJobError(f"Cloud job execution failure: {reason}")

        job_dir = self.workspace_root / f"job_{request.cloud_job_id}"
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
        )
