"""
MassGen OpenAI-compatible server package.

Exposes a FastAPI app with:
- GET /health
- POST /v1/chat/completions (OpenAI-compatible, supports SSE streaming)
"""

from .app import create_app

__all__ = ["create_app"]
