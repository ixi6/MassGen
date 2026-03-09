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
        """
        Initialize the launcher's workspace directory.
        
        If `workspace_root` is provided it is used as the workspace root; otherwise the workspace is set to
        Path.cwd() / ".massgen" / "cloud_jobs". The chosen directory is assigned to `self.workspace_root`
        and created on disk if it does not already exist.
        
        Parameters:
            workspace_root (Path | None): Optional path to use as the workspace root. If `None`, a
                default workspace under the current working directory is used.
        """
        base = workspace_root or (Path.cwd() / ".massgen" / "cloud_jobs")
        self.workspace_root = base
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def launch(self, request: CloudJobRequest) -> CloudJobResult:
        """
        Launches a cloud job described by the given request.
        
        Parameters:
            request (CloudJobRequest): Payload that specifies the job prompt, YAML config, timeout, and optional cloud job identifier.
        
        Returns:
            CloudJobResult: The final result produced by the launched cloud job.
        
        Note:
            This method is abstract and must be implemented by subclasses.
        """
        raise NotImplementedError
