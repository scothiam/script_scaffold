import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Sequence

logger = logging.getLogger(__name__)

_tavily_disabled = False
_ai_disabled = False

LITELLM_DEFAULT_URL = "http://localhost:4000"
LITELLM_DEFAULT_KEY = "sk-local-dev-key"

# LiteLLM load-type route names (see ai-dev-stack/litellm_config.yaml).
AI_LOAD_TYPES = frozenset({"fast", "batch", "standard", "deep", "code", "audit"})

# Legacy aliases still accepted by resolve_route().
_LEGACY_ROUTE_ALIASES = {"light": "batch", "heavy": "deep"}

# Deprecated — use AI_LOAD_TYPES and resolve_route() instead.
LITELLM_LIGHT_MODEL = "batch"
LITELLM_HEAVY_MODEL = "deep"

_UNCACHED = object()
_ai_config_cache: tuple[str, str] | None | object = _UNCACHED

_DDG_EMPTY_MARKERS = ("no results found",)
_DDG_NETWORK_MARKERS = (
    "timeout",
    "timed out",
    "connecttimeout",
    "connection refused",
    "connecterror",
    "connection error",
    "operation timed out",
)


def classify_ddg_exception(exc: Exception) -> tuple[str, int]:
    """Return (outcome, log_level) for a DDG/ddgs library exception."""
    msg = str(exc).lower()
    if any(marker in msg for marker in _DDG_EMPTY_MARKERS):
        return "empty", logging.INFO
    if any(marker in msg for marker in _DDG_NETWORK_MARKERS):
        return "error", logging.WARNING
    return "failed", logging.WARNING


def log_ddg_outcome(
    query: str,
    exc: Exception,
    *,
    context: str = "",
) -> str:
    """Log a DDG search exception at the appropriate level. Returns outcome token."""
    outcome, level = classify_ddg_exception(exc)
    prefix = f"[{context}] " if context else ""
    logger.log(
        level,
        "DDG search %s %squery=%r: %s",
        outcome,
        prefix,
        query,
        exc,
    )
    return outcome


class BaseSearch:
    """Abstract base for all web/API search implementations.

    Subclass and implement search(). The normalised result contract is a list
    of dicts with at minimum {title, url, content}.

    Example::

        class MySearch(BaseSearch):
            def search(self, query, max_results=5, days=None):
                ...
                return [{"title": ..., "url": ..., "content": ...}]
    """

    def search(self, query: str, max_results: int = 5, days: int | None = None) -> list[dict]:
        """Execute a search and return normalised {title, url, content} dicts."""
        raise NotImplementedError


class DdgSearch(BaseSearch):
    """DuckDuckGo text search. No API key required."""

    last_outcome: str = "ok"

    def search(
        self,
        query: str,
        max_results: int = 5,
        days: int | None = None,
        *,
        context: str = "",
    ) -> list[dict]:
        self.last_outcome = "ok"
        timelimit: str | None = None
        if days is not None:
            if days <= 1:
                timelimit = "d"
            elif days <= 7:
                timelimit = "w"
            elif days <= 31:
                timelimit = "m"
        try:
            from ddgs import DDGS
            results = DDGS().text(query, max_results=max_results, timelimit=timelimit)
            parsed = [
                {"title": result.get("title", ""), "url": result.get("href", ""), "content": result.get("body", "")}
                for result in (results or [])
            ]
            if not parsed:
                self.last_outcome = "empty"
                prefix = f"[{context}] " if context else ""
                logger.info("DDG search empty %squery=%r", prefix, query)
            return parsed
        except Exception as exc:
            self.last_outcome = log_ddg_outcome(query, exc, context=context)
            return []


class TavilySearch(BaseSearch):
    """Tavily web search. Requires TAVILY_API_KEY.

    Automatically disables itself for the process lifetime when the usage
    limit is hit, so callers degrade gracefully without crashing.
    """

    def search(self, query: str, max_results: int = 5, days: int | None = None) -> list[dict]:
        global _tavily_disabled
        if _tavily_disabled or not os.getenv("TAVILY_API_KEY"):
            return []
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
            kwargs: dict = {"max_results": max_results}
            if days is not None:
                kwargs["days"] = days
            return client.search(query, **kwargs).get("results", [])
        except Exception as exc:
            error_message = str(exc).lower()
            if any(keyword in error_message for keyword in ("usage limit", "upgrade your plan", "plan's set")):
                _tavily_disabled = True
                logger.warning("Tavily usage limit reached — disabling for this run")
            else:
                logger.warning("Tavily search failed for %r: %s", query, exc)
            return []


# ---------------------------------------------------------------------------
# Backward-compatible module-level functions
# ---------------------------------------------------------------------------

def ddg_search(
    query: str,
    max_results: int = 5,
    days: int | None = None,
    *,
    context: str = "",
) -> list[dict]:
    """Run a DuckDuckGo search. No API key required.

    Results normalised to {title, url, content}.
    """
    return DdgSearch().search(query, max_results=max_results, days=days, context=context)


def tavily_search(query: str, max_results: int = 5, days: int = 30) -> list[dict]:
    """Run a Tavily search. Returns [] when key is unset, limit hit, or on error.

    Results normalised to {title, url, content}.
    """
    return TavilySearch().search(query, max_results=max_results, days=days)


# ---------------------------------------------------------------------------
# Merged web search
# ---------------------------------------------------------------------------

def _normalize_search_hit(hit: dict) -> dict:
    """Ensure {title, url, content} keys for merged results."""
    return {
        "title": hit.get("title") or "",
        "url": hit.get("url") or hit.get("href") or "",
        "content": hit.get("content") or hit.get("body") or "",
    }


@dataclass
class SearchOutcome:
    """Per-engine result of a web search call."""

    engine: str
    outcome: str
    count: int = 0


@dataclass
class MergeWebSearchResult:
    """Merged hits plus per-engine outcomes for metrics and fallback decisions."""

    results: list[dict] = field(default_factory=list)
    outcomes: list[SearchOutcome] = field(default_factory=list)


def merge_web_search(
    query: str,
    *,
    max_results: int = 10,
    days: int | None = None,
    prefer_tavily: bool = False,
    include_tavily: bool = True,
    ddg_context: str = "",
    dedupe_key: Callable[[dict], str] | None = None,
    tag_sources: bool = False,
) -> list[dict]:
    """Merge DuckDuckGo and optional Tavily results with URL deduplication."""
    return merge_web_search_detailed(
        query,
        max_results=max_results,
        days=days,
        prefer_tavily=prefer_tavily,
        include_tavily=include_tavily,
        ddg_context=ddg_context,
        dedupe_key=dedupe_key,
        tag_sources=tag_sources,
    ).results


def merge_web_search_detailed(
    query: str,
    *,
    max_results: int = 10,
    days: int | None = None,
    prefer_tavily: bool = False,
    include_tavily: bool = True,
    ddg_context: str = "",
    dedupe_key: Callable[[dict], str] | None = None,
    tag_sources: bool = False,
    engines: Sequence[BaseSearch] | None = None,
) -> MergeWebSearchResult:
    """Merge web search engines; return hits and per-engine outcomes."""
    key_fn = dedupe_key or (lambda hit: (hit.get("url") or "").strip().lower())

    if prefer_tavily and include_tavily and os.getenv("TAVILY_API_KEY"):
        tavily = TavilySearch()
        tavily_raw = [
            _normalize_search_hit(h)
            for h in tavily.search(query, max_results=max_results, days=days or 30)
        ]
        tavily_outcome = SearchOutcome(
            engine="tavily",
            outcome="empty" if not tavily_raw else "ok",
            count=len(tavily_raw),
        )
        if tavily_raw:
            if tag_sources:
                for hit in tavily_raw:
                    hit["_web_source"] = "tavily"
            return MergeWebSearchResult(results=tavily_raw, outcomes=[tavily_outcome])

        ddg = DdgSearch()
        ddg_raw = [
            _normalize_search_hit(h)
            for h in ddg.search(query, max_results=max_results, days=days, context=ddg_context)
        ]
        if tag_sources:
            for hit in ddg_raw:
                hit["_web_source"] = "ddg"
        return MergeWebSearchResult(
            results=ddg_raw,
            outcomes=[
                tavily_outcome,
                SearchOutcome(engine="ddg", outcome=ddg.last_outcome, count=len(ddg_raw)),
            ],
        )

    ddg = DdgSearch()
    batches: list[tuple[str, list[dict], str]] = []
    ddg_raw = [
        _normalize_search_hit(h)
        for h in ddg.search(query, max_results=max_results, days=days, context=ddg_context)
    ]
    batches.append(("ddg", ddg_raw, ddg.last_outcome))

    if include_tavily and os.getenv("TAVILY_API_KEY"):
        tavily = TavilySearch()
        tavily_raw = [
            _normalize_search_hit(h)
            for h in tavily.search(query, max_results=max_results, days=days or 30)
        ]
        batches.append(("tavily", tavily_raw, "empty" if not tavily_raw else "ok"))
    elif include_tavily:
        batches.append(("tavily", [], "disabled"))

    seen: set[str] = set()
    merged: list[dict] = []
    outcomes: list[SearchOutcome] = []

    for engine, raw, outcome in batches:
        outcomes.append(SearchOutcome(engine=engine, outcome=outcome, count=len(raw)))
        for hit in raw:
            key = key_fn(hit)
            if not key or key in seen:
                continue
            seen.add(key)
            if tag_sources:
                hit = dict(hit)
                hit["_web_source"] = engine
            merged.append(hit)

    return MergeWebSearchResult(results=merged, outcomes=outcomes)


# ---------------------------------------------------------------------------
# LLM helper — single-turn chat, not web search
# ---------------------------------------------------------------------------

def _litellm_healthy(url: str) -> bool:
    master_key = os.getenv("LITELLM_MASTER_KEY", LITELLM_DEFAULT_KEY)
    request = urllib.request.Request(
        f"{url.rstrip('/')}/v1/models",
        headers={"Authorization": f"Bearer {master_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def resolve_route(route: str | None = None, *, default: str = "fast") -> str:
    """Resolve a LiteLLM load-type route name for the current request.

    Priority: AI_ROUTE_OVERRIDE → explicit route arg → legacy env vars
    (AI_FILTER_MODEL, LLM_ROUTE, AI_MODEL) → default.
    """
    override = os.getenv("AI_ROUTE_OVERRIDE", "").strip()
    if override:
        return _LEGACY_ROUTE_ALIASES.get(override, override)

    if route:
        return _LEGACY_ROUTE_ALIASES.get(route, route)

    for env_name in ("AI_FILTER_MODEL", "LLM_ROUTE", "AI_MODEL"):
        legacy = os.getenv(env_name, "").strip()
        if legacy:
            logger.debug("Using deprecated %s=%r — set route= at call site instead", env_name, legacy)
            return _LEGACY_ROUTE_ALIASES.get(legacy, legacy)

    return default


def resolve_ai_config() -> tuple[str, str] | None:
    """Resolve API key and base URL for ai_chat() / get_llm().

    All AI calls route exclusively through the ai-dev-stack LiteLLM proxy at
    LITELLM_URL. Returns None (and logs loudly) when the proxy is unreachable —
    callers must treat that as "AI unavailable," never fall back to a direct
    provider.
    """
    global _ai_config_cache
    if _ai_config_cache is not _UNCACHED:
        return _ai_config_cache  # type: ignore[return-value]

    litellm_url = os.getenv("LITELLM_URL", LITELLM_DEFAULT_URL)
    if not _litellm_healthy(litellm_url):
        logger.error(
            "LiteLLM proxy at %s is unreachable — AI features disabled for this run. "
            "Start it with 'bash start.sh' in ai-dev-stack.",
            litellm_url,
        )
        _ai_config_cache = None
        return None

    config = (
        os.getenv("LITELLM_MASTER_KEY", LITELLM_DEFAULT_KEY),
        f"{litellm_url.rstrip('/')}/v1",
    )
    logger.debug("AI routing via LiteLLM proxy at %s", litellm_url)
    _ai_config_cache = config
    return config


def ai_chat(
    prompt: str,
    route: str | None = None,
    model: str | None = None,
    json_mode: bool = False,
    temperature: float = 0,
    max_tokens: int | None = None,
) -> str | None:
    """Send a single-turn chat prompt through the ai-dev-stack LiteLLM proxy.

    Use ``route`` to select a LiteLLM load type (fast, batch, standard, deep, code,
    audit). Returns None when the proxy is unavailable or after a permanent error —
    never falls back to a direct provider.
    """
    global _ai_disabled
    if _ai_disabled:
        return None

    config = resolve_ai_config()
    if config is None:
        return None

    api_key, base_url = config
    resolved_route = resolve_route(route, default="fast")
    effective_model = model or resolved_route

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        kwargs: dict = {
            "model": effective_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
            # Qwen3 thinking models return empty content via LiteLLM's ollama/
            # provider unless thinking is disabled — breaks JSON listing validation.
            kwargs["reasoning_effort"] = "none"
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
    except Exception as exc:
        error_message = str(exc).lower()
        if any(keyword in error_message for keyword in ("invalid_api_key", "authentication", "quota exceeded", "credit balance", "permission_error")):
            _ai_disabled = True
            logger.warning("AI chat disabled for this run: %s", exc)
        else:
            logger.warning("AI chat failed: %s", exc)
        return None


@dataclass
class AiChatChunkOutcome:
    """Per-prompt outcome from ``ai_chat_chunks``."""

    reply: str | None
    triggered: bool
    skip_reason: str | None = None


def ai_chat_chunks(
    prompts: list[str],
    *,
    route: str | None = "batch",
    json_mode: bool = False,
    max_tokens: int | None = None,
    temperature: float = 0,
) -> list[AiChatChunkOutcome]:
    """Run ``ai_chat`` once per prompt — transport-only batch helper.

    Domain backends (job-hunt, price-checker) build prompts and parse JSON
    replies; this function only sequences LLM calls.
    """
    outcomes: list[AiChatChunkOutcome] = []
    for prompt in prompts:
        reply = ai_chat(
            prompt,
            route=route,
            json_mode=json_mode,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if reply is None:
            outcomes.append(AiChatChunkOutcome(
                reply=None,
                triggered=False,
                skip_reason="no_api_key_or_call_failed",
            ))
        else:
            outcomes.append(AiChatChunkOutcome(reply=reply, triggered=True))
    return outcomes
