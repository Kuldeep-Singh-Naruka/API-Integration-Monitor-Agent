"""
app/services/summarizer.py
--------------------------
LLM-based change summarisation using the Groq API.

Provides two public callables:

    compute_diff(old_content, new_content) -> str
        Generates a unified diff between two documentation snapshots and
        truncates it if it exceeds a configurable character limit.

    summarize_change(diff) -> ChangeSummary
        Sends the diff to the Groq LLM and parses the structured JSON
        response into a typed ChangeSummary dataclass.

Both functions follow the same defensive error-handling style as
fetch_docs_content(): they raise ValueError with a clear, descriptive
message on any malformed or unexpected result -- they never silently
return something wrong-shaped.

Dependency graph (imports flow downward, no cycles):
    summarizer
        <- app.core.config  (settings.GROQ_API_KEY)
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from typing import Literal, Optional, cast

from groq import Groq

from app.core.config import settings


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ChangeSummary:
    """Structured result produced by summarize_change().

    Attributes:
        severity:      "breaking" if the change could break existing
                       integrations (removed/renamed fields or endpoints,
                       changed required parameters, changed response shapes);
                       "non-breaking" if the change is purely additive or
                       clarifying (new optional fields, wording improvements).
        summary:       A concise 1-3 sentence human-readable explanation of
                       what changed and why it matters.
        suggested_fix: A short, concrete suggestion for what a developer
                       should check or update in their own integration because
                       of this change.  If no code change is likely needed,
                       this will say so briefly.
    """

    severity: Literal["breaking", "non-breaking"]
    summary: str
    suggested_fix: Optional[str]


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT: str = (
    "You will receive a unified diff of a third-party API's documentation. "
    "You must respond with ONLY a single JSON object with exactly three keys:\n\n"
    '  "severity": Must be exactly the string "breaking" or "non-breaking". '
    "Breaking means existing integrations could stop working -- for example: "
    "removed or renamed fields or endpoints, changed required parameters, "
    "changed response shapes. Non-breaking means the change is purely "
    "additive or clarifying -- for example: new optional fields, wording "
    "improvements.\n\n"
    '  "summary": A concise 1-3 sentence human-readable explanation of what '
    "changed and why it matters.\n\n"
    '  "suggested_fix": A short, concrete suggestion for what a developer '
    "should check or update in their own integration because of this change. "
    "If no code change is likely needed, say so briefly.\n\n"
    "No text outside the JSON object."
)

_GROQ_MODEL: str = "qwen/qwen3.8-27b"

# Regex that strips optional ```json ... ``` or ``` ... ``` fences from the
# model response before attempting JSON parsing, in case the model does not
# perfectly honour the json_object format instruction.
_CODE_FENCE_RE: re.Pattern[str] = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.DOTALL,
)

_VALID_SEVERITIES: frozenset[str] = frozenset({"breaking", "non-breaking"})
_REQUIRED_KEYS: frozenset[str] = frozenset({"severity", "summary", "suggested_fix"})


# ---------------------------------------------------------------------------
# Public functions
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


def summarize_change(diff: str) -> ChangeSummary:
    """Call the Groq LLM to classify and explain a documentation diff.

    Sends the diff to the Groq API using the llama-3.3-70b-versatile model
    with a structured system prompt that demands a JSON-only response.  The
    response is parsed defensively: markdown code fences are stripped before
    JSON parsing, and the three required keys and a valid severity value are
    all validated before a ChangeSummary is returned.

    Args:
        diff: A unified-diff string, typically produced by compute_diff().

    Returns:
        A ChangeSummary dataclass with severity, summary, and suggested_fix.

    Raises:
        ValueError: If the Groq response is not valid JSON, is missing any
                    of the three required keys ("severity", "summary",
                    "suggested_fix"), or if "severity" is not exactly
                    "breaking" or "non-breaking".  Severity values are never
                    silently coerced or defaulted.
    """
    client: Groq = Groq(api_key=settings.GROQ_API_KEY)

    completion = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": diff},
        ],
        response_format={"type": "json_object"},
        reasoning_effort="none",
        reasoning_format="hidden",
    )

    raw_text: str = completion.choices[0].message.content or ""

    # Strip markdown code fences in case the model wraps its JSON output.
    fence_match: re.Match[str] | None = _CODE_FENCE_RE.match(raw_text)
    cleaned_text: str = fence_match.group(1) if fence_match else raw_text.strip()

    # --- Parse JSON ---
    try:
        parsed: object = json.loads(cleaned_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Groq response is not valid JSON. "
            f"Parse error: {exc}. "
            f"Raw response text (first 500 chars): {raw_text[:500]!r}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Groq response parsed as JSON but is not a dict "
            f"(got {type(parsed).__name__}). "
            f"Raw response text (first 500 chars): {raw_text[:500]!r}"
        )

    # Cast to dict[str, object] so that all key accesses below return `object`
    # (not `Unknown`).  json.loads() returns Any, and Pylance widens that to
    # Unknown after the isinstance narrowing; the cast is purely for the type
    # checker -- no runtime cost.
    parsed_dict: dict[str, object] = cast(dict[str, object], parsed)

    # --- Validate required keys ---
    missing_keys: frozenset[str] = _REQUIRED_KEYS - parsed_dict.keys()
    if missing_keys:
        raise ValueError(
            f"Groq response JSON is missing required key(s): {sorted(missing_keys)}. "
            f"Present keys: {sorted(parsed_dict.keys())}. "
            f"Raw response text (first 500 chars): {raw_text[:500]!r}"
        )

    # --- Validate severity ---
    severity_raw: object = parsed_dict["severity"]
    if severity_raw not in _VALID_SEVERITIES:
        raise ValueError(
            f"Groq response 'severity' field has an invalid value: {severity_raw!r}. "
            f"Expected exactly 'breaking' or 'non-breaking'. "
            f"Coercing or defaulting an invalid severity is not permitted -- "
            f"the LLM response must be corrected."
        )

    # severity_raw is now known to be one of the two valid literals; cast so
    # the return type matches ChangeSummary.severity exactly.
    severity: Literal["breaking", "non-breaking"] = cast(
        Literal["breaking", "non-breaking"], severity_raw
    )

    # suggested_fix may be null in the JSON (model said no fix needed) or a
    # non-empty string.  Coerce to str | None explicitly so the type is clear.
    raw_fix: object = parsed_dict["suggested_fix"]
    suggested_fix: Optional[str] = str(raw_fix) if raw_fix else None

    return ChangeSummary(
        severity=severity,
        summary=str(parsed_dict["summary"]),
        suggested_fix=suggested_fix,
    )
