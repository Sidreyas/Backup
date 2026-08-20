"""
Test fixtures.

Tests run against a real Postgres — the same engine production uses. SQLite
would be faster to set up and would not exercise the things most likely to
break: JSONB columns, the recursive CTE with array operations, advisory locks,
and `DISTINCT ON`. A test suite that passes on a database the product does not
use would be false assurance.

Each test gets a transaction that is rolled back afterwards, so tests neither
see each other's writes nor leave anything behind.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from api import migrate
from api.core.db import Base

# Imported for their registration side effect on Base.metadata.
from api.domain import feasibility as _feas  # noqa: F401
from api.domain import governance as _gov  # noqa: F401
from api.domain import models as _models  # noqa: F401
from api.domain import stlc as _stlc  # noqa: F401

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://meridian:meridian@localhost:5433/meridian_test",
)


@pytest.fixture(scope="session")
def engine():
    """A dedicated test database, created if absent."""
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[1]

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin.dispose()

    eng = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    Base.metadata.create_all(bind=eng)
    # The test database persists between runs, so `create_all` finds the tables
    # already present and skips them — including any column added since.
    # Without this, a schema change passes locally on a fresh database and
    # fails for everyone who already has one.
    migrate.run(engine=eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch):
    """Tests never call a real language model.

    Three reasons, in order of importance. A test whose expected output is a
    model's prose is not a test — it passes or fails on sampling. Real calls
    also make the suite slow and spend quota, and the tests that matter here
    are about *retrieval and grounding*, which are deterministic and which a
    stub exercises exactly as well.

    Autouse rather than opt-in: the failure mode is a developer with a key
    configured getting different results from CI, which is the kind of
    discrepancy nobody thinks to check.
    """
    from api.agents import llm as llm_module

    monkeypatch.setattr(llm_module.llm, "_client", None, raising=False)
    monkeypatch.setattr(llm_module.llm, "provider", "none", raising=False)


@pytest.fixture
def db(engine) -> Session:
    """One transaction per test, rolled back at the end.

    The session is bound to an open connection with an outer transaction, so
    even code that calls `commit()` internally is undone — `commit` ends the
    nested transaction, not the outer one.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
