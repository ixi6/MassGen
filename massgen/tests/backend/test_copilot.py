"""Unit tests for CopilotBackend."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_copilot_module():
    """Provide a scoped fake copilot module so the import doesn't leak."""
    mock_mod = MagicMock()
    mock_mod.types = MagicMock()
    mock_mod.generated.session_events = MagicMock()
    with patch.dict(
        sys.modules,
        {"copilot": mock_mod, "github_copilot_sdk": mock_mod},
    ):
        yield mock_mod


@pytest.fixture
def mock_copilot_client(mock_copilot_module):
    with patch("massgen.backend.copilot.CopilotClient") as mock:
        client_instance = AsyncMock()
        mock.return_value = client_instance
        yield client_instance


@pytest.fixture
def copilot_backend(mock_copilot_client):
    from massgen.backend.copilot import CopilotBackend

    # Ensure SDK availability check passes
    with patch("massgen.backend.copilot.COPILOT_SDK_AVAILABLE", True):
        backend = CopilotBackend(api_key="dummy")
        backend.client = mock_copilot_client
        return backend


def _make_session(session_id="sess-123"):
    """Create a mock Copilot session with a sync .on() that returns a callable unsubscribe."""
    session = AsyncMock()
    session.session_id = session_id
    # .on() must be a plain function that accepts a callback and returns a sync
    # unsubscribe callable — matching the real SDK behaviour.
    session.on = MagicMock(return_value=lambda: None)
    return session


@pytest.mark.asyncio
async def test_initialization(copilot_backend):
    assert copilot_backend.get_provider_name() == "copilot"
    assert copilot_backend.client is not None


@pytest.mark.asyncio
async def test_stream_with_tools_create_session(copilot_backend):
    mock_session = _make_session()
    copilot_backend.client.create_session.return_value = mock_session
    copilot_backend.client.start = AsyncMock()

    messages = [{"role": "user", "content": "Hello"}]
    tools = []

    # Wire side_effect so we can capture the callback passed to session.on()
    captured_callback = None

    def side_effect_on(cb):
        nonlocal captured_callback
        captured_callback = cb
        return lambda: None  # unsubscribe callable

    mock_session.on.side_effect = side_effect_on

    async def event_feeder(callback):
        await asyncio.sleep(0.1)

        event_content = MagicMock()
        event_content.type.value = "assistant.message_delta"
        event_content.data.delta_content = "Hello "
        callback(event_content)

        event_content_2 = MagicMock()
        event_content_2.type.value = "assistant.message_delta"
        event_content_2.data.delta_content = "World"
        callback(event_content_2)

        event_idle = MagicMock()
        event_idle.type.value = "session.idle"
        callback(event_idle)

    gen = copilot_backend.stream_with_tools(messages, tools)
    generator_task = asyncio.create_task(_consume_generator(gen))

    # Wait for callback capture
    for _ in range(50):
        if captured_callback:
            break
        await asyncio.sleep(0.01)
    assert captured_callback is not None

    await event_feeder(captured_callback)
    chunks = await generator_task

    # Filter to content and tool_calls chunks (ignore done/status)
    content_chunks = [c for c in chunks if c.type == "content"]
    tool_chunks = [c for c in chunks if c.type == "tool_calls"]
    done_chunks = [c for c in chunks if c.type == "done"]

    assert len(content_chunks) == 2
    assert content_chunks[0].content == "Hello "
    assert content_chunks[1].content == "World"

    # Synthetic new_answer emitted when model doesn't call workflow tools
    assert len(tool_chunks) == 1
    assert tool_chunks[0].tool_calls[0]["name"] == "new_answer"
    assert tool_chunks[0].tool_calls[0]["arguments"] == {"content": "Hello World"}

    assert len(done_chunks) == 1

    copilot_backend.client.create_session.assert_called_once()
    mock_session.send.assert_called_with({"prompt": "[user]: Hello"})


async def _consume_generator(gen):
    results = []
    async for chunk in gen:
        results.append(chunk)
    return results


@pytest.mark.asyncio
async def test_stream_with_tools_reuses_existing_session(copilot_backend):
    """When a session already exists for an agent, it is reused (no create_session call)."""
    mock_session = _make_session("sess-existing")
    copilot_backend.sessions["agent-1"] = mock_session
    # Pre-populate the signature so it matches and the session is reused.
    # Mock _build_session_signature to return a fixed value we control.
    copilot_backend._build_session_signature = MagicMock(return_value="fixed-sig")
    copilot_backend._session_signatures["agent-1"] = "fixed-sig"

    captured_callback = None

    def side_effect_on(cb):
        nonlocal captured_callback
        captured_callback = cb
        return lambda: None

    mock_session.on.side_effect = side_effect_on

    messages = [{"role": "user", "content": "Again"}]

    gen = copilot_backend.stream_with_tools(messages, [], agent_id="agent-1")
    generator_task = asyncio.create_task(_consume_generator(gen))

    for _ in range(50):
        if captured_callback:
            break
        await asyncio.sleep(0.01)

    assert captured_callback is not None, "Callback was not captured — session.on() was never called"

    event_idle = MagicMock()
    event_idle.type.value = "session.idle"
    captured_callback(event_idle)

    chunks = await generator_task

    done_chunks = [c for c in chunks if c.type == "done"]
    assert len(done_chunks) == 1

    # Session was reused — create_session should NOT have been called
    copilot_backend.client.create_session.assert_not_called()
    mock_session.send.assert_called_with({"prompt": "[user]: Again"})
