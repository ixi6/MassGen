"""End-to-end integration tests for the subagent message injection pipeline.

Tests the full flow: SubagentManager writes to inbox -> RuntimeInboxPoller reads ->
HumanInputHook delivers to correct agent(s).
"""

from __future__ import annotations

import json

import pytest

from massgen.mcp_tools.hooks import HumanInputHook, RuntimeInboxPoller
from massgen.subagent.manager import SubagentManager
from massgen.subagent.models import SubagentConfig, SubagentState


def _make_manager(tmp_path):
    """Create a SubagentManager rooted at tmp_path."""
    workspace = tmp_path / "parent_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return SubagentManager(
        parent_workspace=str(workspace),
        parent_agent_id="parent-agent",
        orchestrator_id="test-orch",
        parent_agent_configs=[],
    )


def _register_running_subagent(manager, subagent_id, workspace_path):
    """Register a fake running subagent in the manager."""
    config = SubagentConfig(
        id=subagent_id,
        task="test task",
        parent_agent_id="parent-agent",
    )
    state = SubagentState(
        config=config,
        status="running",
        workspace_path=str(workspace_path),
    )
    manager._subagents[subagent_id] = state


class TestTargetedMessageE2E:
    """Manager writes a targeted message -> Poller reads -> Hook delivers only to target."""

    def test_targeted_message_reaches_correct_agent(self, tmp_path):
        # --- Write side: SubagentManager ---
        manager = _make_manager(tmp_path)
        sub_workspace = tmp_path / "sub_workspace"
        sub_workspace.mkdir(parents=True)
        _register_running_subagent(manager, "sub1", sub_workspace)

        success, error = manager.send_message_to_subagent(
            "sub1",
            "focus on edge cases",
            target_agents=["agent_a"],
        )
        assert success is True
        assert error is None

        # Verify file was written
        inbox_dir = sub_workspace / ".massgen" / "runtime_inbox"
        msg_files = list(inbox_dir.glob("msg_*.json"))
        assert len(msg_files) == 1

        raw = json.loads(msg_files[0].read_text())
        assert raw["content"] == "focus on edge cases"
        assert raw["target_agents"] == ["agent_a"]

        # --- Read side: RuntimeInboxPoller ---
        poller = RuntimeInboxPoller(inbox_dir=inbox_dir, min_poll_interval=0.0)
        messages = poller.poll()
        assert len(messages) == 1
        assert messages[0]["content"] == "focus on edge cases"
        assert messages[0]["target_agents"] == ["agent_a"]

        # Files consumed
        assert list(inbox_dir.glob("msg_*.json")) == []

        # --- Delivery: HumanInputHook ---
        hook = HumanInputHook()
        for m in messages:
            hook.set_pending_input(m["content"], target_agents=m["target_agents"])

        assert hook.has_pending_input_for_agent("agent_a") is True
        assert hook.has_pending_input_for_agent("agent_b") is False

    @pytest.mark.asyncio
    async def test_targeted_message_injects_only_to_target_agent(self, tmp_path):
        """Full pipeline: write -> poll -> queue -> execute hook for both agents."""
        manager = _make_manager(tmp_path)
        sub_workspace = tmp_path / "sub_workspace"
        sub_workspace.mkdir(parents=True)
        _register_running_subagent(manager, "sub1", sub_workspace)

        manager.send_message_to_subagent(
            "sub1",
            "check error handling",
            target_agents=["agent_a"],
        )

        inbox_dir = sub_workspace / ".massgen" / "runtime_inbox"
        poller = RuntimeInboxPoller(inbox_dir=inbox_dir, min_poll_interval=0.0)
        messages = poller.poll()

        hook = HumanInputHook()
        for m in messages:
            hook.set_pending_input(m["content"], target_agents=m["target_agents"])

        # agent_a should receive
        result_a = await hook.execute(
            "some_tool",
            "{}",
            context={"agent_id": "agent_a"},
        )
        assert result_a.inject is not None
        assert "check error handling" in result_a.inject["content"]

        # agent_b should NOT receive
        result_b = await hook.execute(
            "some_tool",
            "{}",
            context={"agent_id": "agent_b"},
        )
        assert result_b.inject is None


class TestBroadcastMessageE2E:
    """Manager writes a broadcast message -> all agents receive."""

    @pytest.mark.asyncio
    async def test_broadcast_message_reaches_all_agents(self, tmp_path):
        manager = _make_manager(tmp_path)
        sub_workspace = tmp_path / "sub_workspace"
        sub_workspace.mkdir(parents=True)
        _register_running_subagent(manager, "sub1", sub_workspace)

        manager.send_message_to_subagent(
            "sub1",
            "everyone pivot to plan B",
            target_agents=None,
        )

        inbox_dir = sub_workspace / ".massgen" / "runtime_inbox"
        poller = RuntimeInboxPoller(inbox_dir=inbox_dir, min_poll_interval=0.0)
        messages = poller.poll()

        assert len(messages) == 1
        assert messages[0]["target_agents"] is None

        hook = HumanInputHook()
        for m in messages:
            hook.set_pending_input(m["content"], target_agents=m["target_agents"])

        # Both agents should receive
        result_a = await hook.execute(
            "some_tool",
            "{}",
            context={"agent_id": "agent_a"},
        )
        assert result_a.inject is not None
        assert "everyone pivot to plan B" in result_a.inject["content"]

        result_b = await hook.execute(
            "some_tool",
            "{}",
            context={"agent_id": "agent_b"},
        )
        assert result_b.inject is not None
        assert "everyone pivot to plan B" in result_b.inject["content"]


class TestMultipleMessagesE2E:
    """Multiple messages through the pipeline with mixed targeting."""

    @pytest.mark.asyncio
    async def test_multiple_messages_targeted_and_broadcast(self, tmp_path):
        manager = _make_manager(tmp_path)
        sub_workspace = tmp_path / "sub_workspace"
        sub_workspace.mkdir(parents=True)
        _register_running_subagent(manager, "sub1", sub_workspace)

        # Send targeted message first, then broadcast
        manager.send_message_to_subagent(
            "sub1",
            "agent_a only: check tests",
            target_agents=["agent_a"],
        )
        manager.send_message_to_subagent(
            "sub1",
            "everyone: update status",
            target_agents=None,
        )

        inbox_dir = sub_workspace / ".massgen" / "runtime_inbox"
        poller = RuntimeInboxPoller(inbox_dir=inbox_dir, min_poll_interval=0.0)
        messages = poller.poll()
        assert len(messages) == 2

        hook = HumanInputHook()
        for m in messages:
            hook.set_pending_input(m["content"], target_agents=m["target_agents"])

        # agent_a: should get both messages
        result_a = await hook.execute(
            "some_tool",
            "{}",
            context={"agent_id": "agent_a"},
        )
        assert result_a.inject is not None
        assert "agent_a only: check tests" in result_a.inject["content"]
        assert "everyone: update status" in result_a.inject["content"]

        # agent_b: should get only the broadcast
        result_b = await hook.execute(
            "some_tool",
            "{}",
            context={"agent_id": "agent_b"},
        )
        assert result_b.inject is not None
        assert "agent_a only: check tests" not in result_b.inject["content"]
        assert "everyone: update status" in result_b.inject["content"]

    def test_inbox_empty_after_poll(self, tmp_path):
        """After polling, all message files are consumed."""
        manager = _make_manager(tmp_path)
        sub_workspace = tmp_path / "sub_workspace"
        sub_workspace.mkdir(parents=True)
        _register_running_subagent(manager, "sub1", sub_workspace)

        for i in range(3):
            manager.send_message_to_subagent("sub1", f"msg {i}")

        inbox_dir = sub_workspace / ".massgen" / "runtime_inbox"
        assert len(list(inbox_dir.glob("msg_*.json"))) == 3

        poller = RuntimeInboxPoller(inbox_dir=inbox_dir, min_poll_interval=0.0)
        messages = poller.poll()
        assert len(messages) == 3
        assert list(inbox_dir.glob("msg_*.json")) == []


class TestEdgeCases:
    """Edge cases in the pipeline."""

    def test_message_to_nonexistent_subagent_fails(self, tmp_path):
        manager = _make_manager(tmp_path)
        success, error = manager.send_message_to_subagent("nonexistent", "hello")
        assert success is False
        assert "not found" in error

    def test_message_to_non_running_subagent_fails(self, tmp_path):
        manager = _make_manager(tmp_path)
        sub_workspace = tmp_path / "sub_workspace"
        sub_workspace.mkdir(parents=True)

        config = SubagentConfig(
            id="sub1",
            task="test",
            parent_agent_id="parent-agent",
        )
        state = SubagentState(
            config=config,
            status="completed",
            workspace_path=str(sub_workspace),
        )
        manager._subagents["sub1"] = state

        success, error = manager.send_message_to_subagent("sub1", "hello")
        assert success is False
        assert "completed" in error

    def test_message_to_subagent_with_answer_file_fails(self, tmp_path):
        """Running subagent with answer.txt (race condition) -> rejected."""
        manager = _make_manager(tmp_path)
        sub_workspace = tmp_path / "sub_workspace"
        sub_workspace.mkdir(parents=True)
        _register_running_subagent(manager, "sub1", sub_workspace)

        # Simulate subprocess having written answer.txt (subagent effectively done)
        (sub_workspace / "answer.txt").write_text("Final answer from subagent")

        success, error = manager.send_message_to_subagent("sub1", "too late message")
        assert success is False
        assert "already completed" in error

        # Verify no message file was written to inbox
        inbox_dir = sub_workspace / ".massgen" / "runtime_inbox"
        if inbox_dir.exists():
            assert list(inbox_dir.glob("msg_*.json")) == []

    def test_poller_handles_empty_inbox(self, tmp_path):
        inbox_dir = tmp_path / ".massgen" / "runtime_inbox"
        inbox_dir.mkdir(parents=True)
        poller = RuntimeInboxPoller(inbox_dir=inbox_dir, min_poll_interval=0.0)
        assert poller.poll() == []

    def test_poller_handles_nonexistent_inbox(self, tmp_path):
        inbox_dir = tmp_path / ".massgen" / "runtime_inbox"
        # Don't create it
        poller = RuntimeInboxPoller(inbox_dir=inbox_dir, min_poll_interval=0.0)
        assert poller.poll() == []
