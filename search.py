import logging
import os

logger = logging.getLogger(__name__)

_tavily_disabled = False
_openai_disabled = False
_anthropic_disabled = False


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
                {"title": r.get("title", ""), "url": r.get("href", ""), "content": r.get("body", "")}
                for r in (results or [])
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
            msg = str(exc).lower()
            if any(kw in msg for kw in ("usage limit", "upgrade your plan", "plan's set")):
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
# LLM helpers — single-turn chat, not web search
# ---------------------------------------------------------------------------

def openai_chat(
    prompt: str,
    model: str = "gpt-4o-mini",
    json_mode: bool = False,
    temperature: float = 0,
) -> str | None:
    """Send a single-turn chat prompt to OpenAI. Returns the reply text, or None on failure.

    Returns None (gracefully) when OPENAI_API_KEY is unset or after a permanent error,
    so callers can degrade gracefully without crashing.
    """
    global _openai_disabled
    if _openai_disabled or not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
    except Exception as exc:
        msg = str(exc).lower()
        if any(kw in msg for kw in ("invalid_api_key", "authentication", "quota exceeded")):
            _openai_disabled = True
            logger.warning("OpenAI disabled for this run: %s", exc)
        else:
            logger.warning("OpenAI chat failed: %s", exc)
        return None


def anthropic_chat(
    prompt: str,
    model: str = "claude-haiku-4-5-20251001",
    json_mode: bool = False,
    temperature: float = 0,
    max_tokens: int = 1024,
) -> str | None:
    """Send a single-turn prompt to Anthropic. Returns the reply text, or None on failure.

    Returns None (gracefully) when ANTHROPIC_API_KEY is unset or after a permanent
    error, so callers can degrade gracefully without crashing.

    When json_mode=True a system prompt is added instructing the model to respond
    with valid JSON only (Anthropic has no native JSON-mode parameter).
    """
    global _anthropic_disabled
    if _anthropic_disabled or not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            kwargs["system"] = "Respond with valid JSON only. Do not include any other text."
        response = client.messages.create(**kwargs)
        return response.content[0].text
    except Exception as exc:
        msg = str(exc).lower()
        if any(kw in msg for kw in ("authentication_error", "invalid_api_key", "credit balance", "permission_error")):
            _anthropic_disabled = True
            logger.warning("Anthropic disabled for this run: %s", exc)
        else:
            logger.warning("Anthropic chat failed: %s", exc)
        return None
