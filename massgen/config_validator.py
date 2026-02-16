# -*- coding: utf-8 -*-
"""
Configuration validation for MassGen YAML/JSON configs.

This module provides comprehensive validation for MassGen configuration files,
checking schema structure, required fields, valid values, and best practices.

Usage:
    from massgen.config_validator import ConfigValidator

    # Validate a config file
    validator = ConfigValidator()
    result = validator.validate_config_file("config.yaml")

    if result.has_errors():
        print(result.format_errors())
        sys.exit(1)

    if result.has_warnings():
        print(result.format_warnings())

    # Validate a config dict
    result = validator.validate_config(config_dict)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .backend.capabilities import (
    BACKEND_CAPABILITIES,
    get_capabilities,
    validate_backend_config,
)
from .mcp_tools.config_validator import MCPConfigValidator


@dataclass
class ValidationIssue:
    """Represents a validation error or warning."""

    message: str
    location: str
    suggestion: Optional[str] = None
    severity: str = "error"  # "error" or "warning"

    def __str__(self) -> str:
        """Format issue for display."""
        severity_symbol = "❌" if self.severity == "error" else "⚠️"
        parts = [f"{severity_symbol} [{self.location}] {self.message}"]
        if self.suggestion:
            parts.append(f"   💡 Suggestion: {self.suggestion}")
        return "\n".join(parts)


@dataclass
class ValidationResult:
    """Aggregates all validation errors and warnings."""

    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)

    def add_error(self, message: str, location: str, suggestion: Optional[str] = None) -> None:
        """Add a validation error."""
        self.errors.append(ValidationIssue(message, location, suggestion, "error"))

    def add_warning(self, message: str, location: str, suggestion: Optional[str] = None) -> None:
        """Add a validation warning."""
        self.warnings.append(ValidationIssue(message, location, suggestion, "warning"))

    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0

    def is_valid(self) -> bool:
        """Check if config is valid (no errors)."""
        return not self.has_errors()

    def format_errors(self) -> str:
        """Format all errors for display."""
        if not self.errors:
            return ""
        lines = ["\n🔴 Configuration Errors Found:\n"]
        lines.extend(str(error) for error in self.errors)
        return "\n".join(lines)

    def format_warnings(self) -> str:
        """Format all warnings for display."""
        if not self.warnings:
            return ""
        lines = ["\n🟡 Configuration Warnings:\n"]
        lines.extend(str(warning) for warning in self.warnings)
        return "\n".join(lines)

    def format_all(self) -> str:
        """Format all issues for display."""
        parts = []
        if self.has_errors():
            parts.append(self.format_errors())
        if self.has_warnings():
            parts.append(self.format_warnings())
        return "\n".join(parts) if parts else "✅ Configuration is valid!"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "valid": self.is_valid(),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [{"message": e.message, "location": e.location, "suggestion": e.suggestion} for e in self.errors],
            "warnings": [{"message": w.message, "location": w.location, "suggestion": w.suggestion} for w in self.warnings],
        }


class ConfigValidator:
    """Validates MassGen configuration files."""

    # V1 config keywords that are no longer supported
    V1_KEYWORDS = {
        "models",
        "model_configs",
        "num_agents",
        "max_rounds",
        "consensus_threshold",
        "voting_enabled",
        "enable_voting",
    }

    # Valid permission modes for backends that support them
    VALID_PERMISSION_MODES = {"default", "acceptEdits", "bypassPermissions", "plan"}

    # Valid display types for UI
    VALID_DISPLAY_TYPES = {"rich_terminal", "simple", "textual_terminal"}

    # Valid voting sensitivity levels
    VALID_VOTING_SENSITIVITY = {
        "lenient",
        "balanced",
        "strict",
        "roi",
        "roi_conservative",
        "roi_balanced",
        "roi_aggressive",
        "sequential",
        "adversarial",
        "consistency",
        "diversity",
        "reflective",
        "checklist",
        "checklist_scored",
        "checklist_gated",
    }

    # Valid answer novelty requirements
    VALID_ANSWER_NOVELTY = {"lenient", "balanced", "strict"}

    # Valid write modes for isolated write contexts
    VALID_WRITE_MODES = {"auto", "worktree", "isolated", "legacy"}
    VALID_DRIFT_CONFLICT_POLICIES = {"skip", "prefer_presenter", "fail"}
    VALID_NOVELTY_INJECTION = {"none", "gentle", "moderate", "aggressive"}

    # Valid gap report modes
    VALID_GAP_REPORT_MODES = {"changedoc", "separate", "none"}

    def __init__(self):
        """Initialize the validator."""

    def validate_config_file(self, config_path: str) -> ValidationResult:
        """
        Validate a configuration file.

        Args:
            config_path: Path to YAML or JSON config file

        Returns:
            ValidationResult with any errors or warnings found
        """
        result = ValidationResult()

        # Check file exists
        path = Path(config_path)
        if not path.exists():
            result.add_error(f"Config file not found: {config_path}", "file", "Check the file path")
            return result

        # Load config file
        try:
            with open(path, "r") as f:
                if path.suffix in [".yaml", ".yml"]:
                    config = yaml.safe_load(f)
                elif path.suffix == ".json":
                    import json

                    config = json.load(f)
                else:
                    result.add_error(
                        f"Unsupported file format: {path.suffix}",
                        "file",
                        "Use .yaml, .yml, or .json extension",
                    )
                    return result
        except Exception as e:
            result.add_error(f"Failed to parse config file: {e}", "file", "Check file syntax")
            return result

        # Validate the loaded config
        return self.validate_config(config)

    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """
        Validate a configuration dictionary.

        Args:
            config: Configuration dictionary

        Returns:
            ValidationResult with any errors or warnings found
        """
        result = ValidationResult()

        if not isinstance(config, dict):
            result.add_error("Config must be a dictionary/object", "root", "Check YAML/JSON syntax")
            return result

        # Check for V1 config keywords (instant fail)
        self._check_v1_keywords(config, result)
        if result.has_errors():
            return result  # Stop validation if V1 detected

        # Validate top-level structure
        self._validate_top_level(config, result)

        # Validate agents (if present)
        if "agents" in config or "agent" in config:
            self._validate_agents(config, result)

        # Validate orchestrator (if present)
        if "orchestrator" in config:
            self._validate_orchestrator(config["orchestrator"], result)

        # Validate UI (if present)
        if "ui" in config:
            self._validate_ui(config["ui"], result)

        # Validate memory (if present)
        if "memory" in config:
            self._validate_memory(config["memory"], result)

        # Check for warnings (best practices, deprecations, etc.)
        self._check_warnings(config, result)

        return result

    def _check_v1_keywords(self, config: Dict[str, Any], result: ValidationResult) -> None:
        """Check for V1 config keywords and reject them."""
        found_v1_keywords = []
        for keyword in self.V1_KEYWORDS:
            if keyword in config:
                found_v1_keywords.append(keyword)

        if found_v1_keywords:
            result.add_error(
                f"V1 config format detected (found: {', '.join(found_v1_keywords)}). " "V1 configs are no longer supported.",
                "root",
                "Migrate to V2 config format. See docs/source/reference/yaml_schema.rst for the current schema.",
            )

    def _validate_top_level(self, config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate top-level config structure (Level 1)."""
        # Require either 'agents' (list) or 'agent' (single)
        has_agents = "agents" in config
        has_agent = "agent" in config

        if not has_agents and not has_agent:
            result.add_error(
                "Config must have either 'agents' (list) or 'agent' (single agent)",
                "root",
                "Add 'agents: [...]' for multiple agents or 'agent: {...}' for a single agent",
            )
            return

        if has_agents and has_agent:
            result.add_error(
                "Config cannot have both 'agents' and 'agent' fields",
                "root",
                "Use either 'agents' for multiple agents or 'agent' for a single agent",
            )
            return

        # Validate agents is a list (if present)
        if has_agents and not isinstance(config["agents"], list):
            result.add_error(
                f"'agents' must be a list, got {type(config['agents']).__name__}",
                "root.agents",
                "Use 'agents: [...]' for multiple agents",
            )

        # Validate agent is a dict (if present)
        if has_agent and not isinstance(config["agent"], dict):
            result.add_error(
                f"'agent' must be a dictionary, got {type(config['agent']).__name__}",
                "root.agent",
                "Use 'agent: {...}' for a single agent",
            )

        # Validate global hooks if present
        if "hooks" in config:
            self._validate_hooks(config["hooks"], "hooks", result)

    def _validate_agents(self, config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate agent configurations (Level 2)."""
        # Get agents list (normalize single agent to list)
        if "agents" in config:
            agents = config["agents"]
            if not isinstance(agents, list):
                return  # Already reported error in _validate_top_level
        else:
            agents = [config["agent"]]

        # Track agent IDs for duplicate detection
        agent_ids: List[str] = []

        for i, agent_config in enumerate(agents):
            agent_location = f"agents[{i}]" if "agents" in config else "agent"

            # Validate agent is a dict
            if not isinstance(agent_config, dict):
                result.add_error(
                    f"Agent must be a dictionary, got {type(agent_config).__name__}",
                    agent_location,
                    "Use 'id', 'backend', and optional 'system_message' fields",
                )
                continue

            # Validate required field: id
            if "id" not in agent_config:
                result.add_error("Agent missing required field 'id'", agent_location, "Add 'id: \"agent-name\"'")
            else:
                agent_id = agent_config["id"]
                if not isinstance(agent_id, str):
                    result.add_error(
                        f"Agent 'id' must be a string, got {type(agent_id).__name__}",
                        f"{agent_location}.id",
                        "Use a string identifier like 'id: \"researcher\"'",
                    )
                elif agent_id in agent_ids:
                    result.add_error(
                        f"Duplicate agent ID: '{agent_id}'",
                        f"{agent_location}.id",
                        "Each agent must have a unique ID",
                    )
                else:
                    agent_ids.append(agent_id)

            # Validate required field: backend
            if "backend" not in agent_config:
                result.add_error(
                    "Agent missing required field 'backend'",
                    agent_location,
                    "Add 'backend: {type: ..., model: ...}'",
                )
            else:
                self._validate_backend(agent_config["backend"], f"{agent_location}.backend", result)

            # Validate optional field: system_message
            if "system_message" in agent_config:
                system_message = agent_config["system_message"]
                if not isinstance(system_message, str):
                    result.add_error(
                        f"Agent 'system_message' must be a string, got {type(system_message).__name__}",
                        f"{agent_location}.system_message",
                        "Use a string for the system message",
                    )

            # Validate optional field: voting_sensitivity (per-agent override)
            if "voting_sensitivity" in agent_config:
                voting_sensitivity = agent_config["voting_sensitivity"]
                if voting_sensitivity not in self.VALID_VOTING_SENSITIVITY:
                    valid_values = ", ".join(sorted(self.VALID_VOTING_SENSITIVITY))
                    result.add_error(
                        f"Invalid voting_sensitivity: '{voting_sensitivity}'",
                        f"{agent_location}.voting_sensitivity",
                        f"Use one of: {valid_values}",
                    )

            # Validate optional field: subtask (decomposition mode)
            if "subtask" in agent_config:
                subtask = agent_config["subtask"]
                if not isinstance(subtask, str):
                    result.add_error(
                        f"Agent 'subtask' must be a string, got {type(subtask).__name__}",
                        f"{agent_location}.subtask",
                        "Use a string describing the agent's subtask",
                    )

    def _validate_backend(self, backend_config: Dict[str, Any], location: str, result: ValidationResult) -> None:
        """Validate backend configuration (Level 3)."""
        if not isinstance(backend_config, dict):
            result.add_error(
                f"Backend must be a dictionary, got {type(backend_config).__name__}",
                location,
                "Use 'type', 'model', and other backend-specific fields",
            )
            return

        # Validate required field: type
        if "type" not in backend_config:
            result.add_error("Backend missing required field 'type'", location, "Add 'type: \"openai\"' or similar")
            return

        backend_type = backend_config["type"]
        if not isinstance(backend_type, str):
            result.add_error(
                f"Backend 'type' must be a string, got {type(backend_type).__name__}",
                f"{location}.type",
                "Use a string like 'openai', 'claude', 'gemini', etc.",
            )
            return

        # Validate backend type is supported
        if backend_type not in BACKEND_CAPABILITIES:
            valid_types = ", ".join(sorted(BACKEND_CAPABILITIES.keys()))
            result.add_error(
                f"Unknown backend type: '{backend_type}'",
                f"{location}.type",
                f"Use one of: {valid_types}",
            )
            return

        # Validate model field
        # Model is optional for:
        # - ag2 (uses agent_config.llm_config instead)
        # - claude_code (has default model)
        # - backends with default models in BACKEND_CAPABILITIES
        caps = get_capabilities(backend_type)
        has_default_model = caps and caps.default_model != "custom"

        if backend_type != "ag2" and not has_default_model:
            if "model" not in backend_config:
                result.add_error("Backend missing required field 'model'", location, "Add 'model: \"model-name\"'")
            else:
                model = backend_config["model"]
                if not isinstance(model, str):
                    result.add_error(
                        f"Backend 'model' must be a string, got {type(model).__name__}",
                        f"{location}.model",
                        "Use a string model identifier",
                    )
        elif "model" in backend_config:
            # Validate type if model is provided (even if optional)
            model = backend_config["model"]
            if not isinstance(model, str):
                result.add_error(
                    f"Backend 'model' must be a string, got {type(model).__name__}",
                    f"{location}.model",
                    "Use a string model identifier",
                )

        # Validate backend-specific capabilities using existing validator
        capability_errors = validate_backend_config(backend_type, backend_config)
        for error_msg in capability_errors:
            result.add_error(error_msg, location, "Check backend capabilities in documentation")

        # Validate permission_mode if present
        if "permission_mode" in backend_config:
            permission_mode = backend_config["permission_mode"]
            if permission_mode not in self.VALID_PERMISSION_MODES:
                valid_modes = ", ".join(sorted(self.VALID_PERMISSION_MODES))
                result.add_error(
                    f"Invalid permission_mode: '{permission_mode}'",
                    f"{location}.permission_mode",
                    f"Use one of: {valid_modes}",
                )

        # Validate tool filtering (allowed_tools, exclude_tools, disallowed_tools)
        self._validate_tool_filtering(backend_config, location, result)

        # Validate MCP servers if present
        if "mcp_servers" in backend_config:
            try:
                MCPConfigValidator.validate_backend_mcp_config(backend_config)
            except Exception as e:
                result.add_error(
                    f"MCP configuration error: {str(e)}",
                    f"{location}.mcp_servers",
                    "Check MCP server configuration syntax",
                )

        # Validate boolean fields
        boolean_fields = [
            "enable_web_search",
            "enable_code_execution",
            "enable_code_interpreter",
            "enable_programmatic_flow",
            "enable_tool_search",
            "enable_strict_tool_use",
        ]
        for field_name in boolean_fields:
            if field_name in backend_config:
                value = backend_config[field_name]
                if not isinstance(value, bool):
                    result.add_error(
                        f"Backend '{field_name}' must be a boolean, got {type(value).__name__}",
                        f"{location}.{field_name}",
                        "Use 'true' or 'false'",
                    )

        # Validate output_schema if present (structured outputs)
        if "output_schema" in backend_config:
            output_schema = backend_config["output_schema"]
            if not isinstance(output_schema, dict):
                result.add_error(
                    f"'output_schema' must be a dictionary, got {type(output_schema).__name__}",
                    f"{location}.output_schema",
                    "Use a JSON schema object like: {type: object, properties: {...}}",
                )
            elif not output_schema:
                result.add_warning(
                    "'output_schema' is an empty dictionary",
                    f"{location}.output_schema",
                    "Provide a valid JSON schema",
                )
            elif "type" not in output_schema:
                result.add_warning(
                    "'output_schema' should have a 'type' field",
                    f"{location}.output_schema",
                    "Add 'type: object' or similar",
                )

        # Check for incompatible feature combinations
        if backend_config.get("enable_programmatic_flow") and backend_config.get("enable_strict_tool_use"):
            result.add_warning(
                "Strict tool use is not compatible with programmatic tool calling",
                location,
                "Strict tool use will be automatically disabled at runtime. ",
            )

        # Validate hooks if present
        if "hooks" in backend_config:
            self._validate_hooks(backend_config["hooks"], f"{location}.hooks", result)

        # Validate Codex Docker mode requirements
        if backend_type == "codex":
            execution_mode = backend_config.get("command_line_execution_mode")
            if execution_mode == "docker":
                # command_line_docker_network_mode is required for Codex in Docker mode
                if "command_line_docker_network_mode" not in backend_config:
                    result.add_error(
                        "Codex backend in Docker mode requires 'command_line_docker_network_mode'",
                        f"{location}.command_line_docker_network_mode",
                        "Add 'command_line_docker_network_mode: bridge' (required for Codex Docker execution)",
                    )

    def _validate_tool_filtering(
        self,
        backend_config: Dict[str, Any],
        location: str,
        result: ValidationResult,
    ) -> None:
        """Validate tool filtering parameters."""
        # Check allowed_tools
        if "allowed_tools" in backend_config:
            allowed_tools = backend_config["allowed_tools"]
            if not isinstance(allowed_tools, list):
                result.add_error(
                    f"'allowed_tools' must be a list, got {type(allowed_tools).__name__}",
                    f"{location}.allowed_tools",
                    "Use a list of tool names",
                )
            else:
                for i, tool in enumerate(allowed_tools):
                    if not isinstance(tool, str):
                        result.add_error(
                            f"'allowed_tools[{i}]' must be a string, got {type(tool).__name__}",
                            f"{location}.allowed_tools[{i}]",
                            "Use string tool names",
                        )

        # Check exclude_tools
        if "exclude_tools" in backend_config:
            exclude_tools = backend_config["exclude_tools"]
            if not isinstance(exclude_tools, list):
                result.add_error(
                    f"'exclude_tools' must be a list, got {type(exclude_tools).__name__}",
                    f"{location}.exclude_tools",
                    "Use a list of tool names",
                )
            else:
                for i, tool in enumerate(exclude_tools):
                    if not isinstance(tool, str):
                        result.add_error(
                            f"'exclude_tools[{i}]' must be a string, got {type(tool).__name__}",
                            f"{location}.exclude_tools[{i}]",
                            "Use string tool names",
                        )

        # Check disallowed_tools (claude_code specific)
        if "disallowed_tools" in backend_config:
            disallowed_tools = backend_config["disallowed_tools"]
            if not isinstance(disallowed_tools, list):
                result.add_error(
                    f"'disallowed_tools' must be a list, got {type(disallowed_tools).__name__}",
                    f"{location}.disallowed_tools",
                    "Use a list of tool patterns",
                )
            else:
                for i, tool in enumerate(disallowed_tools):
                    if not isinstance(tool, str):
                        result.add_error(
                            f"'disallowed_tools[{i}]' must be a string, got {type(tool).__name__}",
                            f"{location}.disallowed_tools[{i}]",
                            "Use string tool patterns",
                        )

    def _validate_hooks(
        self,
        hooks_config: Dict[str, Any],
        location: str,
        result: ValidationResult,
    ) -> None:
        """Validate hooks configuration.

        Hooks can be defined at two levels:
        - Global (top-level `hooks:`) - applies to all agents
        - Per-agent (in `backend.hooks:`) - can extend or override global hooks
        """
        if not isinstance(hooks_config, dict):
            result.add_error(
                f"'hooks' must be a dictionary, got {type(hooks_config).__name__}",
                location,
                "Use hook types like 'PreToolUse' and 'PostToolUse'",
            )
            return

        valid_hook_types = {"PreToolUse", "PostToolUse"}

        for hook_type, hook_list in hooks_config.items():
            if hook_type == "override":
                # Skip override flag
                continue

            if hook_type not in valid_hook_types:
                result.add_warning(
                    f"Unknown hook type: '{hook_type}'",
                    f"{location}.{hook_type}",
                    f"Use one of: {', '.join(sorted(valid_hook_types))}",
                )
                continue

            # Handle both list format and dict format (with override)
            hooks_to_validate = hook_list
            if isinstance(hook_list, dict):
                hooks_to_validate = hook_list.get("hooks", [])
                if "override" in hook_list and not isinstance(hook_list["override"], bool):
                    result.add_error(
                        "'override' must be a boolean",
                        f"{location}.{hook_type}.override",
                        "Use 'true' or 'false'",
                    )

            if not isinstance(hooks_to_validate, list):
                result.add_error(
                    f"'{hook_type}' must be a list of hooks",
                    f"{location}.{hook_type}",
                    "Use a list of hook configurations",
                )
                continue

            # Validate each hook in the list
            for i, hook_config in enumerate(hooks_to_validate):
                self._validate_single_hook(
                    hook_config,
                    f"{location}.{hook_type}[{i}]",
                    result,
                )

    def _validate_single_hook(
        self,
        hook_config: Dict[str, Any],
        location: str,
        result: ValidationResult,
    ) -> None:
        """Validate a single hook configuration."""
        if not isinstance(hook_config, dict):
            result.add_error(
                f"Hook must be a dictionary, got {type(hook_config).__name__}",
                location,
                "Use 'handler', 'matcher', 'type', and 'timeout' fields",
            )
            return

        # Validate required field: handler
        if "handler" not in hook_config:
            result.add_error(
                "Hook missing required field 'handler'",
                location,
                "Add 'handler: \"module.function\"' or 'handler: \"path/to/script.py\"'",
            )
        else:
            handler = hook_config["handler"]
            if not isinstance(handler, str):
                result.add_error(
                    f"'handler' must be a string, got {type(handler).__name__}",
                    f"{location}.handler",
                    "Use a module path or file path",
                )

        # Validate optional field: type
        if "type" in hook_config:
            hook_type = hook_config["type"]
            valid_types = {"python"}
            if hook_type not in valid_types:
                result.add_error(
                    f"Invalid hook type: '{hook_type}'",
                    f"{location}.type",
                    f"Use one of: {', '.join(sorted(valid_types))}",
                )

        # Validate optional field: matcher
        if "matcher" in hook_config:
            matcher = hook_config["matcher"]
            if not isinstance(matcher, str):
                result.add_error(
                    f"'matcher' must be a string, got {type(matcher).__name__}",
                    f"{location}.matcher",
                    "Use a glob pattern like '*' or 'Write|Edit'",
                )

        # Validate optional field: timeout
        if "timeout" in hook_config:
            timeout = hook_config["timeout"]
            if not isinstance(timeout, (int, float)):
                result.add_error(
                    f"'timeout' must be a number, got {type(timeout).__name__}",
                    f"{location}.timeout",
                    "Use a number of seconds like 30 or 60",
                )
            elif timeout <= 0:
                result.add_error(
                    f"'timeout' must be positive, got {timeout}",
                    f"{location}.timeout",
                    "Use a positive number of seconds",
                )

        # Validate optional field: fail_closed
        if "fail_closed" in hook_config:
            fail_closed = hook_config["fail_closed"]
            if not isinstance(fail_closed, bool):
                result.add_error(
                    f"'fail_closed' must be a boolean, got {type(fail_closed).__name__}",
                    f"{location}.fail_closed",
                    "Use true or false",
                )

    def _validate_orchestrator(self, orchestrator_config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate orchestrator configuration (Level 5)."""
        location = "orchestrator"

        if not isinstance(orchestrator_config, dict):
            result.add_error(
                f"Orchestrator must be a dictionary, got {type(orchestrator_config).__name__}",
                location,
                "Use orchestrator fields like snapshot_storage, context_paths, etc.",
            )
            return

        # Validate coordination_mode if present
        if "coordination_mode" in orchestrator_config:
            coordination_mode = orchestrator_config["coordination_mode"]
            valid_modes = ["voting", "decomposition"]
            if coordination_mode not in valid_modes:
                result.add_error(
                    f"Invalid coordination_mode: '{coordination_mode}'",
                    f"{location}.coordination_mode",
                    f"Use one of: {', '.join(valid_modes)}",
                )

        # Validate presenter_agent if present
        if "presenter_agent" in orchestrator_config:
            presenter = orchestrator_config["presenter_agent"]
            if not isinstance(presenter, str):
                result.add_error(
                    f"'presenter_agent' must be a string, got {type(presenter).__name__}",
                    f"{location}.presenter_agent",
                    "Use an agent ID string like 'integrator'",
                )

        # Validate context_paths if present
        if "context_paths" in orchestrator_config:
            context_paths = orchestrator_config["context_paths"]
            if not isinstance(context_paths, list):
                result.add_error(
                    f"'context_paths' must be a list, got {type(context_paths).__name__}",
                    f"{location}.context_paths",
                    "Use a list of path configurations",
                )
            else:
                for i, path_config in enumerate(context_paths):
                    if not isinstance(path_config, dict):
                        result.add_error(
                            f"'context_paths[{i}]' must be a dictionary",
                            f"{location}.context_paths[{i}]",
                            "Use 'path' and 'permission' fields",
                        )
                        continue

                    # Check required field: path
                    if "path" not in path_config:
                        result.add_error(
                            "context_paths entry missing 'path' field",
                            f"{location}.context_paths[{i}]",
                            "Add 'path: \"/path/to/dir\"'",
                        )

                    # Check permission field
                    if "permission" in path_config:
                        permission = path_config["permission"]
                        if permission not in ["read", "write"]:
                            result.add_error(
                                f"Invalid permission: '{permission}'",
                                f"{location}.context_paths[{i}].permission",
                                "Use 'read' or 'write'",
                            )

        # Validate coordination if present
        if "coordination" in orchestrator_config:
            coordination = orchestrator_config["coordination"]
            if not isinstance(coordination, dict):
                result.add_error(
                    f"'coordination' must be a dictionary, got {type(coordination).__name__}",
                    f"{location}.coordination",
                    "Use coordination fields like enable_planning_mode, max_orchestration_restarts, etc.",
                )
            else:
                # Validate boolean fields
                boolean_fields = ["enable_planning_mode", "use_two_tier_workspace", "enable_changedoc"]
                for field_name in boolean_fields:
                    if field_name in coordination:
                        value = coordination[field_name]
                        if not isinstance(value, bool):
                            result.add_error(
                                f"'{field_name}' must be a boolean, got {type(value).__name__}",
                                f"{location}.coordination.{field_name}",
                                "Use 'true' or 'false'",
                            )

                # Deprecation warning for use_two_tier_workspace
                if coordination.get("use_two_tier_workspace"):
                    write_mode = coordination.get("write_mode")
                    if write_mode:
                        result.add_warning(
                            "'use_two_tier_workspace' is deprecated and ignored when 'write_mode' is set. " "Remove 'use_two_tier_workspace' from your config.",
                            f"{location}.coordination.use_two_tier_workspace",
                        )
                    else:
                        result.add_warning(
                            "'use_two_tier_workspace' is deprecated. " "Migrate to 'write_mode: auto' for the same functionality with git worktree isolation.",
                            f"{location}.coordination.use_two_tier_workspace",
                        )

                # Validate integer fields
                if "max_orchestration_restarts" in coordination:
                    value = coordination["max_orchestration_restarts"]
                    if not isinstance(value, int) or value < 0:
                        result.add_error(
                            "'max_orchestration_restarts' must be a non-negative integer",
                            f"{location}.coordination.max_orchestration_restarts",
                            "Use a value like 0, 1, 2, etc.",
                        )

                # Validate async_subagents if present
                if "async_subagents" in coordination:
                    async_config = coordination["async_subagents"]
                    if not isinstance(async_config, dict):
                        result.add_error(
                            f"'async_subagents' must be a dictionary, got {type(async_config).__name__}",
                            f"{location}.coordination.async_subagents",
                            "Use async_subagents: {enabled: true, injection_strategy: 'tool_result'}",
                        )
                    else:
                        # Validate enabled field
                        if "enabled" in async_config:
                            enabled = async_config["enabled"]
                            if not isinstance(enabled, bool):
                                result.add_error(
                                    f"'async_subagents.enabled' must be a boolean, got {type(enabled).__name__}",
                                    f"{location}.coordination.async_subagents.enabled",
                                    "Use 'true' or 'false'",
                                )

                        # Validate injection_strategy field
                        if "injection_strategy" in async_config:
                            strategy = async_config["injection_strategy"]
                            valid_strategies = ["tool_result", "user_message"]
                            if strategy not in valid_strategies:
                                result.add_error(
                                    f"Invalid async_subagents.injection_strategy: '{strategy}'",
                                    f"{location}.coordination.async_subagents.injection_strategy",
                                    f"Use one of: {', '.join(valid_strategies)}",
                                )
                # Validate plan_depth if present
                if "plan_depth" in coordination:
                    value = coordination["plan_depth"]
                    valid_depths = ["dynamic", "shallow", "medium", "deep"]
                    if value not in valid_depths:
                        result.add_error(
                            f"'plan_depth' must be one of {valid_depths}, got '{value}'",
                            f"{location}.coordination.plan_depth",
                            "Use 'dynamic', 'shallow' (5-10 tasks), 'medium' (20-50 tasks), or 'deep' (100-200+ tasks)",
                        )

                # Validate optional explicit planning targets
                if "plan_target_steps" in coordination:
                    value = coordination["plan_target_steps"]
                    if value is not None and (not isinstance(value, int) or value <= 0):
                        result.add_error(
                            "'plan_target_steps' must be a positive integer or null",
                            f"{location}.coordination.plan_target_steps",
                            "Use values like 20, 40, 80, or omit/null for dynamic sizing.",
                        )

                if "plan_target_chunks" in coordination:
                    value = coordination["plan_target_chunks"]
                    if value is not None and (not isinstance(value, int) or value <= 0):
                        result.add_error(
                            "'plan_target_chunks' must be a positive integer or null",
                            f"{location}.coordination.plan_target_chunks",
                            "Use values like 3, 5, 8, or omit/null for dynamic sizing.",
                        )

                # Validate subagent_round_timeouts if present
                if "subagent_round_timeouts" in coordination:
                    round_timeouts = coordination["subagent_round_timeouts"]
                    if not isinstance(round_timeouts, dict):
                        result.add_error(
                            f"'subagent_round_timeouts' must be a dictionary, got {type(round_timeouts).__name__}",
                            f"{location}.coordination.subagent_round_timeouts",
                            "Use keys like initial_round_timeout_seconds, subsequent_round_timeout_seconds, round_timeout_grace_seconds",
                        )
                    else:
                        timeout_fields = [
                            "initial_round_timeout_seconds",
                            "subsequent_round_timeout_seconds",
                            "round_timeout_grace_seconds",
                        ]
                        for field_name in timeout_fields:
                            if field_name in round_timeouts:
                                value = round_timeouts[field_name]
                                if field_name == "round_timeout_grace_seconds":
                                    if not isinstance(value, (int, float)) or value < 0:
                                        result.add_error(
                                            f"'{field_name}' must be a non-negative number",
                                            f"{location}.coordination.subagent_round_timeouts.{field_name}",
                                            "Use a value like 120 (seconds)",
                                        )
                                else:
                                    if not isinstance(value, (int, float)) or value <= 0:
                                        result.add_error(
                                            f"'{field_name}' must be a positive number",
                                            f"{location}.coordination.subagent_round_timeouts.{field_name}",
                                            "Use a value like 300 (seconds)",
                                        )

                # Validate write_mode if present
                if "write_mode" in coordination:
                    write_mode = coordination["write_mode"]
                    if write_mode not in self.VALID_WRITE_MODES:
                        valid_values = ", ".join(sorted(self.VALID_WRITE_MODES))
                        result.add_error(
                            f"Invalid write_mode: '{write_mode}'",
                            f"{location}.coordination.write_mode",
                            f"Use one of: {valid_values}",
                        )
                if "drift_conflict_policy" in coordination:
                    policy = coordination["drift_conflict_policy"]
                    if policy not in self.VALID_DRIFT_CONFLICT_POLICIES:
                        valid_values = ", ".join(sorted(self.VALID_DRIFT_CONFLICT_POLICIES))
                        result.add_error(
                            f"Invalid drift_conflict_policy: '{policy}'",
                            f"{location}.coordination.drift_conflict_policy",
                            f"Use one of: {valid_values}",
                        )
                if "novelty_injection" in coordination:
                    novelty = coordination["novelty_injection"]
                    if novelty not in self.VALID_NOVELTY_INJECTION:
                        valid_values = ", ".join(sorted(self.VALID_NOVELTY_INJECTION))
                        result.add_error(
                            f"Invalid novelty_injection: '{novelty}'",
                            f"{location}.coordination.novelty_injection",
                            f"Use one of: {valid_values}",
                        )

        # Validate voting_sensitivity if present
        if "voting_sensitivity" in orchestrator_config:
            voting_sensitivity = orchestrator_config["voting_sensitivity"]
            if voting_sensitivity not in self.VALID_VOTING_SENSITIVITY:
                valid_values = ", ".join(sorted(self.VALID_VOTING_SENSITIVITY))
                result.add_error(
                    f"Invalid voting_sensitivity: '{voting_sensitivity}'",
                    f"{location}.voting_sensitivity",
                    f"Use one of: {valid_values}",
                )

        # Validate answer_novelty_requirement if present
        if "answer_novelty_requirement" in orchestrator_config:
            answer_novelty = orchestrator_config["answer_novelty_requirement"]
            if answer_novelty not in self.VALID_ANSWER_NOVELTY:
                valid_values = ", ".join(sorted(self.VALID_ANSWER_NOVELTY))
                result.add_error(
                    f"Invalid answer_novelty_requirement: '{answer_novelty}'",
                    f"{location}.answer_novelty_requirement",
                    f"Use one of: {valid_values}",
                )

        # Validate answer cap fields if present (null means unlimited)
        for field_name in ("max_new_answers_per_agent", "max_new_answers_global"):
            if field_name not in orchestrator_config:
                continue
            value = orchestrator_config[field_name]
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                result.add_error(
                    f"'{field_name}' must be a positive integer or null, got {type(value).__name__}",
                    f"{location}.{field_name}",
                    "Use null (unlimited) or a positive integer like 1, 2, or 3",
                )

        if "checklist_require_gap_report" in orchestrator_config:
            checklist_report_gate = orchestrator_config["checklist_require_gap_report"]
            if not isinstance(checklist_report_gate, bool):
                result.add_error(
                    f"'checklist_require_gap_report' must be a boolean, got {type(checklist_report_gate).__name__}",
                    f"{location}.checklist_require_gap_report",
                    "Use true or false",
                )

        if "gap_report_mode" in orchestrator_config:
            gap_mode = orchestrator_config["gap_report_mode"]
            if gap_mode not in self.VALID_GAP_REPORT_MODES:
                valid_values = ", ".join(sorted(self.VALID_GAP_REPORT_MODES))
                result.add_error(
                    f"Invalid gap_report_mode: '{gap_mode}'",
                    f"{location}.gap_report_mode",
                    f"Use one of: {valid_values}",
                )

        # Validate fairness controls if present
        if "fairness_enabled" in orchestrator_config:
            fairness_enabled = orchestrator_config["fairness_enabled"]
            if not isinstance(fairness_enabled, bool):
                result.add_error(
                    f"'fairness_enabled' must be a boolean, got {type(fairness_enabled).__name__}",
                    f"{location}.fairness_enabled",
                    "Use true or false",
                )

        if "fairness_lead_cap_answers" in orchestrator_config:
            lead_cap = orchestrator_config["fairness_lead_cap_answers"]
            if isinstance(lead_cap, bool) or not isinstance(lead_cap, int) or lead_cap < 0:
                result.add_error(
                    f"'fairness_lead_cap_answers' must be a non-negative integer, got {type(lead_cap).__name__}",
                    f"{location}.fairness_lead_cap_answers",
                    "Use 0 (strict lockstep) or a positive integer like 1 or 2",
                )

        if "max_midstream_injections_per_round" in orchestrator_config:
            injection_cap = orchestrator_config["max_midstream_injections_per_round"]
            if isinstance(injection_cap, bool) or not isinstance(injection_cap, int) or injection_cap <= 0:
                result.add_error(
                    f"'max_midstream_injections_per_round' must be a positive integer, got {type(injection_cap).__name__}",
                    f"{location}.max_midstream_injections_per_round",
                    "Use a positive integer like 1 or 2",
                )

        # Validate timeout if present
        if "timeout" in orchestrator_config:
            timeout = orchestrator_config["timeout"]
            if not isinstance(timeout, dict):
                result.add_error(
                    f"'timeout' must be a dictionary, got {type(timeout).__name__}",
                    f"{location}.timeout",
                    "Use 'orchestrator_timeout_seconds: <number>'",
                )
            elif "orchestrator_timeout_seconds" in timeout:
                value = timeout["orchestrator_timeout_seconds"]
                if not isinstance(value, (int, float)) or value <= 0:
                    result.add_error(
                        "'orchestrator_timeout_seconds' must be a positive number",
                        f"{location}.timeout.orchestrator_timeout_seconds",
                        "Use a value like 1800 (30 minutes)",
                    )

        # Validate boolean fields
        boolean_fields = ["skip_coordination_rounds", "debug_final_answer"]
        for field_name in boolean_fields:
            if field_name in orchestrator_config:
                value = orchestrator_config[field_name]
                # debug_final_answer can be a string or boolean
                if field_name == "debug_final_answer":
                    if not isinstance(value, (bool, str)):
                        result.add_error(
                            f"'{field_name}' must be a boolean or string, got {type(value).__name__}",
                            f"{location}.{field_name}",
                            "Use 'true', 'false', or a string value",
                        )
                else:
                    if not isinstance(value, bool):
                        result.add_error(
                            f"'{field_name}' must be a boolean, got {type(value).__name__}",
                            f"{location}.{field_name}",
                            "Use 'true' or 'false'",
                        )

    def _validate_ui(self, ui_config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate UI configuration (Level 6)."""
        location = "ui"

        if not isinstance(ui_config, dict):
            result.add_error(
                f"UI must be a dictionary, got {type(ui_config).__name__}",
                location,
                "Use UI fields like display_type and logging_enabled",
            )
            return

        # Validate display_type if present
        if "display_type" in ui_config:
            display_type = ui_config["display_type"]
            if display_type not in self.VALID_DISPLAY_TYPES:
                valid_types = ", ".join(sorted(self.VALID_DISPLAY_TYPES))
                result.add_error(
                    f"Invalid display_type: '{display_type}'",
                    f"{location}.display_type",
                    f"Use one of: {valid_types}",
                )

        # Validate logging_enabled if present
        if "logging_enabled" in ui_config:
            logging_enabled = ui_config["logging_enabled"]
            if not isinstance(logging_enabled, bool):
                result.add_error(
                    f"'logging_enabled' must be a boolean, got {type(logging_enabled).__name__}",
                    f"{location}.logging_enabled",
                    "Use 'true' or 'false'",
                )

    def _validate_memory(self, memory_config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate memory configuration."""
        location = "memory"

        if not isinstance(memory_config, dict):
            result.add_error(
                f"Memory must be a dictionary, got {type(memory_config).__name__}",
                location,
                "Use memory fields like enabled, conversation_memory, persistent_memory, etc.",
            )
            return

        # Validate enabled if present
        if "enabled" in memory_config:
            enabled = memory_config["enabled"]
            if not isinstance(enabled, bool):
                result.add_error(
                    f"'enabled' must be a boolean, got {type(enabled).__name__}",
                    f"{location}.enabled",
                    "Use 'true' or 'false'",
                )

        # Validate conversation_memory if present
        if "conversation_memory" in memory_config:
            conv_memory = memory_config["conversation_memory"]
            if not isinstance(conv_memory, dict):
                result.add_error(
                    f"'conversation_memory' must be a dictionary, got {type(conv_memory).__name__}",
                    f"{location}.conversation_memory",
                    "Use 'enabled: true/false'",
                )
            elif "enabled" in conv_memory:
                enabled = conv_memory["enabled"]
                if not isinstance(enabled, bool):
                    result.add_error(
                        f"'enabled' must be a boolean, got {type(enabled).__name__}",
                        f"{location}.conversation_memory.enabled",
                        "Use 'true' or 'false'",
                    )

        # Validate persistent_memory if present
        if "persistent_memory" in memory_config:
            persist_memory = memory_config["persistent_memory"]
            if not isinstance(persist_memory, dict):
                result.add_error(
                    f"'persistent_memory' must be a dictionary, got {type(persist_memory).__name__}",
                    f"{location}.persistent_memory",
                    "Use fields like enabled, on_disk, vector_store, etc.",
                )
            else:
                # Validate boolean fields
                boolean_fields = ["enabled", "on_disk"]
                for field_name in boolean_fields:
                    if field_name in persist_memory:
                        value = persist_memory[field_name]
                        if not isinstance(value, bool):
                            result.add_error(
                                f"'{field_name}' must be a boolean, got {type(value).__name__}",
                                f"{location}.persistent_memory.{field_name}",
                                "Use 'true' or 'false'",
                            )

                # Validate vector_store if present
                if "vector_store" in persist_memory:
                    vector_store = persist_memory["vector_store"]
                    if not isinstance(vector_store, str):
                        result.add_error(
                            f"'vector_store' must be a string, got {type(vector_store).__name__}",
                            f"{location}.persistent_memory.vector_store",
                            "Use 'qdrant' or other vector store name",
                        )

                # Validate llm config if present
                if "llm" in persist_memory:
                    llm_config = persist_memory["llm"]
                    if not isinstance(llm_config, dict):
                        result.add_error(
                            f"'llm' must be a dictionary, got {type(llm_config).__name__}",
                            f"{location}.persistent_memory.llm",
                            "Use 'provider' and 'model' fields",
                        )
                    else:
                        # Check provider and model are strings
                        for field_name in ["provider", "model"]:
                            if field_name in llm_config:
                                value = llm_config[field_name]
                                if not isinstance(value, str):
                                    result.add_error(
                                        f"'{field_name}' must be a string, got {type(value).__name__}",
                                        f"{location}.persistent_memory.llm.{field_name}",
                                        "Use a string value",
                                    )

                # Validate embedding config if present
                if "embedding" in persist_memory:
                    embedding_config = persist_memory["embedding"]
                    if not isinstance(embedding_config, dict):
                        result.add_error(
                            f"'embedding' must be a dictionary, got {type(embedding_config).__name__}",
                            f"{location}.persistent_memory.embedding",
                            "Use 'provider' and 'model' fields",
                        )
                    else:
                        # Check provider and model are strings
                        for field_name in ["provider", "model"]:
                            if field_name in embedding_config:
                                value = embedding_config[field_name]
                                if not isinstance(value, str):
                                    result.add_error(
                                        f"'{field_name}' must be a string, got {type(value).__name__}",
                                        f"{location}.persistent_memory.embedding.{field_name}",
                                        "Use a string value",
                                    )

                # Validate qdrant config if present
                if "qdrant" in persist_memory:
                    qdrant_config = persist_memory["qdrant"]
                    if not isinstance(qdrant_config, dict):
                        result.add_error(
                            f"'qdrant' must be a dictionary, got {type(qdrant_config).__name__}",
                            f"{location}.persistent_memory.qdrant",
                            "Use 'mode', 'host', 'port' or 'path' fields",
                        )
                    else:
                        # Validate mode if present
                        if "mode" in qdrant_config:
                            mode = qdrant_config["mode"]
                            if mode not in ["server", "local"]:
                                result.add_error(
                                    f"Invalid qdrant mode: '{mode}'",
                                    f"{location}.persistent_memory.qdrant.mode",
                                    "Use 'server' or 'local'",
                                )

                        # Validate port if present (for server mode)
                        if "port" in qdrant_config:
                            port = qdrant_config["port"]
                            if not isinstance(port, int) or port <= 0 or port > 65535:
                                result.add_error(
                                    "'port' must be a valid port number (1-65535)",
                                    f"{location}.persistent_memory.qdrant.port",
                                    "Use a port number like 6333",
                                )

        # Validate compression if present
        if "compression" in memory_config:
            compression = memory_config["compression"]
            if not isinstance(compression, dict):
                result.add_error(
                    f"'compression' must be a dictionary, got {type(compression).__name__}",
                    f"{location}.compression",
                    "Use 'trigger_threshold' and 'target_ratio' fields",
                )
            else:
                # Validate threshold values (should be between 0 and 1)
                for field_name in ["trigger_threshold", "target_ratio"]:
                    if field_name in compression:
                        value = compression[field_name]
                        if not isinstance(value, (int, float)):
                            result.add_error(
                                f"'{field_name}' must be a number, got {type(value).__name__}",
                                f"{location}.compression.{field_name}",
                                "Use a decimal value between 0 and 1",
                            )
                        elif not 0 <= value <= 1:
                            result.add_error(
                                f"'{field_name}' must be between 0 and 1, got {value}",
                                f"{location}.compression.{field_name}",
                                "Use a decimal value between 0 and 1 (e.g., 0.75 for 75%)",
                            )

        # Validate retrieval if present
        if "retrieval" in memory_config:
            retrieval = memory_config["retrieval"]
            if not isinstance(retrieval, dict):
                result.add_error(
                    f"'retrieval' must be a dictionary, got {type(retrieval).__name__}",
                    f"{location}.retrieval",
                    "Use 'limit' and 'exclude_recent' fields",
                )
            else:
                # Validate limit if present
                if "limit" in retrieval:
                    limit = retrieval["limit"]
                    if not isinstance(limit, int) or limit <= 0:
                        result.add_error(
                            "'limit' must be a positive integer",
                            f"{location}.retrieval.limit",
                            "Use a value like 5 or 10",
                        )

                # Validate exclude_recent if present
                if "exclude_recent" in retrieval:
                    exclude_recent = retrieval["exclude_recent"]
                    if not isinstance(exclude_recent, bool):
                        result.add_error(
                            f"'exclude_recent' must be a boolean, got {type(exclude_recent).__name__}",
                            f"{location}.retrieval.exclude_recent",
                            "Use 'true' or 'false'",
                        )

    def _check_warnings(self, config: Dict[str, Any], result: ValidationResult) -> None:
        """Check for warnings (best practices, deprecations, etc.)."""
        # Get agents list (normalize single agent to list)
        if "agents" in config:
            agents = config["agents"]
            if not isinstance(agents, list):
                return
        elif "agent" in config:
            agents = [config["agent"]]
        else:
            return

        # Check each agent's backend for warnings
        for i, agent_config in enumerate(agents):
            if not isinstance(agent_config, dict) or "backend" not in agent_config:
                continue

            agent_location = f"agents[{i}]" if "agents" in config else "agent"
            backend_config = agent_config["backend"]

            if not isinstance(backend_config, dict):
                continue

            # Warning: Using both allowed_tools and exclude_tools
            if "allowed_tools" in backend_config and "exclude_tools" in backend_config:
                result.add_warning(
                    "Using both 'allowed_tools' and 'exclude_tools' can be confusing",
                    f"{agent_location}.backend",
                    "Prefer using only 'allowed_tools' (explicit allowlist) or 'exclude_tools' (denylist)",
                )

            # Warning: Check for deprecated fields (add as needed)
            # This is a placeholder for future deprecations

        # Cross-validation: checklist_gated + changedoc
        orchestrator_cfg = config.get("orchestrator", {})
        if isinstance(orchestrator_cfg, dict):
            voting_sens = orchestrator_cfg.get("voting_sensitivity", "")
            coordination = orchestrator_cfg.get("coordination", {})
            if isinstance(coordination, dict):
                changedoc_enabled = coordination.get("enable_changedoc", True)
                if voting_sens == "checklist_gated" and changedoc_enabled is False:
                    result.add_warning(
                        "checklist_gated voting works best with changedoc enabled for integrated quality assessment",
                        "orchestrator.voting_sensitivity",
                        "Set coordination.enable_changedoc: true or use gap_report_mode: 'separate'",
                    )

        # Cross-validation: decomposition mode
        if isinstance(orchestrator_cfg, dict):
            coordination_mode = orchestrator_cfg.get("coordination_mode")
            if coordination_mode == "decomposition":
                # Collect agent IDs
                agent_ids = []
                for agent_config in agents:
                    if isinstance(agent_config, dict) and "id" in agent_config:
                        agent_ids.append(agent_config["id"])

                # Validate presenter_agent references a valid agent
                presenter = orchestrator_cfg.get("presenter_agent")
                if presenter and presenter not in agent_ids:
                    result.add_error(
                        f"presenter_agent '{presenter}' does not match any agent ID",
                        "orchestrator.presenter_agent",
                        f"Use one of: {', '.join(agent_ids)}",
                    )

                # Warn if no subtasks defined (runtime decomposition subagent will be used)
                has_subtasks = any(isinstance(a, dict) and "subtask" in a for a in agents)
                if not has_subtasks:
                    result.add_warning(
                        "No explicit 'subtask' fields defined on agents in decomposition mode",
                        "orchestrator.coordination_mode",
                        "MassGen will spawn a decomposition subagent at runtime to assign subtasks. Add 'subtask' per agent for deterministic assignments.",
                    )
