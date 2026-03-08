"""
Native Tool Backend Mixin — standardized interface for backends with built-in tools.

Backends like Claude Code and Codex come with their own native tools (file editing,
shell execution, web search, etc.). This mixin provides a common interface for:

1. Declaring which native tools to disable (disallowed_tools)
2. Declaring tool_category_overrides (which MCP categories to skip/override)
3. Integrating MassGen hooks into the backend's native hook system

Usage:
    class MyBackend(NativeToolBackendMixin, LLMBackend):
        def get_disallowed_tools(self, config: Dict[str, Any]) -> List[str]:
            return ["SomeTool", "AnotherTool"]
"""

from abc import abstractmethod
from typing import Any

from loguru import logger


class NativeToolBackendMixin:
    """Mixin for backends that have built-in/native tools.

    Provides standardized methods for:
    - Tool filtering: which native tools to disable so MassGen equivalents are used
    - Category overrides: which MassGen MCP tool categories the backend handles natively
    - Hook integration: bridging MassGen hooks into the backend's native hook system
    """

    def __init_native_tool_mixin__(self):
        """Initialize mixin state. Call from subclass __init__."""
        self._native_hook_adapter: Any | None = None
        self._massgen_hooks_config: dict[str, Any] | None = None

    # ── Tool Filtering ──────────────────────────────────────────────────

    @abstractmethod
    def get_disallowed_tools(self, config: dict[str, Any]) -> list[str]:
        """Return list of native tools to disable.

        These are backend-native tools that MassGen replaces with its own
        MCP equivalents (e.g., Read/Write → MassGen filesystem MCP).

        Args:
            config: Backend config dict (enables conditional disabling,
                    e.g., keep WebSearch when enable_web_search=True)

        Returns:
            List of tool name strings/patterns to disable.
            Patterns depend on the backend (e.g., Claude Code supports
            glob patterns like "Bash(rm*)").
        """

    @abstractmethod
    def get_tool_category_overrides(self) -> dict[str, str]:
        """Return tool category overrides for this backend.

        Maps MassGen MCP tool categories to override behavior:
          "skip"     — backend has native equivalent, don't attach this MCP category
          "override" — attach MassGen's version, disable native equivalent

        Categories: filesystem, command_execution, file_search, web_search,
                    planning, subagents, code_based_tools

        Returns:
            Dict mapping category name → "skip" or "override".
        """

    # ── Native Hook Integration ─────────────────────────────────────────

    def supports_native_hooks(self) -> bool:
        """Check if this backend supports native hook integration.

        Returns:
            True if a native hook adapter is available.
        """
        return self._native_hook_adapter is not None

    def get_native_hook_adapter(self) -> Any | None:
        """Get the native hook adapter for this backend.

        Returns:
            NativeHookAdapter instance if available, None otherwise.
        """
        return self._native_hook_adapter

    def set_native_hooks_config(self, config: dict[str, Any]) -> None:
        """Set MassGen hooks converted to native format.

                Called by the orchestrator to set up MassGen hooks (MidStreamInjection,
                HighPriorityTaskReminder, user-configured hooks) in native format.
                These hooks will be merged with permission hooks when building
        backend options.

                Args:
                    config: Native hooks configuration dict with PreToolUse and/or
                           PostToolUse keys containing hook matcher lists.
        """
        self._massgen_hooks_config = config
        logger.debug(
            f"[{self.__class__.__name__}] Set native hooks config: " f"PreToolUse={len(config.get('PreToolUse', []))} hooks, " f"PostToolUse={len(config.get('PostToolUse', []))} hooks",
        )

    def _init_native_hook_adapter(self, adapter_class_path: str) -> None:
        """Initialize a native hook adapter by import path.

        Convenience method that handles ImportError gracefully.

        Args:
            adapter_class_path: Dotted import path like
                "massgen.mcp_tools.native_hook_adapters.ClaudeCodeNativeHookAdapter"
        """
        try:
            module_path, class_name = adapter_class_path.rsplit(".", 1)
            import importlib

            module = importlib.import_module(module_path)
            adapter_cls = getattr(module, class_name)
            self._native_hook_adapter = adapter_cls()
            logger.debug(f"[{self.__class__.__name__}] Native hook adapter initialized: {class_name}")
        except (ImportError, AttributeError) as e:
            logger.debug(f"[{self.__class__.__name__}] Native hook adapter not available: {e}")

    # ── Workflow Tools Setup ─────────────────────────────────────────────

    def _setup_workflow_tools(
        self,
        tools: list[dict[str, Any]],
        mcp_base_path: str,
        mcp_tool_prefix: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        """Setup workflow tools as MCP server with text fallback.

        Shared logic for configuring MassGen workflow tools (new_answer, vote, etc.)
        for native tool backends. Tries to set up an MCP server first; falls back
        to text-based instructions if MCP setup fails.

        Args:
            tools: List of tool schemas from orchestrator.
            mcp_base_path: Base path for writing MCP tool specs (e.g., workspace/.codex).
            mcp_tool_prefix: Prefix for MCP tool names in instructions. For Claude Code,
                            this is "mcp__massgen_workflow_tools__" since Claude Code
                            prefixes MCP tools with "mcp__{server_name}__".

        Returns:
            Tuple of (mcp_config, instructions):
            - mcp_config: MCP server config dict if created, None if using text fallback
            - instructions: Workflow instructions to inject into system prompt
        """
        from .base import (
            build_workflow_instructions,
            build_workflow_mcp_instructions,
            build_workflow_mcp_server_config,
        )

        workflow_mcp_config = build_workflow_mcp_server_config(tools or [], mcp_base_path)
        if workflow_mcp_config:
            instructions = build_workflow_mcp_instructions(tools or [], mcp_prefix=mcp_tool_prefix)
            logger.info(f"[{self.__class__.__name__}] Workflow tools configured as MCP server")
        else:
            instructions = build_workflow_instructions(tools or [])
            logger.info(f"[{self.__class__.__name__}] Workflow tools using text fallback ({len(instructions)} chars)")

        return workflow_mcp_config, instructions
