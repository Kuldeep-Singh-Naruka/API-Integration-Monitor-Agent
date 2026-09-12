"""
app/services/alerts.py
----------------------
Shared service functions for Alert persistence.

Keeping insert logic here (rather than inline in the router) lets the
future scheduler create Alert rows without going through the HTTP layer.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.alert import Alert


def create_alert_record(
    db: Session,
    api_id: int,
    summary: str,
    severity: str,
    raw_diff: Optional[str] = None,
) -> Alert:
    """Insert and return a new Alert row for the given api_id.

    This function assumes api_id has already been validated by the
    caller (e.g. the router's 404 check, or the scheduler having just
    read it from an existing MonitoredAPI row).  It does not query
    MonitoredAPI itself -- callers are responsible for that check if
    they need it.

    Args:
        db:       An active SQLAlchemy Session (provided by Depends(get_db)
                  in the router, or opened directly by the scheduler).
        api_id:   Primary key of the MonitoredAPI this alert belongs to.
        summary:  Human-readable description of the change or failure.
        severity: One of "breaking", "non-breaking", or "error".
                  The caller is expected to pass a value that matches
                  the SeverityLiteral type defined in alert_schema.py.
        raw_diff: Optional unified-diff or change payload.  Should be
                  None when severity is "error" (no diff is available).

    Returns:
        The freshly committed and refreshed Alert ORM instance.
    """
    new_alert = Alert(
        api_id=api_id,
        summary=summary,
        severity=severity,
        raw_diff=raw_diff,
    )
    db.add(new_alert)
    db.commit()
    db.refresh(new_alert)
    return new_alert
