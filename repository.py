from typing import Any, Callable
from contextlib import AbstractContextManager
from sqlalchemy.orm import Session


class BaseRepository:
    """Generic CRUD base. Subclasses supply get_session and the model class."""

    def __init__(self, get_session: Callable[[], AbstractContextManager[Session]], model_cls):
        self._get_session = get_session
        self._model = model_cls

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def all(self) -> list:
        with self._get_session() as session:
            return session.query(self._model).order_by(self._model.id).all()

    def find_by_id(self, record_id: int):
        with self._get_session() as session:
            return session.get(self._model, record_id)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save(self, record) -> None:
        with self._get_session() as session:
            session.add(record)

    def update_by_id(self, record_id: int, **fields: Any) -> bool:
        """Update named fields on a record. Skips fields whose value is None."""
        with self._get_session() as session:
            record = session.get(self._model, record_id)
            if record is None:
                return False
            for field_name, value in fields.items():
                if value is not None:
                    setattr(record, field_name, value)
            return True

    def delete_by_id(self, record_id: int) -> bool:
        with self._get_session() as session:
            record = session.get(self._model, record_id)
            if record is None:
                return False
            session.delete(record)
            return True

    def set_pinned(self, record_id: int, pinned: bool) -> bool:
        with self._get_session() as session:
            record = session.get(self._model, record_id)
            if record is None:
                return False
            record.is_pinned = pinned
            return True
