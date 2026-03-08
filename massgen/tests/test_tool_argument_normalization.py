"""Tests for shared tool-argument normalization utilities."""

import json

import pytest

from massgen.backend.base import LLMBackend, StreamChunk
from massgen.formatter._formatter_base import FormatterBase
from massgen.utils.tool_argument_normalization import normalize_json_object_argument


class _DummyBackend(LLMBackend):
    async def stream_with_tools(self, messages, tools, **kwargs):  # noqa: ARG002
        if False:
            yield StreamChunk(type="done")

    def get_provider_name(self) -> str:
        return "dummy"


def test_normalize_json_object_argument_accepts_dict():
    parsed, decode_passes = normalize_json_object_argument({"city": "Tokyo"})
    assert parsed == {"city": "Tokyo"}
    assert decode_passes == 0


def test_normalize_json_object_argument_accepts_json_string():
    parsed, decode_passes = normalize_json_object_argument('{"city":"Tokyo"}')
    assert parsed == {"city": "Tokyo"}
    assert decode_passes == 1


def test_normalize_json_object_argument_accepts_double_encoded_json_string():
    encoded = json.dumps(json.dumps({"city": "Tokyo"}))
    parsed, decode_passes = normalize_json_object_argument(encoded)
    assert parsed == {"city": "Tokyo"}
    assert decode_passes == 2


def test_normalize_json_object_argument_repairs_missing_trailing_brace():
    malformed = '{"tool_name":"custom_tool__generate_media","arguments":{"mode":"image"}}'[:-1]
    parsed, _ = normalize_json_object_argument(malformed)
    assert parsed == {
        "tool_name": "custom_tool__generate_media",
        "arguments": {"mode": "image"},
    }


def test_normalize_json_object_argument_rejects_non_object_json():
    with pytest.raises(ValueError, match="arguments must be a JSON object"):
        normalize_json_object_argument(json.dumps([1, 2, 3]))


def test_normalize_json_object_argument_rejects_invalid_json():
    with pytest.raises(ValueError, match="arguments must be a JSON object"):
        normalize_json_object_argument("{oops")


def test_backend_extract_tool_arguments_normalizes_double_encoded_json():
    backend = _DummyBackend(api_key="test-key")
    tool_call = {
        "function": {
            "name": "echo",
            "arguments": json.dumps(json.dumps({"city": "Tokyo"})),
        },
    }
    assert backend.extract_tool_arguments(tool_call) == {"city": "Tokyo"}


def test_formatter_extract_tool_arguments_normalizes_double_encoded_json():
    tool_call = {
        "function": {
            "name": "echo",
            "arguments": json.dumps(json.dumps({"city": "Tokyo"})),
        },
    }
    assert FormatterBase.extract_tool_arguments(tool_call) == {"city": "Tokyo"}
