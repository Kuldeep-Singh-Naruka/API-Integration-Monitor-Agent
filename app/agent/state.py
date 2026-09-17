"""
app/agent/state.py
------------------
Shared state type for the monitor StateGraph.

``MonitorState`` is a TypedDict with ``total=False`` so that every node can
return a *partial* dict and LangGraph will merge it into the running state.

IMPORTANT: ``db`` and ``api`` are live SQLAlchemy objects and are NOT
serialisable.  The compiled graph must therefore use NO checkpointer
(``graph.compile()`` with no arguments).  This is enforced in graph.py.

Type annotations for ``db`` and ``api`` use ``Any`` so that LangGraph's
runtime ``get_type_hints()`` call (which resolves all annotations eagerly)
does not fail on forward references to SQLAlchemy types that aren't importable
at module-load time in all contexts.  The actual runtime types are correct --
the ``Any`` is purely a concession to LangGraph's introspection.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from typing_extensions import TypedDict


class MonitorState(TypedDict, total=False):
    """Complete intermediate state threaded through the monitor graph.

    Fields populated by each node:

    fetch_node        -> raw_content, stripped_content
                         (on error -> status, error_message)

    compare_node      -> new_hash, status
                         (on "changed" also stores to DB and Chroma)

    summarize_node    -> diff, search_context, severity, summary,
                         raw_diff_for_alert

    suggest_fix_node  -> suggested_fix

    store_alert_node  -> alert_id

    The ``db`` and ``api`` fields are set once in the initial state and
    passed through every node without modification.
    """

    # --- Pass-through (set by the adapter, never mutated by nodes) ---
    # Typed as Any so LangGraph's get_type_hints() does not fail resolving
    # forward refs to SQLAlchemy types.  Runtime types are Session / MonitoredAPI.
    db: Any  # sqlalchemy.orm.Session
    api: Any  # app.models.monitored_api.MonitoredAPI

    # --- Pre-loaded from DB before graph invocation ---
    old_hash: Optional[str]
    old_content: Optional[str]

    # --- fetch_node outputs ---
    raw_content: Optional[str]
    stripped_content: Optional[str]

    # --- compare_node outputs ---
    new_hash: Optional[str]
    status: Literal["error", "baseline_established", "no_change", "changed"]

    # --- error path ---
    error_message: Optional[str]

    # --- summarize_node outputs ---
    diff: Optional[str]
    search_context: Optional[str]
    severity: Optional[Literal["breaking", "non-breaking", "error"]]
    summary: Optional[str]
    raw_diff_for_alert: Optional[str]

    # --- suggest_fix_node outputs ---
    suggested_fix: Optional[str]

    # --- store_alert_node outputs ---
    alert_id: Optional[int]
