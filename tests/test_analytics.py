"""
The activity dashboard's aggregates.

These numbers get quoted — in status meetings, in cost reviews, to customers.
So what is tested here is mostly *honesty*: that the window a figure claims is
the window it describes, that an unfinished run does not silently drag an
average down, and that an empty installation reports zero rather than
something more flattering.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from api.core.ids import new_id, utcnow
from api.domain.governance import CostEvent
from api.domain.models import ExtractionRun
from api.routers.governance import get_analytics


def _run(db, *, status="complete", nodes=10, started=None, seconds=60.0):
    started = started or utcnow()
    run = ExtractionRun(
        id=new_id("xr"),
        connector_id="cx-workday",
        started_at=started,
        finished_at=(started + timedelta(seconds=seconds)) if seconds else None,
        status=status,
        nodes_created=nodes,
        workspace_id="ws-analytics",
    )
    db.add(run)
    db.flush()
    return run


def _cost(db, *, usd=0.5, at=None, tokens_in=100, tokens_out=50):
    event = CostEvent(
        id=new_id("ce"),
        at=at or utcnow(),
        kind="ask",
        model="openai/gpt-oss-120b",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        llm_usd=usd,
        compute_usd=0.0,
        workspace_id="ws-analytics",
    )
    db.add(event)
    db.flush()
    return event


# --- the window ---------------------------------------------------------------


def test_a_run_outside_the_window_is_not_counted(db):
    """The most consequential bug this endpoint could have.

    A figure labelled "7 days" that silently includes older runs is worse than
    no figure: it is quoted with confidence and it is wrong.
    """
    _run(db, started=utcnow() - timedelta(days=2))
    _run(db, started=utcnow() - timedelta(days=40))

    week = get_analytics(days=7, db=db)
    assert week["runTotals"]["runs"] == 1

    quarter = get_analytics(days=90, db=db)
    assert quarter["runTotals"]["runs"] == 2


def test_the_window_is_reported_back_so_a_figure_is_never_unlabelled(db):
    result = get_analytics(days=7, db=db)
    assert result["windowDays"] == 7
    assert result["runTotals"]["days"] == 7


def test_an_absurd_window_is_clamped_rather_than_obeyed(db):
    """Zero would return an empty dashboard that looks like data loss, and an
    unbounded one scans the whole ledger."""
    assert get_analytics(days=0, db=db)["windowDays"] == 1
    assert get_analytics(days=-5, db=db)["windowDays"] == 1
    assert get_analytics(days=99999, db=db)["windowDays"] == 365


# --- what the totals mean ------------------------------------------------------


def test_a_run_still_in_flight_does_not_drag_the_average_down(db):
    """An unfinished run has no duration.

    Counting it as zero would make the mean fall every time a run starts,
    which reads as an improvement and is the opposite of one.
    """
    _run(db, seconds=100.0)
    _run(db, seconds=None)  # still running

    totals = get_analytics(days=30, db=db)["runTotals"]
    assert totals["runs"] == 2
    assert totals["timedRuns"] == 1
    assert totals["avgSeconds"] == 100.0


def test_failures_are_counted_separately_from_successes(db):
    _run(db, status="complete")
    _run(db, status="failed", nodes=0)

    totals = get_analytics(days=30, db=db)["runTotals"]
    assert totals["runs"] == 2
    assert totals["failed"] == 1
    assert totals["succeeded"] == 1


def test_nodes_are_summed_across_runs(db):
    _run(db, nodes=17)
    _run(db, nodes=25)
    assert get_analytics(days=30, db=db)["runTotals"]["nodes"] == 42


def test_spend_and_tokens_come_from_the_cost_ledger(db):
    _cost(db, usd=0.25, tokens_in=1000, tokens_out=400)
    _cost(db, usd=0.75, tokens_in=500, tokens_out=100)

    totals = get_analytics(days=30, db=db)["runTotals"]
    assert totals["llmUsd"] == pytest.approx(1.0)
    assert totals["tokensIn"] == 1500
    assert totals["tokensOut"] == 500
    assert totals["operations"] == 2


# --- the daily series ----------------------------------------------------------


def test_runs_on_the_same_day_collapse_into_one_point(db):
    day = utcnow() - timedelta(days=1)
    _run(db, started=day, seconds=60.0)
    _run(db, started=day + timedelta(hours=2), seconds=120.0)

    series = get_analytics(days=30, db=db)["runs"]
    assert len(series) == 1
    assert series[0]["runs"] == 2
    # Mean, not total: a day with one slow run and a day with ten fast ones
    # should not draw the same shape.
    assert series[0]["avgSeconds"] == 90.0


def test_the_series_is_ordered_oldest_first(db):
    _run(db, started=utcnow() - timedelta(days=1))
    _run(db, started=utcnow() - timedelta(days=3))

    dates = [p["date"] for p in get_analytics(days=30, db=db)["runs"]]
    assert dates == sorted(dates)


# --- the empty case ------------------------------------------------------------


def test_asking_a_question_persists_what_it_cost(db, monkeypatch):
    """The ask route writes a cost row and nothing else.

    So it is the one route where forgetting to commit loses the row entirely —
    every question answered correctly, and the spend dashboard reading zero
    forever. Other routes that record cost happen to commit for their own
    reasons, which is exactly why this one went unnoticed.
    """
    from api.agents import ask as ask_agent
    from api.routers import ask as ask_router
    from api.routers.deps import Actor

    committed: list[bool] = []
    real_commit = db.commit
    monkeypatch.setattr(
        db, "commit", lambda: (committed.append(True), real_commit())[1], raising=False
    )

    answer = ask_agent.Answer(
        question="q",
        text="a",
        cited=[],
        considered=[],
        fabricated=[],
        gaps=[],
        provenance={},
    )
    monkeypatch.setattr(ask_agent, "ask", lambda *a, **k: answer)

    ask_router.post_ask(
        ask_router.AskRequest(question="q"),
        db=db,
        actor=Actor(email="tester@acme.example", name="Tester", role="qa"),
        workspace_id="ws-analytics",
    )

    assert committed, "the ask route must commit or the cost row is discarded"


def test_a_fresh_install_reports_zero_rather_than_nothing(db):
    """A fresh install is the first thing a new customer sees.

    Zeroes are legible; absent keys crash the dashboard, and invented demo
    curves would make every later figure suspect.
    """
    result = get_analytics(days=30, db=db)
    assert result["runs"] == []
    assert result["runTotals"]["runs"] == 0
    assert result["runTotals"]["avgSeconds"] == 0.0
    assert result["runTotals"]["llmUsd"] == 0.0
