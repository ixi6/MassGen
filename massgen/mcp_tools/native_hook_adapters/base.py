"""Base interface for native hook adapters.

This module provides the abstract base class for adapting MassGen's hook framework
to backend-specific native hook formats. Backends with native hook support (like
Claude Code) can implement this interface to handle hooks natively rather than
through MassGen's GeneralHookManager.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..hooks import GeneralHookManager, HookEvent, HookResult, HookType, PatternHook


class NativeHookAdapter(ABC):
    """Abstract base class for adapting MassGen hooks to native backend formats.

    Backends with native hook support (like Claude Code SDK) can implement this
    interface to convert MassGen's hook framework to their native format. This
    allows hooks to be executed by the backend's native hook system rather than
    by MassGen's GeneralHookManager.

    The adapter is responsible for:
    1. Converting MassGen PatternHook instances to native hook format
    2. Wrapping MassGen hook handlers as native-compatible functions
    3. Converting HookResult responses to native format
    4. Merging multiple hook configurations

    Example implementation for a hypothetical backend:
        class MyBackendNativeHookAdapter(NativeHookAdapter):
            def supports_hook_type(self, hook_type):
                return hook_type in (HookType.PRE_TOOL_USE, HookType.POST_TOOL_USE)

            def convert_hook_to_native(self, hook, hook_type, context_factory):
                # Wrap MassGen hook as native function
                async def native_hook(tool_name, tool_args):
                    event = self.create_hook_event(...)
                    result = await hook.execute(...)
                    return self.convert_result_to_native(result, hook_type)
                return NativeHookConfig(pattern=hook.matcher, handler=native_hook)
    """

    @abstractmethod
    def supports_hook_type(self, hook_type: "HookType") -> bool:
        """Check if this adapter supports the given hook type.

        Args:
            hook_type: The type of hook (PRE_TOOL_USE or POST_TOOL_USE)

        Returns:
            True if this adapter can handle the hook type
        """

    @abstractmethod
    def convert_hook_to_native(
        self,
        hook: "PatternHook",
        hook_type: "HookType",
        context_factory: Callable[[], dict[str, Any]] | None = None,
    ) -> Any:
        """Convert a MassGen hook to native format.

        Creates a wrapper that:
        1. Receives native hook input
        2. Converts to MassGen's HookEvent format
        3. Executes the MassGen hook
        4. Converts HookResult back to native response format

        Args:
            hook: MassGen PatternHook instance to convert
            hook_type: Type of hook (PRE_TOOL_USE or POST_TOOL_USE)
            context_factory: Optional callable that returns context dict with
                session_id, orchestrator_id, agent_id, etc.

        Returns:
            Native hook configuration object (type depends on backend)
        """

    @abstractmethod
    def build_native_hooks_config(
        self,
        hook_manager: "GeneralHookManager",
        agent_id: str | None = None,
        context_factory: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build complete native hooks configuration from GeneralHookManager.

        Iterates through all hooks registered in the GeneralHookManager,
        converts each to native format, and returns a configuration dict
        suitable for passing to the backend.

        Args:
            hook_manager: MassGen GeneralHookManager with registered hooks
            agent_id: Agent ID for per-agent hook filtering
            context_factory: Callable to provide runtime context for hooks

        Returns:
            Native hooks configuration dict (structure depends on backend)
        """

    @abstractmethod
    def merge_native_configs(
        self,
        *configs: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge multiple native hook configs into one.

        Used to combine different sources of hooks:
        - Permission hooks (from filesystem manager)
        - Built-in MassGen hooks (MidStreamInjection, etc.)
        - User-configured hooks (from YAML)

        Args:
            *configs: Variable number of native config dicts to merge

        Returns:
            Merged native hooks configuration
        """

    @staticmethod
    def create_hook_event_from_native(
        native_input: dict[str, Any],
        hook_type: "HookType",
        context: dict[str, Any],
    ) -> "HookEvent":
        """Create MassGen HookEvent from native input format.

        Standard implementation for converting native hook input to MassGen's
        HookEvent dataclass. Subclasses can override if their native format
        differs significantly.

        Args:
            native_input: Native hook input dict, typically containing:
                - tool_name: Name of the tool being called
                - tool_input: Tool arguments (for PreToolUse)
                - tool_output: Tool result (for PostToolUse)
            hook_type: The type of hook event
            context: Context dict with session_id, orchestrator_id, agent_id

        Returns:
            HookEvent instance populated with the native input data
        """
        # Import here to avoid circular imports
        from ..hooks import HookEvent

        tool_name = native_input.get("tool_name", "")
        tool_input = native_input.get("tool_input", {})
        tool_output = native_input.get("tool_output")

        return HookEvent(
            hook_type=hook_type.value,
            session_id=context.get("session_id", ""),
            orchestrator_id=context.get("orchestrator_id", ""),
            agent_id=context.get("agent_id"),
            timestamp=datetime.now(timezone.utc),
            tool_name=tool_name,
            tool_input=tool_input if isinstance(tool_input, dict) else {},
            tool_output=tool_output,
        )

    @staticmethod
    def convert_hook_result_to_native(
        result: "HookResult",
        hook_type: "HookType",
    ) -> dict[str, Any]:
        """Convert MassGen HookResult to native response format.

        This is a default implementation that returns a generic dict.
        Subclasses should override this to return their backend-specific
        response format.

        Args:
            result: MassGen HookResult from hook execution
            hook_type: The type of hook that produced the result

        Returns:
            Native response dict (structure depends on backend)

        Raises:
            NotImplementedError: Subclasses must implement this method
        """
        raise NotImplementedError(
            "Subclasses must implement convert_hook_result_to_native",
        )
