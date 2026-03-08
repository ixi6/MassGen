"""
GitHub Copilot backend implementation using github-copilot-sdk.

Reimplemented to use MCP server integration similar to Codex and Claude Code backends.
Supports custom tools and MCP servers via the SDK's native mcpServers configuration.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

try:
    from copilot import CopilotClient, Tool

    COPILOT_SDK_AVAILABLE = True
except ImportError:
    COPILOT_SDK_AVAILABLE = False
    CopilotClient = object
    Tool = None

from ..logger_config import logger
from ._streaming_buffer_mixin import StreamingBufferMixin
from .base import FilesystemSupport, LLMBackend, StreamChunk
from .native_tool_mixin import NativeToolBackendMixin


class CopilotBackend(NativeToolBackendMixin, StreamingBufferMixin, LLMBackend):
    """GitHub Copilot backend integration with native MCP support."""

    def __init__(self, api_key: str | None = None, **kwargs):
        if not COPILOT_SDK_AVAILABLE:
            raise ImportError(
                "github-copilot-sdk is required for CopilotBackend. " "Install it with: pip install github-copilot-sdk",
            )

        super().__init__(api_key, **kwargs)
        self.__init_native_tool_mixin__()

        self.client = CopilotClient()
        self.sessions: dict[str, Any] = {}
        self._session_signatures: dict[str, str] = {}
        self._started = False

        config_mcp_servers = self.config.get("mcp_servers", [])
        self.mcp_servers = list(config_mcp_servers) if isinstance(config_mcp_servers, list) else []

        if not self.filesystem_manager:
            self._cwd: str = os.getcwd()
        else:
            self._cwd = str(Path(str(self.filesystem_manager.get_current_workspace())).resolve())

        self._custom_tool_specs_path: Path | None = None
        self._custom_tools_config: list[dict[str, Any]] = []
        custom_tools = list(kwargs.get("custom_tools", []))

        enable_multimodal = self.config.get("enable_multimodal_tools", False) or kwargs.get("enable_multimodal_tools", False)
        if enable_multimodal:
            from .base import get_multimodal_tool_definitions

            custom_tools.extend(get_multimodal_tool_definitions())
            logger.info("Copilot backend: multimodal tools enabled (read_media, generate_media)")

        if custom_tools:
            self._setup_custom_tools_mcp(custom_tools)

    def get_provider_name(self) -> str:
        return "copilot"

    def get_filesystem_support(self) -> FilesystemSupport:
        return FilesystemSupport.MCP

    def get_disallowed_tools(self, config: dict[str, Any]) -> list[str]:
        return []

    def get_tool_category_overrides(self) -> dict[str, str]:
        return {}

    def is_mcp_tool_call(self, tool_name: str) -> bool:
        """Check if a tool call should be treated as MCP-originated."""
        if not tool_name:
            return False
        return tool_name.startswith("mcp__") or "/" in tool_name

    def is_custom_tool_call(self, tool_name: str) -> bool:
        """Check if a tool call should be treated as MassGen custom-tool-originated."""
        if not tool_name:
            return False
        return tool_name.startswith("custom_tool__") or tool_name.startswith("massgen_custom_tools/") or tool_name.startswith("mcp__massgen_custom_tools__")

    def is_stateful(self) -> bool:
        return True

    async def clear_history(self) -> None:
        for agent_id in list(self.sessions):
            await self._destroy_session(agent_id)

    async def reset_state(self) -> None:
        for agent_id in list(self.sessions):
            await self._destroy_session(agent_id)

    async def _ensure_started(self):
        if self._started:
            return

        try:
            await self.client.start()
            self._started = True
        except Exception as e:
            if "already running" in str(e).lower():
                self._started = True
            else:
                logger.error(f"[Copilot] Client failed to start: {e}")
                raise

    @staticmethod
    def _extract_auth_status_fields(auth_status: Any) -> tuple[bool | None, str | None]:
        """Extract auth fields from SDK response with backward compatibility."""
        if auth_status is None:
            return None, None

        is_auth = getattr(auth_status, "isAuthenticated", None)
        if is_auth is None:
            is_auth = getattr(auth_status, "authenticated", None)
        if is_auth is not None:
            is_auth = bool(is_auth)

        status_message = getattr(auth_status, "statusMessage", None)
        if status_message is None:
            status_message = getattr(auth_status, "status_message", None)
        if status_message is not None:
            status_message = str(status_message)

        return is_auth, status_message

    @staticmethod
    def _build_auth_error_message(status_message: str | None = None) -> str:
        base = "Copilot authentication is required. Run `copilot login` for this user/session " "and retry."
        if status_message:
            return f"{base} (SDK status: {status_message})"
        return base

    @staticmethod
    def _is_session_send_auth_error(error: Exception) -> bool:
        msg = str(error).lower()
        return "session was not created with authentication info or custom provider" in msg

    @staticmethod
    def _is_invalid_request_body_error(message: str) -> bool:
        return "invalid_request_body" in str(message).lower()

    def _resolve_working_directory(self, explicit_cwd: str | None = None) -> str:
        if explicit_cwd:
            return str(Path(str(explicit_cwd)).resolve())
        if self.filesystem_manager:
            return str(Path(str(self.filesystem_manager.get_current_workspace())).resolve())
        return str(Path(self._cwd).resolve())

    def _ensure_custom_tools_specs_ready(
        self,
        *,
        agent_id: str,
        working_dir: str | None = None,
    ) -> tuple[bool, str | None]:
        """Ensure custom tool specs are present and MCP config points to the current workspace."""
        if not self._custom_tools_config:
            return True, None

        try:
            from ..mcp_tools.custom_tools_server import (
                build_server_config,
                write_tool_specs,
            )
        except ImportError as e:
            error_msg = "Copilot custom tools are configured but custom_tools_server is unavailable. " "Install or fix MassGen custom tools server imports."
            logger.error(f"[Copilot] Custom tools readiness failed for {agent_id}: {error_msg} ({e})")
            return False, error_msg

        cwd = self._resolve_working_directory(working_dir)
        config_dir = Path(cwd) / ".copilot"
        specs_path = config_dir / "custom_tool_specs.json"

        try:
            write_tool_specs(self._custom_tools_config, specs_path)
        except Exception as e:
            error_msg = f"Copilot custom tools setup failed: could not write specs file at {specs_path}. " "Check workspace permissions and retry."
            logger.error(f"[Copilot] Custom tools readiness failed for {agent_id}: {error_msg} ({e})")
            return False, error_msg

        self._custom_tool_specs_path = specs_path
        exists = specs_path.exists()
        size = specs_path.stat().st_size if exists else 0
        logger.info(
            f"[Copilot] Custom tool specs ({agent_id}): " f"workspace={cwd}, path={specs_path}, exists={exists}, size={size}",
        )
        if not exists or size <= 0:
            error_msg = f"Copilot custom tools setup failed: specs file missing or empty at {specs_path}. " "Retry after verifying workspace access."
            logger.error(f"[Copilot] Custom tools readiness failed for {agent_id}: {error_msg}")
            return False, error_msg

        try:
            server_config = build_server_config(
                tool_specs_path=specs_path,
                allowed_paths=[cwd],
                agent_id=self.config.get("agent_id") or agent_id,
                env=self._build_custom_tools_mcp_env(),
            )
        except Exception as e:
            error_msg = "Copilot custom tools setup failed while building MCP server configuration. " "Check custom tools MCP config and retry."
            logger.error(f"[Copilot] Custom tools readiness failed for {agent_id}: {error_msg} ({e})")
            return False, error_msg

        if "tools" not in server_config:
            server_config["tools"] = ["*"]

        replaced = False
        for i, server in enumerate(self.mcp_servers):
            if isinstance(server, dict) and server.get("name") == "massgen_custom_tools":
                self.mcp_servers[i] = server_config
                replaced = True
                break
        if not replaced:
            self.mcp_servers.append(server_config)

        return True, None

    async def _query_auth_status(self, *, context: str) -> tuple[bool | None, str | None]:
        try:
            auth_status = await self.client.get_auth_status()
        except Exception as e:
            logger.warning(f"[Copilot] Could not query auth status ({context}): {e}")
            return None, None

        is_auth, status_message = self._extract_auth_status_fields(auth_status)
        logger.info(
            f"[Copilot] Auth status ({context}): " f"isAuthenticated={is_auth}, statusMessage={status_message!r}",
        )
        return is_auth, status_message

    async def _restart_client_for_auth(self) -> None:
        try:
            await self.client.stop()
        except Exception as e:
            logger.warning(f"[Copilot] Client stop during auth retry failed: {e}")
        self._started = False
        await self._ensure_started()

    async def _ensure_authenticated_with_retry(self, agent_id: str) -> tuple[bool, str | None]:
        is_auth, status_message = await self._query_auth_status(context=f"{agent_id}:initial")
        if is_auth is True:
            return True, status_message
        if is_auth is None:
            logger.error(
                f"[Copilot] Auth state unavailable for {agent_id}. " "Restarting Copilot client once before failing.",
            )
        else:
            logger.error(
                f"[Copilot] Missing authentication for {agent_id}. " "Restarting Copilot client once before failing.",
            )
        await self._restart_client_for_auth()

        is_auth_retry, status_retry = await self._query_auth_status(
            context=f"{agent_id}:post-restart",
        )
        if is_auth_retry is True:
            return True, status_retry

        final_status = status_retry or status_message or "Unable to determine authentication status from Copilot SDK"
        logger.error(
            f"[Copilot] Authentication unavailable for {agent_id} after retry. " f"statusMessage={final_status!r}",
        )
        return False, final_status

    def _setup_custom_tools_mcp(self, custom_tools: list[dict[str, Any]]) -> None:
        """Wrap MassGen custom tools as an MCP server and add to mcp_servers."""
        self._custom_tools_config = custom_tools
        ready, error_msg = self._ensure_custom_tools_specs_ready(
            agent_id=self.config.get("agent_id") or "copilot-init",
            working_dir=self._cwd,
        )
        if not ready:
            logger.error(f"[Copilot] Initial custom tools setup failed: {error_msg}")
            return
        logger.info(f"Custom tools MCP server configured with {len(custom_tools)} tool configs")

    def _build_custom_tools_mcp_env(self) -> dict[str, str]:
        env_vars = {"FASTMCP_SHOW_CLI_BANNER": "false"}

        if not self.config:
            return env_vars

        creds = self.config.get("command_line_docker_credentials") or {}
        if not creds:
            return env_vars

        def _load_env_file(env_file_path: Path) -> dict[str, str]:
            loaded: dict[str, str] = {}
            try:
                with open(env_file_path) as f:
                    for line_num, line in enumerate(f, start=1):
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()
                        # Strip surrounding quotes (same as DockerManager)
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        if key:
                            loaded[key] = value
                        else:
                            logger.warning(
                                f"⚠️ [Copilot] Skipping invalid line {line_num} in {env_file_path}: {line}",
                            )
            except Exception as e:
                logger.warning(f"⚠️ [Copilot] Failed to read env file {env_file_path}: {e}")
            return loaded

        if creds.get("pass_all_env"):
            env_vars.update(os.environ)

        # Search multiple .env locations (same as DockerManager) so
        # subagent workspaces that lack a local .env still pick up keys.
        env_file = creds.get("env_file")
        if env_file:
            home_env = Path.home() / ".massgen" / ".env"
            provided_path = Path(env_file).expanduser().resolve()
            local_env = Path(".env").resolve()

            seen: set[Path] = set()
            candidates: list[Path] = []
            for p in [home_env, provided_path, local_env]:
                resolved = p.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    candidates.append(resolved)

            file_env: dict[str, str] = {}
            for env_path in candidates:
                if env_path.exists():
                    file_env.update(_load_env_file(env_path))

            if file_env:
                filter_list = creds.get("env_vars_from_file")
                if filter_list:
                    filtered_env = {k: v for k, v in file_env.items() if k in filter_list}
                    env_vars.update(filtered_env)
                else:
                    env_vars.update(file_env)
            elif not any(c.exists() for c in candidates):
                logger.warning(
                    f"⚠️ [Copilot] Env file not found in any location: " f"{[str(c) for c in candidates]}",
                )

        for var_name in creds.get("env_vars", []) or []:
            if var_name in os.environ:
                env_vars[var_name] = os.environ[var_name]
            else:
                logger.warning(
                    f"⚠️ [Copilot] Requested env var '{var_name}' not found in host environment",
                )

        return env_vars

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str] | None:
        """Normalize config values that can be a string or list of strings."""
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, (set, tuple)):
            value = list(value)
        if isinstance(value, list):
            normalized: list[str] = []
            for item in value:
                if item is None:
                    continue
                text = str(item).strip()
                if text:
                    normalized.append(text)
            return normalized
        return None

    def _resolve_backend_tool_filters(self, kwargs: dict[str, Any]) -> tuple[list[str] | None, list[str] | None]:
        """Resolve backend-level tool filters from kwargs/config with kwargs precedence."""
        raw_allowed = kwargs.get("allowed_tools") if "allowed_tools" in kwargs else self.config.get("allowed_tools")
        raw_excluded = kwargs.get("exclude_tools") if "exclude_tools" in kwargs else self.config.get("exclude_tools")

        available_tools = self._normalize_string_list(raw_allowed)
        if raw_allowed is not None and available_tools is None:
            logger.warning(f"[Copilot] Ignoring invalid allowed_tools value: {raw_allowed!r}")

        excluded_tools = self._normalize_string_list(raw_excluded)
        if raw_excluded is not None and excluded_tools is None:
            logger.warning(f"[Copilot] Ignoring invalid exclude_tools value: {raw_excluded!r}")

        return available_tools, excluded_tools

    def _resolve_system_message_mode(self, kwargs: dict[str, Any]) -> str:
        """Resolve Copilot system_message mode with safe default."""
        raw_mode = kwargs.get("copilot_system_message_mode")
        if raw_mode is None and "system_message_mode" in kwargs:
            raw_mode = kwargs.get("system_message_mode")
        if raw_mode is None:
            raw_mode = self.config.get("copilot_system_message_mode")
        if raw_mode is None:
            raw_mode = self.config.get("system_message_mode")

        if raw_mode is None:
            return "append"

        mode = str(raw_mode).strip().lower()
        if mode in ("append", "replace"):
            return mode

        logger.warning(
            f"[Copilot] Invalid system message mode {raw_mode!r}; defaulting to 'append'.",
        )
        return "append"

    def _resolve_permission_policy(self, kwargs: dict[str, Any]) -> str:
        """Resolve permission policy into approved/denied decision modes."""
        raw_policy = kwargs.get("copilot_permission_policy")
        if raw_policy is None and "permission_policy" in kwargs:
            raw_policy = kwargs.get("permission_policy")
        if raw_policy is None:
            raw_policy = self.config.get("copilot_permission_policy")
        if raw_policy is None:
            raw_policy = self.config.get("permission_policy")

        if raw_policy is None:
            return "approve"

        policy = str(raw_policy).strip().lower()
        if policy in {"approve", "approved", "allow", "auto", "auto_approve"}:
            return "approve"
        if policy in {"deny", "denied", "reject", "auto_deny"}:
            return "deny"

        logger.warning(
            f"[Copilot] Invalid permission policy {raw_policy!r}; defaulting to approved.",
        )
        return "approve"

    def _build_permission_callback(self, policy: str):
        """Build SDK permission callback from resolved policy."""
        if policy == "deny":

            def _deny_permission(_request, _context):
                return {"kind": "denied-by-rules"}

            return _deny_permission
        return self._auto_approve_permission

    @staticmethod
    def _hash_payload(payload: Any) -> str:
        """Create a deterministic hash for session signature data."""
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_workflow_tools_signature_payload(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize workflow tool schemas for stable signature generation."""
        normalized: list[dict[str, Any]] = []
        for tool_def in tools or []:
            if not isinstance(tool_def, dict):
                continue
            func_def = tool_def.get("function", {})
            if not isinstance(func_def, dict):
                func_def = {}
            tool_name = func_def.get("name") or tool_def.get("name")
            if not tool_name:
                continue
            normalized.append(
                {
                    "name": str(tool_name),
                    "description": str(func_def.get("description", "")),
                    "parameters": func_def.get("parameters", {}),
                },
            )
        normalized.sort(key=lambda item: item["name"])
        return normalized

    def _build_session_signature(
        self,
        *,
        model: str,
        system_message: str | None,
        system_message_mode: str,
        workflow_tools: list[dict[str, Any]],
        mcp_servers: dict[str, Any],
        working_directory: str | None,
        available_tools: list[str] | None,
        excluded_tools: list[str] | None,
        permission_policy: str,
    ) -> str:
        """Build a stable signature for session cache invalidation."""
        payload = {
            "model": model,
            "system_message": system_message or "",
            "system_message_mode": system_message_mode,
            "workflow_tools": self._build_workflow_tools_signature_payload(workflow_tools),
            "mcp_servers_hash": self._hash_payload(mcp_servers),
            "working_directory": working_directory or "",
            "available_tools": available_tools,
            "excluded_tools": excluded_tools,
            "permission_policy": permission_policy,
        }
        return self._hash_payload(payload)

    def _resolve_mcp_tools_for_server(self, server_name: str, server: dict[str, Any]) -> list[str]:
        """Resolve MCP tool filtering for Copilot SDK (allowlist-style tools)."""
        if "tools" in server:
            base_tools = self._normalize_string_list(server.get("tools"))
            if base_tools is None:
                logger.warning(
                    f"[Copilot] MCP server '{server_name}' has invalid 'tools' value; defaulting to ['*']",
                )
                base_tools = ["*"]
        elif "allowed_tools" in server:
            base_tools = self._normalize_string_list(server.get("allowed_tools"))
            if base_tools is None:
                logger.warning(
                    f"[Copilot] MCP server '{server_name}' has invalid 'allowed_tools' value; defaulting to ['*']",
                )
                base_tools = ["*"]
        else:
            base_tools = ["*"]

        if "exclude_tools" in server:
            excluded_tools = self._normalize_string_list(server.get("exclude_tools"))
            if excluded_tools is None:
                logger.warning(
                    f"[Copilot] MCP server '{server_name}' has invalid 'exclude_tools' value; ignoring it.",
                )
                excluded_tools = []

            if excluded_tools:
                if "*" in base_tools:
                    logger.warning(
                        f"[Copilot] MCP server '{server_name}' exclude_tools={excluded_tools} cannot be strictly enforced with wildcard tools in Copilot SDK. Keeping tools={base_tools}.",
                    )
                else:
                    excluded_set = set(excluded_tools)
                    base_tools = [tool_name for tool_name in base_tools if tool_name not in excluded_set]

        return base_tools

    def _build_sdk_tools(
        self,
        tools: list[dict[str, Any]],
        queue: asyncio.Queue,
    ) -> list[Any]:
        """Convert MassGen workflow tool defs (OpenAI format) to SDK Tool objects.

        Tool handlers push a tuple into the shared queue so stream_with_tools
        can emit the corresponding StreamChunk.
        """
        if not Tool or not tools:
            return []

        sdk_tools = []
        for tool_def in tools:
            func_def = tool_def.get("function", {})
            tool_name = func_def.get("name")
            if not tool_name:
                continue

            def _make_handler(name: str, q: asyncio.Queue):
                async def handler(invocation):
                    args = invocation.get("arguments", {})
                    call_id = invocation.get("tool_call_id", f"call-{uuid.uuid4()}")
                    q.put_nowait(("workflow_tool", name, args, call_id))
                    return {
                        "textResultForLlm": f"Tool {name} executed successfully",
                        "resultType": "success",
                    }

                return handler

            sdk_tools.append(
                Tool(
                    name=tool_name,
                    description=func_def.get("description", ""),
                    parameters=func_def.get("parameters"),
                    handler=_make_handler(tool_name, queue),
                ),
            )

        return sdk_tools

    def _build_mcp_servers_dict(self) -> dict[str, Any]:
        """Build SDK-format MCP servers dict from config + internal servers."""
        all_mcp_servers = []

        config_mcp = self.config.get("mcp_servers", [])
        if isinstance(config_mcp, dict):
            for name, srv in config_mcp.items():
                srv_copy = srv.copy()
                srv_copy["name"] = name
                all_mcp_servers.append(srv_copy)
        elif isinstance(config_mcp, list):
            all_mcp_servers.extend(config_mcp)

        existing_names = {s.get("name") for s in all_mcp_servers}
        for s in self.mcp_servers:
            if isinstance(s, dict) and s.get("name") not in existing_names:
                all_mcp_servers.append(s)

        result = {}
        for server in all_mcp_servers:
            name = server.get("name")
            if not name:
                continue

            server_type = str(server.get("type", "local")).lower()
            if server_type == "stdio":
                server_type = "local"
            if server_type not in {"local", "http", "sse"}:
                logger.warning(
                    f"[Copilot] Unknown MCP server type {server_type!r} for '{name}'; defaulting to local.",
                )
                server_type = "local"

            sdk_config: dict[str, Any] = {"type": server_type}

            if server_type == "local":
                for key in ("command", "args", "env", "cwd"):
                    if server.get(key):
                        sdk_config[key] = server[key]

                cmd = sdk_config.get("command")
                if cmd and not os.path.isabs(cmd):
                    venv_bin = Path(sys.executable).parent
                    candidate = venv_bin / (cmd + ".exe" if sys.platform == "win32" else cmd)
                    if candidate.exists():
                        sdk_config["command"] = str(candidate)
                    else:
                        resolved = shutil.which(cmd)
                        if resolved:
                            sdk_config["command"] = resolved

                server_env = sdk_config.get("env") or {}
                env = {**os.environ, **server_env}
                venv_bin_str = str(Path(sys.executable).parent)
                existing_path = env.get("PATH", "")
                if venv_bin_str not in existing_path:
                    env["PATH"] = f"{venv_bin_str}{os.pathsep}{existing_path}" if existing_path else venv_bin_str
                venv_root = os.environ.get("VIRTUAL_ENV")
                if venv_root and "VIRTUAL_ENV" not in env:
                    env["VIRTUAL_ENV"] = venv_root

                sdk_config["env"] = env
            else:
                for key in ("url", "headers"):
                    if server.get(key):
                        sdk_config[key] = server[key]

                if not sdk_config.get("url"):
                    logger.warning(
                        f"[Copilot] Remote MCP server '{name}' missing required 'url' field.",
                    )

            timeout_value = server.get("timeout")
            if timeout_value is not None:
                try:
                    timeout_ms = int(float(timeout_value))
                    if timeout_ms > 0:
                        sdk_config["timeout"] = timeout_ms
                    else:
                        logger.warning(
                            f"[Copilot] Ignoring non-positive timeout={timeout_value!r} on MCP server '{name}'",
                        )
                except (TypeError, ValueError):
                    logger.warning(
                        f"[Copilot] Ignoring invalid timeout={timeout_value!r} on MCP server '{name}'",
                    )
            else:
                timeout_seconds: list[float] = []
                for key in ("tool_timeout_sec", "startup_timeout_sec"):
                    raw_seconds = server.get(key)
                    if raw_seconds is None:
                        continue
                    try:
                        seconds = float(raw_seconds)
                        if seconds > 0:
                            timeout_seconds.append(seconds)
                        else:
                            logger.warning(
                                f"[Copilot] Ignoring non-positive {key}={raw_seconds!r} on MCP server '{name}'",
                            )
                    except (TypeError, ValueError):
                        logger.warning(
                            f"[Copilot] Ignoring invalid {key}={raw_seconds!r} on MCP server '{name}'",
                        )
                if timeout_seconds:
                    sdk_config["timeout"] = int(max(timeout_seconds) * 1000)

            sdk_config["tools"] = self._resolve_mcp_tools_for_server(name, server)

            result[name] = sdk_config

        logger.info(f"[Copilot] Built MCP servers dict: {list(result.keys())}")
        return result

    @staticmethod
    def _auto_approve_permission(request, context):
        return {"kind": "approved"}

    async def stream_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs,
    ) -> AsyncGenerator[StreamChunk]:
        await self._ensure_started()

        agent_id = kwargs.get("agent_id", self.config.get("agent_id") or "default")
        model = kwargs.get("model") or self.config.get("model") or "gpt-4.1"
        queue: asyncio.Queue = asyncio.Queue()

        buffer_kwargs = {k: v for k, v in kwargs.items() if k != "agent_id"}
        self._clear_streaming_buffer(agent_id=agent_id, **buffer_kwargs)
        self.start_api_call_timing(model)

        is_authenticated, auth_status_message = await self._ensure_authenticated_with_retry(
            agent_id,
        )
        if not is_authenticated:
            error_msg = self._build_auth_error_message(auth_status_message)
            logger.error(f"[Copilot] Auth gate blocked request for {agent_id}: {error_msg}")
            self.end_api_call_timing(success=False, error=error_msg)
            self._finalize_streaming_buffer(agent_id=agent_id)
            yield StreamChunk(type="error", error=error_msg, source=agent_id)
            yield StreamChunk(type="done", source=agent_id)
            return

        working_dir = self._resolve_working_directory(kwargs.get("cwd"))
        specs_ready, specs_error = self._ensure_custom_tools_specs_ready(
            agent_id=agent_id,
            working_dir=working_dir,
        )
        if not specs_ready:
            error_msg = specs_error or ("Copilot custom tools setup failed before session start. " "Run again after fixing local workspace/tool configuration.")
            logger.error(f"[Copilot] Pre-session custom tools gate blocked request for {agent_id}: {error_msg}")
            self.end_api_call_timing(success=False, error=error_msg)
            self._finalize_streaming_buffer(agent_id=agent_id)
            yield StreamChunk(type="error", error=error_msg, source=agent_id)
            yield StreamChunk(type="done", source=agent_id)
            return

        sdk_tools = self._build_sdk_tools(tools, queue)
        system_message_mode = self._resolve_system_message_mode(kwargs)
        permission_policy = self._resolve_permission_policy(kwargs)
        permission_callback = self._build_permission_callback(permission_policy)

        system_message = None
        for msg in messages:
            if msg["role"] == "system":
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
                if content:
                    system_message = content
                break

        prompt_parts = []
        for msg in messages:
            if msg["role"] != "system":
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
                if content:
                    prompt_parts.append(f"[{msg['role']}]: {content}")

        prompt = "\n\n".join(prompt_parts) if prompt_parts else "Please continue."

        available_tools, excluded_tools = self._resolve_backend_tool_filters(kwargs)
        mcp_servers = self._build_mcp_servers_dict()
        session_signature = self._build_session_signature(
            model=model,
            system_message=system_message,
            system_message_mode=system_message_mode,
            workflow_tools=tools,
            mcp_servers=mcp_servers,
            working_directory=working_dir,
            available_tools=available_tools,
            excluded_tools=excluded_tools,
            permission_policy=permission_policy,
        )

        session = self.sessions.get(agent_id)
        existing_signature = self._session_signatures.get(agent_id)
        if session is not None and existing_signature != session_signature:
            logger.info(f"[Copilot] Session config changed for {agent_id}; recreating session.")
            await self._destroy_session(agent_id)
            session = None

        if session is None:
            session_config: dict[str, Any] = {
                "model": model,
                "streaming": True,
                "mcp_servers": mcp_servers,
                "on_permission_request": permission_callback,
            }
            if sdk_tools:
                session_config["tools"] = sdk_tools
            if system_message:
                session_config["system_message"] = {
                    "mode": system_message_mode,
                    "content": system_message,
                }
            if working_dir:
                session_config["working_directory"] = working_dir
            if available_tools is not None:
                session_config["available_tools"] = available_tools
            if excluded_tools is not None:
                session_config["excluded_tools"] = excluded_tools

            mcp_names = list(session_config.get("mcp_servers", {}).keys())
            logger.info(f"[Copilot] Creating session for {agent_id} with MCP servers: {mcp_names}")

            try:
                session = await self.client.create_session(session_config)
                self.sessions[agent_id] = session
                self._session_signatures[agent_id] = session_signature
                logger.info(f"[Copilot] Session created successfully for {agent_id}")
            except Exception as e:
                self.end_api_call_timing(success=False, error=str(e))
                logger.error(f"[Copilot] Session creation failed for {agent_id}: {e}")
                self._finalize_streaming_buffer(agent_id=agent_id)
                yield StreamChunk(type="error", error=f"Session creation failed: {e}", source=agent_id)
                yield StreamChunk(type="done", source=agent_id)
                return
        else:
            self._session_signatures[agent_id] = session_signature

        unsubscribe = session.on(lambda event: queue.put_nowait(event))

        seen_event_ids: set = set()
        accumulated_content: list[str] = []
        workflow_tool_called = False
        first_content = True
        usage_data: dict[str, Any] = {}
        stream_success = True

        try:
            logger.debug(f"[Copilot] Sending prompt to session for {agent_id} (length={len(prompt)})")
            send_auth_error: str | None = None
            send_timeout_value = kwargs.get(
                "session_send_timeout_seconds",
                self.config.get("session_send_timeout_seconds", 60),
            )
            try:
                send_timeout_seconds = float(send_timeout_value)
            except (TypeError, ValueError):
                logger.warning(
                    f"[Copilot] Invalid session_send_timeout_seconds={send_timeout_value!r}; using 60s",
                )
                send_timeout_seconds = 60.0
            if send_timeout_seconds <= 0:
                logger.warning(
                    f"[Copilot] Non-positive session_send_timeout_seconds={send_timeout_seconds}; using 60s",
                )
                send_timeout_seconds = 60.0
            try:
                await asyncio.wait_for(
                    session.send({"prompt": prompt}),
                    timeout=send_timeout_seconds,
                )
            except TimeoutError:
                send_auth_error = "Session send timeout while connecting to tools. " "Check Copilot auth (`copilot login`) and MCP server startup."
                logger.error(
                    f"[Copilot] session.send timed out after {send_timeout_seconds}s for {agent_id}. " "(check MCP command paths, env inheritance, and npx/network availability).",
                )
            except Exception as e:
                if self._is_session_send_auth_error(e):
                    send_auth_error = self._build_auth_error_message(
                        "Session was not created with authentication info or custom provider",
                    )
                    logger.error(f"[Copilot] session.send auth error for {agent_id}: {e}")
                else:
                    raise

            if send_auth_error:
                stream_success = False
                yield StreamChunk(type="error", error=send_auth_error, source=agent_id)
                await self._destroy_session(agent_id)
            else:
                logger.debug(f"[Copilot] Prompt sent, waiting for events from {agent_id}...")

                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=300)
                    except TimeoutError:
                        stream_success = False
                        yield StreamChunk(type="error", error="Response timeout", source=agent_id)
                        await self._destroy_session(agent_id)
                        break

                    logger.debug(f"[Copilot] Event received: type={type(event).__name__}, event={getattr(event, 'type', repr(event)[:100])}")

                    if isinstance(event, tuple) and len(event) == 4 and event[0] == "workflow_tool":
                        _, tool_name, tool_args, tool_call_id = event
                        yield StreamChunk(
                            type="tool_calls",
                            tool_calls=[{"name": tool_name, "arguments": tool_args, "id": tool_call_id}],
                            source=agent_id,
                        )
                        if tool_name in ("new_answer", "vote"):
                            workflow_tool_called = True
                            logger.info(
                                f"[Copilot] Terminal workflow tool '{tool_name}' captured for {agent_id}; " "ending stream without waiting for additional model retries.",
                            )
                            await self._destroy_session(agent_id)
                            break
                        continue

                    event_type = event.type
                    if hasattr(event_type, "value"):
                        event_type = event_type.value

                    event_id = getattr(event, "id", None)
                    if event_id is not None:
                        if event_id in seen_event_ids:
                            continue
                        seen_event_ids.add(event_id)

                    if event_type == "assistant.message_delta":
                        data = getattr(event, "data", None)
                        content = getattr(data, "delta_content", None) if data else None
                        if content:
                            if first_content:
                                self.record_first_token()
                                first_content = False
                            accumulated_content.append(content)
                            self._append_to_streaming_buffer(content)
                            yield StreamChunk(type="content", content=content, source=agent_id)

                    elif event_type == "assistant.reasoning_delta":
                        data = getattr(event, "data", None)
                        content = getattr(data, "delta_content", None) if data else None
                        if content:
                            yield StreamChunk(type="reasoning", reasoning_delta=content, source=agent_id)

                    elif event_type == "assistant.message":
                        data = getattr(event, "data", None)
                        final_content = getattr(data, "content", None) if data else None
                        if final_content and not accumulated_content:
                            if first_content:
                                self.record_first_token()
                                first_content = False
                            accumulated_content.append(final_content)
                            self._append_to_streaming_buffer(final_content)
                            yield StreamChunk(type="content", content=final_content, source=agent_id)

                    elif event_type == "assistant.usage":
                        data = getattr(event, "data", None)
                        if data:
                            input_t = getattr(data, "input_tokens", None)
                            output_t = getattr(data, "output_tokens", None)
                            if input_t is not None or output_t is not None:
                                usage_data = {
                                    "prompt_tokens": int(input_t or 0),
                                    "completion_tokens": int(output_t or 0),
                                    "total_tokens": int((input_t or 0) + (output_t or 0)),
                                }

                    elif event_type == "session.error":
                        data = getattr(event, "data", None)
                        error_msg = getattr(data, "message", None) or "Unknown session error"
                        error_type = getattr(data, "error_type", None)
                        status_code = getattr(data, "status_code", None)
                        detail = f"[{error_type}] {error_msg}" if error_type else error_msg
                        if status_code:
                            detail = f"{detail} (HTTP {status_code})"
                        if self._is_invalid_request_body_error(detail):
                            classified_error = "Copilot upstream request-body failure (`invalid_request_body`). " f"Raw error: {detail}"
                            logger.error(
                                f"[Copilot][invalid_request_body] Session error for {agent_id}: {detail}",
                            )
                            stream_success = False
                            yield StreamChunk(type="error", error=classified_error, source=agent_id)
                            await self._destroy_session(agent_id)
                            break
                        logger.error(f"[Copilot] Session error for {agent_id}: {detail}")
                        stream_success = False
                        yield StreamChunk(type="error", error=detail, source=agent_id)
                        await self._destroy_session(agent_id)
                        break

                    elif event_type == "session.idle":
                        break

                    elif event_type == "tool.execution_start":
                        data = getattr(event, "data", None)
                        t_name = getattr(data, "tool_name", None) or getattr(data, "name", None) if data else None
                        if t_name:
                            logger.debug(f"[Copilot] Tool started: {t_name}")

                    elif event_type == "tool.execution_complete":
                        data = getattr(event, "data", None)
                        t_name = getattr(data, "tool_name", None) or getattr(data, "name", None) if data else None
                        if t_name and t_name not in ("new_answer", "vote"):
                            logger.debug(f"[Copilot] Tool complete: {t_name}")

                    elif event_type in ("session.compaction_start", "session.compaction_complete"):
                        logger.info(f"[Copilot] {event_type} for {agent_id}")

                    elif event_type == "session.truncation":
                        logger.warning(f"[Copilot] Session truncated for {agent_id}")

        except Exception as e:
            logger.error(f"[Copilot] Stream error for {agent_id}: {e}")
            stream_success = False
            yield StreamChunk(type="error", error=str(e), source=agent_id)
            await self._destroy_session(agent_id)
        finally:
            unsubscribe()
            self.end_api_call_timing(success=stream_success)
            self._finalize_streaming_buffer(agent_id=agent_id)

        if usage_data:
            self._update_token_usage_from_api_response(usage_data, model)

        if not workflow_tool_called and accumulated_content:
            full_answer = "".join(accumulated_content)
            yield StreamChunk(
                type="tool_calls",
                tool_calls=[
                    {
                        "name": "new_answer",
                        "arguments": {"content": full_answer},
                        "id": f"synth-{agent_id}",
                    },
                ],
                source=agent_id,
            )

        yield StreamChunk(
            type="done",
            usage=usage_data if usage_data else None,
            source=agent_id,
        )

    async def _destroy_session(self, agent_id: str):
        self._session_signatures.pop(agent_id, None)
        session = self.sessions.pop(agent_id, None)
        if session:
            try:
                await session.destroy()
            except Exception:
                pass

    async def close(self):
        for agent_id in list(self.sessions):
            await self._destroy_session(agent_id)

        if self._started:
            try:
                await self.client.stop()
            except Exception as e:
                logger.debug(f"[Copilot] Error stopping client: {e}")
            self._started = False

        if self._custom_tool_specs_path:
            try:
                self._custom_tool_specs_path.unlink(missing_ok=True)
            except Exception as e:
                logger.debug(f"[Copilot] Error cleaning custom tool specs file: {e}")
