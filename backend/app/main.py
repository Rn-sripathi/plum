"""Application entry point.

Run locally:  uv run fastapi dev app/main.py   (from backend/)
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.llm import DocumentAI
from app.api.routes import register_error_handlers, router
from app.core.config import settings
from app.core.store import SqliteClaimStore
from app.kb.snapshot import PolicySnapshot


def create_app(database_path: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.snapshot = PolicySnapshot.from_file(settings.policy_terms_path)
        app.state.store = SqliteClaimStore(database_path or settings.database_path)
        app.state.doc_ai = DocumentAI(settings)
        yield

    app = FastAPI(
        title="Plum Claims Processing",
        description="Automated health-insurance claim adjudication with full decision traces.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # assignment scope; lock down per-origin in production
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    register_error_handlers(app)
    return app


app = create_app()
