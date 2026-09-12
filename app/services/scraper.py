"""
app/services/scraper.py
-----------------------
Tavily-based documentation scraper.

Used by Week-2 modules (ChromaDB ingestion, diff logic) to fetch clean
Markdown text from API documentation pages.  This module is intentionally
free of FastAPI routing concerns -- it is a pure service layer.
"""

from __future__ import annotations

from tavily import TavilyClient

from app.core.config import settings


def fetch_docs_content(url: str) -> str:
    """Fetch and return the clean text content of an API documentation
    page at the given URL, using Tavily's Extract API.

    Uses ``extract_depth="advanced"`` and ``format="markdown"`` because API
    docs pages are often JS-rendered and contain tables/code blocks that
    basic extraction would drop.

    Args:
        url: The fully-qualified URL of the documentation page to scrape.

    Returns:
        A non-empty Markdown string with the page's textual content.

    Raises:
        ValueError: If the URL could not be extracted (Tavily returned it in
            ``failed_results``) or if extraction succeeded but returned
            empty / whitespace-only content.
    """
    client: TavilyClient = TavilyClient(api_key=settings.TAVILY_API_KEY)

    response: dict = client.extract(
        urls=url,
        extract_depth="advanced",
        format="markdown",
    )

    # Check for extraction failure before accessing results.
    failed: list[dict] = response.get("failed_results", [])
    for failure in failed:
        if failure.get("url") == url:
            reason: str = failure.get("error", "unknown error")
            raise ValueError(
                f"Tavily failed to extract content from '{url}': {reason}"
            )

    results: list[dict] = response.get("results", [])
    if not results:
        raise ValueError(
            f"Tavily returned no results for '{url}' "
            "(response contained neither results nor a failure entry)."
        )

    raw_content: str = results[0].get("raw_content", "")
    content: str = raw_content.strip()

    if not content:
        raise ValueError(
            f"Tavily extracted empty content from '{url}'. "
            "The page may require authentication or block automated access."
        )

    return content
