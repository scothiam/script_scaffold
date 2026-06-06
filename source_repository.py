"""Generic repository for Source and SourceItem operations."""

from datetime import timedelta
from typing import Callable
from urllib.parse import urlparse

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from script_scaffold.sources import Source, SourceItem
from script_scaffold.utils import utcnow


class SourceRepository:

    def __init__(self, get_session: Callable):
        self._get_session = get_session

    # ------------------------------------------------------------------
    # Source queries
    # ------------------------------------------------------------------

    def all(self) -> list[Source]:
        with self._get_session() as session:
            return session.query(Source).order_by(Source.scope, Source.scope_value, Source.id).all()

    def find_by_id(self, id: int) -> Source | None:
        with self._get_session() as session:
            return session.get(Source, id)

    def find_by_url(self, url: str) -> Source | None:
        with self._get_session() as session:
            return session.query(Source).filter_by(url=url).first()

    def url_exists(self, url: str) -> bool:
        with self._get_session() as session:
            return session.query(Source).filter_by(url=url).first() is not None

    def url_exists_for_scope(self, url: str, scope_value: str | None) -> bool:
        with self._get_session() as session:
            return (
                session.query(Source)
                .filter_by(url=url, scope_value=scope_value)
                .first()
            ) is not None

    def by_scope(self, scope: str, scope_value: str | None = None) -> list[Source]:
        with self._get_session() as session:
            q = session.query(Source).filter_by(scope=scope)
            if scope_value is not None:
                q = q.filter_by(scope_value=scope_value)
            return q.order_by(Source.id).all()

    def active_crawlable(
        self,
        scopes: list[str] | None = None,
        scope_values: list[str] | None = None,
        fetch_methods: list[str] | None = None,
    ) -> list[Source]:
        """Return active sources matching the given scope/method filters."""
        with self._get_session() as session:
            q = session.query(Source).filter(Source.is_active == True)

            if fetch_methods:
                q = q.filter(Source.fetch_method.in_(fetch_methods))

            if scopes and scope_values is not None:
                q = q.filter(
                    or_(
                        Source.scope_value.is_(None),
                        and_(Source.scope.in_(scopes), Source.scope_value.in_(scope_values)),
                    )
                )
            elif scopes:
                q = q.filter(Source.scope.in_(scopes))

            return q.order_by(Source.scope, Source.scope_value).all()

    # ------------------------------------------------------------------
    # Source writes
    # ------------------------------------------------------------------

    def save(self, source: Source) -> None:
        with self._get_session() as session:
            session.add(source)

    def save_all(self, sources: list[Source]) -> None:
        with self._get_session() as session:
            for s in sources:
                session.add(s)

    def set_active(self, id: int, active: bool) -> Source | None:
        with self._get_session() as session:
            source = session.get(Source, id)
            if source is None:
                return None
            source.is_active = active
            return source

    def delete(self, id: int) -> bool:
        with self._get_session() as session:
            source = session.get(Source, id)
            if source is None:
                return False
            session.delete(source)
            return True

    def mark_crawled(self, id: int) -> None:
        with self._get_session() as session:
            source = session.get(Source, id)
            if source:
                source.last_crawled_at = utcnow()

    # ------------------------------------------------------------------
    # SourceItem queries
    # ------------------------------------------------------------------

    def recent_items(
        self,
        source_ids: list[int],
        cutoff_days: int = 7,
        limit: int = 50,
    ) -> list[SourceItem]:
        if not source_ids:
            return []
        cutoff = utcnow() - timedelta(days=cutoff_days)
        with self._get_session() as session:
            return (
                session.query(SourceItem)
                .filter(
                    SourceItem.source_id.in_(source_ids),
                    or_(SourceItem.published_at >= cutoff, SourceItem.fetched_at >= cutoff),
                )
                .order_by(SourceItem.published_at.desc().nullslast())
                .limit(limit)
                .all()
            )

    def items_mentioning(
        self,
        source_ids: list[int],
        terms: list[str],
        cutoff_days: int = 7,
        limit: int = 20,
    ) -> list[SourceItem]:
        """Find recent items whose title or summary contains any of the given terms."""
        if not source_ids or not terms:
            return []
        cutoff = utcnow() - timedelta(days=cutoff_days)
        mention_clauses = [
            or_(
                SourceItem.title.ilike(f"%{t}%"),
                SourceItem.summary.ilike(f"%{t}%"),
            )
            for t in terms
        ]
        with self._get_session() as session:
            return (
                session.query(SourceItem)
                .filter(
                    SourceItem.source_id.in_(source_ids),
                    or_(SourceItem.published_at >= cutoff, SourceItem.fetched_at >= cutoff),
                    or_(*mention_clauses),
                )
                .order_by(SourceItem.published_at.desc().nullslast())
                .limit(limit)
                .all()
            )


def domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lstrip("www.") or url
