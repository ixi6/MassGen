from __future__ import annotations

from fastapi import FastAPI

from .engine import Engine
from .openai.routes import build_router
from .settings import ServerSettings


def create_app(*, engine: Engine | None = None, settings: ServerSettings | None = None) -> FastAPI:
    settings = settings or ServerSettings.from_env()
    app = FastAPI(title="MassGen OpenAI-Compatible Server", version="0")
    app.include_router(build_router(engine=engine, settings=settings))
    return app
