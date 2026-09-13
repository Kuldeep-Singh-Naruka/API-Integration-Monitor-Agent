"""
tests/summarizer_test.py
-------------------------
Tests for app/services/summarizer.py.

Covers:
    compute_diff()
        1. normal two-line change -- produces a recognisable unified diff
        2. truncation          -- diff exceeding max_chars is capped and annotated
        3. identical inputs    -- raises ValueError (caller bug guard)

    summarize_change()        -- Groq API call is mocked in ALL cases so these
                                 tests run offline without any API key.
        4. happy path          -- valid JSON with breaking severity
        5. non-breaking path   -- valid JSON with non-breaking severity
        6. null suggested_fix  -- model returns null; field becomes None
        7. invalid JSON        -- raises ValueError with clear message
        8. not a dict          -- raises ValueError
        9. missing key         -- raises ValueError naming the missing key
       10. invalid severity    -- raises ValueError; value is not silently coerced
       11. markdown fence      -- ```json fence is stripped before JSON parse

Run from the project root (venv active):
    python tests/summarizer_test.py
"""

from __future__ import annotations

import json
import os
import sys
import types
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

from app.services.summarizer import ChangeSummary, compute_diff, summarize_change

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
# Helper: build a fake Groq completion response carrying the given content.
# ---------------------------------------------------------------------------
def _make_groq_response(content: str) -> MagicMock:
    """Return a MagicMock shaped like a groq ChatCompletion response."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


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

# Build two strings whose diff will be comfortably longer than 50 chars.
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
# TEST 4 -- summarize_change: happy path (breaking)
# ===========================================================================
section("TEST 4 -- summarize_change: happy path with breaking severity")

_payload_breaking = json.dumps({
    "severity": "breaking",
    "summary": "The /v1/users endpoint was removed.",
    "suggested_fix": "Update all callers to use /v2/users instead.",
})

with patch("app.services.summarizer.Groq") as MockGroq:
    MockGroq.return_value.chat.completions.create.return_value = (
        _make_groq_response(_payload_breaking)
    )
    result4: ChangeSummary = summarize_change("--- a\n+++ b\n-old line\n+new line\n")

if result4.severity != "breaking":
    fail(f"Expected severity='breaking', got {result4.severity!r}")
if "removed" not in result4.summary:
    fail(f"Summary does not mention 'removed': {result4.summary!r}")
if result4.suggested_fix is None:
    fail("suggested_fix should not be None when model provides one.")
if "v2/users" not in result4.suggested_fix:
    fail(f"suggested_fix missing expected text: {result4.suggested_fix!r}")

info(f"severity     : {result4.severity}")
info(f"summary      : {result4.summary}")
info(f"suggested_fix: {result4.suggested_fix}")
ok("TEST 4 PASSED -- breaking ChangeSummary parsed correctly")


# ===========================================================================
# TEST 5 -- summarize_change: non-breaking severity
# ===========================================================================
section("TEST 5 -- summarize_change: non-breaking severity")

_payload_nonbreaking = json.dumps({
    "severity": "non-breaking",
    "summary": "A new optional field 'metadata' was added to the response.",
    "suggested_fix": "No code changes required; the field can be safely ignored.",
})

with patch("app.services.summarizer.Groq") as MockGroq:
    MockGroq.return_value.chat.completions.create.return_value = (
        _make_groq_response(_payload_nonbreaking)
    )
    result5: ChangeSummary = summarize_change("--- a\n+++ b\n+new field\n")

if result5.severity != "non-breaking":
    fail(f"Expected 'non-breaking', got {result5.severity!r}")

info(f"severity     : {result5.severity}")
info(f"summary      : {result5.summary}")
info(f"suggested_fix: {result5.suggested_fix}")
ok("TEST 5 PASSED -- non-breaking ChangeSummary parsed correctly")


# ===========================================================================
# TEST 6 -- summarize_change: null suggested_fix becomes None
# ===========================================================================
section("TEST 6 -- summarize_change: null suggested_fix -> None")

_payload_null_fix = json.dumps({
    "severity": "non-breaking",
    "summary": "Wording clarification only.",
    "suggested_fix": None,
})

with patch("app.services.summarizer.Groq") as MockGroq:
    MockGroq.return_value.chat.completions.create.return_value = (
        _make_groq_response(_payload_null_fix)
    )
    result6: ChangeSummary = summarize_change("--- a\n+++ b\n+wording\n")

if result6.suggested_fix is not None:
    fail(f"Expected suggested_fix=None, got {result6.suggested_fix!r}")

info("suggested_fix is None as expected")
ok("TEST 6 PASSED -- null suggested_fix mapped to None")


# ===========================================================================
# TEST 7 -- summarize_change: invalid JSON raises ValueError
# ===========================================================================
section("TEST 7 -- summarize_change: invalid JSON response raises ValueError")

with patch("app.services.summarizer.Groq") as MockGroq:
    MockGroq.return_value.chat.completions.create.return_value = (
        _make_groq_response("not json at all { broken }")
    )
    raised7 = False
    exc7_msg = ""
    try:
        summarize_change("diff text")
    except ValueError as exc:
        raised7 = True
        exc7_msg = str(exc)

if not raised7:
    fail("Expected ValueError for invalid JSON -- not raised.")
if "not valid JSON" not in exc7_msg:
    fail(f"ValueError message does not mention 'not valid JSON': {exc7_msg!r}")

info(f"ValueError: {exc7_msg[:120]}")
ok("TEST 7 PASSED -- invalid JSON raises ValueError")


# ===========================================================================
# TEST 8 -- summarize_change: JSON array (not a dict) raises ValueError
# ===========================================================================
section("TEST 8 -- summarize_change: JSON array (not dict) raises ValueError")

with patch("app.services.summarizer.Groq") as MockGroq:
    MockGroq.return_value.chat.completions.create.return_value = (
        _make_groq_response('["breaking", "summary", "fix"]')
    )
    raised8 = False
    exc8_msg = ""
    try:
        summarize_change("diff text")
    except ValueError as exc:
        raised8 = True
        exc8_msg = str(exc)

if not raised8:
    fail("Expected ValueError for non-dict JSON -- not raised.")
if "not a dict" not in exc8_msg:
    fail(f"ValueError message does not mention 'not a dict': {exc8_msg!r}")

info(f"ValueError: {exc8_msg[:120]}")
ok("TEST 8 PASSED -- non-dict JSON raises ValueError")


# ===========================================================================
# TEST 9 -- summarize_change: missing key raises ValueError naming the key
# ===========================================================================
section("TEST 9 -- summarize_change: missing required key raises ValueError")

_payload_missing_key = json.dumps({
    "severity": "breaking",
    "summary": "Something changed.",
    # "suggested_fix" intentionally omitted
})

with patch("app.services.summarizer.Groq") as MockGroq:
    MockGroq.return_value.chat.completions.create.return_value = (
        _make_groq_response(_payload_missing_key)
    )
    raised9 = False
    exc9_msg = ""
    try:
        summarize_change("diff text")
    except ValueError as exc:
        raised9 = True
        exc9_msg = str(exc)

if not raised9:
    fail("Expected ValueError for missing key -- not raised.")
if "suggested_fix" not in exc9_msg:
    fail(f"ValueError does not name the missing key 'suggested_fix': {exc9_msg!r}")

info(f"ValueError: {exc9_msg[:160]}")
ok("TEST 9 PASSED -- missing key named in ValueError")


# ===========================================================================
# TEST 10 -- summarize_change: invalid severity is rejected (not coerced)
# ===========================================================================
section("TEST 10 -- summarize_change: invalid severity raises ValueError")

_payload_bad_severity = json.dumps({
    "severity": "low",          # invalid -- not "breaking" or "non-breaking"
    "summary": "Something.",
    "suggested_fix": "Do something.",
})

with patch("app.services.summarizer.Groq") as MockGroq:
    MockGroq.return_value.chat.completions.create.return_value = (
        _make_groq_response(_payload_bad_severity)
    )
    raised10 = False
    exc10_msg = ""
    try:
        summarize_change("diff text")
    except ValueError as exc:
        raised10 = True
        exc10_msg = str(exc)

if not raised10:
    fail("Expected ValueError for invalid severity -- not raised.")
if "'low'" not in exc10_msg and "low" not in exc10_msg:
    fail(f"ValueError does not mention the bad value: {exc10_msg!r}")

info(f"ValueError: {exc10_msg[:160]}")
ok("TEST 10 PASSED -- invalid severity raises ValueError (not silently coerced)")


# ===========================================================================
# TEST 11 -- summarize_change: markdown code fence is stripped
# ===========================================================================
section("TEST 11 -- summarize_change: ```json fence stripped before parsing")

_inner = json.dumps({
    "severity": "non-breaking",
    "summary": "Minor wording update.",
    "suggested_fix": "No action needed.",
})
_fenced = f"```json\n{_inner}\n```"

with patch("app.services.summarizer.Groq") as MockGroq:
    MockGroq.return_value.chat.completions.create.return_value = (
        _make_groq_response(_fenced)
    )
    result11: ChangeSummary = summarize_change("diff text")

if result11.severity != "non-breaking":
    fail(f"Fence stripping failed -- severity={result11.severity!r}")
if result11.suggested_fix != "No action needed.":
    fail(f"suggested_fix wrong after fence strip: {result11.suggested_fix!r}")

info(f"Fenced input correctly parsed: severity={result11.severity!r}")
ok("TEST 11 PASSED -- markdown fence stripped transparently")


# ===========================================================================
# SUMMARY
# ===========================================================================
section("RESULT")
print()
print("  ALL 11 TESTS PASSED")
print()
print("  compute_diff tests:")
print("    TEST  1  normal change           : OK")
print("    TEST  2  truncation              : OK")
print("    TEST  3  identical inputs        : OK  (ValueError raised)")
print()
print("  summarize_change tests (Groq mocked, no API calls):")
print("    TEST  4  breaking severity       : OK")
print("    TEST  5  non-breaking severity   : OK")
print("    TEST  6  null suggested_fix      : OK  (mapped to None)")
print("    TEST  7  invalid JSON            : OK  (ValueError raised)")
print("    TEST  8  non-dict JSON           : OK  (ValueError raised)")
print("    TEST  9  missing required key    : OK  (ValueError raised, key named)")
print("    TEST 10  invalid severity        : OK  (ValueError raised, not coerced)")
print("    TEST 11  markdown fence stripped : OK")
print()
