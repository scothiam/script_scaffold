"""Tests for argus_search — ArgusSearch (HTTP client) and the web_search()
fallback switch."""

import json
import urllib.error
from unittest.mock import MagicMock, patch

from script_scaffold.argus_search import ArgusSearch, argus_search, web_search, web_search_detailed
from script_scaffold.search import MergeWebSearchResult, SearchOutcome


def _fake_response(payload: dict):
    body = json.dumps(payload).encode("utf-8")
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body
    cm.__exit__.return_value = False
    return cm


def test_argus_search_returns_normalized_hits():
    payload = {
        "results": [
            {"title": "A", "url": "https://a.example", "snippet": "one"},
            {"title": "B", "url": "https://b.example", "snippet": "two"},
        ]
    }
    with patch("script_scaffold.argus_search.urllib.request.urlopen", return_value=_fake_response(payload)):
        hits = ArgusSearch().search("query", max_results=5)
    assert hits == [
        {"title": "A", "url": "https://a.example", "content": "one"},
        {"title": "B", "url": "https://b.example", "content": "two"},
    ]


def test_argus_search_unavailable_when_server_unreachable():
    with patch(
        "script_scaffold.argus_search.urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        engine = ArgusSearch()
        hits = engine.search("query")
    assert hits == []
    assert engine.last_outcome == "unavailable"


def test_argus_search_unavailable_on_timeout():
    with patch("script_scaffold.argus_search.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        engine = ArgusSearch()
        hits = engine.search("query")
    assert hits == []
    assert engine.last_outcome == "unavailable"


def test_argus_search_handles_bad_json():
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = b"not json"
    cm.__exit__.return_value = False
    with patch("script_scaffold.argus_search.urllib.request.urlopen", return_value=cm):
        engine = ArgusSearch()
        hits = engine.search("query")
    assert hits == []
    assert engine.last_outcome == "error"


def test_argus_search_empty_results():
    with patch("script_scaffold.argus_search.urllib.request.urlopen", return_value=_fake_response({"results": []})):
        engine = ArgusSearch()
        hits = engine.search("query")
    assert hits == []
    assert engine.last_outcome == "empty"


def test_argus_search_wrapper_matches_class():
    payload = {"results": [{"title": "A", "url": "https://a.example", "snippet": ""}]}
    with patch("script_scaffold.argus_search.urllib.request.urlopen", return_value=_fake_response(payload)):
        hits = argus_search("query", max_results=3)
    assert hits == [{"title": "A", "url": "https://a.example", "content": ""}]


def test_web_search_defaults_to_merge_web_search():
    with patch("script_scaffold.argus_search.merge_web_search_detailed") as merge_fn, \
         patch("script_scaffold.argus_search.argus_search") as argus_fn, \
         patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("SEARCH_PROVIDER", None)
        merge_fn.return_value = MergeWebSearchResult(
            results=[{"title": "T", "url": "https://t.example", "content": ""}],
            outcomes=[SearchOutcome(engine="ddg", outcome="ok", count=1)],
        )
        results = web_search("query")
    argus_fn.assert_not_called()
    merge_fn.assert_called_once()
    assert results == [{"title": "T", "url": "https://t.example", "content": ""}]


def test_web_search_uses_argus_when_selected():
    with patch("script_scaffold.argus_search.merge_web_search_detailed") as merge_fn, \
         patch("script_scaffold.argus_search.argus_search") as argus_fn, \
         patch.dict("os.environ", {"SEARCH_PROVIDER": "argus"}):
        argus_fn.return_value = [{"title": "A", "url": "https://a.example", "content": ""}]
        results = web_search("query")
    merge_fn.assert_not_called()
    assert results == [{"title": "A", "url": "https://a.example", "content": ""}]


def test_web_search_falls_back_to_merge_when_argus_empty():
    with patch("script_scaffold.argus_search.merge_web_search_detailed") as merge_fn, \
         patch("script_scaffold.argus_search.argus_search") as argus_fn, \
         patch.dict("os.environ", {"SEARCH_PROVIDER": "argus"}):
        argus_fn.return_value = []
        merge_fn.return_value = MergeWebSearchResult(
            results=[{"title": "T", "url": "https://t.example", "content": ""}],
            outcomes=[SearchOutcome(engine="ddg", outcome="ok", count=1)],
        )
        results = web_search("query")
    argus_fn.assert_called_once()
    merge_fn.assert_called_once()
    assert results == [{"title": "T", "url": "https://t.example", "content": ""}]


def test_web_search_detailed_returns_argus_outcome():
    with patch("script_scaffold.argus_search.argus_search") as argus_fn, \
         patch.dict("os.environ", {"SEARCH_PROVIDER": "argus"}):
        argus_fn.return_value = [{"title": "A", "url": "https://a.example", "content": ""}]
        detailed = web_search_detailed("query")
    assert detailed.results == [{"title": "A", "url": "https://a.example", "content": ""}]
    assert len(detailed.outcomes) == 1
    assert detailed.outcomes[0].engine == "argus"
    assert detailed.outcomes[0].outcome == "ok"
    assert detailed.outcomes[0].count == 1


def test_web_search_detailed_passes_through_ddg_tavily_outcomes():
    with patch("script_scaffold.argus_search.merge_web_search_detailed") as merge_fn, \
         patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("SEARCH_PROVIDER", None)
        expected = MergeWebSearchResult(
            results=[{"title": "T", "url": "https://t.example", "content": ""}],
            outcomes=[
                SearchOutcome(engine="ddg", outcome="ok", count=1),
                SearchOutcome(engine="tavily", outcome="empty", count=0),
            ],
        )
        merge_fn.return_value = expected
        detailed = web_search_detailed("query")
    assert detailed is expected
    assert {o.engine for o in detailed.outcomes} == {"ddg", "tavily"}


def test_web_search_tags_argus_source():
    with patch("script_scaffold.argus_search.argus_search") as argus_fn, \
         patch.dict("os.environ", {"SEARCH_PROVIDER": "argus"}):
        argus_fn.return_value = [{"title": "A", "url": "https://a.example", "content": ""}]
        results = web_search("query", tag_sources=True)
    assert results[0]["_web_source"] == "argus"


def test_web_search_forwards_prefer_tavily_to_merge_fallback():
    with patch("script_scaffold.argus_search.merge_web_search_detailed") as merge_fn, \
         patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("SEARCH_PROVIDER", None)
        merge_fn.return_value = MergeWebSearchResult(
            results=[{"title": "T", "url": "https://t.example", "content": ""}],
            outcomes=[SearchOutcome(engine="tavily", outcome="ok", count=1)],
        )
        web_search("query", prefer_tavily=True)
    assert merge_fn.call_args.kwargs["prefer_tavily"] is True
