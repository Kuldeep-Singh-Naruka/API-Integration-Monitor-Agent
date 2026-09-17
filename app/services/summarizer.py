"""
app/services/summarizer.py
--------------------------
Diff utility for the API Integration Monitor.

Provides one public callable:

    compute_diff(old_content, new_content) -> str
        Generates a unified diff between two documentation snapshots and
        truncates it if it exceeds a configurable character limit.

LLM-based summarisation (classify_change, propose_fix) and the raw Groq SDK
usage have been moved to app/agent/llm.py.  The model used is
qwen/qwen3.8-27b, accessed via langchain_groq.ChatGroq.

Dependency graph (imports flow downward, no cycles):
    summarizer
        (no external dependencies -- pure Python)
"""

from __future__ import annotations

import difflib


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def compute_diff(
    old_content: str,
    new_content: str,
    max_chars: int = 6000,
) -> str:
    """Generate a unified diff between two documentation snapshots.

    Splits both strings on newlines, computes the standard unified diff
    (labelled "previous_version" and "current_version"), and joins the
    result into a single string.  If the diff exceeds ``max_chars``, it
    is truncated and annotated so downstream consumers know it is partial.

    Args:
        old_content: The previous version of the stripped documentation text.
        new_content: The current version of the stripped documentation text.
        max_chars:   Maximum number of characters to include in the returned
                     string before truncation.  Defaults to 6 000 characters,
                     which comfortably fits in the Groq context window while
                     leaving room for the system prompt and response.

    Returns:
        A unified-diff string, possibly truncated with an appended notice.

    Raises:
        ValueError: If old_content and new_content are identical.  This
                    function must never be called when nothing changed --
                    an empty diff indicates a caller bug.
    """
    if old_content == new_content:
        raise ValueError(
            "compute_diff() called with identical old_content and new_content. "
            "This function must only be called when a real content change has "
            "already been confirmed (e.g. by a hash comparison). An empty diff "
            "indicates a caller bug."
        )

    diff_lines: list[str] = list(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile="previous_version",
            tofile="current_version",
        )
    )

    diff_text: str = "".join(diff_lines)

    if len(diff_text) > max_chars:
        diff_text = diff_text[:max_chars] + "\n[... diff truncated for length ...]"

    return diff_text
