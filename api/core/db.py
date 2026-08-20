"""
Database session and base class.

Synchronous SQLAlchemy rather than async. The workload here is dominated by
short transactional reads and the occasional LLM call; the LLM calls are the
only genuinely slow thing and they are issued over httpx from within a request
that is not holding a database transaction. Async SQLAlchemy would add real
complexity (session lifetime, greenlet context, per-driver differences) to buy
throughput this application does not need yet. FastAPI runs sync dependencies
in a threadpool, so the event loop is not blocked.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from api.core.config import settings

engine = create_engine(
    settings.database_url,
    # Verify a pooled connection before handing it out. Without this, a
    # connection dropped by a Postgres restart surfaces as a confusing
    # OperationalError on an unrelated request.
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency. One session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
