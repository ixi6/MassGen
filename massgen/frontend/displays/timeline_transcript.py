"""Utilities for dumping timeline output for comparison/debugging."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterable

_TRANSCRIPT_ENV = "MASSGEN_TUI_TIMELINE_TRANSCRIPT"
_EMIT_EVENTS_ENV = "MASSGEN_TUI_TIMELINE_EVENTS"
_MAX_LINE_LEN = 200
_LOCK = threading.Lock()


def _get_path() -> str | None:
    return os.environ.get(_TRANSCRIPT_ENV)


def _truncate(text: str, max_len: int = _MAX_LINE_LEN) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _sanitize(text: str) -> str:
    return _truncate(text.replace("\n", "\\n").replace("\r", ""))


def _write_line(line: str) -> None:
    path = _get_path()
    if not path:
        return
    with _LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if os.environ.get(_EMIT_EVENTS_ENV):
            try:
                from massgen.events import emit_event

                emit_event("timeline_entry", line=line)
            except Exception:
                pass


def format_separator(label: str, round_number: int, subtitle: str = "") -> str:
    base = f"[{round_number}] separator: {label}" if label else f"[{round_number}] separator"
    if subtitle:
        base = f"{base} | {subtitle}"
    return _sanitize(base)


def format_text(content: str, text_class: str, round_number: int) -> str:
    label = text_class or "text"
    return _sanitize(f"[{round_number}] {label}: {content}")


def format_tool(
    tool_data,
    round_number: int,
    action: str,
    batch_id: str | None = None,
    server_name: str | None = None,
) -> str:
    name = getattr(tool_data, "display_name", None) or getattr(tool_data, "tool_name", "tool")
    status = getattr(tool_data, "status", "unknown")
    tool_id = getattr(tool_data, "tool_id", "")
    args = getattr(tool_data, "args_summary", None) or ""
    result = getattr(tool_data, "result_summary", None) or ""
    parts = [f"[{round_number}] tool {action}", name, f"id={tool_id}", f"status={status}"]
    if batch_id:
        parts.append(f"batch={batch_id}")
    if server_name:
        parts.append(f"server={server_name}")
    if args and action in ("add", "pending"):
        parts.append(f"args={args}")
    if result and status in ("success", "error", "background"):
        parts.append(f"result={result}")
    return _sanitize(" | ".join(parts))


def format_batch(round_number: int, action: str, batch_id: str, server_name: str) -> str:
    return _sanitize(f"[{round_number}] batch {action} | id={batch_id} | server={server_name}")


def format_batch_tool(
    tool_data,
    round_number: int,
    batch_id: str,
    action: str,
) -> str:
    name = getattr(tool_data, "display_name", None) or getattr(tool_data, "tool_name", "tool")
    tool_id = getattr(tool_data, "tool_id", "")
    status = getattr(tool_data, "status", "unknown")
    return _sanitize(f"[{round_number}] batch {action} | id={batch_id} | tool={name} | tool_id={tool_id} | status={status}")


def record_separator(label: str, round_number: int, subtitle: str = "") -> None:
    _write_line(format_separator(label, round_number, subtitle))


def record_text(content: str, text_class: str, round_number: int) -> None:
    _write_line(format_text(content, text_class, round_number))


def record_tool(
    tool_data,
    round_number: int,
    action: str,
    batch_id: str | None = None,
    server_name: str | None = None,
) -> None:
    _write_line(format_tool(tool_data, round_number, action, batch_id=batch_id, server_name=server_name))


def record_batch(round_number: int, action: str, batch_id: str, server_name: str) -> None:
    _write_line(format_batch(round_number, action, batch_id, server_name))


def record_batch_tool(tool_data, round_number: int, batch_id: str, action: str) -> None:
    _write_line(format_batch_tool(tool_data, round_number, batch_id, action))


def render_output(output) -> list[str]:
    """Render ContentOutput-like object into transcript lines."""
    lines: list[str] = []
    round_number = getattr(output, "round_number", None) or 1
    output_type = getattr(output, "output_type", "")

    if output_type == "separator":
        label = getattr(output, "separator_label", "") or ""
        subtitle = getattr(output, "separator_subtitle", "") or ""
        lines.append(format_separator(label, round_number, subtitle))
    elif output_type in ("thinking", "text", "status", "presentation", "reminder", "injection"):
        text = getattr(output, "text_content", "") or ""
        text_class = getattr(output, "text_class", "") or output_type
        lines.append(format_text(text, text_class, round_number))
    elif output_type == "final_answer":
        text = getattr(output, "text_content", "") or ""
        lines.append(format_text(text, "final-answer", round_number))
    elif output_type == "tool" and getattr(output, "tool_data", None):
        tool_data = output.tool_data
        action = getattr(output, "batch_action", None) or "add"
        batch_id = getattr(output, "batch_id", None)
        server_name = getattr(output, "server_name", None)
        lines.append(format_tool(tool_data, round_number, action, batch_id=batch_id, server_name=server_name))
    elif output_type == "tool_batch" and getattr(output, "batch_tools", None):
        batch_id = getattr(output, "batch_id", "") or "batch"
        server_name = getattr(output, "server_name", "") or "tools"
        lines.append(format_batch(round_number, "start", batch_id, server_name))
        for tool in output.batch_tools:
            lines.append(format_batch_tool(tool, round_number, batch_id, "add"))
    return lines


def render_outputs(outputs: Iterable) -> list[str]:
    lines: list[str] = []
    for output in outputs:
        if output is None:
            continue
        lines.extend(render_output(output))
    return lines
