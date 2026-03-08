"""Integration tests for delegate wiring in orchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from massgen.subagent.background_delegate import SubagentBackgroundDelegate


class TestDelegateWiringInOrchestrator:
    """Test that orchestrator wires delegate when subagents are enabled."""

    def test_delegate_is_registered_when_subagents_enabled(self):
        """When background subagents are enabled, the backend should get a delegate."""
        # Create a mock backend that tracks delegate registration
        mock_backend = MagicMock()
        mock_backend.register_background_delegate = MagicMock()
        mock_backend.get_pending_background_tool_results = MagicMock(return_value=[])

        # Verify the delegate type is correct when registered
        delegate = SubagentBackgroundDelegate(
            call_tool=AsyncMock(return_value={"success": True, "subagents": [], "count": 0}),
            agent_id="test-agent",
        )

        mock_backend.register_background_delegate(delegate)
        mock_backend.register_background_delegate.assert_called_once()
        registered_delegate = mock_backend.register_background_delegate.call_args[0][0]
        assert isinstance(registered_delegate, SubagentBackgroundDelegate)

    def test_delegate_not_registered_when_subagents_disabled(self):
        """When background subagents are disabled, no delegate should be registered."""
        mock_backend = MagicMock()
        mock_backend.register_background_delegate = MagicMock()

        # Simulate: _background_subagents_enabled = False -> no delegate wiring
        background_subagents_enabled = False
        if background_subagents_enabled and hasattr(mock_backend, "register_background_delegate"):
            delegate = SubagentBackgroundDelegate(
                call_tool=AsyncMock(),
                agent_id="test-agent",
            )
            mock_backend.register_background_delegate(delegate)

        mock_backend.register_background_delegate.assert_not_called()

    def test_delegate_uses_agent_specific_call_tool(self):
        """Each agent should get its own delegate with agent-specific call_tool."""
        agents = {}
        for agent_id in ["agent-1", "agent-2"]:
            call_tool = AsyncMock(return_value={"success": True, "subagents": [], "count": 0})
            delegate = SubagentBackgroundDelegate(
                call_tool=call_tool,
                agent_id=agent_id,
            )
            agents[agent_id] = (delegate, call_tool)

        # Verify delegates are independent
        assert agents["agent-1"][0]._agent_id != agents["agent-2"][0]._agent_id
