"""Tests for merge_web_search."""

from unittest.mock import MagicMock, patch

from script_scaffold.search import merge_web_search, merge_web_search_detailed


def test_merge_web_search_dedupes_by_url():
    with patch("script_scaffold.search.DdgSearch") as ddg_cls, patch(
        "script_scaffold.search.TavilySearch"
    ) as tavily_cls:
        ddg = ddg_cls.return_value
        ddg.search.return_value = [
            {"title": "A", "url": "https://example.com/a", "content": "one"},
        ]
        ddg.last_outcome = "ok"
        tavily = tavily_cls.return_value
        tavily.search.return_value = [
            {"title": "A dup", "url": "https://example.com/a", "content": "two"},
            {"title": "B", "url": "https://example.com/b", "content": "three"},
        ]
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
            results = merge_web_search("query", include_tavily=True)
    assert len(results) == 2
    urls = {r["url"] for r in results}
    assert urls == {"https://example.com/a", "https://example.com/b"}


def test_merge_web_search_prefer_tavily_returns_tavily_only():
    with patch("script_scaffold.search.TavilySearch") as tavily_cls, patch(
        "script_scaffold.search.DdgSearch"
    ) as ddg_cls:
        tavily_cls.return_value.search.return_value = [
            {"title": "T", "url": "https://t.example", "content": ""},
        ]
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
            detailed = merge_web_search_detailed("q", prefer_tavily=True, max_results=5)
    assert len(detailed.results) == 1
    assert detailed.results[0]["url"] == "https://t.example"
    ddg_cls.return_value.search.assert_not_called()


def test_merge_web_search_prefer_tavily_falls_back_to_ddg():
    with patch("script_scaffold.search.TavilySearch") as tavily_cls, patch(
        "script_scaffold.search.DdgSearch"
    ) as ddg_cls:
        tavily_cls.return_value.search.return_value = []
        ddg = ddg_cls.return_value
        ddg.search.return_value = [{"title": "D", "url": "https://d.example", "content": ""}]
        ddg.last_outcome = "ok"
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
            detailed = merge_web_search_detailed("q", prefer_tavily=True)
    assert detailed.results[0]["url"] == "https://d.example"
    assert any(o.engine == "tavily" for o in detailed.outcomes)
    assert any(o.engine == "ddg" for o in detailed.outcomes)


def test_merge_web_search_tags_sources():
    with patch("script_scaffold.search.DdgSearch") as ddg_cls, patch(
        "script_scaffold.search.TavilySearch"
    ) as tavily_cls:
        ddg = ddg_cls.return_value
        ddg.search.return_value = [{"title": "A", "url": "https://a.example", "content": ""}]
        ddg.last_outcome = "ok"
        tavily_cls.return_value.search.return_value = []
        results = merge_web_search("q", tag_sources=True, include_tavily=False)
    assert results[0]["_web_source"] == "ddg"
