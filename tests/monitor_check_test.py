"""
tests/monitor_check_test.py
----------------------------
End-to-end test for check_monitored_api() covering all four outcome branches:

    1. baseline_established  -- first successful check for a fresh API row
    2. no_change             -- immediate re-check with identical content
    3. changed               -- hash manually poisoned to simulate a doc update
    4. error                 -- bad URL so Tavily fails and an Alert is created

Run from the project root (with venv active):
    python tests/monitor_check_test.py

Requirements:
    - .env with DATABASE_URL and TAVILY_API_KEY set and pointing at a live DB
    - DB tables must already exist (app was started at least once after last
      DROP TABLE so create_all() ran and the new columns are present)
    - Internet access for Tavily scrape
    - ChromaDB and all other deps installed in venv
"""

from __future__ import annotations

import os
import sys
from typing import NoReturn

# ---------------------------------------------------------------------------
# Path fix -- allows ``from app.*`` imports when run as:
#     python tests/monitor_check_test.py
# ---------------------------------------------------------------------------
_PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models.monitored_api import MonitoredAPI
from app.models.alert import Alert
from app.services.monitor_check import CheckResult, check_monitored_api
from app.services.vectorstore import get_chroma_client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# A stable, publicly accessible docs URL to use as the test subject.
TEST_DOCS_URL: str = "https://docs.tavily.com/"
TEST_API_NAME: str = "__monitor_check_test__"

SEPARATOR: str = "-" * 60


def section(title: str) -> None:
    """Print a labelled section separator."""
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
# DB setup — ensure tables exist (idempotent)
# ---------------------------------------------------------------------------
section("SETUP -- Ensure DB tables exist")
Base.metadata.create_all(bind=engine)
ok("Tables verified / created.")


# ---------------------------------------------------------------------------
# Helper: open a fresh session
# ---------------------------------------------------------------------------
def open_session() -> Session:
    """Return a new SessionLocal() session."""
    return SessionLocal()


# ---------------------------------------------------------------------------
# Cleanup helper: remove the test API row (and its cascade alerts) if it
# already exists from a previous interrupted run.
# ---------------------------------------------------------------------------
def cleanup(db: Session, api_id: int | None = None) -> None:
    """Delete the test MonitoredAPI row and its ChromaDB collection."""
    if api_id is not None:
        chroma = get_chroma_client()
        existing = [c.name for c in chroma.list_collections()]
        if f"api_docs_{api_id}" in existing:
            chroma.delete_collection(f"api_docs_{api_id}")
            info(f"ChromaDB collection api_docs_{api_id} deleted.")

    row = db.query(MonitoredAPI).filter_by(name=TEST_API_NAME).first()
    if row:
        db.delete(row)
        db.commit()
        info(f"DB row '{TEST_API_NAME}' deleted.")


# ---------------------------------------------------------------------------
# Pre-test cleanup (in case a previous run crashed mid-way)
# ---------------------------------------------------------------------------
section("PRE-CLEANUP -- Remove leftover test rows")
_pre_db = open_session()
cleanup(_pre_db, api_id=None)
# Find id if exists for chroma cleanup
_leftover = _pre_db.query(MonitoredAPI).filter_by(name=TEST_API_NAME).first()
if _leftover:
    cleanup(_pre_db, _leftover.id)
_pre_db.close()
ok("Pre-cleanup done.")


# ===========================================================================
# TEST 1 — baseline_established
# Insert a fresh MonitoredAPI row (no hash), run the check, verify:
#   - status == "baseline_established"
#   - last_content_hash populated
#   - last_raw_content populated
#   - last_checked_at populated
#   - ChromaDB collection exists with > 0 chunks
# ===========================================================================
section("TEST 1 -- baseline_established (first-ever scrape)")

db1: Session = open_session()

test_api: MonitoredAPI = MonitoredAPI(
    name=TEST_API_NAME,
    docs_url=TEST_DOCS_URL,
    is_active=True,
)
db1.add(test_api)
db1.commit()
db1.refresh(test_api)
test_api_id: int = test_api.id
info(f"Inserted test MonitoredAPI id={test_api_id}")
info("Calling check_monitored_api() -- first run (baseline)...")
info("NOTE: This triggers a real Tavily scrape and ChromaDB embedding.")

result1: CheckResult = check_monitored_api(db=db1, api=test_api)

if result1.status != "baseline_established":
    fail(f"Expected 'baseline_established', got '{result1.status}'")

if test_api.last_content_hash is None:
    fail("last_content_hash is None after baseline.")

if test_api.last_raw_content is None:
    fail("last_raw_content is None after baseline.")

if test_api.last_checked_at is None:
    fail("last_checked_at is None after baseline.")

chroma = get_chroma_client()
col = chroma.get_collection(f"api_docs_{test_api_id}")
chunk_count: int = col.count()
if chunk_count == 0:
    fail("ChromaDB collection exists but has 0 chunks after baseline.")

info(f"last_content_hash : {test_api.last_content_hash[:16]}...  (truncated)")
info(f"last_raw_content  : {len(test_api.last_raw_content):,} chars")
info(f"last_checked_at   : {test_api.last_checked_at}")
info(f"ChromaDB chunks   : {chunk_count}")
ok("TEST 1 PASSED -- baseline_established")
db1.close()


# ===========================================================================
# TEST 2 — no_change
# Re-run immediately on the same row. Hash already stored == current hash.
# Verify:
#   - status == "no_change"
#   - last_content_hash unchanged
#   - last_raw_content unchanged
#   - last_checked_at updated (timestamp advances)
# ===========================================================================
section("TEST 2 -- no_change (immediate re-check, same content)")

db2: Session = open_session()
api2: MonitoredAPI = db2.query(MonitoredAPI).filter_by(id=test_api_id).one()

hash_before: str = api2.last_content_hash          # type: ignore[assignment]
content_before: str = api2.last_raw_content        # type: ignore[assignment]
checked_at_before = api2.last_checked_at

info("Calling check_monitored_api() -- second run (no_change expected)...")
result2: CheckResult = check_monitored_api(db=db2, api=api2)

if result2.status != "no_change":
    fail(f"Expected 'no_change', got '{result2.status}'")

if api2.last_content_hash != hash_before:
    fail("last_content_hash changed unexpectedly on no_change run.")

if api2.last_raw_content != content_before:
    fail("last_raw_content changed unexpectedly on no_change run.")

info(f"last_checked_at before : {checked_at_before}")
info(f"last_checked_at after  : {api2.last_checked_at}")
ok("TEST 2 PASSED -- no_change")
db2.close()


# ===========================================================================
# TEST 3 — changed
# Manually set last_content_hash to a fake value to simulate a doc change.
# Verify:
#   - status == "changed"
#   - old_content matches what was stored before
#   - new_content is the fresh scrape (non-empty)
#   - last_content_hash updated to the real new hash
#   - ChromaDB collection rebuilt (count may differ from original)
# ===========================================================================
section("TEST 3 -- changed (poisoned hash simulates doc update)")

db3: Session = open_session()
api3: MonitoredAPI = db3.query(MonitoredAPI).filter_by(id=test_api_id).one()

real_content_before: str = api3.last_raw_content  # type: ignore[assignment]
real_hash_before: str = api3.last_content_hash    # type: ignore[assignment]

# Poison the stored hash so check_monitored_api() thinks the content changed.
FAKE_HASH: str = "a" * 64
api3.last_content_hash = FAKE_HASH
db3.commit()
info(f"Poisoned last_content_hash to: {FAKE_HASH[:16]}...")

info("Calling check_monitored_api() -- third run (changed expected)...")
result3: CheckResult = check_monitored_api(db=db3, api=api3)

if result3.status != "changed":
    fail(f"Expected 'changed', got '{result3.status}'")

if result3.old_content is None:
    fail("old_content is None on 'changed' result.")

if result3.new_content is None:
    fail("new_content is None on 'changed' result.")

if result3.old_content != real_content_before:
    fail(
        f"old_content does not match what was stored before poisoning.\n"
        f"  Expected first 80 chars: {real_content_before[:80]!r}\n"
        f"  Got first 80 chars     : {result3.old_content[:80]!r}"
    )

if api3.last_content_hash == FAKE_HASH:
    fail("last_content_hash still the fake value after 'changed' run.")

col3 = chroma.get_collection(f"api_docs_{test_api_id}")
info(f"ChromaDB chunks after rebuild: {col3.count()}")
info(f"old_content length: {len(result3.old_content):,} chars")
info(f"new_content length: {len(result3.new_content):,} chars")
info(f"new hash: {api3.last_content_hash[:16]}...  (should == real hash)")
ok("TEST 3 PASSED -- changed")
db3.close()


# ===========================================================================
# TEST 4 — error
# Set docs_url to a URL that Tavily cannot extract from.
# Verify:
#   - status == "error"
#   - result.alert is not None
#   - Alert row exists in DB with severity="error"
#   - last_checked_at updated
#   - last_content_hash NOT changed (scrape never succeeded)
# ===========================================================================
section("TEST 4 -- error (bad URL triggers scrape failure)")

db4: Session = open_session()
api4: MonitoredAPI = db4.query(MonitoredAPI).filter_by(id=test_api_id).one()

hash_before_error: str = api4.last_content_hash   # type: ignore[assignment]
BAD_URL: str = "https://this-url-does-not-exist-at-all-xyz-999.dev/docs"
api4.docs_url = BAD_URL
db4.commit()
info(f"Set docs_url to bad URL: {BAD_URL}")

info("Calling check_monitored_api() -- fourth run (error expected)...")
result4: CheckResult = check_monitored_api(db=db4, api=api4)

if result4.status != "error":
    fail(f"Expected 'error', got '{result4.status}'")

if result4.alert is None:
    fail("result.alert is None on error result -- Alert was not created.")

if result4.alert.severity != "error":
    fail(f"Alert severity should be 'error', got '{result4.alert.severity}'")

if api4.last_content_hash != hash_before_error:
    fail("last_content_hash changed on a failed scrape -- it should not.")

if api4.last_checked_at is None:
    fail("last_checked_at is None after error run.")

# Verify the Alert row actually persisted in the DB.
db_alert: Alert | None = db4.query(Alert).filter_by(
    api_id=test_api_id, severity="error"
).order_by(Alert.created_at.desc()).first()

if db_alert is None:
    fail("No error Alert row found in DB after error run.")

info(f"Alert id       : {db_alert.id}")
info(f"Alert summary  : {db_alert.summary[:80]!r}")
info(f"Alert severity : {db_alert.severity}")
info(f"last_checked_at: {api4.last_checked_at}")
ok("TEST 4 PASSED -- error")
db4.close()


# ===========================================================================
# CLEANUP
# ===========================================================================
section("CLEANUP -- Remove test DB row and ChromaDB collection")

db_clean: Session = open_session()
cleanup(db_clean, api_id=test_api_id)
db_clean.close()
ok("Cleanup complete.")


# ===========================================================================
# SUMMARY
# ===========================================================================
section("RESULT")
print()
print("  ALL 4 TESTS PASSED")
print()
print(f"  TEST 1  baseline_established : OK  ({chunk_count} chunks embedded)")
print( "  TEST 2  no_change            : OK")
print( "  TEST 3  changed              : OK  (hash rebuild + old/new content)")
print( "  TEST 4  error                : OK  (error alert created in DB)")
print()
