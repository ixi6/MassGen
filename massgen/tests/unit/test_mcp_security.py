"""Unit tests for MCP security validation helpers."""

import pytest

from massgen.mcp_tools.security import prepare_command, validate_environment_variables


def test_path_traversal_blocked():
    """Commands with traversal patterns should be rejected."""
    with pytest.raises(ValueError):
        prepare_command("../bin/python -m pytest")


def test_allowlisted_operation_permitted():
    """Allowlist mode should permit explicitly allowed variables."""
    env = {"SAFE_TOKEN": "abc123"}
    validated = validate_environment_variables(
        env,
        mode="allowlist",
        allowed_vars={"SAFE_TOKEN"},
    )
    assert validated == env


def test_allowlist_blocks_unlisted_environment_variable():
    """Allowlist mode should reject variables not on the allowlist."""
    with pytest.raises(ValueError):
        validate_environment_variables(
            {"UNLISTED_VAR": "value"},
            mode="allowlist",
            allowed_vars={"SAFE_TOKEN"},
        )
