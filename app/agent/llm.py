"""
app/agent/llm.py
----------------
LangChain-based LLM helpers for the monitor agent.

Replaces the raw ``groq`` SDK usage in the old ``summarizer.py``.  Uses the
same model and reasoning parameters as before (qwen/qwen3.8-27b,
reasoning_effort="none", reasoning_format="hidden") but delivered via
``langchain_groq.ChatGroq`` with ``.with_structured_output()`` so that Pydantic
validation replaces all manual JSON parsing, code-fence stripping, key checks,
and severity checks.

Design note on ``reasoning_format="hidden"``
--------------------------------------------
``langchain-groq`` passes unknown constructor kwargs through as ``model_kwargs``
which the underlying ``groq`` SDK forwards in the request body.  The
``reasoning_format="hidden"`` param suppresses reasoning tokens in the raw
completion, which is what we want even when the model is invoked via tool-
calling (the mechanism used by ``with_structured_output``).  The combination
is valid per Groq's API spec.
"""

from __future__ import annotations

from typing import Literal, Optional

from langchain_groq import ChatGroq
from pydantic import BaseModel

from app.core.config import settings

_GROQ_MODEL: str = "qwen/qwen3.8-27b"


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------


def get_groq_chat_model() -> ChatGroq:
    """Return a fresh ``ChatGroq`` instance with the project's standard params.

    Uses ``qwen/qwen3.8-27b`` with ``reasoning_effort="none"`` and
    ``reasoning_format="hidden"`` so the model returns concise answers without
    emitting reasoning tokens.  ``api_key`` is pulled from settings so the
    model is never constructed with a hard-coded secret.
    """
    return ChatGroq(
        model=_GROQ_MODEL,
        api_key=settings.GROQ_API_KEY,  # type: ignore[arg-type]
        max_tokens=500,
        # These are forwarded to the Groq API as extra body params.
        # reasoning_effort="none"  → fastest response, no chain-of-thought.
        # reasoning_format="hidden" → reasoning tokens suppressed from output,
        #   which also applies when the model is invoked in tool-calling mode
        #   (as used by with_structured_output).
        reasoning_effort="none",  # type: ignore[call-arg]
        reasoning_format="hidden",  # type: ignore[call-arg]
    )


# ---------------------------------------------------------------------------
# Pydantic output schemas
# ---------------------------------------------------------------------------


class SeverityClassification(BaseModel):
    """Structured output for the classify_change call.

    Deliberately excludes ``suggested_fix``; that is handled by a separate
    ``propose_fix`` call so the two responsibilities stay cleanly separated.
    """

    severity: Literal["breaking", "non-breaking"]
    summary: str


class SuggestedFix(BaseModel):
    """Structured output for the propose_fix call.

    ``suggested_fix`` is Optional so the model can return ``null`` when no
    developer action is required.
    """

    suggested_fix: Optional[str] = None


# ---------------------------------------------------------------------------
# Prompts (module-level constants)
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM: str = (
    "You will receive a unified diff of a third-party API's documentation "
    "and optional web-search context about recent API changes.\n\n"
    "Classify the change:\n\n"
    "  severity: exactly \"breaking\" or \"non-breaking\".\n"
    "    Breaking = existing integrations could stop working (removed/renamed "
    "fields or endpoints, changed required parameters, changed response shapes).\n"
    "    Non-breaking = purely additive or clarifying (new optional fields, "
    "wording improvements).\n\n"
    "  summary: A concise 1-3 sentence human-readable explanation of what "
    "changed and why it matters."
)

_FIX_SYSTEM: str = (
    "You will receive a unified diff, optional search context, the severity "
    "classification, and a summary of an API documentation change.\n\n"
    "Provide a short, concrete suggestion for what a developer should check or "
    "update in their own integration because of this change.\n"
    "If no code change is likely needed, say so briefly.\n"
    "Return null for suggested_fix only when truly no action is required."
)


# ---------------------------------------------------------------------------
# Public callable helpers
# ---------------------------------------------------------------------------


def classify_change(diff: str, search_context: str) -> SeverityClassification:
    """Classify a documentation diff as breaking or non-breaking.

    Uses ``ChatGroq.with_structured_output(SeverityClassification)`` so
    Pydantic validation enforces the schema — no manual JSON/key/severity
    checks needed.  Raises on any LLM or validation failure (same contract as
    the old ``summarize_change()``).

    Args:
        diff:           Unified-diff string produced by ``compute_diff()``.
        search_context: Newline-joined Tavily search snippets (may be empty).

    Returns:
        A ``SeverityClassification`` with ``severity`` and ``summary``.

    Raises:
        Any exception from the LLM call or Pydantic validation.
    """
    llm = get_groq_chat_model()
    chain = llm.with_structured_output(SeverityClassification)

    user_content = f"## Diff\n{diff}"
    if search_context:
        user_content += f"\n\n## Search context\n{search_context}"

    result = chain.invoke(
        [
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": user_content},
        ]
    )
    return result  # type: ignore[return-value]


def propose_fix(
    diff: str,
    search_context: str,
    severity: str,
    summary: str,
) -> Optional[str]:
    """Suggest a concrete developer action for an API change.

    Uses a separate ``ChatGroq.with_structured_output(SuggestedFix)`` call so
    the fix suggestion is decoupled from the severity classification.

    Args:
        diff:           Unified-diff string.
        search_context: Newline-joined Tavily search snippets (may be empty).
        severity:       The severity string from ``classify_change()``.
        summary:        The summary string from ``classify_change()``.

    Returns:
        A string with the suggested fix, or ``None`` if no action is needed.

    Raises:
        Any exception from the LLM call or Pydantic validation.
    """
    llm = get_groq_chat_model()
    chain = llm.with_structured_output(SuggestedFix)

    user_content = (
        f"## Severity\n{severity}\n\n"
        f"## Summary\n{summary}\n\n"
        f"## Diff\n{diff}"
    )
    if search_context:
        user_content += f"\n\n## Search context\n{search_context}"

    result = chain.invoke(
        [
            {"role": "system", "content": _FIX_SYSTEM},
            {"role": "user", "content": user_content},
        ]
    )
    # result is SuggestedFix (validated by Pydantic)
    fix: SuggestedFix = result  # type: ignore[assignment]
    return fix.suggested_fix
