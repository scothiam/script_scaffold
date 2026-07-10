"""Shared SourceItem upsert helpers for RSS, HTML, and board crawlers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal

from script_scaffold.utils import utcnow

UpsertStatus = Literal["new", "updated", "unchanged"]


def source_item_content_hash(title: str, summary: str = "", *, lowercase: bool = False) -> str:
    """Stable hash for title + summary change detection."""
    if lowercase:
        blob = f"{title}\n{summary}".strip().lower()
    else:
        blob = title + summary
    return hashlib.sha256(blob.encode("utf-8", errors="replace")).hexdigest()


@dataclass
class SourceItemUpsertResult:
    """Outcome of upserting one row into ``source_items``."""

    status: UpsertStatus
    item: Any


def upsert_source_item(
    session,
    item_cls,
    source_id: int,
    *,
    item_url: str,
    title: str,
    summary: str = "",
    published_at: datetime | None = None,
    normalize_url: Callable[[str], str] | None = None,
    lowercase_hash: bool = False,
    max_title_chars: int | None = None,
    max_summary_chars: int | None = None,
) -> SourceItemUpsertResult:
    """Insert or update one source item.

    Returns ``SourceItemUpsertResult`` with ``status`` in
    ``new`` / ``updated`` / ``unchanged``. New rows are flushed so ``item.id``
    is available to callers (e.g. job board crawl hits).
    """
    url = normalize_url(item_url) if normalize_url else item_url
    title_stored = title[:max_title_chars] if max_title_chars and title else title
    summary_stored = summary
    if max_summary_chars and summary_stored:
        summary_stored = summary_stored[:max_summary_chars]

    digest = source_item_content_hash(title_stored or "", summary_stored or "", lowercase=lowercase_hash)

    existing = session.query(item_cls).filter_by(item_url=url).first()
    if existing:
        if existing.content_hash != digest:
            if title_stored:
                existing.title = title_stored
            if summary_stored or summary:
                existing.summary = summary_stored or summary
            existing.content_hash = digest
            if published_at is not None:
                existing.published_at = published_at
            existing.fetched_at = utcnow()
            existing.is_processed = False
            return SourceItemUpsertResult(status="updated", item=existing)
        existing.fetched_at = utcnow()
        return SourceItemUpsertResult(status="unchanged", item=existing)

    item = item_cls(
        source_id=source_id,
        item_url=url,
        title=title_stored or None,
        summary=summary_stored or None,
        content_hash=digest,
        published_at=published_at,
        fetched_at=utcnow(),
        is_processed=False,
    )
    session.add(item)
    session.flush()
    return SourceItemUpsertResult(status="new", item=item)
