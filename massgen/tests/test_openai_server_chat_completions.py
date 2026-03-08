from fastapi.testclient import TestClient

from massgen.server.app import create_app
from massgen.server.openai.model_router import ResolvedModel


class FakeEngine:
    async def completion(self, req, resolved: ResolvedModel, *, request_id: str):
        _ = (req, resolved, request_id)
        return {
            "id": f"chatcmpl-{request_id}",
            "object": "chat.completion",
            "created": 123,
            "model": "massgen",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello world",
                    },
                    "finish_reason": "stop",
                },
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        }


class FakeEngineWithReasoning:
    async def completion(self, req, resolved: ResolvedModel, *, request_id: str):
        _ = (req, resolved, request_id)
        return {
            "id": f"chatcmpl-{request_id}",
            "object": "chat.completion",
            "created": 123,
            "model": "massgen",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "The answer is 42.",
                        "reasoning_content": ("Starting coordination...\n" "Agent thinking...\n" "Generating answer"),
                    },
                    "finish_reason": "stop",
                },
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        }


def test_chat_completions_non_stream():
    app = create_app(engine=FakeEngine())
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "massgen",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["message"]["content"] == "Hello world"
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["usage"] == {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}


def test_chat_completions_streaming_not_supported():
    app = create_app(engine=FakeEngine())
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "massgen",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert resp.status_code == 501
    body = resp.json().get("detail", {})
    assert "not yet supported" in body.get("error", "").lower()


def test_chat_completions_reasoning_content_non_stream():
    """Test that non-content chunks are collected into reasoning_content."""
    app = create_app(engine=FakeEngineWithReasoning())
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "massgen",
            "messages": [{"role": "user", "content": "What is the meaning of life?"}],
            "stream": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    message = data["choices"][0]["message"]

    # Final content should only contain the answer
    assert message["content"] == "The answer is 42."

    # reasoning_content should contain traces
    assert "reasoning_content" in message
    reasoning = message["reasoning_content"]
    assert "Starting coordination" in reasoning
    assert "Agent thinking" in reasoning
    assert "Generating answer" in reasoning
    assert data["usage"] == {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}


def test_chat_completions_reasoning_content_streaming_not_supported():
    """Streaming remains unsupported even when reasoning content is available."""
    app = create_app(engine=FakeEngineWithReasoning())
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "massgen",
            "messages": [{"role": "user", "content": "What is the meaning of life?"}],
            "stream": True,
        },
    )
    assert resp.status_code == 501
    body = resp.json().get("detail", {})
    assert "not yet supported" in body.get("error", "").lower()
