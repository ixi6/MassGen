"""Utilities for normalizing tool argument payloads across backends."""

from __future__ import annotations

import json
from typing import Any


def _repair_missing_json_closers(raw: str) -> str | None:
    """Attempt minimal JSON repair by appending missing closing delimiters.

    This intentionally applies only a narrow, deterministic repair:
    - input must look like a JSON object/array (starts with `{` or `[`)
    - existing closing delimiters must be structurally valid
    - repair only appends missing `}` / `]` (and a closing quote if a string
      was left open by truncation)
    """
    text = raw.strip()
    if not text or text[0] not in "{[":
        return None

    stack: list[str] = []
    in_string = False
    escaping = False

    for ch in text:
        if in_string:
            if escaping:
                escaping = False
                continue
            if ch == "\\":
                escaping = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch in "{[":
            stack.append(ch)
            continue
        if ch in "}]":
            if not stack:
                return None
            opener = stack.pop()
            if (opener == "{" and ch != "}") or (opener == "[" and ch != "]"):
                return None

    if not stack and not in_string:
        return None

    repaired = text
    if in_string:
        repaired += '"'

    if stack:
        repaired += "".join("}" if opener == "{" else "]" for opener in reversed(stack))

    return repaired


def normalize_json_object_argument(
    arguments: Any,
    *,
    field_name: str = "arguments",
    max_decode_passes: int = 2,
) -> tuple[dict[str, Any], int]:
    """Normalize a tool argument payload into a JSON object.

    This accepts:
    - dict payloads directly
    - JSON object strings
    - double-encoded JSON object strings (bounded by ``max_decode_passes``)

    Returns:
        Tuple of ``(parsed_object, decode_passes)``.

    Raises:
        ValueError: If payload cannot be normalized to a JSON object.
    """
    if max_decode_passes < 1:
        max_decode_passes = 1

    if arguments is None:
        return {}, 0

    if isinstance(arguments, dict):
        return arguments, 0

    current: Any = arguments
    decode_passes = 0

    while isinstance(current, str) and decode_passes < max_decode_passes:
        if not current.strip():
            return {}, decode_passes
        try:
            current = json.loads(current)
        except (json.JSONDecodeError, TypeError) as exc:
            repaired = _repair_missing_json_closers(current)
            if repaired is None:
                raise ValueError(f"{field_name} must be a JSON object") from exc
            try:
                current = json.loads(repaired)
            except (json.JSONDecodeError, TypeError) as repaired_exc:
                raise ValueError(f"{field_name} must be a JSON object") from repaired_exc
        decode_passes += 1
        if isinstance(current, dict):
            return current, decode_passes

    if isinstance(current, dict):
        return current, decode_passes

    raise ValueError(f"{field_name} must be a JSON object")


__all__ = ["normalize_json_object_argument"]
