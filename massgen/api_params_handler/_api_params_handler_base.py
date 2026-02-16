# -*- coding: utf-8 -*-
"""
Base class for API parameters handlers.
Provides common functionality for building API parameters across different backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Set


class APIParamsHandlerBase(ABC):
    """Abstract base class for API parameter handlers."""

    def __init__(self, backend_instance: Any):
        """Initialize the API params handler.

        Args:
            backend_instance: The backend instance containing necessary formatters and config
        """
        self.backend = backend_instance
        self.formatter = backend_instance.formatter
        self.custom_tool_manager = backend_instance.custom_tool_manager

    @abstractmethod
    async def build_api_params(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        all_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build API parameters for the specific backend.

        Args:
            messages: List of messages in framework format
            tools: List of tools in framework format
            all_params: All parameters including config and runtime params

        Returns:
            Dictionary of API parameters ready for the backend
        """

    @abstractmethod
    def get_excluded_params(self) -> Set[str]:
        """Get backend-specific parameters to exclude from API calls."""

    @abstractmethod
    def get_provider_tools(self, all_params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get provider-specific tools based on parameters."""

    def get_base_excluded_params(self) -> Set[str]:
        """Get common parameters to exclude across all backends."""
        return {
            "upload_files",
            # Filesystem manager parameters (handled by base class)
            "cwd",
            "agent_temporary_workspace",
            "agent_temporary_workspace_parent",
            "context_paths",
            "context_write_access_enabled",
            "enforce_read_before_delete",
            "enable_image_generation",
            "enable_audio_generation",
            "enable_file_generation",
            "enable_video_generation",
            # Generation backend/model preferences (used by generate_media tool)
            "image_generation_backend",
            "image_generation_model",
            "video_generation_backend",
            "video_generation_model",
            "audio_generation_backend",
            "audio_generation_model",
            "multimodal_config",
            "enable_mcp_command_line",
            "command_line_allowed_commands",
            "command_line_blocked_commands",
            "command_line_execution_mode",
            "command_line_docker_image",
            "command_line_docker_memory_limit",
            "command_line_docker_cpu_limit",
            "command_line_docker_network_mode",
            "command_line_docker_enable_sudo",
            # Docker credential and package management (nested dicts)
            "command_line_docker_credentials",
            "command_line_docker_packages",
            "exclude_file_operation_mcps",
            "use_mcpwrapped_for_tool_filtering",
            "use_no_roots_wrapper",
            # Code-based tools (CodeAct paradigm)
            "enable_code_based_tools",
            "custom_tools_path",
            "auto_discover_custom_tools",
            "exclude_custom_tools",
            "direct_mcp_servers",
            "shared_tools_directory",
            # Backend identification (handled by orchestrator)
            "type",
            "agent_id",
            "session_id",  # Memory/conversation session ID from chat_agent
            "filesystem_session_id",  # Docker filesystem session mount
            "session_storage_base",
            # MCP configuration (handled by base class for MCP backends)
            "mcp_servers",
            # Coordination parameters (handled by orchestrator, not passed to API)
            "vote_only",  # Vote-only mode flag for coordination
            "plan_depth",
            "plan_target_steps",
            "plan_target_chunks",
            "use_two_tier_workspace",  # Two-tier workspace (scratch/deliverable) + git versioning
            "write_mode",  # Isolated write context mode (auto/worktree/isolated/legacy)
            "drift_conflict_policy",  # Isolated apply drift resolution policy
            "novelty_injection",  # Novelty pressure level (none/gentle/moderate/aggressive)
            # NLIP configuration belongs to MassGen routing, never provider APIs
            "enable_nlip",
            "nlip",
            "nlip_config",
            # Parallelization
            "instance_id",
            # Rate limiting (handled by rate_limiter.py)
            "enable_rate_limit",
            "concurrent_tool_execution",  # Local execution control (not sent to API)
            "max_concurrent_tools",  # Local execution control (not sent to API)
            # Multimodal tools (handled by base_with_custom_tool_and_mcp.py)
            "enable_multimodal_tools",
            "multimodal_config",
            # Hook framework (handled by base class)
            "hooks",
            # Debug options (not passed to API)
            "debug_delay_seconds",
            "debug_delay_after_n_tools",
            # Per-agent voting sensitivity (coordination config, not API param)
            "voting_sensitivity",
            "voting_threshold",
            "checklist_require_gap_report",
            "gap_report_mode",
            # Decomposition mode parameters (handled by orchestrator, not passed to API)
            "coordination_mode",
            "presenter_agent",
            "subtask",
            # Fairness controls (handled by orchestrator, not passed to API)
            "fairness_enabled",
            "fairness_lead_cap_answers",
            "max_midstream_injections_per_round",
        }

    def build_base_api_params(
        self,
        messages: List[Dict[str, Any]],
        all_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build base API parameters common to most backends."""
        api_params = {"stream": True}

        # Add filtered parameters
        excluded = self.get_excluded_params()
        for key, value in all_params.items():
            if key not in excluded and value is not None:
                api_params[key] = value

        return api_params

    def get_mcp_tools(self) -> List[Dict[str, Any]]:
        """Get MCP tools from backend if available."""
        if hasattr(self.backend, "_mcp_functions") and self.backend._mcp_functions:
            if hasattr(self.backend, "get_mcp_tools_formatted"):
                return self.backend.get_mcp_tools_formatted()
        return []
