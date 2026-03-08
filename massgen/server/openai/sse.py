from __future__ import annotations

import json
from typing import Any

SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_sse(data: Any) -> str:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return f"data: {payload}\n\n"


def format_done() -> str:
    return "data: [DONE]\n\n"
