"""
File-based delegation protocol for container-to-host subagent launch.

The outbox pattern: a container writes a DelegationRequest file to a shared
directory; the host-side SubagentLaunchWatcher picks it up, creates an isolated
container for the subagent, and writes back a DelegationResponse file.

All writes are atomic: write to `.tmp` then `os.rename()`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DELEGATION_PROTOCOL_VERSION = 1


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON to path atomically (write .tmp, then rename)."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    os.rename(str(tmp_path), str(path))


@dataclass
class DelegationRequest:
    """
    Request written by the container to ask the host to create a subagent container.

    Written atomically to {delegation_dir}/request_{subagent_id}.json.
    """

    version: int
    subagent_id: str
    request_id: str
    task: str
    yaml_config: dict[str, Any]
    answer_file: str
    workspace: str
    timeout_seconds: int
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "subagent_id": self.subagent_id,
            "request_id": self.request_id,
            "task": self.task,
            "yaml_config": self.yaml_config,
            "answer_file": self.answer_file,
            "workspace": self.workspace,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at,
        }

    def to_file(self, delegation_dir: Path) -> Path:
        """Write this request atomically to delegation_dir/request_{subagent_id}.json."""
        path = delegation_dir / f"request_{self.subagent_id}.json"
        _atomic_write_json(path, self.to_dict())
        return path

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DelegationRequest:
        """Parse a DelegationRequest from a dict, ignoring unknown fields."""
        return cls(
            version=int(data["version"]),
            subagent_id=str(data["subagent_id"]),
            request_id=str(data["request_id"]),
            task=str(data["task"]),
            yaml_config=dict(data["yaml_config"]),
            answer_file=str(data["answer_file"]),
            workspace=str(data["workspace"]),
            timeout_seconds=int(data["timeout_seconds"]),
            created_at=str(data.get("created_at", _now_iso())),
        )

    @classmethod
    def from_file(cls, path: Path) -> DelegationRequest:
        """Read a DelegationRequest from a JSON file."""
        data = json.loads(path.read_text())
        return cls.from_dict(data)

    def validate(self) -> None:
        """Raise ValueError if the request is malformed."""
        if self.version != DELEGATION_PROTOCOL_VERSION:
            raise ValueError(
                f"Unsupported delegation protocol version: {self.version} " f"(expected {DELEGATION_PROTOCOL_VERSION})",
            )
        if not self.subagent_id:
            raise ValueError("subagent_id must not be empty")
        if not self.request_id:
            raise ValueError("request_id must not be empty")
        if not self.task:
            raise ValueError("task must not be empty")
        if not self.workspace:
            raise ValueError("workspace must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be positive, got {self.timeout_seconds}")


# Valid status values for DelegationResponse
DELEGATION_STATUS_COMPLETED = "completed"
DELEGATION_STATUS_ERROR = "error"
DELEGATION_STATUS_TIMEOUT = "timeout"
DELEGATION_STATUS_CANCELLED = "cancelled"

VALID_DELEGATION_STATUSES = {
    DELEGATION_STATUS_COMPLETED,
    DELEGATION_STATUS_ERROR,
    DELEGATION_STATUS_TIMEOUT,
    DELEGATION_STATUS_CANCELLED,
}


@dataclass
class DelegationResponse:
    """
    Response written by the host after running the subagent container.

    Written atomically to {delegation_dir}/response_{subagent_id}.json.
    """

    version: int
    subagent_id: str
    request_id: str
    status: str  # "completed" | "error" | "timeout" | "cancelled"
    exit_code: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    completed_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "subagent_id": self.subagent_id,
            "request_id": self.request_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "completed_at": self.completed_at,
        }

    def to_file(self, delegation_dir: Path) -> Path:
        """Write this response atomically to delegation_dir/response_{subagent_id}.json."""
        path = delegation_dir / f"response_{self.subagent_id}.json"
        _atomic_write_json(path, self.to_dict())
        return path

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DelegationResponse:
        """Parse a DelegationResponse from a dict, ignoring unknown fields."""
        return cls(
            version=int(data["version"]),
            subagent_id=str(data["subagent_id"]),
            request_id=str(data["request_id"]),
            status=str(data["status"]),
            exit_code=int(data["exit_code"]),
            stdout_tail=str(data.get("stdout_tail", "")),
            stderr_tail=str(data.get("stderr_tail", "")),
            completed_at=str(data.get("completed_at", _now_iso())),
        )

    @classmethod
    def from_file(cls, path: Path) -> DelegationResponse:
        """Read a DelegationResponse from a JSON file."""
        data = json.loads(path.read_text())
        return cls.from_dict(data)

    def validate(self) -> None:
        """Raise ValueError if the response is malformed."""
        if self.version != DELEGATION_PROTOCOL_VERSION:
            raise ValueError(
                f"Unsupported delegation protocol version: {self.version} " f"(expected {DELEGATION_PROTOCOL_VERSION})",
            )
        if not self.subagent_id:
            raise ValueError("subagent_id must not be empty")
        if self.status not in VALID_DELEGATION_STATUSES:
            raise ValueError(
                f"Invalid delegation status: '{self.status}'. " f"Must be one of: {sorted(VALID_DELEGATION_STATUSES)}",
            )


def write_cancel_sentinel(delegation_dir: Path, subagent_id: str) -> Path:
    """
    Write a cancel sentinel file for the given subagent.

    The sentinel is an empty file named cancel_{subagent_id} in the delegation dir.
    The host-side watcher monitors for this file and cancels the running container.
    """
    sentinel = delegation_dir / f"cancel_{subagent_id}"
    sentinel.touch()
    return sentinel


def cancel_sentinel_path(delegation_dir: Path, subagent_id: str) -> Path:
    """Return the path where the cancel sentinel file would be written."""
    return delegation_dir / f"cancel_{subagent_id}"


def request_path(delegation_dir: Path, subagent_id: str) -> Path:
    """Return the path for a delegation request file."""
    return delegation_dir / f"request_{subagent_id}.json"


def response_path(delegation_dir: Path, subagent_id: str) -> Path:
    """Return the path for a delegation response file."""
    return delegation_dir / f"response_{subagent_id}.json"
