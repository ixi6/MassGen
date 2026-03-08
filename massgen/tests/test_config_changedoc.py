"""Tests for changedoc configuration.

Tests cover:
- CoordinationConfig.enable_changedoc field defaults
- Config validator accepts enable_changedoc boolean
"""

from massgen.agent_config import CoordinationConfig
from massgen.config_validator import ConfigValidator


class TestCoordinationConfigChangedoc:
    """Tests for enable_changedoc in CoordinationConfig."""

    def test_defaults_to_true(self):
        """enable_changedoc defaults to True."""
        config = CoordinationConfig()
        assert config.enable_changedoc is True

    def test_can_set_to_true(self):
        """enable_changedoc can be set to True."""
        config = CoordinationConfig(enable_changedoc=True)
        assert config.enable_changedoc is True


class TestConfigValidatorChangedoc:
    """Tests for config validator accepting enable_changedoc."""

    def test_valid_changedoc_config(self):
        """Config with enable_changedoc: true passes validation."""
        config = {
            "agents": [
                {
                    "id": "agent-1",
                    "backend": {"type": "openai", "model": "gpt-4o"},
                },
            ],
            "orchestrator": {
                "coordination": {
                    "enable_planning_mode": True,
                    "enable_changedoc": True,
                },
            },
        }
        validator = ConfigValidator()
        result = validator.validate_config(config)
        assert result.is_valid()
        assert not result.has_errors()

    def test_invalid_changedoc_type(self):
        """Config with non-boolean enable_changedoc fails validation."""
        config = {
            "agents": [
                {
                    "id": "agent-1",
                    "backend": {"type": "openai", "model": "gpt-4o"},
                },
            ],
            "orchestrator": {
                "coordination": {
                    "enable_changedoc": "yes",
                },
            },
        }
        validator = ConfigValidator()
        result = validator.validate_config(config)
        assert result.has_errors()
        assert any("enable_changedoc" in e.message for e in result.errors)
