from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from script_scaffold.utils import utcnow


class Base(DeclarativeBase):
    pass


class PinnableMixin:
    """Adds is_pinned, created_at, updated_at to any tracked item model."""

    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AnalysisMixin:
    """Columns shared by all periodic analysis result tables.

    Provides id, analysis_date, and created_at. The entity foreign key
    (e.g. stock_id, gpu_id) must be defined by the concrete subclass via
    declared_attr so SQLAlchemy generates one constraint per table.

    Usage::

        class MyAnalysis(Base, AnalysisMixin):
            __tablename__ = "my_analysis"

            @declared_attr
            def stock_id(cls) -> Mapped[int]:
                return mapped_column(Integer, ForeignKey("stocks.id"), nullable=False)

            sentiment: Mapped[str] = mapped_column(String(10))
    """

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ScorecardAnalysisMixin(AnalysisMixin):
    """Extends AnalysisMixin with an overall numeric score and LLM response fields.

    Suitable for any scorecard pipeline that produces a single aggregate score
    with a JSON rationale and a raw LLM response. Concrete subclasses add the
    category scores appropriate for their domain.

    Example — mining scorecard::

        class MiningScorecard(Base, ScorecardAnalysisMixin):
            __tablename__ = "mining_scorecard"

            @declared_attr
            def stock_id(cls) -> Mapped[int]:
                return mapped_column(Integer, ForeignKey("stocks.id"), nullable=False)

            resource_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
            management_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """

    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_llm_response: Mapped[str | None] = mapped_column(Text, nullable=True)
