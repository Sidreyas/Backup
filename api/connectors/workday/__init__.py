"""Workday connector — SOAP, RaaS and OAuth against a customer tenant."""

from api.connectors.workday.auth import WorkdayAuth, WorkdayCredentials
from api.connectors.workday.connector import WorkdayConnector
from api.connectors.workday.reports import (
    REPORT_PACK,
    REPORTS_BY_ID,
    TENANT_SETUP_STEPS,
    setup_checklist,
)

__all__ = [
    "REPORTS_BY_ID",
    "REPORT_PACK",
    "TENANT_SETUP_STEPS",
    "WorkdayAuth",
    "WorkdayConnector",
    "WorkdayCredentials",
    "setup_checklist",
]
