"""Generic repository for Source and SourceItem operations."""

from datetime import datetime, timedelta
from typing import Callable, Type
from urllib.parse import urlparse

from sqlalchemy import and_, or_

from script_scaffold.sources import Source, SourceItem
from script_scaffold.utils import utcnow


class SourceRepository:

    def __init__(
        self,
        get_session: Callable,
        source_cls: Type | None = None,
        source_item_cls: Type | None = None,
    ):
        self._get_session = get_session
        self._Source = source_cls or Source
        self._SourceItem = source_item_cls or SourceItem

    # ------------------------------------------------------------------
    # Source queries
    # ------------------------------------------------------------------

    def all(self) -> list:
        with self._get_session() as session:
            return session.query(self._Source).order_by(self._Source.scope, self._Source.scope_value, self._Source.id).all()

    def find_by_id(self, id: int):
        with self._get_session() as session:
            return session.get(self._Source, id)

    def find_by_url(self, url: str):
        with self._get_session() as session:
            return session.query(self._Source).filter_by(url=url).first()

    def url_exists(self, url: str) -> bool:
        with self._get_session() as session:
            return session.query(self._Source).filter_by(url=url).first() is not None

    def url_exists_for_scope(self, url: str, scope_value: str | None) -> bool:
        with self._get_session() as session:
            return (
                session.query(self._Source)
                .filter_by(url=url, scope_value=scope_value)
                .first()
            ) is not None

    def by_scope(self, scope: str, scope_value: str | None = None, active_only: bool = False) -> list:
        with self._get_session() as session:
            q = session.query(self._Source).filter_by(scope=scope)
            if scope_value is not None:
                q = q.filter_by(scope_value=scope_value)
            if active_only:
                q = q.filter(self._Source.is_active == True)
            return q.order_by(self._Source.id).all()

    def active_crawlable(
        self,
        scopes: list[str] | None = None,
        scope_values: list[str] | None = None,
        fetch_methods: list[str] | None = None,
    ) -> list:
        """Return active sources matching the given scope/method filters."""
        with self._get_session() as session:
            q = session.query(self._Source).filter(self._Source.is_active == True)

            if fetch_methods:
                q = q.filter(self._Source.fetch_method.in_(fetch_methods))

            if scopes and scope_values is not None:
                q = q.filter(
                    or_(
                        self._Source.scope_value.is_(None),
                        and_(self._Source.scope.in_(scopes), self._Source.scope_value.in_(scope_values)),
                    )
                )
            elif scopes:
                q = q.filter(self._Source.scope.in_(scopes))

            return q.order_by(self._Source.scope, self._Source.scope_value).all()

    # ------------------------------------------------------------------
    # Source writes
    # ------------------------------------------------------------------

    def save(self, source) -> None:
        with self._get_session() as session:
            session.add(source)

    def save_all(self, sources: list) -> None:
        with self._get_session() as session:
            for s in sources:
                session.add(s)

    def set_active(self, id: int, active: bool):
        with self._get_session() as session:
            source = session.get(self._Source, id)
            if source is None:
                return None
            source.is_active = active
            return source

    def delete(self, id: int) -> bool:
        with self._get_session() as session:
            source = session.get(self._Source, id)
            if source is None:
                return False
            session.delete(source)
            return True

    def mark_crawled(self, id: int) -> None:
        with self._get_session() as session:
            source = session.get(self._Source, id)
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
    ) -> list:
        if not source_ids:
            return []
        cutoff = utcnow() - timedelta(days=cutoff_days)
        with self._get_session() as session:
            return (
                session.query(self._SourceItem)
                .filter(
                    self._SourceItem.source_id.in_(source_ids),
                    or_(self._SourceItem.published_at >= cutoff, self._SourceItem.fetched_at >= cutoff),
                )
                .order_by(self._SourceItem.published_at.desc().nullslast())
                .limit(limit)
                .all()
            )

    def items_in_range(
        self,
        source_ids: list[int],
        start: datetime,
        end: datetime,
        limit: int = 50,
    ) -> list:
        """Return items published in [start, end), ordered by published_at desc."""
        if not source_ids:
            return []
        with self._get_session() as session:
            return (
                session.query(self._SourceItem)
                .filter(
                    self._SourceItem.source_id.in_(source_ids),
                    self._SourceItem.published_at >= start,
                    self._SourceItem.published_at < end,
                )
                .order_by(self._SourceItem.published_at.desc())
                .limit(limit)
                .all()
            )

    def items_mentioning(
        self,
        source_ids: list[int],
        terms: list[str],
        cutoff_days: int = 7,
        limit: int = 20,
    ) -> list:
        """Find recent items whose title or summary contains any of the given terms."""
        if not source_ids or not terms:
            return []
        cutoff = utcnow() - timedelta(days=cutoff_days)
        mention_clauses = [
            or_(
                self._SourceItem.title.ilike(f"%{t}%"),
                self._SourceItem.summary.ilike(f"%{t}%"),
            )
            for t in terms
        ]
        with self._get_session() as session:
            return (
                session.query(self._SourceItem)
                .filter(
                    self._SourceItem.source_id.in_(source_ids),
                    or_(self._SourceItem.published_at >= cutoff, self._SourceItem.fetched_at >= cutoff),
                    or_(*mention_clauses),
                )
                .order_by(self._SourceItem.published_at.desc().nullslast())
                .limit(limit)
                .all()
            )

    def items_mentioning_in_range(
        self,
        source_ids: list[int],
        terms: list[str],
        start: datetime,
        end: datetime,
        limit: int = 20,
    ) -> list:
        """Find items in [start, end) whose title or summary contains any of the given terms."""
        if not source_ids or not terms:
            return []
        mention_clauses = [
            or_(
                self._SourceItem.title.ilike(f"%{t}%"),
                self._SourceItem.summary.ilike(f"%{t}%"),
            )
            for t in terms
        ]
        with self._get_session() as session:
            return (
                session.query(self._SourceItem)
                .filter(
                    self._SourceItem.source_id.in_(source_ids),
                    self._SourceItem.published_at >= start,
                    self._SourceItem.published_at < end,
                    or_(*mention_clauses),
                )
                .order_by(self._SourceItem.published_at.desc())
                .limit(limit)
                .all()
            )


def domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lstrip("www.") or url
