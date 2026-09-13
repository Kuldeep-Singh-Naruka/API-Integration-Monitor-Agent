"""
app/routers/internal.py
-----------------------
Internal-only endpoints intended to be called by the scheduled GitHub
Actions workflow (using a shared secret header), NOT by end users or the
frontend.  These routes are not part of the public API surface and should
not be referenced in any user-facing documentation.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.services.scheduler import run_all_checks


router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
)


@router.post(
    "/run-checks",
    summary="Run a check cycle for all active monitored APIs",
)
def run_checks(
    x_scheduler_secret: str = Header(..., alias="X-Scheduler-Secret"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Trigger one check cycle across all active MonitoredAPI rows.

    Iterates over every MonitoredAPI where ``is_active=True``, calls
    ``check_monitored_api()`` for each one, and returns a summary of the
    results.  Failures for individual APIs are isolated — one API's error
    never prevents the remaining APIs from being checked.

    Authentication:
        Requires the ``X-Scheduler-Secret`` request header to match the
        ``SCHEDULER_SECRET`` environment variable.  The comparison is done
        with ``secrets.compare_digest()`` to prevent timing-attack leakage
        of the secret value.

    Intended caller:
        The GitHub Actions workflow at ``.github/workflows/scheduled-check.yml``
        running on its daily cron schedule (or a manual ``workflow_dispatch``
        trigger for testing).

    Args:
        x_scheduler_secret: Value of the ``X-Scheduler-Secret`` request header.
        db: SQLAlchemy session injected by ``Depends(get_db)``.

    Returns:
        A JSON object with:

        - ``total_checked`` (int)  — number of active APIs processed.
        - ``results``       (list) — one entry per API, each containing
                                     ``api_id``, ``api_name``, and ``status``.

    Raises:
        HTTPException 401: If the ``X-Scheduler-Secret`` header does not match
                           ``settings.SCHEDULER_SECRET``.
    """
    # Use secrets.compare_digest() instead of == to avoid timing-attack
    # leakage that could allow an attacker to brute-force the secret by
    # measuring response time differences character by character.
    if not secrets.compare_digest(x_scheduler_secret, settings.SCHEDULER_SECRET):
        raise HTTPException(status_code=401, detail="Invalid scheduler secret.")

    results: list[dict[str, Any]] = run_all_checks(db)
    return {
        "total_checked": len(results),
        "results": results,
    }
