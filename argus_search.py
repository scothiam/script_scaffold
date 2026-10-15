"""Argus-based web search provider — additive, does not modify search.py.

Argus (https://github.com/Khamel83/argus, PyPI: argus-search) is a
multi-provider search broker: it fans out across DuckDuckGo/Yahoo/GitHub
(free, no key required) plus optional paid/keyed providers, with its own
ranking, dedup, and caching. This module talks to a running `argus serve`
instance over HTTP and provides a provider-switchable web_search() entry
point so callers can fall back to the original Tavily+DDG behavior
(script_scaffold.search.merge_web_search) at any time via one env var —
no code changes required to revert.

Why HTTP, not the `argus` CLI directly: Argus's query cache
(argus/broker/cache.py) is a plain in-memory dict owned by the broker
instance. The CLI builds a fresh broker (and therefore an empty cache) on
every invocation and discards it on exit, so CLI mode can never benefit
from caching across calls — confirmed by direct testing and by reading
Argus's source (argus/broker/router.py's create_broker(),
argus/api/main.py's lazy broker singleton). `argus serve` keeps one broker
alive for the life of the process, so its cache actually persists across
requests (verified: repeat query returns "cached": true). ARGUS_URL points
at that persistent instance — see ai-dev-stack/start_argus.sh, which runs
it alongside LiteLLM so the 7-day cache TTL spans separate daily.sh runs,
not just one.

Fails soft like DdgSearch/TavilySearch: returns [] rather than raising if
the Argus server is unreachable, times out, or errors.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from script_scaffold.search import (
    BaseSearch,
    MergeWebSearchResult,
    SearchOutcome,
    merge_web_search_detailed,
)

logger = logging.getLogger(__name__)

ARGUS_DEFAULT_URL = "http://192.168.0.121:8000"
_ARGUS_TIMEOUT = float(os.getenv("ARGUS_TIMEOUT", "30"))


class ArgusSearch(BaseSearch):
    """Search provider backed by a running `argus serve` instance (HTTP)."""

    last_outcome: str = "ok"

    def search(self, query: str, max_results: int = 5, days: int | None = None) -> list[dict]:
        del days  # argus does not take a recency window; providers decide freshness themselves
        base_url = os.getenv("ARGUS_URL", ARGUS_DEFAULT_URL).rstrip("/")
        payload = json.dumps({
            "query": query,
            "mode": "discovery",
            "max_results": max_results,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/search",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=_ARGUS_TIMEOUT) as response:
                data = json.loads(response.read())
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            self.last_outcome = "unavailable"
            logger.warning("Argus server at %s unreachable for query=%r: %s", base_url, query, exc)
            return []
        except json.JSONDecodeError as exc:
            self.last_outcome = "error"
            logger.warning("Argus search returned invalid JSON for query=%r: %s", query, exc)
            return []

        hits = [
            {
                "title": r.get("title") or "",
                "url": r.get("url") or "",
                "content": r.get("snippet") or "",
            }
            for r in data.get("results", [])
        ]
        self.last_outcome = "ok" if hits else "empty"
        return hits


def argus_search(query: str, max_results: int = 5) -> list[dict]:
    """Run an Argus search. Returns [] when the server is unreachable or on error.

    Results normalised to {title, url, content}, mirroring tavily_search/
    ddg_search in script_scaffold.search.
    """
    return ArgusSearch().search(query, max_results=max_results)


def web_search(
    query: str,
    *,
    max_results: int = 10,
    days: int | None = None,
    prefer_tavily: bool = False,
    ddg_context: str = "",
    tag_sources: bool = False,
) -> list[dict]:
    """Provider-switchable web search — the intended fallback point.

    Default (SEARCH_PROVIDER unset, or set to anything other than "argus"):
    calls script_scaffold.search.merge_web_search_detailed unchanged — the
    original Tavily+DDG behavior, exactly as it worked before this module
    existed (including prefer_tavily semantics, for callers like
    ticker-snapshot that rely on Tavily-first/DDG-fallback rather than a
    merged fan-out).

    Set SEARCH_PROVIDER=argus to route through Argus instead (requires
    `argus serve` running and reachable at ARGUS_URL, default
    http://192.168.0.121:8000, the opi16 hub's container — see ai-dev-stack/agent/FLOW.md). If Argus
    returns no results for a given call, this falls back to the original
    merge automatically for that call. To fully revert to the original
    behavior, just unset SEARCH_PROVIDER — no code changes needed at any
    call site that already uses web_search().
    """
    return web_search_detailed(
        query,
        max_results=max_results,
        days=days,
        prefer_tavily=prefer_tavily,
        ddg_context=ddg_context,
        tag_sources=tag_sources,
    ).results


def web_search_detailed(
    query: str,
    *,
    max_results: int = 10,
    days: int | None = None,
    prefer_tavily: bool = False,
    ddg_context: str = "",
    tag_sources: bool = False,
) -> MergeWebSearchResult:
    """Provider-switchable web search with per-engine outcomes.

    Same fallback contract as web_search(), but returns the
    MergeWebSearchResult shape (results + per-engine SearchOutcome list)
    for callers that need it — e.g. price_checker/retail_search.py's
    metrics/tracing, which reads outcomes by engine name ("ddg"/"tavily").
    When routed through Argus, outcomes contains a single entry with
    engine="argus" instead — prefer_tavily has no effect on that branch,
    since Argus does its own provider ranking; it's only forwarded to the
    merge_web_search_detailed fallback path.
    """
    provider = os.getenv("SEARCH_PROVIDER", "").strip().lower()
    if provider == "argus":
        hits = argus_search(query, max_results=max_results)
        if hits:
            if tag_sources:
                for hit in hits:
                    hit["_web_source"] = "argus"
            return MergeWebSearchResult(
                results=hits,
                outcomes=[SearchOutcome(engine="argus", outcome="ok", count=len(hits))],
            )
        logger.info("Argus returned no results for query=%r; falling back to Tavily/DDG", query)

    return merge_web_search_detailed(
        query,
        max_results=max_results,
        days=days,
        prefer_tavily=prefer_tavily,
        ddg_context=ddg_context,
        tag_sources=tag_sources,
    )
