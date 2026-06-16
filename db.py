from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def make_engine(db_path: Path):
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )


def make_session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(session_factory) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_tables(engine, base: type[DeclarativeBase]) -> None:
    base.metadata.create_all(bind=engine)


def seed_from_list(
    get_session,
    model_cls,
    records: list[dict],
    match_on: list[str],
) -> int:
    """Insert records that do not yet exist. Returns the count of rows inserted.

    For each dict in records, queries the database using the fields in match_on
    to check for an existing row. Inserts only when no match is found.
    Idempotent — safe to call on every startup.

    Args:
        get_session:  Context-manager factory (e.g. the get_session from db.py).
        model_cls:    The SQLAlchemy ORM class to insert into.
        records:      List of dicts; each must contain at least the match_on keys.
        match_on:     Field names used to detect duplicates (e.g. ["url"] or ["domain", "scope"]).

    Example::

        seed_from_list(get_session, Source, SEEDED_SOURCES, match_on=["url", "scope"])
    """
    inserted = 0
    with get_session() as session:
        for data in records:
            filters = {field_name: data[field_name] for field_name in match_on if field_name in data}
            existing = session.query(model_cls).filter_by(**filters).first()
            if not existing:
                session.add(model_cls(**data))
                inserted += 1
    return inserted
