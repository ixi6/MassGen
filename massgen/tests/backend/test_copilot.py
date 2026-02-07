# -*- coding: utf-8 -*-
"""Unit tests for CopilotBackend."""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

# Mock copilot module for imports
import sys
mock_copilot = MagicMock()
mock_copilot.types = MagicMock()
mock_copilot.generated.session_events = MagicMock()
sys.modules["copilot"] = mock_copilot
sys.modules["github_copilot_sdk"] = mock_copilot # Alias if needed

from massgen.backend.copilot import CopilotBackend

@pytest.fixture
def mock_copilot_client():
    with patch("massgen.backend.copilot.CopilotClient") as mock:
        client_instance = AsyncMock()
        mock.return_value = client_instance
        yield client_instance

@pytest.fixture
def copilot_backend(mock_copilot_client):
    # Ensure SDK availability check passes
    with patch("massgen.backend.copilot.COPILOT_SDK_AVAILABLE", True):
        backend = CopilotBackend(api_key="dummy")
        backend.client = mock_copilot_client
        return backend

@pytest.mark.asyncio
async def test_initialization(copilot_backend):
    assert copilot_backend.get_provider_name() == "copilot"
    assert copilot_backend.client is not None

@pytest.mark.asyncio
async def test_stream_with_tools_create_session(copilot_backend):
    # Setup mocks
    mock_session = AsyncMock()
    mock_session.session_id = "sess-123"
    copilot_backend.client.create_session.return_value = mock_session
    copilot_backend.client.start = AsyncMock()
    
    # Mock session.on (subscription)
    mock_session.on = MagicMock(return_value=lambda: None)
    
    # Mock event queue behavior
    # We need to simulate events being put into the queue
    # The backend creates its own queue and subscription callback
    # We can capture the callback passed to session.on
    
    messages = [{"role": "user", "content": "Hello"}]
    tools = []
    
    # Run the generator
    # We need to inject events while the generator runs
    # This requires running the generator in a task or carefully structuring the test
    
    # Alternatively, we can mock asyncio.Queue inside the backend?
    # Or start a background task that calls the callback
    
    async def event_feeder(callback):
        # Allow time for send() to be called
        await asyncio.sleep(0.1)
        
        # content event
        event_content = MagicMock()
        event_content.type.value = "assistant.message_delta" # Enum simulation
        event_content.data.delta_content = "Hello "
        callback(event_content)

        event_content_2 = MagicMock()
        event_content_2.type.value = "assistant.message_delta"
        event_content_2.data.delta_content = "World"
        callback(event_content_2)
        
        # finish event
        event_idle = MagicMock()
        event_idle.type.value = "session.idle"
        callback(event_idle)

    # Capture callback
    captured_callback = None
    def side_effect_on(cb):
        nonlocal captured_callback
        captured_callback = cb
        return lambda: None
    
    mock_session.on.side_effect = side_effect_on
    
    # Run stream
    gen = copilot_backend.stream_with_tools(messages, tools)
    
    # Start generator (it will pause at queue.get)
    # But first, it calls await session.send()
    # verify session_creation called
    
    # We iterate manually
    # 1. Start generator - executes up to session creation
    # But sending is async. 
    
    # Better approach: Use a task for the feeder
    
    generator_task = asyncio.create_task(_consume_generator(gen))
    
    # Wait for callback capture
    for _ in range(10):
        if captured_callback:
            break
        await asyncio.sleep(0.01)
        
    assert captured_callback is not None
    
    # Feed events
    await event_feeder(captured_callback)
    
    # Get results
    chunks = await generator_task
    
    # Verification
    assert len(chunks) == 3
    assert chunks[0].content == "Hello "
    assert chunks[1].content == "World"
    # Bug fix: synthetic new_answer emitted when model doesn't call workflow tools
    assert chunks[2].type == "tool_calls"
    assert chunks[2].tool_calls[0]["name"] == "new_answer"
    assert chunks[2].tool_calls[0]["arguments"] == {"content": "Hello World"}
    
    copilot_backend.client.create_session.assert_called_once()
    mock_session.send.assert_called_with({"prompt": "[user]: Hello"})


async def _consume_generator(gen):
    results = []
    async for chunk in gen:
        results.append(chunk)
    return results

@pytest.mark.asyncio
async def test_stream_with_tools_resume_session(copilot_backend):
    # Setup existent session
    mock_old_session = AsyncMock()
    mock_old_session.session_id = "sess-old"
    copilot_backend.sessions["agent-1"] = mock_old_session
    
    mock_new_session = AsyncMock()
    mock_new_session.session_id = "sess-from-resume"
    mock_new_session.on = MagicMock(return_value=lambda: None)
    
    copilot_backend.client.resume_session.return_value = mock_new_session
    
    messages = [{"role": "user", "content": "Again"}]
    
    # Capture callback
    captured_callback = None
    def side_effect_on(cb):
        nonlocal captured_callback
        captured_callback = cb
        return lambda: None
    mock_new_session.on.side_effect = side_effect_on
    
    gen = copilot_backend.stream_with_tools(messages, [], agent_id="agent-1")
    generator_task = asyncio.create_task(_consume_generator(gen))
    
    for _ in range(10):
        if captured_callback:
            break
        await asyncio.sleep(0.01)
        
    # Just finish it
    event_idle = MagicMock()
    event_idle.type.value = "session.idle"
    captured_callback(event_idle)
    
    await generator_task
    
    # Verify resume called
    copilot_backend.client.resume_session.assert_called_with("sess-old", {"model": "gpt-4", "streaming": True, "tools": []})
    mock_new_session.send.assert_called_with({"prompt": "[user]: Again"})
