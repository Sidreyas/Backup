"""
Meridian API.

The system of record for enterprise change: what was asked for, what it means
against the real configuration, what evidence proves it works, who signed off,
and what it cost.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.core.config import settings
from api.core.db import Base, engine

# Registers every table on Base.metadata. See api/domain/__init__.py for why
# importing the package (rather than individual modules) is the safe form.
from api import domain as _domain  # noqa: F401
from api import migrate
from api.routers import ask, catalog, governance, requirements, sessions, stlc

logger = logging.getLogger("meridian")

app = FastAPI(
    title="Meridian API",
    version="0.1.0",
    description=(
        "The governance layer over the AI-assisted SDLC. Every response here is "
        "intended to be traceable to evidence; endpoints that cannot be are "
        "explicit about it."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    """Create tables if they are absent, then apply additive migrations.

    `create_all` alone is not enough: it creates missing *tables* and silently
    ignores missing *columns* on tables that already exist, so a new column
    would fail at query time with nothing having complained at startup.
    `api.migrate` closes that gap for additive changes. A rename or a type
    change still needs Alembic and a data-migration plan.
    """
    Base.metadata.create_all(bind=engine)
    migrate.run()
    if not settings.llm_enabled:
        logger.warning(
            "ANTHROPIC_API_KEY is not set. Agent endpoints will return labelled "
            "stub output (source='stub') rather than failing."
        )


@app.exception_handler(NotImplementedError)
def not_implemented(_: Request, exc: NotImplementedError) -> JSONResponse:
    """A declared-but-unbuilt connector is a 501, not a 500.

    The distinction matters to whoever is reading the response: one is a
    roadmap item, the other is a bug.
    """
    return JSONResponse(status_code=501, content={"detail": str(exc)})


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness plus an honest statement of what is degraded.

    `llm` reports whether real analysis is available. A deployment running
    without a key still answers every endpoint, and this is where that shows.
    """
    from api.connectors import registry

    implemented = [e.id for e in registry.all_entries() if e.implemented]
    return {
        "status": "ok",
        "llm": "configured" if settings.llm_enabled else "stub",
        "model": settings.meridian_model,
        "modelVersion": settings.meridian_model_version,
        "connectorsImplemented": implemented,
        "connectorsDeclared": len(registry.REGISTRY) - len(implemented),
    }


app.include_router(catalog.router, prefix="/api")
app.include_router(requirements.router, prefix="/api")
app.include_router(stlc.router, prefix="/api")
app.include_router(governance.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
