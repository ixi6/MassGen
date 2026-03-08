from fastapi.testclient import TestClient

from massgen.server.app import create_app
from massgen.server.openai.model_router import ResolvedModel
from massgen.tool.workflow_toolkits.base import WORKFLOW_TOOL_NAMES


class FakeToolCallEngine:
    def __init__(self, *, tool_name: str):
        self._tool_name = tool_name

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
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": self._tool_name, "arguments": {"x": 1}},
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                },
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


def test_tool_calls_non_stream_finish_reason_tool_calls():
    app = create_app(engine=FakeToolCallEngine(tool_name="client_tool"))
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "massgen",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "client_tool", "description": "x", "parameters": {"type": "object"}},
                },
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["finish_reason"] == "tool_calls"
    msg = data["choices"][0]["message"]
    assert msg["role"] == "assistant"
    assert msg["tool_calls"][0]["function"]["name"] == "client_tool"


def test_tool_calls_streaming():
    app = create_app(engine=FakeToolCallEngine(tool_name="client_tool"))
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "massgen",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "client_tool", "description": "x", "parameters": {"type": "object"}},
                },
            ],
        },
    )
    assert resp.status_code == 501


def test_internal_workflow_tools_are_passed_through_from_engine():
    internal_name = next(iter(WORKFLOW_TOOL_NAMES))
    app = create_app(engine=FakeToolCallEngine(tool_name=internal_name))
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
    assert data["choices"][0]["finish_reason"] == "tool_calls"
    assert data["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == internal_name


def test_tool_name_collision_rejected():
    internal_name = next(iter(WORKFLOW_TOOL_NAMES))
    app = create_app(engine=FakeToolCallEngine(tool_name="client_tool"))
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "massgen",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "function": {"name": internal_name, "parameters": {"type": "object"}}}],
        },
    )
    assert resp.status_code == 400
