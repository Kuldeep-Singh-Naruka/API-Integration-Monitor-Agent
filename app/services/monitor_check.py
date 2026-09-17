"""
app/services/monitor_check.py
------------------------------
Thin adapter over the compiled LangGraph StateGraph.

This module preserves the original public API -- CheckResult dataclass and
check_monitored_api() signature -- so that tests/monitor_check_test.py
needs ZERO changes.  The orchestration logic now lives in app/agent/.

Dependency graph (imports flow downward, no cycles):
    monitor_check
        <- agent/graph      (compiled_monitor_graph)
        <- models           (MonitoredAPI, Alert)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from sqlalchemy.orm import Session

from app.agent.graph import compiled_monitor_graph
from app.models.alert import Alert
from app.models.monitored_api import MonitoredAPI


# ---------------------------------------------------------------------------
# Result type  (unchanged -- tests depend on this exact shape)
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
                raw content.  An Alert is always created for this status:
                either a "breaking" or "non-breaking" alert produced by LLM
                summarisation, or an "error" alert if summarisation itself
                failed (the diff is still captured in raw_diff in that case).
                ``old_content`` and ``new_content`` are populated in all
                "changed" outcomes.

        alert:       Set when status == "error" or status == "changed".
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

    Thin adapter that builds the initial MonitorState, invokes the compiled
    LangGraph StateGraph, and maps the final state back to a CheckResult.

    The CheckResult contract is identical to the pre-LangGraph implementation
    so that tests/monitor_check_test.py needs zero changes.

    Args:
        db:  An open SQLAlchemy Session.  Committed inside the graph nodes;
             the caller should not commit it separately.
        api: The MonitoredAPI ORM instance to check.  Its last_content_hash,
             last_checked_at, and last_raw_content fields are mutated
             in-place inside the graph nodes and persisted there.

    Returns:
        A CheckResult with one of four statuses:
            "error"               -- scrape failed; error alert created.
            "baseline_established" -- first ever scrape; baseline stored.
            "no_change"           -- content hash unchanged; no action taken.
            "changed"             -- new content detected; ChromaDB rebuilt;
                                     alert created (breaking/non-breaking from
                                     LLM, or error if summarisation failed).

    Raises:
        Any exception from chunk_markdown() or store_chunks() -- these
        indicate infrastructure or logic bugs and must not be silently
        swallowed (propagated from compare_node uncaught).
    """
    initial_state = {
        "db": db,
        "api": api,
        "old_hash": api.last_content_hash,
        "old_content": api.last_raw_content,
    }

    final_state = compiled_monitor_graph.invoke(initial_state)

    status: Literal["error", "baseline_established", "no_change", "changed"] = (
        final_state["status"]
    )

    # Resolve the Alert ORM object when an alert_id was stored.
    alert: Optional[Alert] = None
    alert_id: Optional[int] = final_state.get("alert_id")
    if alert_id is not None:
        alert = db.get(Alert, alert_id)

    # old_content / new_content are only meaningful on the "changed" path.
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    if status == "changed":
        old_content = initial_state["old_content"]
        new_content = final_state.get("stripped_content")

    return CheckResult(
        status=status,
        alert=alert,
        old_content=old_content,
        new_content=new_content,
    )
