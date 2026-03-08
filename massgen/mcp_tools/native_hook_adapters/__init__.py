"""Native hook adapters for backend-specific hook integration.

This module provides adapters for converting MassGen's hook framework
to backend-specific native formats. Backends with native hook support
(like Claude Code SDK) can use these adapters to handle hooks natively
rather than through MassGen's GeneralHookManager.

Available adapters:
- NativeHookAdapter: Abstract base class for all adapters
- ClaudeCodeNativeHookAdapter: Adapter for Claude Code SDK HookMatcher format

Example usage:
    from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

    adapter = ClaudeCodeNativeHookAdapter()
    native_config = adapter.build_native_hooks_config(hook_manager)
"""

from .base import NativeHookAdapter
from .claude_code_adapter import ClaudeCodeNativeHookAdapter, is_claude_sdk_available

__all__ = [
    "ClaudeCodeNativeHookAdapter",
    "NativeHookAdapter",
    "is_claude_sdk_available",
]
