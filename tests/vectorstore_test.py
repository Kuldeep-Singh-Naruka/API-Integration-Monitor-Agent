"""
tests/vectorstore_test.py
--------------------------
End-to-end smoke test for the ChromaDB vectorstore pipeline.

Tests the full chain:
    fetch_docs_content  (Tavily scraper)
        -> strip_navigation_boilerplate
        -> chunk_markdown
        -> compute_content_hash
        -> store_chunks            (triggers real embedding via all-MiniLM-L6-v2)
        -> verify collection count
        -> full-replace path       (call store_chunks again, assert count changes)
        -> cleanup

Run from the project root:
    python tests/vectorstore_test.py

Requirements:
    - .env file present with TAVILY_API_KEY set
    - venv active (chromadb, tavily-python installed)
    - Internet access for Tavily scrape
"""

from __future__ import annotations

import os
import sys
from typing import NoReturn

# ---------------------------------------------------------------------------
# Path fix -- ensures ``from app.*`` resolves when run as:
#   python tests/vectorstore_test.py
# Must come before any app.* imports.
# ---------------------------------------------------------------------------
_PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv

# Load .env before any app imports so settings picks up TAVILY_API_KEY.
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from app.services.scraper import fetch_docs_content
from app.services.vectorstore import (
    strip_navigation_boilerplate,
    chunk_markdown,
    compute_content_hash,
    get_chroma_client,
    store_chunks,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TEST_URL: str = "https://docs.tavily.com/"
TEST_API_ID: int = 99999  # Fake ID -- cleaned up at the end.

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
# Step 1: Scrape
# ---------------------------------------------------------------------------
section("STEP 1 -- Tavily scrape")
info(f"URL: {TEST_URL}")

try:
    raw_content: str = fetch_docs_content(TEST_URL)
except Exception as exc:
    fail(
        f"fetch_docs_content raised an error: {exc}\n"
        "  Check your TAVILY_API_KEY in .env and that the URL is reachable."
    )

info(f"Raw content length : {len(raw_content):,} chars")
info(f"First 200 chars    :\n{raw_content[:200]!r}")
ok("Scrape succeeded.")


# ---------------------------------------------------------------------------
# Step 2: Strip boilerplate
# ---------------------------------------------------------------------------
section("STEP 2 -- strip_navigation_boilerplate")

stripped: str = strip_navigation_boilerplate(raw_content)

info(f"Raw length     : {len(raw_content):,} chars")
info(f"Stripped length: {len(stripped):,} chars")
info(f"Chars removed  : {len(raw_content) - len(stripped):,}")
info(f"First 200 chars of stripped content:\n{stripped[:200]!r}")

if not stripped:
    fail("strip_navigation_boilerplate returned empty string -- this should never happen.")

ok("Boilerplate stripped.")


# ---------------------------------------------------------------------------
# Step 3: Chunk
# ---------------------------------------------------------------------------
section("STEP 3 -- chunk_markdown")

try:
    chunks: list[str] = chunk_markdown(stripped)
except ValueError as exc:
    fail(f"chunk_markdown raised ValueError: {exc}")

info(f"Total chunks produced: {len(chunks)}")
for i, chunk in enumerate(chunks[:3]):
    info(f"Chunk {i} ({len(chunk)} chars): {chunk[:120]!r} ...")

ok(f"Chunking produced {len(chunks)} chunk(s).")


# ---------------------------------------------------------------------------
# Step 4: Hash
# ---------------------------------------------------------------------------
section("STEP 4 -- compute_content_hash")

content_hash: str = compute_content_hash(stripped)

assert len(content_hash) == 64, f"Expected 64-char digest, got {len(content_hash)}"
assert all(c in "0123456789abcdef" for c in content_hash), "Hash is not hex."
info(f"SHA-256 digest: {content_hash}")
ok("Hash computed and validated.")


# ---------------------------------------------------------------------------
# Step 5: store_chunks (first call -- initial ingest + real embedding)
# ---------------------------------------------------------------------------
section("STEP 5 -- store_chunks (initial ingest, triggers embedding model)")

info(f"Calling store_chunks(api_id={TEST_API_ID}, chunks=[{len(chunks)} chunks]) ...")
info("NOTE: If the embedding model is not yet cached this may take 30-60 s.")

try:
    store_chunks(TEST_API_ID, chunks)
except Exception as exc:
    fail(f"store_chunks raised an error: {exc}")

client = get_chroma_client()
col = client.get_collection(f"api_docs_{TEST_API_ID}")
stored_count: int = col.count()

info(f"Collection 'api_docs_{TEST_API_ID}' now has {stored_count} document(s).")

if stored_count != len(chunks):
    fail(f"Count mismatch: expected {len(chunks)}, got {stored_count}.")

ok(f"Initial ingest OK -- {stored_count} chunks stored and embedded.")


# ---------------------------------------------------------------------------
# Step 6: store_chunks (second call -- full-replace path)
# ---------------------------------------------------------------------------
section("STEP 6 -- store_chunks (full-replace path)")

replacement_chunks: list[str] = [
    "# Replacement chunk 1\nThis is a test replacement document.",
    "# Replacement chunk 2\nThis confirms the full-replace path works correctly.",
]

info(f"Calling store_chunks again with {len(replacement_chunks)} replacement chunks ...")

try:
    store_chunks(TEST_API_ID, replacement_chunks)
except Exception as exc:
    fail(f"store_chunks (replace) raised an error: {exc}")

col2 = client.get_collection(f"api_docs_{TEST_API_ID}")
replaced_count: int = col2.count()

info(f"Collection now has {replaced_count} document(s) after replace.")

if replaced_count != len(replacement_chunks):
    fail(
        f"Count mismatch after replace: expected {len(replacement_chunks)}, got {replaced_count}."
    )

ok(f"Full-replace OK -- old {stored_count} chunks replaced with {replaced_count}.")


# ---------------------------------------------------------------------------
# Step 7: Cleanup
# ---------------------------------------------------------------------------
section("STEP 7 -- Cleanup")

client.delete_collection(f"api_docs_{TEST_API_ID}")
remaining_names = [col.name for col in client.list_collections()]

if f"api_docs_{TEST_API_ID}" in remaining_names:
    fail("Cleanup failed -- test collection still exists.")

ok(f"Test collection 'api_docs_{TEST_API_ID}' deleted.")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
section("RESULT")
print()
print("  ALL TESTS PASSED")
print()
print(f"  URL scraped   : {TEST_URL}")
print(f"  Raw length    : {len(raw_content):,} chars")
print(f"  Stripped len  : {len(stripped):,} chars")
print(f"  Chunks made   : {len(chunks)}")
print(f"  Content hash  : {content_hash[:16]}...  (truncated)")
print(f"  Chunks stored : {stored_count}")
print(f"  Replace test  : {stored_count} -> {replaced_count} chunks OK")
print()
