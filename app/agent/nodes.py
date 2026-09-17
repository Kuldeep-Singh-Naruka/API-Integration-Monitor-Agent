"""
app/agent/nodes.py
------------------
The five node functions for the monitor StateGraph.

Each function receives the full ``MonitorState`` and returns a *partial* dict
that LangGraph merges back into the running state.  Side-effects (DB commits,
ChromaDB writes) happen inside the nodes, not in the graph wiring.

Dependency graph (imports flow downward, no cycles):
    nodes
        <- agent/llm          (classify_change, propose_fix)
        <- agent/tools        (search_change_context)
        <- services/scraper   (fetch_docs_content)
        <- services/vectorstore (strip_navigation_boilerplate, chunk_markdown,
                                 compute_content_hash, store_chunks)
        <- services/alerts    (create_alert_record)
        <- services/summarizer (compute_diff)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.agent.llm import classify_change, propose_fix
from app.agent.state import MonitorState
from app.agent.tools import search_change_context
from app.services.alerts import create_alert_record
from app.services.scraper import fetch_docs_content
from app.services.summarizer import compute_diff
from app.services.vectorstore import (
    chunk_markdown,
    compute_content_hash,
    store_chunks,
    strip_navigation_boilerplate,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. fetch_node
# ---------------------------------------------------------------------------


def fetch_node(state: MonitorState) -> dict:
    """Scrape the API docs URL and strip navigation boilerplate.

    On ``ValueError`` (Tavily failed): stamps ``api.last_checked_at``,
    commits, and returns ``status="error"`` so the router sends the graph
    straight to ``store_alert_node``.

    On success: returns ``raw_content`` and ``stripped_content``.
    """
    api = state["api"]
    db = state["db"]

    try:
        raw_content: str = fetch_docs_content(api.docs_url)
    except ValueError as exc:
        api.last_checked_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "status": "error",
            "error_message": f"Failed to fetch docs: {exc}",
        }

    stripped_content: str = strip_navigation_boilerplate(raw_content)
    return {
        "raw_content": raw_content,
        "stripped_content": stripped_content,
    }


# ---------------------------------------------------------------------------
# 2. compare_node
# ---------------------------------------------------------------------------


def compare_node(state: MonitorState) -> dict:
    """Hash the new content and compare to the stored hash.

    Always stamps ``api.last_checked_at``.  Never returns ``status="error"``
    -- hash/chunk/store exceptions other than ``ValueError`` from
    ``chunk_markdown``/``store_chunks`` propagate uncaught (real bugs).

    Three possible outcomes:
        - ``status="baseline_established"`` -- no previous hash; stores
          baseline to DB + ChromaDB.
        - ``status="no_change"``            -- hash unchanged; only commits
          last_checked_at.
        - ``status="changed"``              -- hash differs; rebuilds ChromaDB
          and updates DB.
    """
    api = state["api"]
    db = state["db"]
    stripped_content: str = state["stripped_content"]  # type: ignore[assignment]
    old_hash = state.get("old_hash")

    new_hash: str = compute_content_hash(stripped_content)
    api.last_checked_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # 3a: First-ever check -- establish baseline.
    # ------------------------------------------------------------------
    if old_hash is None:
        chunks = chunk_markdown(stripped_content)
        store_chunks(api.id, chunks)

        api.last_content_hash = new_hash
        api.last_raw_content = stripped_content
        db.commit()
        db.refresh(api)

        return {"new_hash": new_hash, "status": "baseline_established"}

    # ------------------------------------------------------------------
    # 3b: Hash unchanged.
    # ------------------------------------------------------------------
    if old_hash == new_hash:
        db.commit()
        return {"new_hash": new_hash, "status": "no_change"}

    # ------------------------------------------------------------------
    # 3c: Hash differs -- real content change.
    # ------------------------------------------------------------------
    chunks = chunk_markdown(stripped_content)
    store_chunks(api.id, chunks)

    api.last_content_hash = new_hash
    api.last_raw_content = stripped_content
    db.commit()
    db.refresh(api)

    return {"new_hash": new_hash, "status": "changed"}


# ---------------------------------------------------------------------------
# 3. summarize_node
# ---------------------------------------------------------------------------


def summarize_node(state: MonitorState) -> dict:
    """Compute a diff and classify the change with the LLM.

    Steps:
    1. Compute unified diff (``compute_diff``).  If ``old_content`` is None
       or ``compute_diff()`` raises, set ``severity="error"`` immediately and
       skip LLM calls.
    2. Fetch Tavily search context (best-effort -- any failure is logged and
       treated as empty string; it never escalates to ``severity="error"``).
    3. Call ``classify_change(diff, search_context)``.  On failure set
       ``severity="error"`` + explanatory summary.

    Returns a partial dict suitable for merging into ``MonitorState``.
    """
    api = state["api"]
    old_content = state.get("old_content")
    stripped_content: str = state["stripped_content"]  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Step 1: compute diff.
    # ------------------------------------------------------------------
    if old_content is None:
        return {
            "diff": None,
            "search_context": "",
            "severity": "error",
            "summary": (
                "Content changed (hash mismatch) but the previous content "
                "snapshot is missing -- cannot compute diff."
            ),
            "raw_diff_for_alert": None,
        }

    try:
        diff: str = compute_diff(old_content, stripped_content)
    except Exception as exc:
        return {
            "diff": None,
            "search_context": "",
            "severity": "error",
            "summary": f"Content changed but diff computation failed: {exc}",
            "raw_diff_for_alert": None,
        }

    # ------------------------------------------------------------------
    # Step 2: search context (best-effort, never escalates to error).
    # ------------------------------------------------------------------
    search_context: str = ""
    try:
        search_context = search_change_context(api.name)
    except Exception as exc:
        logger.warning(
            "search_change_context failed for api=%r, continuing with "
            "empty context. Error: %s",
            api.name,
            exc,
        )

    # ------------------------------------------------------------------
    # Step 3: classify with LLM.
    # ------------------------------------------------------------------
    try:
        classification = classify_change(diff, search_context)
    except Exception as exc:
        return {
            "diff": diff,
            "search_context": search_context,
            "severity": "error",
            "summary": f"Content changed but summarization failed: {exc}",
            "raw_diff_for_alert": diff,
        }

    return {
        "diff": diff,
        "search_context": search_context,
        "severity": classification.severity,
        "summary": classification.summary,
        "raw_diff_for_alert": diff,
    }


# ---------------------------------------------------------------------------
# 4. suggest_fix_node
# ---------------------------------------------------------------------------


def suggest_fix_node(state: MonitorState) -> dict:
    """Propose a concrete developer action for the detected change.

    Only reached when ``severity`` is ``"breaking"`` or ``"non-breaking"``
    (the router skips this node when ``severity="error"``).

    Calls ``propose_fix()`` and returns the result.  Exceptions propagate
    uncaught -- the graph's per-API isolation in the scheduler will catch them.
    """
    diff: str = state.get("diff") or ""
    search_context: str = state.get("search_context") or ""
    severity: str = state.get("severity") or ""
    summary: str = state.get("summary") or ""

    suggested_fix = propose_fix(diff, search_context, severity, summary)
    return {"suggested_fix": suggested_fix}


# ---------------------------------------------------------------------------
# 5. store_alert_node
# ---------------------------------------------------------------------------


def store_alert_node(state: MonitorState) -> dict:
    """Persist an Alert record based on the current graph outcome.

    Three shapes (per spec):

    (1) ``status == "error"``
        Scrape failed.  Alert has ``severity="error"``, ``summary`` from
        ``error_message``, no diff, no suggested_fix.

    (2) ``status == "changed"`` and ``severity == "error"``
        Summarisation failed after a real change was detected.  Alert has
        ``severity="error"``, ``summary`` and ``raw_diff`` from the summarise
        node, no suggested_fix.

    (3) ``status == "changed"`` and ``severity in {"breaking","non-breaking"}``
        Full successful path.  Alert includes severity, summary, raw_diff, and
        suggested_fix.

    Returns ``alert_id`` (the primary key of the created Alert row).
    """
    db = state["db"]
    api = state["api"]
    status = state.get("status")
    severity = state.get("severity")

    if status == "error":
        # Scrape failed -- error_message carries the human-readable reason.
        alert = create_alert_record(
            db=db,
            api_id=api.id,
            summary=state.get("error_message") or "Unknown scrape error.",
            severity="error",
            raw_diff=None,
            suggested_fix=None,
        )
    elif status == "changed" and severity == "error":
        # Summarisation failed after a real change.
        alert = create_alert_record(
            db=db,
            api_id=api.id,
            summary=state.get("summary") or "Summarisation failed.",
            severity="error",
            raw_diff=state.get("raw_diff_for_alert"),
            suggested_fix=None,
        )
    else:
        # Full happy path: breaking or non-breaking change with full metadata.
        alert = create_alert_record(
            db=db,
            api_id=api.id,
            summary=state.get("summary") or "",
            severity=severity or "error",
            raw_diff=state.get("raw_diff_for_alert"),
            suggested_fix=state.get("suggested_fix"),
        )

    return {"alert_id": alert.id}
