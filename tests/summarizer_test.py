"""
tests/summarizer_test.py
-------------------------
Tests for app/services/summarizer.py and app/agent/llm.py.

Covers:
    compute_diff()          (app/services/summarizer.py)
        1. normal two-line change -- produces a recognisable unified diff
        2. truncation          -- diff exceeding max_chars is capped and annotated
        3. identical inputs    -- raises ValueError (caller bug guard)

    classify_change()       (app/agent/llm.py) -- ChatGroq is mocked in ALL cases
        4. happy path          -- breaking severity + summary returned
        5. non-breaking path   -- non-breaking severity returned
        6. LLM exception       -- exception propagates out of classify_change

    propose_fix()           (app/agent/llm.py) -- ChatGroq is mocked in ALL cases
        7. returns None        -- model says no fix needed (suggested_fix=None)
        8. returns string      -- model suggests a fix
        9. Pydantic rejection  -- model returns wrong schema; ValidationError raised
       10. exception from LLM  -- arbitrary LLM failure propagates
       11. both fields round-trip -- severity/summary round-trip correctly through
                                    the classification schema

Run from the project root (venv active):
    python tests/summarizer_test.py
"""

from __future__ import annotations

import os
import sys
from typing import NoReturn
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path fix -- allows ``from app.*`` imports when run as:
#     python tests/summarizer_test.py
# ---------------------------------------------------------------------------
_PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from app.services.summarizer import compute_diff
from app.agent.llm import (
    SeverityClassification,
    SuggestedFix,
    classify_change,
    propose_fix,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SEPARATOR: str = "-" * 60


def section(title: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def info(msg: str) -> None:
    print(f"  [..] {msg}")


def fail(msg: str) -> NoReturn:
    print(f"  [FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helper: build a mock chain whose .invoke() returns the given Pydantic object.
# ---------------------------------------------------------------------------
def _mock_chain(return_value: object) -> MagicMock:
    """Return a MagicMock whose .invoke() returns ``return_value``."""
    chain = MagicMock()
    chain.invoke.return_value = return_value
    return chain


# ===========================================================================
# TEST 1 -- compute_diff: normal two-line change
# ===========================================================================
section("TEST 1 -- compute_diff: normal change produces unified diff")

old = "line one\nline two\nline three\n"
new = "line one\nline TWO (changed)\nline three\n"

diff = compute_diff(old, new)

if "--- previous_version" not in diff:
    fail("Diff missing '--- previous_version' header.")
if "+++ current_version" not in diff:
    fail("Diff missing '+++ current_version' header.")
if "-line two" not in diff:
    fail("Diff missing removed line '-line two'.")
if "+line TWO (changed)" not in diff:
    fail("Diff missing added line '+line TWO (changed)'.")

info(f"Diff produced ({len(diff)} chars):")
for line in diff.splitlines():
    info(f"  {line}")
ok("TEST 1 PASSED -- unified diff is correct")


# ===========================================================================
# TEST 2 -- compute_diff: truncation
# ===========================================================================
section("TEST 2 -- compute_diff: long diff is truncated at max_chars")

old_long = "\n".join(f"old line {i}" for i in range(50))
new_long = "\n".join(f"new line {i}" for i in range(50))

diff_short = compute_diff(old_long, new_long, max_chars=50)

if len(diff_short) > 50 + len("\n[... diff truncated for length ...]"):
    fail(f"Truncated diff is too long: {len(diff_short)} chars.")
if "[... diff truncated for length ...]" not in diff_short:
    fail("Truncation notice not appended to short diff.")

info(f"Diff with max_chars=50 ({len(diff_short)} chars): {diff_short!r}")
ok("TEST 2 PASSED -- truncation and notice are correct")


# ===========================================================================
# TEST 3 -- compute_diff: identical inputs raise ValueError
# ===========================================================================
section("TEST 3 -- compute_diff: identical inputs raise ValueError")

same = "same content\nno change here\n"
raised = False
try:
    compute_diff(same, same)
except ValueError as exc:
    raised = True
    info(f"ValueError raised as expected: {exc}")

if not raised:
    fail("compute_diff did NOT raise ValueError on identical inputs.")

ok("TEST 3 PASSED -- ValueError raised on identical inputs")


# ===========================================================================
# TEST 4 -- classify_change: happy path (breaking)
# ===========================================================================
section("TEST 4 -- classify_change: happy path with breaking severity")

_breaking_result = SeverityClassification(
    severity="breaking",
    summary="The /v1/users endpoint was removed.",
)

with patch("app.agent.llm.get_groq_chat_model") as mock_factory:
    mock_llm = MagicMock()
    mock_factory.return_value = mock_llm
    mock_llm.with_structured_output.return_value = _mock_chain(_breaking_result)

    result4 = classify_change(
        diff="--- a\n+++ b\n-old line\n+new line\n",
        search_context="",
    )

if result4.severity != "breaking":
    fail(f"Expected severity='breaking', got {result4.severity!r}")
if "removed" not in result4.summary:
    fail(f"Summary does not mention 'removed': {result4.summary!r}")

info(f"severity : {result4.severity}")
info(f"summary  : {result4.summary}")
ok("TEST 4 PASSED -- breaking SeverityClassification returned correctly")


# ===========================================================================
# TEST 5 -- classify_change: non-breaking severity
# ===========================================================================
section("TEST 5 -- classify_change: non-breaking severity")

_nonbreaking_result = SeverityClassification(
    severity="non-breaking",
    summary="A new optional field 'metadata' was added to the response.",
)

with patch("app.agent.llm.get_groq_chat_model") as mock_factory:
    mock_llm = MagicMock()
    mock_factory.return_value = mock_llm
    mock_llm.with_structured_output.return_value = _mock_chain(_nonbreaking_result)

    result5 = classify_change(
        diff="--- a\n+++ b\n+new field\n",
        search_context="Some changelog context.",
    )

if result5.severity != "non-breaking":
    fail(f"Expected 'non-breaking', got {result5.severity!r}")

info(f"severity : {result5.severity}")
info(f"summary  : {result5.summary}")
ok("TEST 5 PASSED -- non-breaking SeverityClassification returned correctly")


# ===========================================================================
# TEST 6 -- classify_change: LLM exception propagates
# ===========================================================================
section("TEST 6 -- classify_change: LLM exception propagates to caller")

with patch("app.agent.llm.get_groq_chat_model") as mock_factory:
    mock_llm = MagicMock()
    mock_factory.return_value = mock_llm
    mock_chain = MagicMock()
    mock_chain.invoke.side_effect = RuntimeError("LLM unavailable")
    mock_llm.with_structured_output.return_value = mock_chain

    raised6 = False
    try:
        classify_change(diff="diff text", search_context="")
    except RuntimeError as exc:
        raised6 = True
        info(f"RuntimeError propagated: {exc}")

if not raised6:
    fail("Expected RuntimeError from LLM failure to propagate -- not raised.")

ok("TEST 6 PASSED -- LLM exception propagates out of classify_change")


# ===========================================================================
# TEST 7 -- propose_fix: returns None (no fix needed)
# ===========================================================================
section("TEST 7 -- propose_fix: model returns None for suggested_fix")

_no_fix = SuggestedFix(suggested_fix=None)

with patch("app.agent.llm.get_groq_chat_model") as mock_factory:
    mock_llm = MagicMock()
    mock_factory.return_value = mock_llm
    mock_llm.with_structured_output.return_value = _mock_chain(_no_fix)

    fix7 = propose_fix(
        diff="diff",
        search_context="",
        severity="non-breaking",
        summary="Minor wording change.",
    )

if fix7 is not None:
    fail(f"Expected None, got {fix7!r}")

info("suggested_fix is None as expected")
ok("TEST 7 PASSED -- propose_fix returns None when model indicates no fix needed")


# ===========================================================================
# TEST 8 -- propose_fix: returns a string fix
# ===========================================================================
section("TEST 8 -- propose_fix: model returns a concrete fix string")

_with_fix = SuggestedFix(suggested_fix="Update all callers to use /v2/users.")

with patch("app.agent.llm.get_groq_chat_model") as mock_factory:
    mock_llm = MagicMock()
    mock_factory.return_value = mock_llm
    mock_llm.with_structured_output.return_value = _mock_chain(_with_fix)

    fix8 = propose_fix(
        diff="--- a\n+++ b\n-GET /v1/users\n+GET /v2/users\n",
        search_context="",
        severity="breaking",
        summary="Endpoint renamed.",
    )

if fix8 is None:
    fail("Expected a non-None string fix, got None.")
if "v2/users" not in fix8:
    fail(f"Fix does not mention 'v2/users': {fix8!r}")

info(f"suggested_fix: {fix8}")
ok("TEST 8 PASSED -- propose_fix returns correct string fix")


# ===========================================================================
# TEST 9 -- propose_fix: Pydantic ValidationError from bad schema
# ===========================================================================
section("TEST 9 -- propose_fix: ValidationError from unexpected model output")

from pydantic import ValidationError

with patch("app.agent.llm.get_groq_chat_model") as mock_factory:
    mock_llm = MagicMock()
    mock_factory.return_value = mock_llm
    mock_chain = MagicMock()
    # Simulate Pydantic raising on bad output (e.g. model returned wrong schema)
    mock_chain.invoke.side_effect = ValidationError.from_exception_data(
        title="SuggestedFix",
        input_type="python",
        line_errors=[],
    )
    mock_llm.with_structured_output.return_value = mock_chain

    raised9 = False
    try:
        propose_fix(
            diff="diff",
            search_context="",
            severity="breaking",
            summary="Something changed.",
        )
    except (ValidationError, Exception):
        raised9 = True
        info("Exception raised as expected on bad schema output")

if not raised9:
    fail("Expected an exception from bad schema -- not raised.")

ok("TEST 9 PASSED -- bad schema raises exception from propose_fix")


# ===========================================================================
# TEST 10 -- propose_fix: arbitrary LLM exception propagates
# ===========================================================================
section("TEST 10 -- propose_fix: arbitrary LLM exception propagates")

with patch("app.agent.llm.get_groq_chat_model") as mock_factory:
    mock_llm = MagicMock()
    mock_factory.return_value = mock_llm
    mock_chain = MagicMock()
    mock_chain.invoke.side_effect = ConnectionError("network timeout")
    mock_llm.with_structured_output.return_value = mock_chain

    raised10 = False
    try:
        propose_fix(
            diff="diff",
            search_context="",
            severity="breaking",
            summary="Something changed.",
        )
    except ConnectionError as exc:
        raised10 = True
        info(f"ConnectionError propagated: {exc}")

if not raised10:
    fail("Expected ConnectionError to propagate -- not raised.")

ok("TEST 10 PASSED -- arbitrary LLM exception propagates out of propose_fix")


# ===========================================================================
# TEST 11 -- SeverityClassification: both fields round-trip correctly
# ===========================================================================
section("TEST 11 -- SeverityClassification: fields are accessible as typed attrs")

sc = SeverityClassification(severity="non-breaking", summary="Minor wording update.")

if sc.severity != "non-breaking":
    fail(f"severity wrong: {sc.severity!r}")
if sc.summary != "Minor wording update.":
    fail(f"summary wrong: {sc.summary!r}")

# SeverityClassification must NOT have a suggested_fix attribute -- it is
# deliberately excluded from this schema (it lives in SuggestedFix).
if hasattr(sc, "suggested_fix"):
    fail("SeverityClassification should NOT have a 'suggested_fix' field.")

info(f"severity : {sc.severity}")
info(f"summary  : {sc.summary}")
ok("TEST 11 PASSED -- SeverityClassification fields round-trip correctly, no suggested_fix")


# ===========================================================================
# SUMMARY
# ===========================================================================
section("RESULT")
print()
print("  ALL 11 TESTS PASSED")
print()
print("  compute_diff tests:")
print("    TEST  1  normal change                : OK")
print("    TEST  2  truncation                   : OK")
print("    TEST  3  identical inputs             : OK  (ValueError raised)")
print()
print("  classify_change tests (ChatGroq mocked, no API calls):")
print("    TEST  4  breaking severity            : OK")
print("    TEST  5  non-breaking severity        : OK")
print("    TEST  6  LLM exception propagates     : OK")
print()
print("  propose_fix tests (ChatGroq mocked, no API calls):")
print("    TEST  7  returns None (no fix needed) : OK")
print("    TEST  8  returns string fix           : OK")
print("    TEST  9  ValidationError on bad schema: OK")
print("    TEST 10  arbitrary LLM exception      : OK")
print("    TEST 11  SeverityClassification attrs : OK")
print()
