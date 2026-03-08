"""Claude Code native hook adapter.

This module provides the adapter for converting MassGen's hook framework
to Claude Code SDK's HookMatcher format, enabling native hook execution
for both PreToolUse and PostToolUse events.
"""

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ...logger_config import logger
from .base import NativeHookAdapter

if TYPE_CHECKING:
    from ..hooks import GeneralHookManager, HookResult, HookType, PatternHook

# Import Claude Agent SDK conditionally
try:
    from claude_agent_sdk import HookMatcher

    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False
    HookMatcher = None  # type: ignore


class ClaudeCodeNativeHookAdapter(NativeHookAdapter):
    """Adapts MassGen hooks to Claude Code SDK's HookMatcher format.

    Claude Code SDK uses:
    - HookMatcher(matcher="pattern", hooks=[async_func, ...])
    - Hook function signature: async def hook(input_data, tool_use_id, context) -> dict
    - Return {} for allow, {"hookSpecificOutput": {...}} for deny/modify/inject

    This adapter:
    1. Wraps MassGen PatternHook instances as Claude-compatible async functions
    2. Converts HookResult to Claude's response format
    3. Supports both PreToolUse and PostToolUse
    4. Handles PostToolUse injection content via additional context

    Example usage:
        adapter = ClaudeCodeNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(HookType.POST_TOOL_USE, MidStreamInjectionHook())

        native_config = adapter.build_native_hooks_config(manager)
        # Pass to ClaudeAgentOptions(hooks=native_config)
    """

    def __init__(self):
        """Initialize the Claude Code native hook adapter.

        Raises:
            ImportError: If claude_agent_sdk is not available
        """
        if not CLAUDE_SDK_AVAILABLE:
            raise ImportError(
                "claude_agent_sdk is required for ClaudeCodeNativeHookAdapter. " "Install with: pip install claude-code-sdk-python",
            )
        # Cache for wrapped hooks to avoid recreating on each call
        self._wrapped_hooks: dict[str, Callable] = {}

    def supports_hook_type(self, hook_type: "HookType") -> bool:
        """Check if this adapter supports the given hook type.

        Claude Code SDK supports both PreToolUse and PostToolUse hooks.

        Args:
            hook_type: The type of hook to check

        Returns:
            True for PRE_TOOL_USE and POST_TOOL_USE
        """
        from ..hooks import HookType as HT

        return hook_type in (HT.PRE_TOOL_USE, HT.POST_TOOL_USE)

    def convert_hook_to_native(
        self,
        hook: "PatternHook",
        hook_type: "HookType",
        context_factory: Callable[[], dict[str, Any]] | None = None,
    ) -> "HookMatcher":
        """Convert a MassGen PatternHook to Claude's HookMatcher format.

        Creates a wrapper function that:
        1. Receives Claude's input format (input_data, tool_use_id, context)
        2. Checks pattern match
        3. Executes the MassGen hook
        4. Converts HookResult back to Claude's response format

        Args:
            hook: MassGen PatternHook instance to convert
            hook_type: Type of hook (PRE_TOOL_USE or POST_TOOL_USE)
            context_factory: Optional callable that returns context dict

        Returns:
            HookMatcher configured with the wrapped hook function
        """

        # Create unique key for caching
        hook_key = f"{hook_type.value}_{hook.name}_{id(hook)}"

        if hook_key not in self._wrapped_hooks:
            # Create wrapper function - capture hook and context_factory
            wrapper = self._create_hook_wrapper(hook, hook_type, context_factory)
            self._wrapped_hooks[hook_key] = wrapper

        return HookMatcher(
            matcher=hook.matcher,
            hooks=[self._wrapped_hooks[hook_key]],
        )

    def _create_hook_wrapper(
        self,
        hook: "PatternHook",
        hook_type: "HookType",
        context_factory: Callable[[], dict[str, Any]] | None = None,
    ) -> Callable:
        """Create Claude SDK compatible wrapper function for a MassGen hook.

        Args:
            hook: The MassGen hook to wrap
            hook_type: Type of hook event
            context_factory: Optional callable for runtime context

        Returns:
            Async function compatible with Claude SDK hook API
        """

        async def hook_wrapper(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            context: Any,  # HookContext from SDK
        ) -> dict[str, Any]:
            """Claude SDK compatible hook wrapper."""
            # Build context dict
            ctx = context_factory() if context_factory else {}
            ctx["tool_use_id"] = tool_use_id

            # Extract tool info from input_data
            tool_name = input_data.get("tool_name", "")
            tool_input = input_data.get("tool_input", {})
            tool_output = input_data.get("tool_output")  # PostToolUse only

            # Check pattern match first (optimization)
            if not hook.matches(tool_name):
                return {}  # Allow - pattern didn't match

            # Build arguments string for MassGen hook
            arguments_str = json.dumps(tool_input) if tool_input else "{}"

            # Add tool_output to context for PostToolUse
            if tool_output is not None:
                ctx["tool_output"] = tool_output
                ctx["hook_type"] = "PostToolUse"
            else:
                ctx["hook_type"] = "PreToolUse"

            try:
                # Execute MassGen hook
                result = await hook.execute(tool_name, arguments_str, ctx)

                # Convert result to Claude format
                return self._convert_result_to_claude_format(result, hook_type)

            except Exception as e:
                # Log error with stack trace for debugging
                logger.error(
                    f"[ClaudeCodeNativeHookAdapter] Hook {hook.name} failed: {e}",
                    exc_info=True,
                )

                # Check fail_closed setting
                if hasattr(hook, "fail_closed") and hook.fail_closed:
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": hook_type.value,
                            "permissionDecision": "deny",
                            "permissionDecisionReason": f"Hook error: {str(e)}",
                        },
                    }
                return {}  # Fail open

        return hook_wrapper

    def _convert_result_to_claude_format(
        self,
        result: "HookResult",
        hook_type: "HookType",
    ) -> dict[str, Any]:
        """Convert MassGen HookResult to Claude SDK response format.

        Claude SDK response format:
        - {} : Allow without modifications
        - {"hookSpecificOutput": {"permissionDecision": "deny", ...}}: Deny
        - {"hookSpecificOutput": {"updatedInput": {...}}}: Modify input
        - {"hookSpecificOutput": {"additionalContext": "..."}}: Inject context after tool use

        Args:
            result: MassGen HookResult from hook execution
            hook_type: The type of hook that produced the result

        Returns:
            Claude SDK compatible response dict
        """
        from ..hooks import HookType as HT

        # Handle deny
        if not result.allowed or result.decision == "deny":
            return {
                "hookSpecificOutput": {
                    "hookEventName": hook_type.value,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": result.reason or "Denied by hook",
                },
            }

        # Handle ask (maps to deny with specific message for user confirmation)
        if result.decision == "ask":
            return {
                "hookSpecificOutput": {
                    "hookEventName": hook_type.value,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"User confirmation required: {result.reason}",
                },
            }

        # Handle PreToolUse with modified arguments
        if hook_type == HT.PRE_TOOL_USE and (result.updated_input or result.modified_args):
            # Prefer updated_input (dict), fall back to modified_args (JSON string)
            updated = result.updated_input
            if updated is None and result.modified_args:
                try:
                    updated = json.loads(result.modified_args)
                except (json.JSONDecodeError, TypeError):
                    updated = None
            if isinstance(updated, dict) and updated:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "updatedInput": updated,
                    },
                }

        # Handle PostToolUse with injection
        if hook_type == HT.POST_TOOL_USE and result.inject:
            inject_content = result.inject.get("content", "")
            if not inject_content:
                return {}

            # Claude SDK expects PostToolUse injections via additionalContext.
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": inject_content,
                },
            }

        # Default: allow without modifications
        return {}

    def build_native_hooks_config(
        self,
        hook_manager: "GeneralHookManager",
        agent_id: str | None = None,
        context_factory: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build complete Claude Code hooks config from GeneralHookManager.

        Iterates through all hooks registered in the GeneralHookManager,
        converts each to HookMatcher format, and returns a configuration
        dict suitable for ClaudeAgentOptions.

        Args:
            hook_manager: MassGen GeneralHookManager with registered hooks
            agent_id: Agent ID for per-agent hook filtering
            context_factory: Callable to provide runtime context

        Returns:
            Dict with "PreToolUse" and "PostToolUse" keys containing
            lists of HookMatcher objects
        """
        from ..hooks import HookType as HT

        config: dict[str, list] = {
            "PreToolUse": [],
            "PostToolUse": [],
        }

        # Get hooks for this agent (includes global hooks)
        for hook_type in [HT.PRE_TOOL_USE, HT.POST_TOOL_USE]:
            hooks = hook_manager.get_hooks_for_agent(agent_id, hook_type)

            for hook in hooks:
                native_matcher = self.convert_hook_to_native(
                    hook,
                    hook_type,
                    context_factory,
                )

                hook_type_key = hook_type.value  # "PreToolUse" or "PostToolUse"
                config[hook_type_key].append(native_matcher)

        # Remove empty lists to keep config clean
        return {k: v for k, v in config.items() if v}

    def merge_native_configs(
        self,
        *configs: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge multiple Claude Code hook configs.

        Combines HookMatcher lists from each config. All hooks from all
        configs are included - later configs extend earlier ones.

        Args:
            *configs: Variable number of Claude Code hook config dicts

        Returns:
            Merged config with combined HookMatcher lists
        """
        merged: dict[str, list] = {
            "PreToolUse": [],
            "PostToolUse": [],
        }

        for config in configs:
            if not config:
                continue
            for hook_type in ["PreToolUse", "PostToolUse"]:
                if hook_type in config:
                    matchers = config[hook_type]
                    if isinstance(matchers, list):
                        merged[hook_type].extend(matchers)

        # Remove empty lists
        return {k: v for k, v in merged.items() if v}


def is_claude_sdk_available() -> bool:
    """Check if Claude Agent SDK is available.

    Returns:
        True if claude_agent_sdk can be imported
    """
    return CLAUDE_SDK_AVAILABLE
