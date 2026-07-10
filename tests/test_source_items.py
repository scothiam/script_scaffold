"""Tests for shared SourceItem upsert helpers."""

from script_scaffold.source_items import (
    SourceItemUpsertResult,
    source_item_content_hash,
    upsert_source_item,
)


class _FakeItem:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.id = kwargs.get("id")


class _FakeQuery:
    def __init__(self, session):
        self._session = session
        self._filters = {}

    def filter_by(self, **kwargs):
        self._filters = kwargs
        return self

    def first(self):
        for item in self._session._items:
            if all(getattr(item, k, None) == v for k, v in self._filters.items()):
                return item
        return None


class _FakeSession:
    def __init__(self):
        self._items = []
        self.added = []
        self._next_id = 1

    def query(self, item_cls):
        return _FakeQuery(self)

    def add(self, item):
        item.id = self._next_id
        self._next_id += 1
        self.added.append(item)
        self._items.append(item)

    def flush(self):
        pass


def test_source_item_content_hash_lowercase_mode():
    assert source_item_content_hash("Title", "Body", lowercase=True) == source_item_content_hash(
        "title", "body", lowercase=True
    )


def test_upsert_source_item_inserts_new():
    session = _FakeSession()
    result = upsert_source_item(
        session,
        _FakeItem,
        3,
        item_url="https://example.com/item",
        title="DDR5 32GB",
        summary="$99",
    )
    assert isinstance(result, SourceItemUpsertResult)
    assert result.status == "new"
    assert result.item.id == 1


def test_upsert_source_item_normalizes_url():
    session = _FakeSession()
    result = upsert_source_item(
        session,
        _FakeItem,
        3,
        item_url="https://Example.com/Jobs/1?utm=1",
        title="Job",
        normalize_url=lambda url: url.split("?")[0].lower(),
    )
    assert result.item.item_url == "https://example.com/jobs/1"


def test_upsert_source_item_updates_on_hash_change():
    session = _FakeSession()
    existing = _FakeItem(
        id=5,
        source_id=3,
        item_url="https://example.com/item",
        title="Old",
        summary="",
        content_hash=source_item_content_hash("Old", ""),
        is_processed=True,
    )
    session._items.append(existing)

    result = upsert_source_item(
        session,
        _FakeItem,
        3,
        item_url="https://example.com/item",
        title="New title",
    )
    assert result.status == "updated"
    assert existing.title == "New title"
    assert existing.is_processed is False
