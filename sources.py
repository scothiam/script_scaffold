"""Source and SourceItem ORM models.

Source  — a known URL (or API endpoint) to fetch content from.
          Scoped so apps can group sources by type (e.g. general vs item-specific).

SourceItem — a single article, post, or page fetched from a Source.
             Deduplicated by item_url; content_hash detects changes on re-fetch.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from script_scaffold.models import Base
from script_scaffold.utils import utcnow


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # scope is app-defined (e.g. "general", "gpu", "stock", "commodity")
    scope: Mapped[str] = mapped_column(String(30), nullable=False)
    # scope_value narrows the scope: None = applies to all, otherwise a key (GPU model, ticker, etc.)
    scope_value: Mapped[str | None] = mapped_column(String(150), nullable=True)

    # quality is app-defined (e.g. "deal_aggregator", "retailer", "community", "trusted_news")
    quality: Mapped[str] = mapped_column(String(40), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)        # None for pure-API entries
    fetch_method: Mapped[str] = mapped_column(String(10), nullable=False)  # rss | html | api
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    discovered_by: Mapped[str] = mapped_column(String(20), nullable=False, default="seeded")  # seeded | manual | auto
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    items: Mapped[list["SourceItem"]] = relationship(
        "SourceItem", back_populates="source", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Source(id={self.id}, scope={self.scope!r}, value={self.scope_value!r}, domain={self.domain!r})>"


class SourceItem(Base):
    """A single article or page fetched from a Source.

    Deduplicated by item_url. content_hash detects whether a previously-seen
    URL has changed since the last fetch, without re-processing unchanged content.
    """

    __tablename__ = "source_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    item_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    source: Mapped["Source"] = relationship("Source", back_populates="items")

    def __repr__(self) -> str:
        return f"<SourceItem(url={self.item_url!r}, processed={self.is_processed})>"
