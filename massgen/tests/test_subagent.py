"""
Tests for the Subagent feature.

Tests cover:
- SubagentConfig creation and serialization
- SubagentResult creation and serialization
- SubagentPointer tracking
- TaskPlan subagent tracking
"""

import pytest

from massgen.mcp_tools.planning.planning_dataclasses import TaskPlan
from massgen.subagent.models import (
    SubagentConfig,
    SubagentOrchestratorConfig,
    SubagentPointer,
    SubagentResult,
    SubagentState,
)


class TestSubagentConfig:
    """Tests for SubagentConfig dataclass."""

    def test_create_with_defaults(self):
        """Test creating config with default values."""
        config = SubagentConfig.create(
            task="Test task",
            parent_agent_id="parent_1",
        )
        assert config.task == "Test task"
        assert config.parent_agent_id == "parent_1"
        assert config.id.startswith("sub_")
        assert config.timeout_seconds == 300
        assert config.model is None
        assert config.context_files == []

    def test_create_with_custom_id(self):
        """Test creating config with custom ID."""
        config = SubagentConfig.create(
            task="Custom task",
            parent_agent_id="parent_1",
            subagent_id="custom_id",
        )
        assert config.id == "custom_id"

    def test_create_with_all_options(self):
        """Test creating config with all options specified."""
        config = SubagentConfig.create(
            task="Full config task",
            parent_agent_id="parent_1",
            subagent_id="full_config",
            model="gpt-4",
            timeout_seconds=600,
            context_files=["src/main.py", "README.md"],
            system_prompt="You are a test agent",
            metadata={"key": "value"},
        )
        assert config.id == "full_config"
        assert config.model == "gpt-4"
        assert config.timeout_seconds == 600
        assert config.context_files == ["src/main.py", "README.md"]
        assert config.system_prompt == "You are a test agent"
        assert config.metadata == {"key": "value"}

    def test_to_dict(self):
        """Test serialization to dictionary."""
        config = SubagentConfig.create(
            task="Test task",
            parent_agent_id="parent_1",
            subagent_id="test_id",
        )
        data = config.to_dict()
        assert data["id"] == "test_id"
        assert data["task"] == "Test task"
        assert data["parent_agent_id"] == "parent_1"
        assert "created_at" in data

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        config = SubagentConfig.create(
            task="Test task",
            parent_agent_id="parent_1",
            subagent_id="test_id",
        )
        data = config.to_dict()
        restored = SubagentConfig.from_dict(data)
        assert restored.id == config.id
        assert restored.task == config.task
        assert restored.parent_agent_id == config.parent_agent_id


class TestSubagentResult:
    """Tests for SubagentResult dataclass."""

    def test_create_success(self):
        """Test creating a successful result."""
        result = SubagentResult.create_success(
            subagent_id="test_sub",
            answer="Task completed successfully",
            workspace_path="/workspace/subagents/test_sub",
            execution_time_seconds=45.2,
        )
        assert result.success is True
        assert result.status == "completed"
        assert result.answer == "Task completed successfully"
        assert result.execution_time_seconds == 45.2
        assert result.error is None

    def test_create_timeout(self):
        """Test creating a timeout result."""
        result = SubagentResult.create_timeout(
            subagent_id="test_sub",
            workspace_path="/workspace",
            timeout_seconds=300.0,
        )
        assert result.success is False
        assert result.status == "timeout"
        assert result.answer is None
        assert "timeout" in result.error.lower()

    def test_create_error(self):
        """Test creating an error result."""
        result = SubagentResult.create_error(
            subagent_id="test_sub",
            error="Something went wrong",
        )
        assert result.success is False
        assert result.status == "error"
        assert result.error == "Something went wrong"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        result = SubagentResult.create_success(
            subagent_id="test_sub",
            answer="Done",
            workspace_path="/workspace",
            execution_time_seconds=10.0,
        )
        data = result.to_dict()
        assert data["subagent_id"] == "test_sub"
        assert data["success"] is True
        assert data["status"] == "completed"
        assert "workspace" in data

    def test_create_success_with_token_usage(self):
        """Test creating a successful result with token usage and cost tracking."""
        token_usage = {
            "input_tokens": 150,
            "output_tokens": 75,
            "reasoning_tokens": 0,
            "cached_input_tokens": 50,
            "estimated_cost": 0.000325,
        }
        result = SubagentResult.create_success(
            subagent_id="test_sub",
            answer="Task completed",
            workspace_path="/workspace",
            execution_time_seconds=12.5,
            token_usage=token_usage,
        )
        assert result.success is True
        assert result.token_usage == token_usage
        assert result.token_usage["input_tokens"] == 150
        assert result.token_usage["output_tokens"] == 75
        assert result.token_usage["estimated_cost"] == 0.000325

    def test_token_usage_in_to_dict(self):
        """Test that token_usage is included in serialization."""
        token_usage = {
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost": 0.0001,
        }
        result = SubagentResult.create_success(
            subagent_id="test_sub",
            answer="Done",
            workspace_path="/workspace",
            execution_time_seconds=5.0,
            token_usage=token_usage,
        )
        data = result.to_dict()
        assert "token_usage" in data
        assert data["token_usage"]["input_tokens"] == 100
        assert data["token_usage"]["estimated_cost"] == 0.0001

    def test_token_usage_from_dict(self):
        """Test that token_usage is preserved through serialization round-trip."""
        token_usage = {
            "input_tokens": 200,
            "output_tokens": 100,
            "estimated_cost": 0.0005,
        }
        original = SubagentResult.create_success(
            subagent_id="test_sub",
            answer="Done",
            workspace_path="/workspace",
            execution_time_seconds=8.0,
            token_usage=token_usage,
        )
        data = original.to_dict()
        restored = SubagentResult.from_dict(data)
        assert restored.token_usage == token_usage
        assert restored.token_usage["estimated_cost"] == 0.0005


class TestSubagentPointer:
    """Tests for SubagentPointer dataclass."""

    def test_create_pointer(self):
        """Test creating a subagent pointer."""
        pointer = SubagentPointer(
            id="test_sub",
            task="Test task",
            workspace="/workspace/subagents/test_sub",
            status="running",
        )
        assert pointer.id == "test_sub"
        assert pointer.task == "Test task"
        assert pointer.status == "running"
        assert pointer.completed_at is None

    def test_mark_completed_success(self):
        """Test marking pointer completed with success."""
        pointer = SubagentPointer(
            id="test_sub",
            task="Test task",
            workspace="/workspace",
            status="running",
        )
        result = SubagentResult.create_success(
            subagent_id="test_sub",
            answer="Completed successfully with detailed output",
            workspace_path="/workspace",
            execution_time_seconds=10.0,
        )
        pointer.mark_completed(result)
        assert pointer.status == "completed"
        assert pointer.completed_at is not None
        assert pointer.result_summary is not None

    def test_mark_completed_failure(self):
        """Test marking pointer completed with failure."""
        pointer = SubagentPointer(
            id="test_sub",
            task="Test task",
            workspace="/workspace",
            status="running",
        )
        result = SubagentResult.create_error(
            subagent_id="test_sub",
            error="Failed",
        )
        pointer.mark_completed(result)
        assert pointer.status == "failed"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        pointer = SubagentPointer(
            id="test_sub",
            task="Test task",
            workspace="/workspace",
            status="running",
        )
        data = pointer.to_dict()
        assert data["id"] == "test_sub"
        assert data["task"] == "Test task"
        assert data["status"] == "running"


class TestTaskPlanSubagentTracking:
    """Tests for TaskPlan subagent tracking."""

    def test_add_subagent(self):
        """Test adding a subagent to task plan."""
        plan = TaskPlan(agent_id="test_agent")
        plan.add_subagent(
            subagent_id="sub_1",
            task="Research OAuth",
            workspace="/workspace/subagents/sub_1",
        )
        assert "sub_1" in plan.subagents
        assert plan.subagents["sub_1"]["task"] == "Research OAuth"
        assert plan.subagents["sub_1"]["status"] == "running"

    def test_update_subagent_status(self):
        """Test updating subagent status."""
        plan = TaskPlan(agent_id="test_agent")
        plan.add_subagent("sub_1", "Test task", "/workspace")
        plan.update_subagent_status("sub_1", "completed", "Task done")
        assert plan.subagents["sub_1"]["status"] == "completed"
        assert plan.subagents["sub_1"]["result_summary"] == "Task done"
        assert plan.subagents["sub_1"]["completed_at"] is not None

    def test_get_subagent(self):
        """Test getting a subagent by ID."""
        plan = TaskPlan(agent_id="test_agent")
        plan.add_subagent("sub_1", "Test task", "/workspace")
        sub = plan.get_subagent("sub_1")
        assert sub is not None
        assert sub["id"] == "sub_1"

    def test_get_subagent_not_found(self):
        """Test getting a non-existent subagent."""
        plan = TaskPlan(agent_id="test_agent")
        sub = plan.get_subagent("nonexistent")
        assert sub is None

    def test_to_dict_with_subagents(self):
        """Test serialization includes subagents."""
        plan = TaskPlan(agent_id="test_agent")
        plan.add_subagent("sub_1", "Test task", "/workspace")
        data = plan.to_dict()
        assert "subagents" in data
        assert "sub_1" in data["subagents"]

    def test_from_dict_with_subagents(self):
        """Test deserialization preserves subagents."""
        plan = TaskPlan(agent_id="test_agent")
        plan.add_subagent("sub_1", "Test task", "/workspace")
        data = plan.to_dict()
        restored = TaskPlan.from_dict(data)
        assert "sub_1" in restored.subagents
        assert restored.subagents["sub_1"]["task"] == "Test task"


class TestSubagentState:
    """Tests for SubagentState dataclass."""

    def test_create_state(self):
        """Test creating a subagent state."""
        config = SubagentConfig.create(
            task="Test task",
            parent_agent_id="parent_1",
        )
        state = SubagentState(config=config)
        assert state.status == "pending"
        assert state.result is None

    def test_to_dict(self):
        """Test serialization to dictionary."""
        config = SubagentConfig.create(
            task="Test task",
            parent_agent_id="parent_1",
        )
        state = SubagentState(config=config, status="running")
        data = state.to_dict()
        assert data["status"] == "running"
        assert "config" in data


class TestSubagentOrchestratorConfig:
    """Tests for SubagentOrchestratorConfig dataclass."""

    def test_default_values(self):
        """Test creating config with default values."""
        config = SubagentOrchestratorConfig()
        assert config.enabled is False
        assert config.num_agents == 1  # Defaults to 1 when agents list is empty
        assert config.agents == []
        assert config.coordination == {}
        assert config.parse_at_references is False

    def test_enabled_with_custom_agents(self):
        """Test creating config with custom agent configs."""
        agents = [
            {"backend": {"type": "openai", "model": "gpt-4-turbo"}},
            {"backend": {"type": "anthropic", "model": "claude-sonnet-4-20250514"}},
            {"id": "custom_agent", "backend": {"model": "gpt-4o"}},
        ]
        config = SubagentOrchestratorConfig(
            enabled=True,
            agents=agents,
            coordination={"broadcast": {"type": "always"}},
        )
        assert config.enabled is True
        assert config.num_agents == 3
        assert len(config.agents) == 3
        assert config.coordination == {"broadcast": {"type": "always"}}

    def test_num_agents_property(self):
        """Test that num_agents property returns correct count."""
        # Empty agents defaults to 1
        config = SubagentOrchestratorConfig(enabled=True)
        assert config.num_agents == 1

        # With agents list
        config = SubagentOrchestratorConfig(
            enabled=True,
            agents=[{"backend": {"model": "gpt-4o"}}] * 5,
        )
        assert config.num_agents == 5

    def test_validation_max_agents(self):
        """Test that agents list cannot exceed 10."""
        with pytest.raises(ValueError, match="Cannot have more than 10 agents"):
            SubagentOrchestratorConfig(enabled=True, agents=[{"backend": {}}] * 11)

    def test_from_dict(self):
        """Test creating config from dictionary (YAML parsing)."""
        data = {
            "enabled": True,
            "agents": [
                {"backend": {"type": "openai", "model": "gpt-4o-mini"}},
                {"backend": {"type": "anthropic", "model": "claude-3-sonnet"}},
            ],
            "coordination": {"voting": {"enabled": True}},
            "parse_at_references": False,
        }
        config = SubagentOrchestratorConfig.from_dict(data)
        assert config.enabled is True
        assert config.num_agents == 2
        assert len(config.agents) == 2
        assert config.agents[0]["backend"]["model"] == "gpt-4o-mini"
        assert config.coordination == {"voting": {"enabled": True}}
        assert config.parse_at_references is False

    def test_from_dict_with_defaults(self):
        """Test from_dict uses defaults for missing keys."""
        config = SubagentOrchestratorConfig.from_dict({})
        assert config.enabled is False
        assert config.num_agents == 1
        assert config.agents == []
        assert config.coordination == {}

    def test_to_dict(self):
        """Test serialization to dictionary."""
        agents = [
            {"backend": {"type": "openai", "model": "gpt-4"}},
            {"id": "agent_2", "backend": {"model": "gpt-4o-mini"}},
        ]
        config = SubagentOrchestratorConfig(
            enabled=True,
            agents=agents,
            coordination={"planning": True},
            parse_at_references=False,
        )
        data = config.to_dict()
        assert data["enabled"] is True
        assert len(data["agents"]) == 2
        assert data["coordination"] == {"planning": True}
        assert data["parse_at_references"] is False

    def test_roundtrip_serialization(self):
        """Test that config survives serialization round-trip."""
        agents = [
            {"backend": {"type": "openai", "model": "gpt-4o"}},
            {"backend": {"type": "anthropic", "model": "claude-sonnet-4-20250514"}},
            {"id": "custom", "backend": {"model": "gpt-4o-mini"}},
        ]
        original = SubagentOrchestratorConfig(
            enabled=True,
            agents=agents,
            coordination={"broadcast": {"type": "always"}},
            parse_at_references=False,
        )
        data = original.to_dict()
        restored = SubagentOrchestratorConfig.from_dict(data)
        assert restored.enabled == original.enabled
        assert restored.num_agents == original.num_agents
        assert len(restored.agents) == len(original.agents)
        assert restored.coordination == original.coordination
        assert restored.parse_at_references == original.parse_at_references

    def test_get_agent_config(self):
        """Test get_agent_config method."""
        agents = [
            {"backend": {"model": "gpt-4o"}},
            {"id": "my_agent", "backend": {"type": "anthropic", "model": "claude"}},
        ]
        config = SubagentOrchestratorConfig(enabled=True, agents=agents)

        # First agent - no id, should auto-generate
        agent0 = config.get_agent_config(0, "sub_123")
        assert agent0["id"] == "sub_123_agent_1"
        assert agent0["backend"]["model"] == "gpt-4o"

        # Second agent - has custom id
        agent1 = config.get_agent_config(1, "sub_123")
        assert agent1["id"] == "my_agent"
        assert agent1["backend"]["type"] == "anthropic"

        # Out of bounds - returns empty dict
        agent2 = config.get_agent_config(2, "sub_123")
        assert agent2 == {}

    def test_empty_coordination(self):
        """Test handling of empty/None coordination."""
        config = SubagentOrchestratorConfig(enabled=True)
        data = config.to_dict()
        assert data["coordination"] == {}
        assert config.coordination == {}

    def test_blocking_ignored_for_backwards_compat(self):
        """Test that blocking key in config is ignored (backwards compatibility)."""
        # Old configs with blocking: true/false should still parse without error
        data = {"enabled": True, "blocking": False}
        config = SubagentOrchestratorConfig.from_dict(data)
        assert config.enabled is True
        # blocking is no longer a field, just silently ignored
        assert not hasattr(config, "blocking") or "blocking" not in config.to_dict()
