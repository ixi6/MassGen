# -*- coding: utf-8 -*-
"""
Hook system for tool call interception in the MassGen multi-agent framework.

This module provides the infrastructure for intercepting tool calls
across different backend architectures (OpenAI, Claude, Gemini, etc.).

Hook Types:
- PRE_TOOL_USE: Fires before tool execution (can block or modify)
- POST_TOOL_USE: Fires after tool execution (can inject content)

Hook Registration:
- Global hooks: Apply to all agents (top-level `hooks:` in config)
- Per-agent hooks: Apply to specific agents (in `backend.hooks:`)
- Per-agent hooks can extend or override global hooks

Built-in Hooks:
- MidStreamInjectionHook: Injects cross-agent updates during tool execution
- HighPriorityTaskReminderHook: Injects reminders for completed high-priority tasks
"""

import asyncio
import fnmatch
import importlib
import json
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Optional, Union

from ..logger_config import logger

# MCP imports for session-based backends
try:
    from mcp import ClientSession, types
    from mcp.client.session import ProgressFnT

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    ClientSession = object
    types = None
    ProgressFnT = None


class HookType(Enum):
    """Types of function call hooks."""

    # Legacy hook types (for backward compatibility)
    PRE_CALL = "pre_call"
    POST_CALL = "post_call"

    # New general hook types
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"


@dataclass
class HookEvent:
    """Input data provided to all hooks.

    This dataclass represents the context passed to hook handlers,
    containing information about the tool call and agent state.
    """

    hook_type: str  # "PreToolUse" or "PostToolUse"
    session_id: str
    orchestrator_id: str
    agent_id: Optional[str]
    timestamp: datetime
    tool_name: str
    tool_input: Dict[str, Any]
    tool_output: Optional[str] = None  # Only populated for PostToolUse

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "hook_type": self.hook_type,
            "session_id": self.session_id,
            "orchestrator_id": self.orchestrator_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat(),
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "tool_output": self.tool_output,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass
class HookResult:
    """Result of a hook execution.

    This dataclass is backward compatible with the old HookResult class
    while adding new fields for the general hook framework.

    The `hook_errors` field tracks any errors that occurred during hook execution
    when using fail-open behavior. This allows callers to be aware of partial
    failures even when the overall result is "allow".
    """

    # Legacy fields (for backward compatibility)
    allowed: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    modified_args: Optional[str] = None

    # New fields for general hook framework
    decision: Literal["allow", "deny", "ask"] = "allow"
    reason: Optional[str] = None
    updated_input: Optional[Dict[str, Any]] = None  # For PreToolUse
    inject: Optional[Dict[str, Any]] = None  # For PostToolUse injection

    # Error tracking for fail-open scenarios
    hook_errors: List[str] = field(default_factory=list)

    # Hook execution tracking (for display in TUI/WebUI)
    hook_name: Optional[str] = None
    hook_type: Optional[str] = None  # "pre" or "post"
    execution_time_ms: Optional[float] = None

    # Aggregated hook executions (populated by GeneralHookManager.execute_hooks)
    # Each entry: {"hook_name": str, "hook_type": str, "decision": str, "reason": str, "execution_time_ms": float, "injection_preview": str}
    executed_hooks: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        """Sync legacy and new fields for compatibility."""
        # Sync decision with allowed
        if not self.allowed:
            self.decision = "deny"
        elif self.decision == "deny":
            self.allowed = False

    def add_error(self, error: str) -> None:
        """Add an error message to track partial failures in fail-open mode."""
        self.hook_errors.append(error)

    def has_errors(self) -> bool:
        """Check if any errors occurred during hook execution."""
        return len(self.hook_errors) > 0

    def add_executed_hook(
        self,
        hook_name: str,
        hook_type: str,
        decision: str,
        reason: Optional[str] = None,
        execution_time_ms: Optional[float] = None,
        injection_preview: Optional[str] = None,
        injection_content: Optional[str] = None,
    ) -> None:
        """Track an executed hook for display purposes."""
        self.executed_hooks.append(
            {
                "hook_name": hook_name,
                "hook_type": hook_type,
                "decision": decision,
                "reason": reason,
                "execution_time_ms": execution_time_ms,
                "injection_preview": injection_preview,
                "injection_content": injection_content,
            },
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HookResult":
        """Create HookResult from dictionary (e.g., from JSON)."""
        return cls(
            allowed=data.get("allowed", True),
            metadata=data.get("metadata", {}),
            modified_args=data.get("modified_args"),
            decision=data.get("decision", "allow"),
            reason=data.get("reason"),
            updated_input=data.get("updated_input"),
            inject=data.get("inject"),
            hook_errors=data.get("hook_errors", []),
            hook_name=data.get("hook_name"),
            hook_type=data.get("hook_type"),
            execution_time_ms=data.get("execution_time_ms"),
            executed_hooks=data.get("executed_hooks", []),
        )

    @classmethod
    def allow(cls) -> "HookResult":
        """Create a result that allows the operation."""
        return cls(allowed=True, decision="allow")

    @classmethod
    def deny(cls, reason: Optional[str] = None) -> "HookResult":
        """Create a result that denies the operation."""
        return cls(allowed=False, decision="deny", reason=reason)

    @classmethod
    def ask(cls, reason: Optional[str] = None) -> "HookResult":
        """Create a result that requires user confirmation."""
        return cls(allowed=True, decision="ask", reason=reason)


class FunctionHook(ABC):
    """Base class for function call hooks."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def execute(self, function_name: str, arguments: str, context: Optional[Dict[str, Any]] = None, **kwargs) -> HookResult:
        """
        Execute the hook.

        Args:
            function_name: Name of the function being called
            arguments: JSON string of arguments
            context: Additional context (backend, timestamp, etc.)

        Returns:
            HookResult with allowed flag and optional modifications
        """


class FunctionHookManager:
    """Manages registration and execution of function hooks."""

    def __init__(self):
        self._hooks: Dict[HookType, List[FunctionHook]] = {hook_type: [] for hook_type in HookType}
        self._global_hooks: Dict[HookType, List[FunctionHook]] = {hook_type: [] for hook_type in HookType}

    def register_hook(self, function_name: str, hook_type: HookType, hook: FunctionHook):
        """Register a hook for a specific function."""
        if function_name not in self._hooks:
            self._hooks[function_name] = {hook_type: [] for hook_type in HookType}

        if hook_type not in self._hooks[function_name]:
            self._hooks[function_name][hook_type] = []

        self._hooks[function_name][hook_type].append(hook)

    def register_global_hook(self, hook_type: HookType, hook: FunctionHook):
        """Register a hook that applies to all functions."""
        self._global_hooks[hook_type].append(hook)

    def get_hooks_for_function(self, function_name: str) -> Dict[HookType, List[FunctionHook]]:
        """Get all hooks (function-specific + global) for a function."""
        result = {hook_type: [] for hook_type in HookType}

        # Add global hooks first
        for hook_type in HookType:
            result[hook_type].extend(self._global_hooks[hook_type])

        # Add function-specific hooks
        if function_name in self._hooks:
            for hook_type in HookType:
                if hook_type in self._hooks[function_name]:
                    result[hook_type].extend(self._hooks[function_name][hook_type])

        return result

    def clear_hooks(self):
        """Clear all registered hooks."""
        self._hooks.clear()
        self._global_hooks = {hook_type: [] for hook_type in HookType}


# =============================================================================
# New General Hook Framework
# =============================================================================


class PatternHook(FunctionHook):
    """Base class for hooks that support pattern-based tool matching."""

    def __init__(
        self,
        name: str,
        matcher: str = "*",
        timeout: int = 30,
    ):
        """
        Initialize a pattern-based hook.

        Args:
            name: Hook identifier
            matcher: Glob pattern for tool name matching (e.g., "*", "Write|Edit", "mcp__*")
            timeout: Execution timeout in seconds
        """
        super().__init__(name)
        self.matcher = matcher
        self.timeout = timeout
        self._patterns = self._parse_matcher(matcher)

    def _parse_matcher(self, matcher: str) -> List[str]:
        """Parse matcher into list of patterns (supports | for OR)."""
        if not matcher:
            return ["*"]
        return [p.strip() for p in matcher.split("|") if p.strip()]

    def matches(self, tool_name: str) -> bool:
        """Check if this hook matches the given tool name."""
        for pattern in self._patterns:
            if fnmatch.fnmatch(tool_name, pattern):
                return True
        return False


class PythonCallableHook(PatternHook):
    """Hook that invokes a Python callable.

    The callable can be specified as:
    - A module path string (e.g., "massgen.hooks.my_hook")
    - A direct callable (function or async function)

    The callable receives a HookEvent and returns a HookResult (or dict).
    """

    def __init__(
        self,
        name: str,
        handler: Union[str, Callable],
        matcher: str = "*",
        timeout: int = 30,
        fail_closed: bool = False,
    ):
        """
        Initialize a Python callable hook.

        Args:
            name: Hook identifier
            handler: Module path string or callable
            matcher: Glob pattern for tool name matching
            timeout: Execution timeout in seconds
            fail_closed: If True, deny tool execution on hook errors/timeouts.
                        If False (default), allow execution on errors (fail-open).
        """
        super().__init__(name, matcher, timeout)
        self._handler_path = handler if isinstance(handler, str) else None
        self._callable: Optional[Callable] = handler if callable(handler) else None
        self.fail_closed = fail_closed

    def _import_callable(self, path: str) -> Callable:
        """Import a callable from a module path."""
        parts = path.rsplit(".", 1)
        if len(parts) != 2:
            raise ImportError(f"Invalid callable path: {path}")
        module_path, func_name = parts
        module = importlib.import_module(module_path)
        return getattr(module, func_name)

    async def execute(
        self,
        function_name: str,
        arguments: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> HookResult:
        """Execute the Python callable hook."""
        if not self.matches(function_name):
            return HookResult.allow()

        # Lazy load callable
        if self._callable is None and self._handler_path:
            try:
                self._callable = self._import_callable(self._handler_path)
            except Exception as e:
                logger.error(f"[PythonCallableHook] Failed to import {self._handler_path}: {e}")
                # Fail closed on import error
                return HookResult.deny(reason=f"Hook import failed: {e}")

        if self._callable is None:
            return HookResult.allow()

        # Build HookEvent
        ctx = context or {}
        try:
            tool_input = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            tool_input = {"raw": arguments}

        event = HookEvent(
            hook_type=ctx.get("hook_type", "PreToolUse"),
            session_id=ctx.get("session_id", ""),
            orchestrator_id=ctx.get("orchestrator_id", ""),
            agent_id=ctx.get("agent_id"),
            timestamp=datetime.now(timezone.utc),
            tool_name=function_name,
            tool_input=tool_input,
            tool_output=ctx.get("tool_output"),
        )

        try:
            # Execute with timeout
            if asyncio.iscoroutinefunction(self._callable):
                result = await asyncio.wait_for(
                    self._callable(event),
                    timeout=self.timeout,
                )
            else:
                # Sync callable - run in executor
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, self._callable, event),
                    timeout=self.timeout,
                )

            return self._normalize_result(result)

        except asyncio.TimeoutError:
            logger.warning(f"[PythonCallableHook] Hook {self.name} timed out for {function_name}")
            if self.fail_closed:
                return HookResult.deny(reason=f"Hook {self.name} timed out")
            return HookResult.allow()
        except Exception as e:
            logger.error(f"[PythonCallableHook] Hook {self.name} failed: {e}")
            if self.fail_closed:
                return HookResult.deny(reason=f"Hook {self.name} failed: {e}")
            return HookResult.allow()

    def _normalize_result(self, result: Any) -> HookResult:
        """Normalize hook result to HookResult."""
        if isinstance(result, HookResult):
            return result
        if isinstance(result, dict):
            return HookResult.from_dict(result)
        if result is None:
            return HookResult.allow()
        # Unknown type - treat as allow
        logger.warning(f"[PythonCallableHook] Unknown result type: {type(result)}")
        return HookResult.allow()


class GeneralHookManager:
    """Extended hook manager supporting pattern-based matching and global/per-agent hooks.

    This manager supports:
    - Global hooks that apply to all agents
    - Per-agent hooks that can extend or override global hooks
    - Pattern-based matching on tool names
    - Aggregation of results from multiple hooks
    """

    def __init__(self):
        self._global_hooks: Dict[HookType, List[PatternHook]] = {
            HookType.PRE_TOOL_USE: [],
            HookType.POST_TOOL_USE: [],
        }
        self._agent_hooks: Dict[str, Dict[HookType, List[PatternHook]]] = {}
        self._agent_overrides: Dict[str, Dict[HookType, bool]] = {}

    def register_global_hook(self, hook_type: HookType, hook: PatternHook) -> None:
        """Register a hook that applies to all agents."""
        if hook_type not in self._global_hooks:
            self._global_hooks[hook_type] = []
        self._global_hooks[hook_type].append(hook)
        logger.debug(f"[GeneralHookManager] Registered global {hook_type.value} hook: {hook.name}")

    def register_agent_hook(
        self,
        agent_id: str,
        hook_type: HookType,
        hook: PatternHook,
        override: bool = False,
    ) -> None:
        """Register a hook for a specific agent.

        Args:
            agent_id: The agent identifier
            hook_type: Type of hook (PRE_TOOL_USE or POST_TOOL_USE)
            hook: The hook to register
            override: If True, disable global hooks for this event type
        """
        if agent_id not in self._agent_hooks:
            self._agent_hooks[agent_id] = {
                HookType.PRE_TOOL_USE: [],
                HookType.POST_TOOL_USE: [],
            }
            self._agent_overrides[agent_id] = {
                HookType.PRE_TOOL_USE: False,
                HookType.POST_TOOL_USE: False,
            }

        if hook_type not in self._agent_hooks[agent_id]:
            self._agent_hooks[agent_id][hook_type] = []

        self._agent_hooks[agent_id][hook_type].append(hook)

        if override:
            self._agent_overrides[agent_id][hook_type] = True

        logger.debug(
            f"[GeneralHookManager] Registered {hook_type.value} hook for agent {agent_id}: {hook.name}" f"{' (override)' if override else ''}",
        )

    def get_hooks_for_agent(
        self,
        agent_id: Optional[str],
        hook_type: HookType,
    ) -> List[PatternHook]:
        """Get all applicable hooks for an agent.

        If the agent has override=True for this hook type, only agent hooks are returned.
        Otherwise, global hooks are returned first, then agent hooks.
        """
        hooks = []

        # Check if agent overrides global hooks for this type
        if agent_id and agent_id in self._agent_overrides:
            if self._agent_overrides[agent_id].get(hook_type, False):
                # Override - only use agent hooks
                return list(self._agent_hooks.get(agent_id, {}).get(hook_type, []))

        # Add global hooks first
        hooks.extend(self._global_hooks.get(hook_type, []))

        # Add agent-specific hooks
        if agent_id and agent_id in self._agent_hooks:
            hooks.extend(self._agent_hooks[agent_id].get(hook_type, []))

        return hooks

    async def execute_hooks(
        self,
        hook_type: HookType,
        function_name: str,
        arguments: str,
        context: Dict[str, Any],
        tool_output: Optional[str] = None,
    ) -> HookResult:
        """Execute all matching hooks and aggregate results.

        For PreToolUse:
        - Any deny = deny
        - Modified inputs chain (each hook sees previous modifications)

        For PostToolUse:
        - All injection content is collected

        Args:
            hook_type: The type of hook (PRE_TOOL_USE or POST_TOOL_USE)
            function_name: Name of the tool being called
            arguments: JSON string of tool arguments
            context: Additional context (session_id, agent_id, etc.)
            tool_output: Tool output string (only for POST_TOOL_USE)

        Returns:
            Aggregated HookResult from all matching hooks
        """
        agent_id = context.get("agent_id")
        hooks = self.get_hooks_for_agent(agent_id, hook_type)

        # Add tool_output to context for PostToolUse hooks
        if tool_output is not None:
            context["tool_output"] = tool_output

        if not hooks:
            logger.info(f"[GeneralHookManager] No hooks registered for agent_id={agent_id}, hook_type={hook_type}")
            return HookResult.allow()

        # Filter to matching hooks
        matching_hooks = [h for h in hooks if h.matches(function_name)]
        logger.info(f"[GeneralHookManager] {len(matching_hooks)} matching hooks for {function_name} (out of {len(hooks)} registered)")

        if not matching_hooks:
            return HookResult.allow()

        final_result = HookResult.allow()
        modified_args = arguments
        all_injections: List[Dict[str, Any]] = []
        hook_type_str = "pre" if hook_type == HookType.PRE_TOOL_USE else "post"

        for hook in matching_hooks:
            start_time = time.time()
            try:
                # Update context with current args
                ctx = dict(context)
                result = await hook.execute(function_name, modified_args, ctx)

                # Calculate execution time
                execution_time_ms = (time.time() - start_time) * 1000

                # Handle deny - short circuit
                if not result.allowed or result.decision == "deny":
                    deny_result = HookResult.deny(
                        reason=result.reason or result.metadata.get("reason", f"Denied by hook {hook.name}"),
                    )
                    # Track the denying hook
                    deny_result.add_executed_hook(
                        hook_name=hook.name,
                        hook_type=hook_type_str,
                        decision="deny",
                        reason=deny_result.reason,
                        execution_time_ms=execution_time_ms,
                    )
                    return deny_result

                # Track successful hook execution
                injection_preview = None
                injection_content = None
                if result.inject and result.inject.get("content"):
                    content = result.inject["content"]
                    injection_preview = content[:100] + "..." if len(content) > 100 else content
                    injection_content = content

                final_result.add_executed_hook(
                    hook_name=hook.name,
                    hook_type=hook_type_str,
                    decision=result.decision,
                    reason=result.reason,
                    execution_time_ms=execution_time_ms,
                    injection_preview=injection_preview,
                    injection_content=injection_content,
                )
                logger.info(
                    f"[GeneralHookManager] Tracked hook execution: {hook.name} ({hook_type_str}) - " f"decision={result.decision}, has_inject={result.inject is not None}",
                )

                # Handle ask decision
                if result.decision == "ask":
                    final_result.decision = "ask"
                    final_result.reason = result.reason

                # Chain modified arguments
                if result.modified_args is not None:
                    modified_args = result.modified_args
                elif result.updated_input is not None:
                    modified_args = json.dumps(result.updated_input)

                # Collect injections
                if result.inject:
                    all_injections.append(result.inject)

                # Propagate any errors from the individual hook result
                if result.has_errors():
                    for err in result.hook_errors:
                        final_result.add_error(err)

            except Exception as e:
                execution_time_ms = (time.time() - start_time) * 1000
                error_msg = f"Hook '{hook.name}' failed unexpectedly: {e}"
                logger.error(f"[GeneralHookManager] {error_msg}", exc_info=True)
                # Track the error but fail open (allow tool execution to proceed)
                # This ensures users can see which hooks failed even in fail-open mode
                final_result.add_error(error_msg)

                # Track failed hook execution
                final_result.add_executed_hook(
                    hook_name=hook.name,
                    hook_type=hook_type_str,
                    decision="error",
                    reason=error_msg,
                    execution_time_ms=execution_time_ms,
                )

                # Check if hook requires fail-closed behavior
                if hasattr(hook, "fail_closed") and hook.fail_closed:
                    return HookResult.deny(reason=error_msg)

        # Build final result
        final_result.modified_args = modified_args if modified_args != arguments else None
        if all_injections:
            # Combine injections
            combined_content = "\n".join(inj.get("content", "") for inj in all_injections if inj.get("content"))
            if combined_content:
                final_result.inject = {
                    "content": combined_content,
                    "strategy": all_injections[-1].get("strategy", "tool_result"),
                }

        return final_result

    def register_hooks_from_config(
        self,
        hooks_config: Dict[str, Any],
        agent_id: Optional[str] = None,
    ) -> None:
        """Register hooks from YAML configuration.

        Args:
            hooks_config: Hook configuration dictionary. Supports two formats:

                List format (extends existing hooks):
                    PreToolUse:
                      - matcher: "*"
                        handler: "mymodule.my_hook"

                Override format (replaces existing hooks for this agent):
                    PreToolUse:
                      override: true
                      hooks:
                        - matcher: "*"
                          handler: "mymodule.my_hook"

            agent_id: If provided, register as agent-specific hooks.
                     If None, register as global hooks that apply to all agents.
        """
        hook_type_map = {
            "PreToolUse": HookType.PRE_TOOL_USE,
            "PostToolUse": HookType.POST_TOOL_USE,
        }

        for hook_type_name, hook_configs in hooks_config.items():
            if hook_type_name == "override":
                continue

            hook_type = hook_type_map.get(hook_type_name)
            if not hook_type:
                logger.warning(f"[GeneralHookManager] Unknown hook type: {hook_type_name}")
                continue

            # Handle override flag
            override = False
            if isinstance(hook_configs, dict):
                override = hook_configs.get("override", False)
                hook_configs = hook_configs.get("hooks", [])

            for config in hook_configs:
                hook = self._create_hook_from_config(config)
                if hook:
                    if agent_id:
                        self.register_agent_hook(agent_id, hook_type, hook, override)
                    else:
                        self.register_global_hook(hook_type, hook)

    def _create_hook_from_config(self, config: Dict[str, Any]) -> Optional[PatternHook]:
        """Create a hook instance from configuration."""
        handler = config.get("handler")
        if not handler:
            logger.warning("[GeneralHookManager] Hook config missing 'handler'")
            return None

        hook_handler_type = config.get("type", "python")
        matcher = config.get("matcher", "*")
        timeout = config.get("timeout", 30)
        fail_closed = config.get("fail_closed", False)
        name = f"{hook_handler_type}_{handler}"

        # Only python hooks supported currently
        return PythonCallableHook(
            name=name,
            handler=handler,
            matcher=matcher,
            timeout=timeout,
            fail_closed=fail_closed,
        )

    def clear_hooks(self) -> None:
        """Clear all registered hooks."""
        self._global_hooks = {
            HookType.PRE_TOOL_USE: [],
            HookType.POST_TOOL_USE: [],
        }
        self._agent_hooks.clear()
        self._agent_overrides.clear()


# =============================================================================
# Built-in Hooks for Migration
# =============================================================================


class MidStreamInjectionHook(PatternHook):
    """Built-in PostToolUse hook for mid-stream injection.

    This hook checks for pending updates from other agents during tool execution
    and injects their content into the tool result.

    Used by the orchestrator to inject answers from other agents mid-stream.
    """

    def __init__(
        self,
        name: str = "mid_stream_injection",
        injection_callback: Optional[Callable[[], Optional[str]]] = None,
    ):
        """
        Initialize the mid-stream injection hook.

        Args:
            name: Hook identifier
            injection_callback: Callable that returns injection content or None
        """
        super().__init__(name, matcher="*", timeout=5)
        self._injection_callback = injection_callback

    def set_callback(self, callback: Callable[[], Optional[str]]) -> None:
        """Set the injection callback dynamically.

        The callback can be either sync or async - both are supported.

        Args:
            callback: A callable that returns:
                - str: Content to inject into the tool result
                - None: No injection (hook passes through)
        """
        self._injection_callback = callback

    async def execute(
        self,
        function_name: str,
        arguments: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> HookResult:
        """Execute the mid-stream injection hook.

        This is a critical infrastructure hook for multi-agent coordination.
        Errors are tracked in the result so callers can be aware of injection failures.
        """
        if not self._injection_callback:
            return HookResult.allow()

        try:
            # Get injection content from callback (supports both sync and async)
            result = self._injection_callback()
            if asyncio.iscoroutine(result):
                content = await result
            else:
                content = result

            if content:
                logger.debug(f"[MidStreamInjectionHook] Injecting content for {function_name}")
                return HookResult(
                    allowed=True,
                    inject={
                        "content": content,
                        "strategy": "tool_result",
                    },
                )
        except Exception as e:
            # Log as error (not warning) since this is critical infrastructure
            error_msg = f"Injection callback failed: {e}"
            logger.error(f"[MidStreamInjectionHook] {error_msg}", exc_info=True)
            # Return allow but track the error so callers know injection was skipped
            # This is fail-open behavior but with visibility into the failure
            result = HookResult.allow()
            result.add_error(error_msg)
            result.metadata["injection_skipped"] = True
            return result

        return HookResult.allow()


class SubagentCompleteHook(PatternHook):
    """PostToolUse hook that injects completed background subagent results.

    This hook checks the pending results queue after each tool call
    and injects any completed subagent results into the tool output.

    Used for background subagent execution where subagents
    run in the background and results are automatically injected when
    the parent agent executes its next tool.
    """

    def __init__(
        self,
        name: str = "subagent_complete",
        get_pending_results: Optional[Callable[[], List]] = None,
        injection_strategy: str = "tool_result",
    ):
        """
        Initialize the subagent complete hook.

        Args:
            name: Hook identifier
            get_pending_results: Callable that returns list of (subagent_id, SubagentResult) tuples
            injection_strategy: How to inject results - "tool_result" (append to output) or
                              "user_message" (add as separate message)
        """
        super().__init__(name, matcher="*", timeout=5)
        self._get_pending_results = get_pending_results
        self._injection_strategy = injection_strategy

    def set_pending_results_getter(
        self,
        getter: Callable[[], List],
    ) -> None:
        """Set the function to retrieve pending results.

        The getter should return a list of (subagent_id, SubagentResult) tuples
        representing completed background subagents that need their results injected.

        Args:
            getter: A callable that returns pending results and clears the queue
        """
        self._get_pending_results = getter

    async def execute(
        self,
        function_name: str,
        arguments: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> HookResult:
        """Execute the subagent complete hook.

        Checks for pending background subagent results and injects them if available.

        Args:
            function_name (str): Name of the subagent function.
            arguments (str): Serialized arguments passed to the function.
            context (Optional[Dict[str, Any]]): Optional execution context.
            **kwargs: Additional options for hook execution.

        Returns:
            HookResult: Indicates success or failure and includes any payload.
        """
        if not self._get_pending_results:
            return HookResult.allow()

        try:
            # Get pending results (getter should also clear them)
            pending = self._get_pending_results()
            if not pending:
                return HookResult.allow()

            # Format results for injection
            from massgen.subagent.result_formatter import format_batch_results

            content = format_batch_results(pending)

            logger.debug(
                f"[SubagentCompleteHook] Injecting {len(pending)} completed subagent result(s)",
            )

            return HookResult(
                allowed=True,
                inject={
                    "content": content,
                    "strategy": self._injection_strategy,
                },
            )
        except Exception as e:
            # Fail open - don't block tool execution if injection fails
            error_msg = f"Subagent result injection failed: {e}"
            logger.error(f"[SubagentCompleteHook] {error_msg}", exc_info=True)
            result = HookResult.allow()
            result.add_error(error_msg)
            result.metadata["injection_skipped"] = True
            return result


class BackgroundToolCompleteHook(PatternHook):
    """PostToolUse hook that injects completed background tool results."""

    def __init__(
        self,
        name: str = "background_tool_complete",
        get_completed_jobs: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        injection_strategy: str = "tool_result",
        max_result_chars: int = 600,
    ):
        super().__init__(name, matcher="*", timeout=5)
        self._get_completed_jobs = get_completed_jobs
        self._injection_strategy = injection_strategy
        self._max_result_chars = max_result_chars

    def set_completed_jobs_getter(
        self,
        getter: Callable[[], List[Dict[str, Any]]],
    ) -> None:
        """Set the function used to retrieve completed background jobs."""
        self._get_completed_jobs = getter

    def _format_completed_jobs(self, jobs: List[Dict[str, Any]]) -> str:
        """Format completed background jobs for injection."""
        lines = [
            "",
            "=" * 60,
            "🔄 BACKGROUND TOOL RESULTS",
            "=" * 60,
            "",
        ]

        for job in jobs:
            job_id = str(job.get("job_id", "unknown"))
            tool_name = str(job.get("tool_name", "unknown_tool"))
            status = str(job.get("status", "completed"))
            lines.append(f"- [{job_id}] {tool_name} ({status})")

            if job.get("result"):
                result_text = str(job.get("result", ""))
                if len(result_text) > self._max_result_chars:
                    result_text = result_text[: self._max_result_chars] + "..."
                lines.append(f"  Result: {result_text}")
            elif job.get("error"):
                lines.append(f"  Error: {job.get('error')}")

            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)

    async def execute(
        self,
        function_name: str,
        arguments: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> HookResult:
        """Inject completed background tool results when available."""
        if not self._get_completed_jobs:
            return HookResult.allow()

        try:
            completed_jobs = self._get_completed_jobs()
            if not completed_jobs:
                return HookResult.allow()

            content = self._format_completed_jobs(completed_jobs)
            logger.debug(
                f"[BackgroundToolCompleteHook] Injecting {len(completed_jobs)} completed background job(s)",
            )
            return HookResult(
                allowed=True,
                inject={
                    "content": content,
                    "strategy": self._injection_strategy,
                },
            )
        except Exception as e:
            error_msg = f"Background tool result injection failed: {e}"
            logger.error(f"[BackgroundToolCompleteHook] {error_msg}", exc_info=True)
            result = HookResult.allow()
            result.add_error(error_msg)
            result.metadata["injection_skipped"] = True
            return result


class HighPriorityTaskReminderHook(PatternHook):
    """PostToolUse hook that injects reminder when high-priority task is completed.

    Instead of tools returning reminder keys, this hook inspects tool output
    and injects reminders based on conditions (consistent hook pattern).

    This hook matches update_task_status and checks if a high-priority
    task was completed, then injects a reminder to document learnings.
    """

    def __init__(self, name: str = "high_priority_task_reminder"):
        """Initialize the high-priority task reminder hook."""
        # Match update_task_status - the tool that sets status to "completed"
        super().__init__(name, matcher="*update_task_status", timeout=5)

    def _format_reminder(self) -> str:
        """Format the high-priority task completion reminder."""
        separator = "=" * 60
        reminder_text = (
            "✓ High-priority task completed! Document decisions to optimize future work:\n"
            "  • Which skills/tools were effective (or not)? → memory/long_term/skill_effectiveness.md\n"
            "  • What approach worked (or failed) and why? → memory/long_term/approach_patterns.md\n"
            "  • What would prevent mistakes on similar tasks? → memory/long_term/lessons_learned.md\n"
            "  • User preferences revealed? → memory/short_term/user_prefs.md"
        )
        return f"\n{separator}\n⚠️  SYSTEM REMINDER\n{separator}\n\n{reminder_text}\n\n{separator}\n"

    async def execute(
        self,
        function_name: str,
        arguments: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> HookResult:
        """Execute the high-priority task reminder hook."""
        # Check pattern match first (only fires for update_task_status)
        if not self.matches(function_name):
            return HookResult.allow()

        tool_output = (context or {}).get("tool_output")
        if not tool_output:
            return HookResult.allow()

        try:
            # Parse tool output to check task details
            result_dict = json.loads(tool_output)
            if isinstance(result_dict, dict):
                task = result_dict.get("task", {})
                # Check if high-priority task was completed
                if task.get("priority") == "high" and task.get("status") == "completed":
                    logger.debug(f"[HighPriorityTaskReminderHook] Injecting reminder for {function_name}")
                    return HookResult(
                        allowed=True,
                        inject={
                            "content": self._format_reminder(),
                            "strategy": "user_message",
                        },
                    )
        except (json.JSONDecodeError, TypeError):
            pass

        return HookResult.allow()


class RoundTimeoutState:
    """Shared state between soft and hard timeout hooks.

    This ensures the hard timeout only fires after the soft timeout has been
    delivered, guaranteeing the progression: soft timeout → grace period → hard timeout.

    Also tracks consecutive hard timeout denials to detect infinite loops where
    the model keeps trying blocked tools instead of voting.
    """

    # Maximum consecutive denials before forcing termination
    MAX_CONSECUTIVE_DENIALS = 10

    def __init__(self):
        self.soft_timeout_fired_at: Optional[float] = None
        self.consecutive_hard_denials: int = 0
        self.force_terminate: bool = False

    def mark_soft_fired(self) -> None:
        """Record the timestamp when soft timeout was injected."""
        self.soft_timeout_fired_at = time.time()

    def record_hard_denial(self) -> bool:
        """Record a hard timeout denial and check if we should force terminate.

        Returns:
            True if we've exceeded the max consecutive denials and should terminate
        """
        self.consecutive_hard_denials += 1
        if self.consecutive_hard_denials >= self.MAX_CONSECUTIVE_DENIALS:
            self.force_terminate = True
            logger.warning(
                f"[RoundTimeoutState] Force terminate triggered after " f"{self.consecutive_hard_denials} consecutive hard timeout denials",
            )
            return True
        return False

    def reset_denial_count(self) -> None:
        """Reset denial count (called when a valid tool is allowed)."""
        self.consecutive_hard_denials = 0

    def reset(self) -> None:
        """Reset state for a new round."""
        self.soft_timeout_fired_at = None
        self.consecutive_hard_denials = 0
        self.force_terminate = False


class RoundTimeoutPostHook(PatternHook):
    """PostToolUse hook that injects soft timeout warning when round time limit is exceeded.

    This hook checks elapsed time after each tool call and injects a warning message
    telling the agent to submit an answer or vote immediately when the soft timeout
    is reached. Different timeouts can be configured for round 0 (initial answer)
    vs subsequent rounds (voting/refinement).

    The hook fires only once per round - after injecting the warning, it won't
    inject again until reset_for_new_round() is called.
    """

    def __init__(
        self,
        name: str,
        get_round_start_time: Callable[[], float],
        get_agent_round: Callable[[], int],
        initial_timeout_seconds: Optional[int],
        subsequent_timeout_seconds: Optional[int],
        grace_seconds: int,
        agent_id: str,
        shared_state: Optional["RoundTimeoutState"] = None,
        use_two_tier_workspace: bool = False,
    ):
        """
        Initialize the round timeout post hook.

        Args:
            name: Hook identifier
            get_round_start_time: Callable returning the start time of current round
            get_agent_round: Callable returning the current round number for this agent
            initial_timeout_seconds: Soft timeout for round 0 (None = disabled)
            subsequent_timeout_seconds: Soft timeout for rounds 1+ (None = disabled)
            grace_seconds: Time allowed after soft timeout before hard block
            agent_id: Agent identifier for logging
            shared_state: Optional shared state for coordinating with hard timeout hook
            use_two_tier_workspace: If True, include guidance about deliverable/ directory
        """
        super().__init__(name, matcher="*", timeout=5)
        self.get_round_start_time = get_round_start_time
        self.get_agent_round = get_agent_round
        self.initial_timeout_seconds = initial_timeout_seconds
        self.subsequent_timeout_seconds = subsequent_timeout_seconds
        self.grace_seconds = grace_seconds
        self.agent_id = agent_id
        self._soft_timeout_fired = False
        self._shared_state = shared_state
        self.use_two_tier_workspace = use_two_tier_workspace

    def _get_timeout_for_current_round(self) -> Optional[int]:
        """Return timeout based on round number (0 = initial, 1+ = subsequent)."""
        round_num = self.get_agent_round()
        if round_num == 0:
            return self.initial_timeout_seconds
        else:
            return self.subsequent_timeout_seconds

    def reset_for_new_round(self) -> None:
        """Reset the hook state for a new round."""
        self._soft_timeout_fired = False
        if self._shared_state:
            self._shared_state.reset()

    async def execute(
        self,
        _function_name: str,
        _arguments: str,
        _context: Optional[Dict[str, Any]] = None,
        **_kwargs,
    ) -> HookResult:
        """Execute the soft timeout check after each tool call."""
        if self._soft_timeout_fired:
            return HookResult.allow()

        timeout = self._get_timeout_for_current_round()
        if timeout is None:
            return HookResult.allow()

        elapsed = time.time() - self.get_round_start_time()
        logger.debug(
            f"[RoundTimeoutPostHook] Agent {self.agent_id}: " f"elapsed={elapsed:.0f}s, soft_timeout={timeout}s, soft_fired={self._soft_timeout_fired}",
        )
        if elapsed < timeout:
            return HookResult.allow()

        self._soft_timeout_fired = True
        # Record timestamp for hard timeout coordination
        if self._shared_state:
            self._shared_state.mark_soft_fired()
        round_num = self.get_agent_round()
        round_type = "initial answer" if round_num == 0 else "voting"

        # Add deliverable guidance if two-tier workspace is enabled
        deliverable_guidance = ""
        if self.use_two_tier_workspace:
            deliverable_guidance = """
IMPORTANT: Before submitting, ensure your `deliverable/` directory is COMPLETE and SELF-CONTAINED.
Voters will evaluate `deliverable/` as a standalone package. It must include:
- ALL files needed to use your output (not just one component)
- Any assets, dependencies, or supporting files
- A README if helpful for understanding how to run/use it

Do NOT leave partial work in deliverable/ - include everything needed or nothing.
"""

        injection = f"""
============================================================
⏰ ROUND TIME LIMIT APPROACHING - PLEASE WRAP UP
============================================================

You have exceeded the soft time limit for this {round_type} round ({elapsed:.0f}s / {timeout}s).
{deliverable_guidance}
Please wrap up your current work and submit soon:
1. `new_answer` - Submit your current best answer (can be a work-in-progress)
2. `vote` - Vote for an existing answer if one is satisfactory

You may finish any final touches to make your work presentable, but please
submit within the next {self.grace_seconds} seconds. After that, tool calls
will be blocked and you'll need to submit immediately.

The next coordination round will allow further iteration if needed.
============================================================
"""

        logger.info(f"[RoundTimeoutPostHook] Soft timeout reached for {self.agent_id} after {elapsed:.0f}s")
        return HookResult(
            allowed=True,
            inject={
                "content": injection,
                "strategy": "tool_result",
            },
        )


class RoundTimeoutPreHook(PatternHook):
    """PreToolUse hook that blocks non-terminal tools after hard timeout.

    This hook enforces a hard timeout after the soft timeout was injected + grace period.
    The hard timeout only fires AFTER the soft timeout has been delivered, ensuring
    the progression: soft timeout → grace period → hard timeout.

    Once hard timeout is reached, only 'vote' and 'new_answer' tools are allowed.
    All other tool calls are denied with an error message.

    This ensures agents cannot continue indefinitely and must submit.
    """

    def __init__(
        self,
        name: str,
        get_round_start_time: Callable[[], float],
        get_agent_round: Callable[[], int],
        initial_timeout_seconds: Optional[int],
        subsequent_timeout_seconds: Optional[int],
        grace_seconds: int,
        agent_id: str,
        shared_state: Optional["RoundTimeoutState"] = None,
    ):
        """
        Initialize the round timeout pre hook.

        Args:
            name: Hook identifier
            get_round_start_time: Callable returning the start time of current round
            get_agent_round: Callable returning the current round number for this agent
            initial_timeout_seconds: Soft timeout for round 0 (None = disabled)
            subsequent_timeout_seconds: Soft timeout for rounds 1+ (None = disabled)
            grace_seconds: Grace period after soft timeout before blocking
            agent_id: Agent identifier for logging
            shared_state: Optional shared state for coordinating with soft timeout hook
        """
        super().__init__(name, matcher="*", timeout=5)
        self.get_round_start_time = get_round_start_time
        self.get_agent_round = get_agent_round
        self.initial_timeout_seconds = initial_timeout_seconds
        self.subsequent_timeout_seconds = subsequent_timeout_seconds
        self.grace_seconds = grace_seconds
        self.agent_id = agent_id
        self._shared_state = shared_state

    def _get_timeout_for_current_round(self) -> Optional[int]:
        """Return timeout based on round number (0 = initial, 1+ = subsequent)."""
        round_num = self.get_agent_round()
        if round_num == 0:
            return self.initial_timeout_seconds
        else:
            return self.subsequent_timeout_seconds

    async def execute(
        self,
        function_name: str,
        arguments: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> HookResult:
        """Execute the hard timeout check before each tool call.

        Hard timeout is calculated from when the soft timeout was injected,
        NOT from round start time. This ensures agents always get the soft
        timeout warning before being blocked.

        Also tracks consecutive denials to detect infinite loops.
        """
        timeout = self._get_timeout_for_current_round()
        if timeout is None:
            return HookResult.allow()

        # If using shared state, check if soft timeout has fired first
        if self._shared_state:
            # Check if force terminate has been triggered by too many denials
            if self._shared_state.force_terminate:
                logger.error(
                    f"[RoundTimeoutPreHook] FORCE TERMINATE active for {self.agent_id} - " f"blocking {function_name} (agent stuck in denial loop)",
                )
                return HookResult(
                    decision="deny",
                    reason=(
                        f"⛔ FORCE TERMINATED - Too many blocked tool calls\n"
                        f"Tool `{function_name}` blocked. You have made {self._shared_state.consecutive_hard_denials} "
                        f"consecutive blocked tool calls.\n"
                        f"The system is terminating your turn. Use `vote` or `new_answer` ONLY."
                    ),
                )

            soft_fired_at = self._shared_state.soft_timeout_fired_at
            if soft_fired_at is None:
                # Soft timeout hasn't fired yet - allow tool call
                # (Can't have hard timeout without soft first)
                logger.debug(
                    f"[RoundTimeoutPreHook] Agent {self.agent_id}: " f"soft timeout not fired yet, allowing {function_name}",
                )
                return HookResult.allow()

            # Calculate hard timeout from when soft was injected
            time_since_soft = time.time() - soft_fired_at
            logger.debug(
                f"[RoundTimeoutPreHook] Agent {self.agent_id}: " f"time_since_soft={time_since_soft:.0f}s, grace={self.grace_seconds}s",
            )

            if time_since_soft < self.grace_seconds:
                # Within grace period - reset denial count and allow
                self._shared_state.reset_denial_count()
                return HookResult.allow()

            # Hard timeout reached - only allow vote/new_answer
            if function_name in ("vote", "new_answer"):
                # Valid terminal tool - reset denial count
                self._shared_state.reset_denial_count()
                return HookResult.allow()

            # Block this tool and track the denial
            denial_count = self._shared_state.consecutive_hard_denials + 1
            force_terminate = self._shared_state.record_hard_denial()

            logger.warning(
                f"[RoundTimeoutPreHook] DENIED tool `{function_name}` for {self.agent_id} - "
                f"grace period exceeded ({time_since_soft:.0f}s / {self.grace_seconds}s), "
                f"denial #{denial_count}" + (" - FORCE TERMINATE TRIGGERED" if force_terminate else ""),
            )

            return HookResult(
                decision="deny",
                reason=(
                    f"⛔ HARD TIMEOUT - TOOL `{function_name}` BLOCKED (attempt #{denial_count})\n"
                    f"You received the time limit warning {time_since_soft:.0f}s ago "
                    f"(grace period: {self.grace_seconds}s).\n"
                    f"Only `vote` or `new_answer` tools are allowed. Submit immediately. Note any unsolved problems."
                    + (
                        f"\n⚠️ WARNING: {denial_count} consecutive blocked calls. " f"Turn will be terminated after {RoundTimeoutState.MAX_CONSECUTIVE_DENIALS} blocked calls."
                        if denial_count >= 3
                        else ""
                    )
                ),
            )

        # Fallback to wall-clock based timeout if no shared state (backwards compatibility)
        elapsed = time.time() - self.get_round_start_time()
        hard_timeout = timeout + self.grace_seconds

        if elapsed < hard_timeout:
            return HookResult.allow()

        # Hard timeout reached - only allow vote/new_answer
        if function_name in ("vote", "new_answer"):
            return HookResult.allow()

        # Block all other tools
        logger.warning(
            f"[RoundTimeoutPreHook] DENIED tool `{function_name}` for {self.agent_id} - " f"hard timeout exceeded ({elapsed:.0f}s / {hard_timeout:.0f}s)",
        )
        return HookResult(
            decision="deny",
            reason=(
                f"⛔ HARD TIMEOUT - TOOL `{function_name}` BLOCKED\n"
                f"You have exceeded the hard time limit ({elapsed:.0f}s / {hard_timeout:.0f}s).\n"
                f"Only `vote` or `new_answer` tools are allowed. Submit immediately. Note any unsolved problems."
            ),
        )

    def reset_for_new_round(self) -> None:
        """Reset hook state for a new round.

        Note: RoundTimeoutPreHook now uses shared state for coordination,
        but the reset is handled by RoundTimeoutPostHook which owns the state.
        """


class PermissionClientSession(ClientSession):
    """
    ClientSession subclass that intercepts tool calls to apply permission hooks.

    This inherits from ClientSession instead of wrapping it, which ensures
    compatibility with SDK type checking and attribute access.
    """

    def __init__(self, wrapped_session: ClientSession, permission_manager):
        """
        Initialize by copying state from an existing ClientSession.

        Args:
            wrapped_session: The actual ClientSession to copy state from
            permission_manager: Object with pre_tool_use_hook method for validation
        """
        # Store the permission manager
        self._permission_manager = permission_manager

        # Copy all attributes from the wrapped session to this instance
        # This is a bit hacky but necessary to preserve the session state
        self.__dict__.update(wrapped_session.__dict__)

        logger.debug(f"[PermissionClientSession] Created permission session from {id(wrapped_session)}")

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: timedelta | None = None,
        progress_callback: ProgressFnT | None = None,
    ) -> types.CallToolResult:
        """
        Override call_tool to apply permission hooks before calling the actual tool.
        """
        tool_args = arguments or {}

        # Log tool call for debugging
        logger.debug(f"[PermissionClientSession] Intercepted tool call: {name} with args: {tool_args}")

        # Apply permission hook if available
        if self._permission_manager and hasattr(self._permission_manager, "pre_tool_use_hook"):
            try:
                allowed, reason = await self._permission_manager.pre_tool_use_hook(name, tool_args)

                if not allowed:
                    error_msg = f"Permission denied for tool '{name}'"
                    if reason:
                        error_msg += f": {reason}"
                    logger.warning(f"🚫 [PermissionClientSession] {error_msg}")

                    # Return an error result instead of calling the tool
                    return types.CallToolResult(content=[types.TextContent(type="text", text=f"Error: {error_msg}")], isError=True)
                else:
                    logger.debug(f"[PermissionClientSession] Tool '{name}' permission check passed")

            except Exception as e:
                logger.error(f"[PermissionClientSession] Error in permission hook: {e}")
                # Fail closed: deny tool execution when permission check errors
                # This is safer than allowing potentially dangerous operations through
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=f"Error: Permission check failed: {e}")],
                    isError=True,
                )

        # Call the parent's call_tool method
        try:
            result = await super().call_tool(name=name, arguments=arguments, read_timeout_seconds=read_timeout_seconds, progress_callback=progress_callback)
            logger.debug(f"[PermissionClientSession] Tool '{name}' completed successfully")
            return result
        except Exception as e:
            logger.error(f"[PermissionClientSession] Tool '{name}' failed: {e}")
            raise


def convert_sessions_to_permission_sessions(sessions: List[ClientSession], permission_manager) -> List[PermissionClientSession]:
    """
    Convert a list of ClientSession objects to PermissionClientSession subclasses.

    Args:
        sessions: List of ClientSession objects to convert
        permission_manager: Object with pre_tool_use_hook method

    Returns:
        List of PermissionClientSession objects that apply permission hooks
    """
    logger.debug(f"[PermissionClientSession] Converting {len(sessions)} sessions to permission sessions")
    converted = []
    for session in sessions:
        # Create a new PermissionClientSession that inherits from ClientSession
        perm_session = PermissionClientSession(session, permission_manager)
        converted.append(perm_session)
    logger.debug(f"[PermissionClientSession] Successfully converted {len(converted)} sessions")
    return converted


class HumanInputHook(PatternHook):
    """PostToolUse hook that injects human-provided input during agent execution.

    This hook allows users to inject messages to agents mid-stream during execution.
    When a user types input while agents are working, it gets queued and injected
    into the next tool result via this hook.

    The hook is thread-safe and supports callbacks to notify the TUI when
    input has been injected (so the visual indicator can be cleared).
    """

    def __init__(self, name: str = "human_input_hook"):
        """Initialize the human input hook.

        Args:
            name: Hook identifier
        """
        super().__init__(name, matcher="*", timeout=5)
        # Queue of pending messages, each with its own set of agents that received it
        # Format: [{"content": str, "injected_agents": set}, ...]
        self._pending_messages: list = []
        self._lock = threading.Lock()
        self._on_inject_callback: Optional[Callable[[str], None]] = None

    def set_pending_input(self, content: str) -> None:
        """Queue human input for injection into ALL agents' next tool results.

        Multiple messages can be queued - each will be injected to all agents.

        Args:
            content: The human input text to inject
        """
        with self._lock:
            self._pending_messages.append(
                {
                    "content": content,
                    "injected_agents": set(),
                },
            )
            logger.info(
                f"[HumanInputHook] QUEUED message #{len(self._pending_messages)}: " f"'{content[:50]}...' (len={len(content)})",
            )

    def clear_pending_input(self) -> None:
        """Clear all pending messages without injecting them."""
        with self._lock:
            count = len(self._pending_messages)
            self._pending_messages.clear()
            logger.debug(f"[HumanInputHook] Cleared {count} pending messages")

    def has_pending_input(self) -> bool:
        """Check if there are any pending messages queued for injection.

        Returns:
            True if any messages are queued, False otherwise
        """
        with self._lock:
            return len(self._pending_messages) > 0

    def set_inject_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        """Set a callback to be invoked when input is injected.

        The callback receives the injected content string.

        Args:
            callback: Function to call after injection, or None to clear
        """
        self._on_inject_callback = callback

    async def execute(
        self,
        function_name: str,
        arguments: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> HookResult:
        """Execute the human input hook after a tool call.

        Injects ALL pending messages that this agent hasn't received yet.
        Each message is delivered to ALL agents (once per agent per message).
        Messages are kept until explicitly cleared (e.g., when turn ends).

        Args:
            function_name: Name of the tool that just executed
            arguments: Tool arguments (JSON string)
            context: Additional context (should contain 'agent_id')

        Returns:
            HookResult with injection content if any messages pending for this agent
        """
        # Get agent_id from context
        agent_id = (context or {}).get("agent_id", "unknown")

        messages_to_inject = []
        is_first_injection = False

        with self._lock:
            logger.info(
                f"[HumanInputHook] execute() for {function_name}, agent={agent_id}, " f"pending_count={len(self._pending_messages)}",
            )

            # Find all messages this agent hasn't received yet
            for msg in self._pending_messages:
                if agent_id not in msg["injected_agents"]:
                    messages_to_inject.append(msg["content"])
                    msg["injected_agents"].add(agent_id)
                    # First injection globally (first message, first agent)
                    if not is_first_injection and len(msg["injected_agents"]) == 1:
                        is_first_injection = True

            if messages_to_inject:
                logger.info(
                    f"[HumanInputHook] Will inject {len(messages_to_inject)} message(s) for {agent_id}",
                )

        # Check outside the lock to avoid holding it during callback
        if messages_to_inject:
            # Combine all messages
            combined_content = "\n".join(messages_to_inject)
            logger.info(
                f"[HumanInputHook] INJECTING {len(messages_to_inject)} message(s) " f"after {function_name} for {agent_id}",
            )

            # Notify TUI on first injection (to clear the banner)
            if is_first_injection and self._on_inject_callback:
                try:
                    self._on_inject_callback(combined_content)
                except Exception as e:
                    logger.warning(f"[HumanInputHook] Inject callback failed: {e}")

            return HookResult(
                allowed=True,
                inject={
                    "content": f"\n[Human Input]: {combined_content}\n",
                    "strategy": "tool_result",
                },
            )

        return HookResult.allow()


__all__ = [
    # Core types
    "HookType",
    "HookEvent",
    "HookResult",
    # Legacy hook infrastructure
    "FunctionHook",
    "FunctionHookManager",
    # New general hook framework
    "PatternHook",
    "PythonCallableHook",
    "GeneralHookManager",
    # Built-in hooks
    "MidStreamInjectionHook",
    "BackgroundToolCompleteHook",
    "SubagentCompleteHook",
    "HighPriorityTaskReminderHook",
    "HumanInputHook",
    # Per-round timeout hooks
    "RoundTimeoutPostHook",
    "RoundTimeoutPreHook",
    # Session-based hooks
    "PermissionClientSession",
    "convert_sessions_to_permission_sessions",
]
