"""
Turn a raw tenant probe into committed test fixtures.

The probe output is large, contains a session cookie, and names a live tenant.
What the tests need is much smaller: the tab structure, the grid headers, and
one row of representative values per grid. This extracts that and drops
everything else.

Run after `explore_absence.py`. The result goes in `tests/fixtures/` and is
safe to commit — no session state, no worker rows, no credentials.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tmp_absence_probe"
DEST = ROOT / "tests" / "fixtures"
DEST.mkdir(parents=True, exist_ok=True)

#: Grid headers carry Workday's sort/filter affordance text appended to the
#: column name. Stripped here rather than in the parser so fixtures read as the
#: column names a person would recognise.
NOISE = ("Sort and filter column", "Filter column")


def clean_header(header: str) -> str:
    text = header.replace("\n", " ").strip()
    for noise in NOISE:
        text = text.replace(noise, "")
    return " ".join(text.split())


def condense(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict = {
        "key": raw["key"],
        # The instance URL is tenant-specific and not reusable; the task name
        # is what identifies this screen anywhere.
        "task": raw.get("heading") or raw.get("title", ""),
        "tabs": raw.get("tabs", []),
        "tabs_detail": {},
    }

    for tab, content in (raw.get("tabContent") or {}).items():
        grids = []
        for grid in content.get("grids", []):
            headers = [clean_header(h) for h in grid.get("headers", [])]
            headers = [h for h in headers if h]
            rows = [r for r in grid.get("rows", []) if any(r)]
            if not headers or not rows:
                continue
            grids.append({"headers": headers, "rows": rows[:3]})
        out["tabs_detail"][tab] = {"grids": grids}

    return out


def condense_accruals(raw: dict) -> dict:
    """Keep the accrual grids, dropping the page chrome around them."""
    out: dict = {}
    for plan_key, accruals in raw.items():
        kept = []
        for accrual in accruals:
            if "error" in accrual:
                continue
            grids = []
            for grid in accrual.get("grids", []):
                headers = [clean_header(h) for h in grid.get("headers", [])]
                headers = [h for h in headers if h]
                rows = [r for r in grid.get("rows", []) if any(r)]
                if headers and rows:
                    grids.append({"headers": headers, "rows": rows[:4]})
            kept.append({"name": accrual["name"], "grids": grids})
        out[plan_key] = kept
    return out


def condense_lookups(raw: dict) -> dict:
    """Keep the calculation type and its resolved values.

    Two shapes come out of this walk and both matter: a Lookup Calculation
    resolves to a Search Value / Return Value table, and a Conditional
    Calculation resolves to ordered condition/result rows. Neither is more
    correct — they are different ways of expressing an entitlement, and the
    summary phrases each differently.
    """
    out: dict = {}
    for plan_key, entries in raw.items():
        kept = []
        for entry in entries:
            record = {
                "accrual": entry.get("accrual", ""),
                "calculation": entry.get("calculation", ""),
                "calculationType": entry.get("calculationType", ""),
                "lookupTable": entry.get("lookupTable", ""),
                "searchCriteria": entry.get("searchCriteria", ""),
                "note": entry.get("note", ""),
            }
            for source, target in (
                ("tableGrids", "tableGrids"),
                ("calculationGrids", "calculationGrids"),
            ):
                grids = []
                for grid in entry.get(source) or []:
                    headers = [clean_header(h) for h in grid.get("headers", [])]
                    headers = [h for h in headers if h]
                    rows = [r for r in grid.get("rows", []) if any(r)]
                    if headers and rows:
                        grids.append({"headers": headers, "rows": rows[:20]})
                if grids:
                    record[target] = grids
            kept.append(record)
        out[plan_key] = kept
    return out


def main() -> int:
    if not SRC.exists():
        print(f"No probe output at {SRC}. Run explore_absence.py first.")
        return 1

    lookups_src = SRC / "lookups.json"
    if lookups_src.exists():
        data = condense_lookups(json.loads(lookups_src.read_text(encoding="utf-8")))
        target = DEST / "workday_lookups.json"
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"wrote {target.relative_to(ROOT)}")
        for plan, entries in data.items():
            for e in entries:
                print(f"   {plan}: {e['accrual'][:38]} -> {e['calculationType'] or '-'}")

    accruals_src = SRC / "accruals.json"
    if accruals_src.exists():
        data = condense_accruals(
            json.loads(accruals_src.read_text(encoding="utf-8"))
        )
        target = DEST / "workday_accruals.json"
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"wrote {target.relative_to(ROOT)}")
        for plan, accruals in data.items():
            print(f"   {plan}: {len(accruals)} accrual(s)")

    for name in ("hkg_annual_leave", "gbr_statutory_holiday"):
        src = SRC / f"{name}.json"
        if not src.exists():
            print(f"missing {src}")
            continue
        data = condense(src)
        target = DEST / f"workday_timeoffplan_{name}.json"
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"wrote {target.relative_to(ROOT)}")
        for tab, detail in data["tabs_detail"].items():
            print(f"   {tab}: {len(detail['grids'])} grid(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
