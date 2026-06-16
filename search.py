import logging
import os

logger = logging.getLogger(__name__)

_tavily_disabled = False
_ai_disabled = False

AI_DEFAULT_MODEL = "gpt-4o-mini"


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

def ai_chat(
    prompt: str,
    model: str | None = None,
    json_mode: bool = False,
    temperature: float = 0,
    max_tokens: int | None = None,
) -> str | None:
    """Send a single-turn chat prompt to a configurable OpenAI-compatible endpoint.

    Endpoint, key, and model are read from AI_BASE_URL / AI_API_KEY / AI_MODEL, so the
    same function can hit OpenAI itself (the default, if AI_BASE_URL is unset), Anthropic's
    OpenAI-compatible endpoint, a local Ollama/vLLM/LM Studio server, OpenRouter, etc. —
    whatever base_url the deployment points it at.

    Returns None (gracefully) when AI_API_KEY is unset or after a permanent error, so
    callers can degrade gracefully without crashing.

    json_mode=True requests response_format={"type": "json_object"}; not every
    OpenAI-compatible endpoint honors this, so verify it against your configured provider.
    """
    global _ai_disabled
    if _ai_disabled or not os.getenv("AI_API_KEY"):
        return None
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["AI_API_KEY"],
            base_url=os.getenv("AI_BASE_URL") or None,
        )
        kwargs: dict = {
            "model": model or os.getenv("AI_MODEL", AI_DEFAULT_MODEL),
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
