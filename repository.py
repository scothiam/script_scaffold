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

    def find_by_id(self, id: int):
        with self._get_session() as session:
            return session.get(self._model, id)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save(self, obj) -> None:
        with self._get_session() as session:
            session.add(obj)

    def update_by_id(self, id: int, **fields: Any) -> bool:
        """Update named fields on a record. Skips fields whose value is None."""
        with self._get_session() as session:
            obj = session.get(self._model, id)
            if obj is None:
                return False
            for key, val in fields.items():
                if val is not None:
                    setattr(obj, key, val)
            return True

    def delete_by_id(self, id: int) -> bool:
        with self._get_session() as session:
            obj = session.get(self._model, id)
            if obj is None:
                return False
            session.delete(obj)
            return True

    def set_pinned(self, id: int, pinned: bool) -> bool:
        with self._get_session() as session:
            obj = session.get(self._model, id)
            if obj is None:
                return False
            obj.is_pinned = pinned
            return True
