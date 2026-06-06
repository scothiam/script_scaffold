import logging
import os

logger = logging.getLogger(__name__)

_tavily_disabled = False
_openai_disabled = False


def tavily_search(query: str, max_results: int = 5, days: int = 30) -> list[dict]:
    """Run a Tavily search. Returns [] when key is unset, limit hit, or on error.

    Results normalised to {title, url, content}.
    """
    global _tavily_disabled
    if _tavily_disabled or not os.getenv("TAVILY_API_KEY"):
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
        return client.search(query, max_results=max_results, days=days).get("results", [])
    except Exception as exc:
        msg = str(exc).lower()
        if any(kw in msg for kw in ("usage limit", "upgrade your plan", "plan's set")):
            _tavily_disabled = True
            logger.warning("Tavily usage limit reached — disabling for this run")
        else:
            logger.warning("Tavily search failed for %r: %s", query, exc)
        return []


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


def ddg_search(query: str, max_results: int = 5, days: int | None = None) -> list[dict]:
    """Run a DuckDuckGo search. No API key required.

    Results normalised to {title, url, content}.
    """
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
