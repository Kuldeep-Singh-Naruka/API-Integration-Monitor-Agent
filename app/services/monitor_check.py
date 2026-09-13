"""
app/services/monitor_check.py
------------------------------
Orchestration layer that ties scraping, change-detection, ChromaDB storage,
and alert creation together into a single, testable function.

This module sits between the scheduler (next task) and the lower-level
service modules.  It never imports from app.routers and has no FastAPI
dependencies -- it is a pure service layer.

Dependency graph (imports flow downward, no cycles):
    monitor_check
        <- scraper          (fetch_docs_content)
        <- vectorstore      (strip_navigation_boilerplate, chunk_markdown,
                             compute_content_hash, store_chunks)
        <- alerts           (create_alert_record)
        <- models           (MonitoredAPI, Alert)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.monitored_api import MonitoredAPI
from app.services.alerts import create_alert_record
from app.services.scraper import fetch_docs_content
from app.services.vectorstore import (
    chunk_markdown,
    compute_content_hash,
    store_chunks,
    strip_navigation_boilerplate,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Outcome of one check_monitored_api() call for a single API.

    Attributes:
        status: One of four terminal states:

            "error"
                Scraping failed (Tavily raised ValueError).  An Alert row
                with severity="error" has already been created.  The
                ``alert`` field holds that record.

            "baseline_established"
                First successful scrape for this API -- no previous hash
                existed to compare against.  The content has been embedded
                into ChromaDB and the hash + raw content saved to Postgres.
                No Alert is created (nothing to compare).

            "no_change"
                Hash matches the stored value -- the docs have not changed
                since the last check.  ChromaDB and Postgres are untouched
                (last_checked_at is still updated so the timestamp stays
                current).

            "changed"
                Hash differs from the stored value -- a real content change
                was detected.  ChromaDB has been fully rebuilt with the new
                chunks and Postgres has been updated with the new hash and
                raw content.  ``old_content`` and ``new_content`` are
                populated for the LLM summarization step (next task).
                No Alert is created here -- the severity decision
                (breaking vs non-breaking) requires LLM analysis.

        alert:       Set only when status == "error".
        old_content: Set only when status == "changed".  The stripped text
                     from the *previous* successful scrape, read from
                     MonitoredAPI.last_raw_content before it was overwritten.
        new_content: Set only when status == "changed".  The stripped text
                     from the current scrape.
    """

    status: Literal["error", "baseline_established", "no_change", "changed"]
    alert: Optional[Alert] = field(default=None)
    old_content: Optional[str] = field(default=None)
    new_content: Optional[str] = field(default=None)


# ---------------------------------------------------------------------------
# Orchestration function
# ---------------------------------------------------------------------------

def check_monitored_api(db: Session, api: MonitoredAPI) -> CheckResult:
    """Run one full check cycle for a single monitored API.

    This function is the central orchestration point called by the scheduler
    on every poll interval.  It always returns a CheckResult and never lets
    exceptions propagate to the caller, *except* for errors from
    chunk_markdown() and store_chunks() -- those indicate real bugs (not
    expected network/availability failures) and should surface as unhandled
    exceptions so they are visible in logs/Sentry.

    Assumptions:
        - ``api`` is a live, attached SQLAlchemy ORM instance bound to ``db``.
        - ``db`` is an active Session; this function commits it internally.
        - The caller is responsible for filtering to only active APIs
          (is_active == True) before calling this function.

    Args:
        db:  An open SQLAlchemy Session.  Committed inside this function;
             the caller should not commit it separately.
        api: The MonitoredAPI ORM instance to check.  Its last_content_hash,
             last_checked_at, and last_raw_content fields are mutated
             in-place and persisted.

    Returns:
        A CheckResult with one of four statuses:
            "error"               -- scrape failed; error alert created.
            "baseline_established" -- first ever scrape; baseline stored.
            "no_change"           -- content hash unchanged; no action taken.
            "changed"             -- new content detected; ChromaDB rebuilt;
                                     old/new content returned for LLM step.

    Raises:
        Any exception from chunk_markdown() or store_chunks() -- these
        indicate infrastructure or logic bugs and must not be silently
        swallowed.
    """
    _utcnow: datetime = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Step 1: Attempt scrape.
    # ------------------------------------------------------------------
    try:
        raw_content: str = fetch_docs_content(api.docs_url)
    except ValueError as exc:
        # Scrape failed (URL unreachable, auth wall, Tavily error, etc.).
        # Update last_checked_at so operators can see when the last attempt
        # ran, then persist an error-severity Alert.
        api.last_checked_at = _utcnow
        db.commit()

        error_alert: Alert = create_alert_record(
            db=db,
            api_id=api.id,
            summary=f"Failed to fetch docs: {exc}",
            severity="error",
            raw_diff=None,
        )
        return CheckResult(status="error", alert=error_alert)

    # ------------------------------------------------------------------
    # Step 2: Strip boilerplate and compute the hash of the new content.
    # ------------------------------------------------------------------
    stripped: str = strip_navigation_boilerplate(raw_content)
    new_hash: str = compute_content_hash(stripped)

    # Read both change-detection fields *before* overwriting them so we
    # have the previous values available for the diff/return path.
    old_hash: Optional[str] = api.last_content_hash
    old_content: Optional[str] = api.last_raw_content

    # Always stamp last_checked_at -- regardless of which branch below runs.
    api.last_checked_at = _utcnow

    # ------------------------------------------------------------------
    # Step 3a: First-ever successful check -- establish the baseline.
    # ------------------------------------------------------------------
    if old_hash is None:
        chunks: list[str] = chunk_markdown(stripped)
        store_chunks(api.id, chunks)

        api.last_content_hash = new_hash
        api.last_raw_content = stripped
        db.commit()
        db.refresh(api)

        return CheckResult(status="baseline_established")

    # ------------------------------------------------------------------
    # Step 3b: Hash unchanged -- docs have not changed.
    # ------------------------------------------------------------------
    if old_hash == new_hash:
        # Only last_checked_at was mutated; commit it.
        db.commit()
        return CheckResult(status="no_change")

    # ------------------------------------------------------------------
    # Step 3c: Hash differs -- real content change detected.
    # ------------------------------------------------------------------
    chunks = chunk_markdown(stripped)
    store_chunks(api.id, chunks)  # Fully replaces the ChromaDB collection.

    api.last_content_hash = new_hash
    api.last_raw_content = stripped
    db.commit()
    db.refresh(api)

    # Return old and new content for the LLM summarization step (next task).
    # No Alert is created here -- severity (breaking vs non-breaking) requires
    # LLM analysis that does not exist yet.
    return CheckResult(
        status="changed",
        old_content=old_content,
        new_content=stripped,
    )
