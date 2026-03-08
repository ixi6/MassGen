"""Smoke tests for shared mock fixtures in conftest.py."""

import pytest


@pytest.mark.asyncio
async def test_mock_backend_streams_content(mock_backend):
    backend = mock_backend(responses=["hello"])
    chunks = []
    async for chunk in backend.stream_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
    ):
        chunks.append(chunk)

    assert [c.type for c in chunks] == ["content", "complete_message", "done"]
    assert chunks[0].content == "hello"
    assert chunks[1].complete_message["content"] == "hello"


def test_mock_orchestrator_factory_creates_agents(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=3)
    assert sorted(orchestrator.agents.keys()) == ["agent_a", "agent_b", "agent_c"]
