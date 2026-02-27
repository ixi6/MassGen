"""
Host-side SubagentLaunchWatcher for file-based subprocess delegation (MAS-325).

The watcher polls a shared delegation directory for DelegationRequest files written
by containerized SubagentManager instances. For each request it:
1. Validates the workspace path against an allowlist
2. Runs the subagent as a host subprocess via `uv run massgen --automation`
3. Writes a DelegationResponse file atomically

The subagent's yaml_config selects the backend (claude_code, codex, etc.) and each
backend handles its own isolation. This watcher's sole job is to escape the parent
container boundary — NOT to provide additional sandboxing.

Security properties enforced by this class (running on the HOST, not in the container):
- workspace path validated against allowed_workspace_roots
- Unknown fields in request files are silently ignored

Usage:
    watcher = SubagentLaunchWatcher(
        delegation_dir=path,
        allowed_workspace_roots=[Path("/runs")],
    )
    await watcher.start()
    # ... watcher runs in background ...
    await watcher.stop()
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from massgen.subagent.delegation_protocol import (
    DELEGATION_PROTOCOL_VERSION,
    DelegationRequest,
    DelegationResponse,
    cancel_sentinel_path,
)

# Poll interval for checking for new request files
_POLL_INTERVAL_SECONDS = 0.5


class SubagentLaunchWatcher:
    """
    Host-side watcher that processes delegated subagent requests.

    Polls `delegation_dir` for `request_*.json` files and executes each
    subagent as a host subprocess (`uv run massgen --automation`), writing
    back a response file.

    Each subagent's yaml_config selects the backend; that backend handles
    its own container/isolation. This watcher does NOT create Docker containers.
    """

    def __init__(
        self,
        delegation_dir: Path,
        allowed_workspace_roots: list[Path] | None = None,
        poll_interval: float = _POLL_INTERVAL_SECONDS,
    ) -> None:
        """
        Initialize the SubagentLaunchWatcher.

        Args:
            delegation_dir: Shared directory for request/response files.
            allowed_workspace_roots: Workspace paths must be under one of these roots.
                If None, no allowlist enforcement (not recommended for production).
            poll_interval: How often to check for new requests (seconds).
        """
        self.delegation_dir = Path(delegation_dir)
        self.allowed_workspace_roots: list[Path] = [Path(r).resolve() for r in allowed_workspace_roots] if allowed_workspace_roots else []
        self.poll_interval = poll_interval

        self._running: bool = False
        self._poll_task: asyncio.Task | None = None
        self._active_tasks: dict[str, asyncio.Task] = {}  # subagent_id -> task
        self._seen_requests: set[str] = set()  # subagent_ids already processing or done

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the polling loop in the background."""
        if self._running:
            return
        self.delegation_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop(), name="SubagentLaunchWatcher.poll")
        logger.info(
            f"[SubagentLaunchWatcher] Started, polling {self.delegation_dir} " f"every {self.poll_interval}s",
        )

    async def stop(self) -> None:
        """Stop the polling loop and cancel all active subprocess tasks."""
        if not self._running:
            return
        self._running = False

        # Cancel poll loop
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        # Cancel all active subprocess runs
        for subagent_id, task in list(self._active_tasks.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._active_tasks.clear()

        logger.info("[SubagentLaunchWatcher] Stopped")

    def cancel_subagent(self, subagent_id: str) -> bool:
        """
        Request cancellation of a running subagent task.

        Returns True if the task was found and cancellation requested,
        False if subagent_id was not found in active tasks.
        """
        task = self._active_tasks.get(subagent_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    # -------------------------------------------------------------------------
    # Internal polling
    # -------------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Main polling loop: scan delegation_dir for new request files."""
        while self._running:
            try:
                await self._scan_and_dispatch()
            except Exception as e:
                logger.error(f"[SubagentLaunchWatcher] Poll loop error: {e}", exc_info=True)
            await asyncio.sleep(self.poll_interval)

    async def _scan_and_dispatch(self) -> None:
        """Scan delegation_dir for new request files and dispatch handlers."""
        try:
            request_files = list(self.delegation_dir.glob("request_*.json"))
        except OSError as e:
            logger.warning(f"[SubagentLaunchWatcher] Cannot scan delegation dir: {e}")
            return

        for req_file in request_files:
            # Extract subagent_id from filename: request_{subagent_id}.json
            subagent_id = req_file.stem[len("request_") :]
            if subagent_id in self._seen_requests:
                continue

            self._seen_requests.add(subagent_id)
            task = asyncio.create_task(
                self._handle_request_file(req_file, subagent_id),
                name=f"SubagentLaunchWatcher.handle.{subagent_id}",
            )
            self._active_tasks[subagent_id] = task

        # Clean up completed tasks
        done_ids = [sid for sid, t in self._active_tasks.items() if t.done()]
        for sid in done_ids:
            del self._active_tasks[sid]

    async def _handle_request_file(self, req_file: Path, subagent_id: str) -> None:
        """Load a request file and dispatch to _handle_request."""
        try:
            request = DelegationRequest.from_file(req_file)
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
            logger.error(f"[SubagentLaunchWatcher] Failed to parse request {req_file}: {e}")
            return

        try:
            request.validate()
        except ValueError as e:
            logger.error(f"[SubagentLaunchWatcher] Invalid request from {req_file}: {e}")
            self._write_error_response(request, f"Invalid request: {e}")
            return

        await self._handle_request(request)

    async def _handle_request(self, request: DelegationRequest) -> None:
        """Process a validated DelegationRequest: validate workspace, run subprocess, write response."""
        subagent_id = request.subagent_id

        # Security: validate workspace path
        if not self._validate_workspace_path(request.workspace):
            logger.error(
                f"[SubagentLaunchWatcher] Rejected request {subagent_id}: " f"workspace '{request.workspace}' outside allowed roots",
            )
            self._write_error_response(request, f"Workspace path not in allowed roots: {request.workspace}")
            return

        logger.info(
            f"[SubagentLaunchWatcher] Handling delegated request for {subagent_id}, " f"workspace={request.workspace}, timeout={request.timeout_seconds}s",
        )

        # Run the subagent subprocess
        exit_code = 1
        stdout_tail = ""
        stderr_tail = ""
        status = "error"

        try:
            exit_code, stdout_tail, stderr_tail = await asyncio.wait_for(
                self._run_subprocess(request, request.yaml_config),
                timeout=request.timeout_seconds + 30,  # grace period
            )
            status = "completed" if exit_code == 0 else "error"
        except TimeoutError:
            logger.warning(f"[SubagentLaunchWatcher] Subagent {subagent_id} timed out")
            status = "timeout"
            exit_code = -1
        except asyncio.CancelledError:
            logger.warning(f"[SubagentLaunchWatcher] Subagent {subagent_id} cancelled")
            status = "cancelled"
            exit_code = -1
            raise  # Re-raise so the task is marked cancelled
        except Exception as e:
            logger.error(f"[SubagentLaunchWatcher] Subprocess error for {subagent_id}: {e}", exc_info=True)
            status = "error"
            stderr_tail = str(e)[-2000:]

        # Check for cancel sentinel (container may have written it during execution)
        sentinel = cancel_sentinel_path(self.delegation_dir, subagent_id)
        if sentinel.exists():
            status = "cancelled"
            exit_code = -1

        self._write_response(request, status, exit_code, stdout_tail, stderr_tail)

    # -------------------------------------------------------------------------
    # Subprocess execution
    # -------------------------------------------------------------------------

    async def _run_subprocess(
        self,
        request: DelegationRequest,
        yaml_config: dict[str, Any],
    ) -> tuple[int, str, str]:
        """
        Run the subagent as a host subprocess.

        Writes the YAML config to the workspace and invokes `uv run massgen --automation`.
        The subagent's backend (claude_code, codex, etc.) handles its own isolation.

        Returns:
            Tuple of (exit_code, stdout_tail, stderr_tail)
        """
        workspace = Path(request.workspace)
        workspace.mkdir(parents=True, exist_ok=True)

        # Write YAML config to workspace
        config_path = workspace / f"delegated_config_{request.subagent_id}.yaml"
        config_path.write_text(yaml.dump(yaml_config, default_flow_style=False))

        answer_file = Path(request.answer_file)
        answer_file.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "uv",
            "run",
            "massgen",
            "--config",
            str(config_path),
            "--automation",
            "--output-file",
            str(answer_file),
            request.task,
        ]

        logger.debug(f"[SubagentLaunchWatcher] Launching subprocess for {request.subagent_id}: {cmd}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace),
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                process.communicate(),
                timeout=request.timeout_seconds,
            )
            exit_code = process.returncode if process.returncode is not None else 1
            return exit_code, stdout_b.decode()[-2000:], stderr_b.decode()[-2000:]
        except (TimeoutError, asyncio.CancelledError):
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except TimeoutError:
                process.kill()
                await process.wait()
            raise

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def _validate_workspace_path(self, workspace_str: str) -> bool:
        """
        Validate that workspace is under one of the allowed roots.

        Returns True if allowed (or no allowlist configured), False if rejected.
        """
        if not self.allowed_workspace_roots:
            return True  # No allowlist configured, allow all

        try:
            workspace = Path(workspace_str).resolve()
        except (OSError, ValueError):
            return False

        for root in self.allowed_workspace_roots:
            if workspace == root or workspace.is_relative_to(root):
                return True

        return False

    # -------------------------------------------------------------------------
    # Response writing
    # -------------------------------------------------------------------------

    def _write_response(
        self,
        request: DelegationRequest,
        status: str,
        exit_code: int,
        stdout_tail: str,
        stderr_tail: str,
    ) -> None:
        """Write a DelegationResponse file atomically."""
        resp = DelegationResponse(
            version=DELEGATION_PROTOCOL_VERSION,
            subagent_id=request.subagent_id,
            request_id=request.request_id,
            status=status,
            exit_code=exit_code,
            stdout_tail=stdout_tail[-2000:] if stdout_tail else "",
            stderr_tail=stderr_tail[-2000:] if stderr_tail else "",
        )
        try:
            resp.to_file(self.delegation_dir)
            logger.info(
                f"[SubagentLaunchWatcher] Wrote response for {request.subagent_id}: " f"status={status}, exit_code={exit_code}",
            )
        except OSError as e:
            logger.error(f"[SubagentLaunchWatcher] Failed to write response for {request.subagent_id}: {e}")

    def _write_error_response(self, request: DelegationRequest, error_msg: str) -> None:
        """Write an error response for a request that failed validation or parsing."""
        self._write_response(request, "error", -1, "", error_msg[-2000:])
