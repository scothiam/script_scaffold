import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_tavily_disabled = False
_ai_disabled = False

AI_DEFAULT_MODEL = "gpt-4o-mini"
LITELLM_DEFAULT_URL = "http://localhost:4000"
LITELLM_DEFAULT_KEY = "sk-local-dev-key"

# LiteLLM load-type route names (see ai-dev-stack/litellm_config.yaml).
AI_LOAD_TYPES = frozenset({"fast", "batch", "standard", "deep", "code", "audit"})

# Legacy aliases still accepted by resolve_route().
_LEGACY_ROUTE_ALIASES = {"light": "batch", "heavy": "deep"}

# When LiteLLM is down, map load types to direct OpenAI model IDs.
_DIRECT_CLOUD_MODEL: dict[str, str] = {
    "fast": "gpt-4o-mini",
    "batch": "gpt-4o-mini",
    "standard": "gpt-4o-mini",
    "deep": "gpt-4o",
    "code": "gpt-4o",
    "audit": "gpt-4o",
}

# Deprecated — use AI_LOAD_TYPES and resolve_route() instead.
LITELLM_LIGHT_MODEL = "batch"
LITELLM_HEAVY_MODEL = "deep"

_UNCACHED = object()
_ai_config_cache: tuple[str, str | None] | None | object = _UNCACHED


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

    def search(self, query: str, max_results: int = 5, days: int | None = None) -> list[dict]:
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
            return [
                {"title": result.get("title", ""), "url": result.get("href", ""), "content": result.get("body", "")}
                for result in (results or [])
            ]
        except Exception as exc:
            logger.warning("DuckDuckGo search failed for %r: %s", query, exc)
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

def ddg_search(query: str, max_results: int = 5, days: int | None = None) -> list[dict]:
    """Run a DuckDuckGo search. No API key required.

    Results normalised to {title, url, content}.
    """
    return DdgSearch().search(query, max_results=max_results, days=days)


def tavily_search(query: str, max_results: int = 5, days: int = 30) -> list[dict]:
    """Run a Tavily search. Returns [] when key is unset, limit hit, or on error.

    Results normalised to {title, url, content}.
    """
    return TavilySearch().search(query, max_results=max_results, days=days)


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


def route_to_model(route: str, *, via_litellm: bool) -> str:
    """Return the model string to pass to the OpenAI-compatible API."""
    if via_litellm:
        return route
    return _DIRECT_CLOUD_MODEL.get(route, AI_DEFAULT_MODEL)


def resolve_ai_config() -> tuple[str, str | None] | None:
    """Resolve API key and base URL for ai_chat() / get_llm().

    Priority (matches ai-dev-stack):
    1. Explicit AI_BASE_URL — use AI_API_KEY (or OPENAI_API_KEY) with that endpoint.
    2. LiteLLM proxy at LITELLM_URL when healthy — load-type routes with cloud fallback.
    3. Direct OpenAI via OPENAI_API_KEY or legacy AI_API_KEY.
    """
    global _ai_config_cache
    if _ai_config_cache is not _UNCACHED:
        return _ai_config_cache  # type: ignore[return-value]

    explicit_base = os.getenv("AI_BASE_URL")
    if explicit_base:
        api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if api_key:
            config = (api_key, explicit_base)
            _ai_config_cache = config
            return config
        _ai_config_cache = None
        return None

    litellm_url = os.getenv("LITELLM_URL", LITELLM_DEFAULT_URL)
    if _litellm_healthy(litellm_url):
        config = (
            os.getenv("LITELLM_MASTER_KEY", LITELLM_DEFAULT_KEY),
            f"{litellm_url.rstrip('/')}/v1",
        )
        logger.debug("AI routing via LiteLLM proxy at %s", litellm_url)
        _ai_config_cache = config
        return config

    openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY")
    if openai_key:
        config = (openai_key, None)
        logger.debug("AI routing via direct OpenAI API")
        _ai_config_cache = config
        return config

    _ai_config_cache = None
    return None


def ai_default_model() -> str:
    """Default direct-OpenAI model when no LiteLLM proxy is available."""
    return AI_DEFAULT_MODEL


def ai_chat(
    prompt: str,
    route: str | None = None,
    model: str | None = None,
    json_mode: bool = False,
    temperature: float = 0,
    max_tokens: int | None = None,
) -> str | None:
    """Send a single-turn chat prompt to a configurable OpenAI-compatible endpoint.

    Use ``route`` to select a LiteLLM load type (fast, batch, standard, deep, code,
    audit). When the proxy is unavailable, falls back to direct OpenAI with a
    mapped cloud model. Returns None when no credentials are available or after a
    permanent error.
    """
    global _ai_disabled
    if _ai_disabled:
        return None

    config = resolve_ai_config()
    if config is None:
        return None

    api_key, base_url = config
    via_litellm = base_url is not None
    resolved_route = resolve_route(route, default="fast")
    effective_model = model or route_to_model(resolved_route, via_litellm=via_litellm)
    if not via_litellm and os.getenv("AI_MODEL"):
        effective_model = os.getenv("AI_MODEL", effective_model)

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
