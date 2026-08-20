"""
Ingest the captured absence fixtures into the running database.

Bridges the tenant walk and the live app: the fixtures are real configuration
read from the client's tenant, and this puts them in the graph so `/api/ask`
answers from them.

A stand-in for the connector's own browser walk, which is the remaining piece —
`_browser_discovery()` replays recipes but has no absence recipe wired yet.
Once it does, this script is redundant.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.connectors.base import RawRecord  # noqa: E402
from api.connectors.workday.absence_screen import (  # noqa: E402
    attach_accrual_detail,
    attach_calculations,
    parse_plan_screen,
)
from api.connectors.workday.connector import WorkdayConnector  # noqa: E402
from api.core.db import SessionLocal  # noqa: E402
from api.core.ids import new_id  # noqa: E402
from api.domain import enums  # noqa: E402
from api.domain.models import ExtractionRun, KnowledgeSource  # noqa: E402
from api.graph.normalize import Normalizer  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
WORKSPACE = "ws-acme"

PLANS = (
    ("hkg_annual_leave", "HKG", "HKG Annual Leave"),
    ("gbr_statutory_holiday", "GBR", "GBR Statutory Holiday (Days)"),
)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def main() -> int:
    accruals = _load("workday_accruals.json")
    lookups = _load("workday_lookups.json")

    connector = WorkdayConnector(
        {
            "host": "https://wcpdev.wd101.myworkday.com",
            "tenant": "aia_wcpdev1",
            "method": "isu_basic",
            "username": "u",
            "password": "p",
        }
    )

    records: list[RawRecord] = []
    for key, plan_id, name in PLANS:
        plan = parse_plan_screen(
            _load(f"workday_timeoffplan_{key}.json"),
            plan_id=plan_id,
            name=name,
            unit_of_time="Days",
        )
        plan = attach_accrual_detail(plan, accruals[key])
        plan = attach_calculations(plan, lookups[key])
        records.extend(connector._records_for_plan(plan))

    db = SessionLocal()
    try:
        source = (
            db.query(KnowledgeSource)
            .filter(
                KnowledgeSource.workspace_id == WORKSPACE,
                KnowledgeSource.name == "Workday Absence",
            )
            .one_or_none()
        )
        if source is None:
            source = KnowledgeSource(
                id=new_id("src"),
                workspace_id=WORKSPACE,
                name="Workday Absence",
                kind=enums.SourceKind.PLATFORM,
                provider="Workday, Inc.",
            )
            db.add(source)

        run = ExtractionRun(
            id=new_id("xr"),
            connector_id="cx-workday",
            extractor_version="1",
            workspace_id=WORKSPACE,
        )
        db.add(run)
        db.flush()

        result = Normalizer(
            db, run, source_id=source.id, workspace_id=WORKSPACE
        ).ingest(records)
        db.commit()

        print(f"records:            {len(records)}")
        print(f"nodes created:      {result.nodes_created}")
        print(f"nodes updated:      {result.nodes_updated}")
        print(f"assertions:         {result.assertions_proposed}")
        print(f"rejected:           {result.rejected}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
