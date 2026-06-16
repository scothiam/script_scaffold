"""RSS/Atom feed crawler — fetches feeds and upserts items into source_items.

Behaviour:
  - New items → inserted with is_processed=False.
  - Re-fetched items, content unchanged → only fetched_at updated.
  - Re-fetched items, content changed → updated and marked unprocessed.
  - Feeds returning HTTP 4xx → source marked inactive.
  - One row per unique item_url across the whole table.

Requires: feedparser
"""

import hashlib
import logging
import re
from datetime import datetime
from typing import Callable

from script_scaffold.sources import Source, SourceItem
from script_scaffold.utils import utcnow

logger = logging.getLogger(__name__)

_MAX_SUMMARY_CHARS = 500


def _parse_published(entry: dict) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        value = entry.get(field)
        if value:
            try:
                return datetime(*value[:6])
            except Exception:
                pass
    return None


def _entry_summary(entry: dict) -> str:
    for field in ("summary", "description"):
        text = entry.get(field, "")
        if text:
            return re.sub(r"<[^>]+>", " ", text).strip()[:_MAX_SUMMARY_CHARS]
    content_list = entry.get("content", [])
    if content_list:
        raw_html = content_list[0].get("value", "")
        return re.sub(r"<[^>]+>", " ", raw_html).strip()[:_MAX_SUMMARY_CHARS]
    return ""


class BaseCrawler:
    """Abstract base for all source crawlers.

    Subclass and implement crawl(). The item_cls constructor argument lets
    consuming projects pass their own SourceItem subclass so rows are inserted
    into the correct table.

    Example::

        class HtmlCrawler(BaseCrawler):
            def crawl(self, source: Source, session) -> tuple[int, int]:
                ...
                return new_count, updated_count
    """

    def __init__(self, item_cls=None):
        self._item_cls = item_cls or SourceItem

    def crawl(self, source: Source, session) -> tuple[int, int]:
        """Fetch one source and upsert its items. Returns (new_count, updated_count)."""
        raise NotImplementedError


class RssCrawler(BaseCrawler):
    """Crawls RSS/Atom feeds using feedparser.

    Marks source.last_crawled_at on success.
    Marks source.is_active=False on persistent HTTP errors.
    """

    def crawl(self, source: Source, session) -> tuple[int, int]:
        try:
            import feedparser
        except ImportError:
            logger.error("feedparser is not installed — run: pip install feedparser")
            return 0, 0

        try:
            feed = feedparser.parse(source.url)
        except Exception as exc:
            logger.warning("RSS fetch failed for %s: %s", source.url, exc)
            return 0, 0

        if not feed.entries:
            status = getattr(feed, "status", None)
            bozo_exc = getattr(feed, "bozo_exception", None)
            if status and status >= 400:
                logger.warning("Feed HTTP %d — marking inactive: %s", status, source.url)
                source.is_active = False
            elif bozo_exc:
                logger.warning("Feed parse error (%s): %s", type(bozo_exc).__name__, source.url)
            else:
                logger.debug("Feed returned no entries: %s", source.url)
            return 0, 0

        new_count = updated_count = 0

        for entry in feed.entries:
            url = (entry.get("link") or "").strip()
            if not url:
                continue

            title = (entry.get("title") or "").strip()
            summary = _entry_summary(entry)
            published_at = _parse_published(entry)
            content_hash = hashlib.sha256(
                (title + summary).encode("utf-8", errors="replace")
            ).hexdigest()

            existing = session.query(self._item_cls).filter_by(item_url=url).first()
            if existing:
                if existing.content_hash != content_hash:
                    existing.title = title
                    existing.summary = summary
                    existing.content_hash = content_hash
                    existing.published_at = published_at
                    existing.fetched_at = utcnow()
                    existing.is_processed = False
                    updated_count += 1
                else:
                    existing.fetched_at = utcnow()
            else:
                session.add(self._item_cls(
                    source_id=source.id,
                    item_url=url,
                    title=title,
                    summary=summary,
                    content_hash=content_hash,
                    published_at=published_at,
                    fetched_at=utcnow(),
                    is_processed=False,
                ))
                new_count += 1

        source.last_crawled_at = utcnow()
        return new_count, updated_count


# ---------------------------------------------------------------------------
# Backward-compatible module-level functions
# ---------------------------------------------------------------------------

def crawl_rss(source: Source, session, item_cls=None) -> tuple[int, int]:
    """Fetch one RSS/Atom feed and upsert items into the session.

    Returns (new_count, updated_count). Marks source.last_crawled_at on success.
    Marks source.is_active=False on persistent HTTP errors.

    item_cls: SourceItem subclass to use when creating/querying rows. Defaults to SourceItem.
    """
    return RssCrawler(item_cls=item_cls).crawl(source, session)


def crawl_sources(sources: list[Source], get_session: Callable, source_cls=None, item_cls=None) -> dict:
    """Crawl a list of sources and return a summary.

    Each source is crawled in its own session so one failure doesn't
    roll back the rest.

    source_cls: Source subclass to use when re-fetching rows. Defaults to Source.
    item_cls: SourceItem subclass to use when inserting/querying rows. Defaults to SourceItem.

    Returns: {sources_crawled, new_items, updated_items, errors}
    """
    if source_cls is None:
        source_cls = Source
    if item_cls is None:
        item_cls = SourceItem

    crawler = RssCrawler(item_cls=item_cls)
    total_new = total_updated = errors = 0

    for source in sources:
        if source.fetch_method == "rss":
            try:
                with get_session() as session:
                    src = session.get(source_cls, source.id)
                    if src is None:
                        continue
                    new_ct, upd_ct = crawler.crawl(src, session)
                total_new += new_ct
                total_updated += upd_ct
                if new_ct or upd_ct:
                    logger.info("Crawled %s — %d new, %d updated", source.url, new_ct, upd_ct)
            except Exception as exc:
                logger.warning("Crawl failed for source %d (%s): %s", source.id, source.url, exc)
                errors += 1
        elif source.fetch_method == "html":
            logger.debug("HTML crawling not yet implemented — skipping %s", source.url)

    return {
        "sources_crawled": len(sources),
        "new_items": total_new,
        "updated_items": total_updated,
        "errors": errors,
    }
