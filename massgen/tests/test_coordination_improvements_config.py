"""Tests for wiring and validation of coordination.improvements config."""

from massgen.cli import _parse_coordination_config
from massgen.config_validator import ConfigValidator


def test_parse_coordination_config_passes_improvements():
    """coordination.improvements should be preserved on parsed config."""
    improvements = {
        "min_transformative": 1,
        "min_structural": 0,
        "min_non_incremental": 2,
    }
    config = _parse_coordination_config({"improvements": improvements})
    assert config.improvements == improvements


def test_parse_coordination_config_defaults_improvements_to_empty_dict():
    """coordination.improvements should default to {} when omitted."""
    config = _parse_coordination_config({})
    assert config.improvements == {}


def test_config_validator_accepts_valid_coordination_improvements():
    """Validator should accept a valid improvements gate object."""
    config = {
        "agents": [
            {
                "id": "agent_a",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
        ],
        "orchestrator": {
            "coordination": {
                "improvements": {
                    "min_transformative": 1,
                    "min_structural": 0,
                    "min_non_incremental": 1,
                },
            },
        },
    }

    validator = ConfigValidator()
    result = validator.validate_config(config)
    assert not result.has_errors()


def test_config_validator_rejects_non_dict_coordination_improvements():
    """Validator should reject non-dict improvements values."""
    config = {
        "agents": [
            {
                "id": "agent_a",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
        ],
        "orchestrator": {
            "coordination": {
                "improvements": "required",
            },
        },
    }

    validator = ConfigValidator()
    result = validator.validate_config(config)
    assert result.has_errors()
    assert any("improvements" in error.location for error in result.errors)


def test_config_validator_rejects_negative_coordination_improvements_values():
    """Validator should reject negative minimums."""
    config = {
        "agents": [
            {
                "id": "agent_a",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
        ],
        "orchestrator": {
            "coordination": {
                "improvements": {
                    "min_transformative": -1,
                },
            },
        },
    }

    validator = ConfigValidator()
    result = validator.validate_config(config)
    assert result.has_errors()
    assert any("improvements.min_transformative" in error.location for error in result.errors)
