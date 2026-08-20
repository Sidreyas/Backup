"""
The domain model.

Importing this package registers **every** table on `Base.metadata`.

That matters because the model spans three modules with foreign keys across
them — `EvidenceArtifact` in `models.py` references `case_results` and
`test_runs`, which are defined in `stlc.py`. Importing only one module leaves
SQLAlchemy unable to resolve those keys, and the failure surfaces late and
confusingly: not at import, but at the first `flush()`, as
`NoReferencedTableError` naming a table the caller never mentioned.

Re-exporting here means `from api.domain import models` is sufficient for any
caller, and no one has to know the cross-module dependency exists.
"""

from __future__ import annotations

from api.domain import enums as enums
from api.domain import feasibility as feasibility
from api.domain import governance as governance
from api.domain import models as models
from api.domain import stlc as stlc

__all__ = ["enums", "feasibility", "governance", "models", "stlc"]
