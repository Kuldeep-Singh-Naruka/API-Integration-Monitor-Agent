"""
app/agent/graph.py
------------------
StateGraph definition and compiled singleton for the monitor agent.

Wiring:
    fetch_node
        -- route_after_fetch --> compare_node | store_alert_node
    compare_node
        -- route_after_compare --> summarize_node | END
    summarize_node
        -- route_after_summarize --> suggest_fix_node | store_alert_node
    suggest_fix_node  -->  store_alert_node  (fixed edge)
    store_alert_node  -->  END               (fixed edge)

No checkpointer is used because ``MonitorState`` holds live SQLAlchemy
Session and ORM objects that are not serialisable.

Note on explicit ``path_map`` dicts
------------------------------------
All three ``add_conditional_edges()`` calls below include an explicit
``path_map`` as the third argument.  Without it LangGraph cannot statically
infer the possible destination nodes, so ``compiled_monitor_graph.get_graph()
.draw_mermaid()`` would render a broken diagram (only ``fetch_node → __end__``,
all other nodes disconnected).  The routing functions' return values already
match these keys exactly — the path_maps add no runtime logic, only static
graph metadata.
"""

from __future__ import annotations

from langgraph.constants import END
from langgraph.graph import StateGraph

from app.agent.nodes import (
    compare_node,
    fetch_node,
    store_alert_node,
    suggest_fix_node,
    summarize_node,
)
from app.agent.state import MonitorState


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def route_after_fetch(state: MonitorState) -> str:
    """Route after fetch_node.

    ``status == "error"`` → ``store_alert_node`` (skip remaining processing).
    Otherwise → ``compare_node``.
    """
    if state.get("status") == "error":
        return "store_alert_node"
    return "compare_node"


def route_after_compare(state: MonitorState) -> str:
    """Route after compare_node.

    ``status == "changed"`` → ``summarize_node``.
    Otherwise (``baseline_established`` or ``no_change``) → ``END`` (no alert
    needed; no further nodes run).
    """
    if state.get("status") == "changed":
        return "summarize_node"
    return END


def route_after_summarize(state: MonitorState) -> str:
    """Route after summarize_node.

    ``severity == "error"`` → ``store_alert_node`` (skip fix suggestion).
    Otherwise → ``suggest_fix_node``.
    """
    if state.get("severity") == "error":
        return "store_alert_node"
    return "suggest_fix_node"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_monitor_graph():
    """Build and compile the monitor StateGraph.

    Returns a compiled LangGraph runnable.  Compiled WITHOUT a checkpointer
    because ``MonitorState`` holds non-serialisable SQLAlchemy objects.
    """
    graph = StateGraph(MonitorState)

    # --- Nodes ---
    graph.add_node("fetch_node", fetch_node)
    graph.add_node("compare_node", compare_node)
    graph.add_node("summarize_node", summarize_node)
    graph.add_node("suggest_fix_node", suggest_fix_node)
    graph.add_node("store_alert_node", store_alert_node)

    # --- Entry point ---
    graph.set_entry_point("fetch_node")

    # --- Conditional edges (explicit path_map enables static graph analysis) ---
    graph.add_conditional_edges(
        "fetch_node",
        route_after_fetch,
        {"compare_node": "compare_node", "store_alert_node": "store_alert_node"},
    )
    graph.add_conditional_edges(
        "compare_node",
        route_after_compare,
        {"summarize_node": "summarize_node", END: END},
    )
    graph.add_conditional_edges(
        "summarize_node",
        route_after_summarize,
        {"suggest_fix_node": "suggest_fix_node", "store_alert_node": "store_alert_node"},
    )

    # --- Fixed edges ---
    graph.add_edge("suggest_fix_node", "store_alert_node")
    graph.add_edge("store_alert_node", END)

    # Compile WITHOUT checkpointer -- SQLAlchemy objects are not serialisable.
    return graph.compile()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

compiled_monitor_graph = build_monitor_graph()
