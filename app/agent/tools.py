"""
app/agent/tools.py
------------------
Tavily *search* step for the monitor agent.

This module is intentionally distinct from ``scraper.py``, which uses
Tavily's *extract* API to fetch raw documentation page content.  Here we use
Tavily's *search* API to retrieve contextual snippets about recent API
changes — a different operation with a different contract.

The query is derived from the API name only (not the diff), because the diff
is too long and noisy to produce useful search results.
"""

from __future__ import annotations

import logging

from tavily import TavilyClient

from app.core.config import settings

logger = logging.getLogger(__name__)


def search_change_context(api_name: str, max_results: int = 3) -> str:
    """Search for recent changelog / breaking-change context for an API.

    Calls ``TavilyClient.search()`` (not ``.extract()``) with a fixed query
    built from the API name.  The query intentionally does NOT include the
    diff — the diff is too long and noisy for a useful web search.

    Args:
        api_name:    The human-readable name of the monitored API (e.g.
                     ``"Stripe"`` or ``"OpenAI"``).
        max_results: Maximum number of search result snippets to include.
                     Defaults to 3.

    Returns:
        A newline-joined string of result snippets, or ``""`` if the search
        returned no usable results.

    Raises:
        Any exception originating from a real network or authentication
        failure.  The caller (``summarize_node``) treats this as best-effort
        and catches all exceptions, continuing with ``""`` instead.
    """
    client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    query = f"{api_name} API changelog breaking changes"

    response = client.search(query=query, max_results=max_results)

    results: list[dict] = response.get("results", [])
    snippets: list[str] = []
    for result in results:
        content: str = result.get("content", "").strip()
        if content:
            snippets.append(content)

    return "\n".join(snippets)
