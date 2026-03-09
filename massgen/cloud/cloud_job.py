#!/usr/bin/env python3

from dataclasses import dataclass
from pathlib import Path


class CloudJobError(RuntimeError):
    """Raised when a cloud job fails or returns invalid output."""


@dataclass
class CloudJobRequest:
    """Payload for launching a cloud run."""

    prompt: str
    config_yaml: str
    timeout_seconds: int
    cloud_job_id: str = ""


@dataclass
class CloudJobResult:
    """Result returned from the cloud launcher."""

    final_answer: str
    artifacts_dir: Path
    local_log_dir: Path | None
    local_events_path: Path | None
    remote_log_dir: str | None


class CloudJobLauncher:
    """Interface for launching cloud jobs."""

    RESULT_MARKER = "__MASSGEN_CLOUD_JOB_RESULT__"

    def __init__(self, workspace_root: Path | None = None):
        base = workspace_root or (Path.cwd() / ".massgen" / "cloud_jobs")
        self.workspace_root = base
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def launch(self, request: CloudJobRequest) -> CloudJobResult:
        raise NotImplementedError
