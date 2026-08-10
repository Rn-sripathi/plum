"""Application entry point.

Run locally:  uv run fastapi dev app/main.py   (from backend/)
"""

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.assistant import Assistant
from app.agents.llm import DocumentAI
from app.api.routes import register_error_handlers, router
from app.core.config import settings
from app.core.store import SqliteClaimStore, make_store
from app.kb.graph import PolicyGraph
from app.kb.semantic import SemanticPolicyIndex
from app.kb.snapshot import PolicySnapshot


def create_app(database_path: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.snapshot = PolicySnapshot.from_file(settings.policy_terms_path)
        app.state.store = (
            SqliteClaimStore(database_path) if database_path else make_store(settings)
        )
        app.state.doc_ai = DocumentAI(settings)
        app.state.assistant = Assistant(settings)
        app.state.semantic = SemanticPolicyIndex(settings)
        app.state.graph = PolicyGraph(settings)
        # Warm the vector index off the startup path: loading it costs ~24s the
        # first time, and neither startup nor the first question should wear that.
        threading.Thread(target=app.state.semantic.warm, daemon=True).start()
        yield
        app.state.graph.close()

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
