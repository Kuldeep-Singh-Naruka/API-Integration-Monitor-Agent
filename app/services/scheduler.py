"""
app/services/scheduler.py
--------------------------
Batch orchestration layer for the scheduled check runner.

This module contains the business logic for one complete check cycle
across every active MonitoredAPI row.  It is intentionally kept as a
pure service function (no FastAPI imports) so it can be unit-tested and
reused independently of the HTTP layer.

Dependency graph (no cycles):
    scheduler
        <- monitor_check  (check_monitored_api, CheckResult)
        <- alerts         (create_alert_record)
        <- models         (MonitoredAPI)
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.monitored_api import MonitoredAPI
from app.services.alerts import create_alert_record
from app.services.monitor_check import check_monitored_api


def run_all_checks(db: Session) -> list[dict[str, Any]]:
    """Run check_monitored_api() for every active (is_active=True) MonitoredAPI row.

    Failures are isolated per-API: if check_monitored_api() raises an
    unexpected exception for one API (e.g. a bug in chunk_markdown or
    store_chunks that check_monitored_api deliberately lets propagate),
    the error is recorded as an "error"-severity Alert so it is visible
    through the REST API, and the loop continues with the next API.

    Does not commit or rollback the session itself beyond what
    check_monitored_api() and create_alert_record() already do internally.

    Args:
        db: An active SQLAlchemy Session, typically provided by Depends(get_db).
            This session is shared across the entire batch; each inner call
            commits it independently.

    Returns:
        A list of one dict per API that was processed during this cycle.
        Each dict contains:

        - ``api_id``   (int)  — primary key of the MonitoredAPI row.
        - ``api_name`` (str)  — human-readable name for logging / response bodies.
        - ``status``   (str)  — the CheckResult.status string returned by
                                check_monitored_api(), or ``"unexpected_error"``
                                when the try/except block caught an unhandled
                                exception before check_monitored_api() could
                                return a result.
    """
    active_apis: list[MonitoredAPI] = (
        db.query(MonitoredAPI)
        .filter(MonitoredAPI.is_active == True)  # noqa: E712 — SQLAlchemy requires == not `is`
        .all()
    )

    results: list[dict[str, Any]] = []

    for api in active_apis:
        try:
            check_result = check_monitored_api(db, api)
            results.append(
                {
                    "api_id": api.id,
                    "api_name": api.name,
                    "status": check_result.status,
                }
            )
        except Exception as exc:
            # check_monitored_api deliberately lets chunk_markdown / store_chunks
            # exceptions propagate so they surface in logs.  We catch them here
            # at the batch level to keep the rest of the APIs running, and
            # persist an error-severity Alert so the failure is visible through
            # the REST API and not just buried in server logs.
            create_alert_record(
                db=db,
                api_id=api.id,
                summary=f"Unexpected error during scheduled check: {exc}",
                severity="error",
                raw_diff=None,
            )
            results.append(
                {
                    "api_id": api.id,
                    "api_name": api.name,
                    "status": "unexpected_error",
                }
            )

    return results
