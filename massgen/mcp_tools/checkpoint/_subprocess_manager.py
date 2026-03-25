"""
Checkpoint Subprocess Manager for MassGen.

Manages the lifecycle of checkpoint sub-runs as child processes:
- Generates checkpoint config from parent config + signal
- Spawns ``massgen --stream-events`` subprocess
- Relays events back to the parent orchestrator with remapped agent IDs
- Syncs workspace deliverables back to the main agent after completion
"""

import asyncio
import json
import logging
import os
import secrets
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from massgen.events import MassGenEvent
from massgen.mcp_tools.subrun_utils import (
    generate_checkpoint_config,
    sync_workspace_from_subrun,
    write_subrun_config,
)

logger = logging.getLogger(__name__)

# Match SubagentManager's buffer size for large JSON event lines
_SUBPROCESS_STREAM_LIMIT = 4 * 1024 * 1024

# Default timeout for checkpoint subprocess (30 minutes).
# Checkpoints run full multi-agent coordination rounds which can take
# significantly longer than single subagent tasks.
_DEFAULT_TIMEOUT = 1800


class CheckpointSubprocessManager:
    """Manages a checkpoint sub-run as a child process.

    Usage::

        mgr = CheckpointSubprocessManager(
            parent_config=raw_config_dict,
            parent_workspace=main_agent_workspace,
            checkpoint_number=1,
        )
        result = await mgr.spawn(
            signal=checkpoint_signal,
            on_event=relay_callback,
        )
    """

    def __init__(
        self,
        parent_config: dict[str, Any],
        parent_workspace: str | Path,
        checkpoint_number: int,
        timeout: int = _DEFAULT_TIMEOUT,
    ):
        self._parent_config = parent_config
        self._parent_workspace = Path(parent_workspace)
        self._checkpoint_number = checkpoint_number
        self._timeout = timeout
        self._process: asyncio.subprocess.Process | None = None
        self._checkpoint_workspace: Path | None = None

    def _remap_agent_id(self, agent_id: str | None) -> str | None:
        """Remap an agent ID to include the checkpoint suffix."""
        if agent_id is None:
            return None
        return f"{agent_id}-ckpt{self._checkpoint_number}"

    def _create_checkpoint_workspace(self) -> Path:
        """Create an isolated workspace directory for the checkpoint subprocess."""
        suffix = secrets.token_hex(4)
        ws = self._parent_workspace.parent / (f"{self._parent_workspace.name}_ckpt_{self._checkpoint_number}_{suffix}")
        ws.mkdir(parents=True, exist_ok=True)

        # Clone parent workspace files into checkpoint workspace
        if self._parent_workspace.exists():
            for item in self._parent_workspace.iterdir():
                if item.name.startswith("."):
                    continue
                dst = ws / item.name
                if dst.exists():
                    continue
                try:
                    if item.is_file():
                        shutil.copy2(item, dst)
                    elif item.is_dir() and not item.is_symlink():
                        shutil.copytree(item, dst, dirs_exist_ok=True)
                except Exception as e:
                    logger.warning(
                        f"[CheckpointSubprocess] Failed to clone {item.name}: {e}",
                    )

        self._checkpoint_workspace = ws
        logger.info(
            f"[CheckpointSubprocess] Created workspace: {ws}",
        )
        return ws

    def _get_checkpoint_log_dir(self) -> Path | None:
        """Get/create the checkpoint log directory in the parent's log tree.

        Returns:
            Path like ``{parent_log}/checkpoint_1/``, or None.
        """
        try:
            from massgen.logger_config import get_log_session_dir

            parent_log_dir = get_log_session_dir()
            if not parent_log_dir:
                return None
            log_dir = Path(parent_log_dir) / f"checkpoint_{self._checkpoint_number}"
            log_dir.mkdir(parents=True, exist_ok=True)
            return log_dir
        except Exception:
            return None

    def _create_live_log_symlink(self, workspace: Path) -> None:
        """Create ``live_logs`` symlink in the checkpoint log dir.

        Points at the checkpoint workspace so you can follow subprocess
        logs in real-time. Same pattern as SubagentManager.
        """
        log_dir = self._get_checkpoint_log_dir()
        if not log_dir:
            return
        link = log_dir / "live_logs"
        try:
            target = workspace.resolve() / ".massgen" / "massgen_logs"
            if link.is_symlink():
                link.unlink()
            link.symlink_to(target)
            logger.info(f"[CheckpointSubprocess] Live logs: {link}")
        except Exception as e:
            logger.debug(f"[CheckpointSubprocess] Symlink failed: {e}")

    def _copy_subprocess_logs(self) -> None:
        """Copy subprocess logs into the parent's log directory.

        Copies ``{workspace}/.massgen/massgen_logs/log_*/`` to
        ``{parent_log}/checkpoint_N/full_logs/``. Same pattern as
        SubagentManager._write_subprocess_log_reference().
        """
        if not self._checkpoint_workspace:
            return
        log_dir = self._get_checkpoint_log_dir()
        if not log_dir:
            return

        sub_logs_base = self._checkpoint_workspace / ".massgen" / "massgen_logs"
        if not sub_logs_base.exists():
            return

        dest = log_dir / "full_logs"
        try:
            log_dirs = sorted(sub_logs_base.iterdir())
            if log_dirs:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(log_dirs[-1], dest, symlinks=True, ignore_dangling_symlinks=True)
                logger.info(f"[CheckpointSubprocess] Logs copied to: {dest}")
            # Remove live_logs symlink now that we have the real logs
            live_link = log_dir / "live_logs"
            if live_link.is_symlink():
                live_link.unlink()
        except Exception as e:
            logger.warning(f"[CheckpointSubprocess] Failed to copy logs: {e}")

    def _build_command(
        self,
        config_path: Path,
        answer_file: Path,
        task: str,
    ) -> list[str]:
        """Build the subprocess command for the checkpoint sub-run."""
        cmd = [
            "uv",
            "run",
            "massgen",
            "--config",
            str(config_path),
            "--stream-events",  # implies --automation
            "--no-session-registry",
            "--output-file",
            str(answer_file),
            task,
        ]
        return cmd

    @staticmethod
    def _clean_subprocess_env() -> dict[str, str]:
        """Return a copy of os.environ with CLAUDECODE removed.

        Prevents nested Claude Code session detection in child processes.
        """
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        return env

    async def spawn(
        self,
        signal: dict[str, Any],
        on_event: Callable[[MassGenEvent], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Spawn the checkpoint subprocess and relay events.

        Args:
            signal: The checkpoint signal dict with task, eval_criteria, etc.
            on_event: Async callback receiving each remapped MassGenEvent.

        Returns:
            Dict with ``success``, ``output``, ``workspace_changes``,
            ``execution_time_seconds``.
        """
        start_time = time.time()
        task = signal.get("task", "")

        # Create isolated workspace
        workspace = self._create_checkpoint_workspace()

        # Generate and write config
        config = generate_checkpoint_config(
            parent_config=self._parent_config,
            workspace=workspace,
            signal=signal,
        )
        config_path = workspace / f"checkpoint_{self._checkpoint_number}.yaml"
        write_subrun_config(config, config_path)

        # Build command
        answer_file = workspace / "answer.txt"
        cmd = self._build_command(config_path, answer_file, task)

        logger.info(
            f"[CheckpointSubprocess] Spawning checkpoint #{self._checkpoint_number}: " f"{task[:80]}",
        )

        # Create a symlink in the parent's log directory pointing to the
        # live checkpoint workspace so users can find it during the run.
        self._create_live_log_symlink(workspace)

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_SUBPROCESS_STREAM_LIMIT,
                cwd=str(workspace),
                env=self._clean_subprocess_env(),
            )

            # Stream events from subprocess stdout
            stderr_chunks: list[bytes] = []

            async def _relay_events():
                if self._process and self._process.stdout:
                    async for line in self._process.stdout:
                        try:
                            line_str = line.decode().strip()
                            if not line_str:
                                continue
                            event = MassGenEvent.from_json(line_str)
                            # Remap agent_id
                            event.agent_id = self._remap_agent_id(event.agent_id)
                            if on_event:
                                await on_event(event)
                        except json.JSONDecodeError:
                            logger.debug(
                                "[CheckpointSubprocess] Non-JSON: %s",
                                line_str[:200],
                            )
                        except Exception as e:
                            logger.warning(
                                f"[CheckpointSubprocess] Event relay error: {e}",
                            )

            async def _drain_stderr():
                if self._process and self._process.stderr:
                    async for line in self._process.stderr:
                        stderr_chunks.append(line)

            stderr_task = asyncio.create_task(_drain_stderr())
            try:
                await asyncio.wait_for(_relay_events(), timeout=self._timeout)
                if self._process:
                    await self._process.wait()
            except TimeoutError:
                logger.warning(
                    f"[CheckpointSubprocess] Timed out after {self._timeout}s, " "terminating...",
                )
                if self._process:
                    self._process.terminate()
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=5.0)
                    except TimeoutError:
                        self._process.kill()
                        await self._process.wait()
                return {
                    "success": False,
                    "output": "",
                    "error": f"Checkpoint timed out after {self._timeout}s",
                    "workspace_changes": [],
                    "execution_time_seconds": time.time() - start_time,
                }
            finally:
                stderr_task.cancel()
                try:
                    await stderr_task
                except asyncio.CancelledError:
                    pass

            execution_time = time.time() - start_time

            # Check exit code
            returncode = self._process.returncode if self._process else -1
            if returncode != 0:
                stderr_text = b"".join(stderr_chunks).decode(errors="replace")
                logger.error(
                    f"[CheckpointSubprocess] Failed with code {returncode}: " f"{stderr_text[:500]}",
                )
                return {
                    "success": False,
                    "output": "",
                    "error": f"Checkpoint subprocess failed (exit {returncode})",
                    "workspace_changes": [],
                    "execution_time_seconds": execution_time,
                }

            # Read answer
            output = ""
            if answer_file.exists():
                output = answer_file.read_text().strip()

            # Sync workspace deliverables back to parent
            workspace_changes = sync_workspace_from_subrun(
                subrun_workspace=workspace,
                main_workspace=self._parent_workspace,
            )

            logger.info(
                f"[CheckpointSubprocess] Completed in {execution_time:.1f}s, " f"{len(workspace_changes)} files synced back",
            )

            return {
                "success": True,
                "output": output,
                "workspace_changes": workspace_changes,
                "execution_time_seconds": execution_time,
            }

        except Exception as e:
            logger.error(f"[CheckpointSubprocess] Error: {e}")
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "workspace_changes": [],
                "execution_time_seconds": time.time() - start_time,
            }

    def cleanup(self) -> None:
        """Remove the checkpoint workspace directory."""
        if self._checkpoint_workspace and self._checkpoint_workspace.exists():
            try:
                shutil.rmtree(self._checkpoint_workspace, ignore_errors=True)
                logger.info(
                    f"[CheckpointSubprocess] Cleaned up: " f"{self._checkpoint_workspace}",
                )
            except Exception as e:
                logger.debug(
                    f"[CheckpointSubprocess] Cleanup failed: {e}",
                )

    async def terminate(self) -> None:
        """Terminate the subprocess if running."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
