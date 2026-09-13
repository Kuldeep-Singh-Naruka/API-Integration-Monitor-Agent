"""
app/services/vectorstore.py
---------------------------
ChromaDB vector-store service for the API Integration Monitor Agent.

Responsibilities:
  - Strip site-wide navigation boilerplate from scraped Markdown content.
  - Chunk Markdown documents on heading boundaries for embedding.
  - Compute a SHA-256 content hash for change-detection comparisons.
  - Provide a shared, lazily-initialised ChromaDB PersistentClient.
  - Fully replace a per-API ChromaDB collection with freshly chunked content.

Architecture note
-----------------
ChromaDB is used as a *downstream, rebuildable* store.  It does NOT need to
survive process restarts (Render''s free tier wipes local disk on every
spin-down), so a ``PersistentClient`` pointed at a local directory is fine -
the orchestrator (next step) will repopulate it on the next scheduled check
whenever the hash changes.

This module is intentionally free of FastAPI routing and SQLAlchemy concerns;
it is a pure service layer.
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional

import chromadb
from chromadb.api import ClientAPI


# ---------------------------------------------------------------------------
# Module-level cached client -- created once, reused across calls.
# ---------------------------------------------------------------------------
_chroma_client: Optional[ClientAPI] = None

# Directory where ChromaDB will persist its data.  Relative to the project
# root (i.e. the directory from which ``uvicorn main:app`` is launched).
_CHROMA_DATA_DIR: str = "./chroma_data"


# ---------------------------------------------------------------------------
# 1. strip_navigation_boilerplate
# ---------------------------------------------------------------------------

def strip_navigation_boilerplate(content: str) -> str:
    """Strip site-wide navigation link boilerplate from scraped Markdown.

    Tavily-extracted docs pages often begin with a wall of navigation links
    before the real page content.  The real content reliably starts at the
    first Markdown level-1 heading (a line beginning with "# ").

    The function searches for the first occurrence of "\n# " in *content*.
    If found, everything from that "# " onwards (inclusive) is returned,
    stripped of leading/trailing whitespace.  If not found, the original
    content is returned unchanged -- this is the safe fallback so that pages
    without a level-1 heading are never silently discarded.

    Args:
        content: Raw Markdown text as returned by the scraper.

    Returns:
        Content starting from the first level-1 heading, or the original
        content unchanged if no such heading is present.
    """
    marker: str = "\n# "
    idx: int = content.find(marker)
    if idx == -1:
        # No level-1 heading found -- return the full content as a safe fallback.
        return content
    # Return from the "# " character onwards (skip the leading newline).
    return content[idx + 1:].strip()


# ---------------------------------------------------------------------------
# 2. chunk_markdown
# ---------------------------------------------------------------------------

def chunk_markdown(content: str, max_chunk_chars: int = 1500) -> list[str]:
    """Split Markdown content into embed-friendly chunks on heading boundaries.

    Algorithm:
      1. Walk the lines of *content* and collect runs of text that begin on a
         Markdown heading line (``#`` or ``##``).  Each run becomes a
         "primary chunk".
      2. If a primary chunk exceeds *max_chunk_chars*, further split it on
         blank-line paragraph boundaries (``\\n\\n``), accumulating paragraphs
         into sub-chunks up to *max_chunk_chars* each.
      3. Empty or whitespace-only chunks are dropped.

    Assumptions:
      - The caller has already stripped navigation boilerplate.
      - *content* is non-empty (behaviour on empty string is defined: raises
        ``ValueError`` because the resulting list would be empty).

    Args:
        content: Markdown text to split (should be pre-stripped).
        max_chunk_chars: Soft upper bound on chunk size in characters.
            Defaults to 1500.

    Returns:
        A flat list of non-empty chunk strings.

    Raises:
        ValueError: If the resulting chunk list is empty (nothing to store).
            This can happen when *content* is entirely whitespace.
    """
    lines: list[str] = content.splitlines()
    primary_chunks: list[str] = []
    current_lines: list[str] = []

    for line in lines:
        stripped: str = line.lstrip()
        is_heading: bool = stripped.startswith("## ") or stripped.startswith("# ")
        if is_heading and current_lines:
            # Flush the accumulated block before starting the new heading.
            primary_chunks.append("\n".join(current_lines))
            current_lines = []
        current_lines.append(line)

    # Flush the final block.
    if current_lines:
        primary_chunks.append("\n".join(current_lines))

    # Phase 2: sub-split any oversized primary chunk on paragraph boundaries.
    final_chunks: list[str] = []
    for chunk in primary_chunks:
        if len(chunk) <= max_chunk_chars:
            stripped_chunk: str = chunk.strip()
            if stripped_chunk:
                final_chunks.append(stripped_chunk)
            continue

        # Split on blank lines and re-accumulate up to the size limit.
        paragraphs: list[str] = chunk.split("\n\n")
        sub_chunk_parts: list[str] = []
        sub_chunk_len: int = 0

        for para in paragraphs:
            para_stripped: str = para.strip()
            if not para_stripped:
                continue
            # +2 accounts for the "\n\n" separator that will be re-added.
            added_len: int = len(para_stripped) + (2 if sub_chunk_parts else 0)
            if sub_chunk_parts and sub_chunk_len + added_len > max_chunk_chars:
                # Flush current sub-chunk.
                final_chunks.append("\n\n".join(sub_chunk_parts))
                sub_chunk_parts = [para_stripped]
                sub_chunk_len = len(para_stripped)
            else:
                sub_chunk_parts.append(para_stripped)
                sub_chunk_len += added_len

        # Flush the last sub-chunk.
        if sub_chunk_parts:
            final_chunks.append("\n\n".join(sub_chunk_parts))

    if not final_chunks:
        raise ValueError(
            "chunk_markdown produced an empty chunk list -- the input content "
            "may be entirely whitespace."
        )

    return final_chunks


# ---------------------------------------------------------------------------
# 3. compute_content_hash
# ---------------------------------------------------------------------------

def compute_content_hash(content: str) -> str:
    """Return the SHA-256 hex digest of *content* (UTF-8 encoded).

    This is used by the orchestrator to compare against
    ``MonitoredAPI.last_content_hash`` to decide whether the docs have
    changed since the last scrape.  This function *only* computes the hash --
    it does not touch the database or make any comparisons itself.

    Args:
        content: The trimmed doc content string to hash.

    Returns:
        A 64-character lowercase hexadecimal SHA-256 digest string.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 4. get_chroma_client
# ---------------------------------------------------------------------------

def get_chroma_client() -> ClientAPI:
    """Return the shared ChromaDB PersistentClient, creating it on first call.

    The client is cached at module level so that the underlying SQLite
    connection is not reopened on every request.  The data directory
    (``./chroma_data``) is created automatically by ``chromadb`` if it does
    not already exist.

    Returns:
        A ``chromadb.ClientAPI`` instance pointed at ``./chroma_data``.
    """
    global _chroma_client
    if _chroma_client is None:
        os.makedirs(_CHROMA_DATA_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=_CHROMA_DATA_DIR)
    return _chroma_client


# ---------------------------------------------------------------------------
# 5. store_chunks
# ---------------------------------------------------------------------------

def store_chunks(api_id: int, chunks: list[str]) -> None:
    """Fully replace the ChromaDB collection for *api_id* with *chunks*.

    The replacement is intentionally destructive: the existing collection (if
    any) is deleted and recreated from scratch before inserting the new
    chunks.  This avoids stale leftover chunks when heading/paragraph
    boundaries shift between doc versions -- a clean rebuild is safer than
    trying to diff two sets of variable-length text chunks.

    Chunk IDs follow the pattern ``f"{api_id}_chunk_{i}"`` where *i* is the
    zero-based index in *chunks*.  No explicit embedding function is passed so
    Chroma uses its default local embedding function (all-MiniLM-L6-v2).

    Args:
        api_id: The primary key of the ``MonitoredAPI`` record.  Used to name
            the collection (``f"api_docs_{api_id}"``).
        chunks: Non-empty list of text strings to embed and store.

    Raises:
        ValueError: If *chunks* is empty (guard against accidentally wiping a
            collection and leaving it empty -- callers should validate before
            calling this function).
    """
    if not chunks:
        raise ValueError(
            f"store_chunks called with an empty chunk list for api_id={api_id}. "
            "The collection was NOT modified."
        )

    client: ClientAPI = get_chroma_client()
    collection_name: str = f"api_docs_{api_id}"

    # Delete the existing collection if it exists, then create it fresh.
    # chromadb raises an exception if you try to delete a collection that
    # does not exist, so we check first.
    existing_names: list[str] = [col.name for col in client.list_collections()]
    if collection_name in existing_names:
        client.delete_collection(name=collection_name)

    collection = client.create_collection(name=collection_name)

    # Build parallel id / document lists and add in a single batch.
    ids: list[str] = [f"{api_id}_chunk_{i}" for i in range(len(chunks))]
    collection.add(ids=ids, documents=chunks)
