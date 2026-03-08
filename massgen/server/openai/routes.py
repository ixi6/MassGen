"""
OpenAI-compatible API routes for MassGen HTTP server.

Provides /v1/chat/completions endpoint that uses massgen.run() for full feature parity.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse

from massgen.tool.workflow_toolkits.base import WORKFLOW_TOOL_NAMES

from ..engine import Engine, MassGenEngine
from ..settings import ServerSettings
from .model_router import resolve_model
from .schema import ChatCompletionRequest


def _extract_client_tool_names(tools: list[dict[str, Any]] | None) -> list[str]:
    if not tools:
        return []
    names: list[str] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if isinstance(t.get("function"), dict) else {}
        name = fn.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def build_router(*, engine: Engine | None = None, settings: ServerSettings | None = None) -> APIRouter:
    router = APIRouter()
    settings = settings or ServerSettings.from_env()
    engine = engine or MassGenEngine(default_config=settings.default_config)

    @router.get("/health")
    async def health() -> dict[str, Any]:
        import massgen

        return {"status": "ok", "service": "massgen-server", "version": getattr(massgen, "__version__", "unknown")}

    @router.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest, request: Request):
        # Guard against collisions with MassGen workflow tools.
        tool_names = _extract_client_tool_names(req.tools)
        collisions = sorted(set(tool_names).intersection(set(WORKFLOW_TOOL_NAMES)))
        if collisions:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Client tool names collide with reserved MassGen workflow tools",
                    "collisions": collisions,
                },
            )

        # Streaming is not yet supported - return error if requested
        if req.stream:
            raise HTTPException(
                status_code=501,
                detail={
                    "error": "Streaming is not yet supported. Please set stream=false.",
                    "hint": "Streaming support is planned for a future release.",
                },
            )

        resolved = resolve_model(
            req.model or "massgen",
            default_config=settings.default_config,
        )

        request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex}"

        try:
            response = await engine.completion(req, resolved, request_id=request_id)
            return JSONResponse(response)
        except ValueError as e:
            raise HTTPException(status_code=400, detail={"error": str(e)})
        except Exception as e:
            raise HTTPException(status_code=500, detail={"error": f"Internal server error: {str(e)}"})

    return router
