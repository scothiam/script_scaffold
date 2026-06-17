"""LangChain provider factory for structured-output LLM pipelines.

Supported providers (set via LLM_PROVIDER env var):
  litellm    — ChatOpenAI via ai-dev-stack LiteLLM proxy (default). Load-type routes
               (fast, batch, standard, deep, code, audit) with local + cloud fallback.
  openai     — ChatOpenAI direct. Requires OPENAI_API_KEY.
  anthropic  — ChatAnthropic. Requires ANTHROPIC_API_KEY.
  ollama     — ChatOllama pointed at a local/remote Ollama server. No API key needed.

Route selection:
  Pass ``route=`` to get_llm() — e.g. route="deep" for analysis, route="standard"
  for structured extraction. Optional debug override: AI_ROUTE_OVERRIDE=deep.
  CLI --model still sets LLM_MODEL and overrides the route.

Usage::

    from script_scaffold.llm import get_llm, check_credentials, apply_options

    check_credentials()
    llm = get_llm(temperature=0.1, route="deep")
    structured = llm.with_structured_output(MyPydanticSchema)
    result = structured.invoke("Analyse this: ...")
"""

import os

OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
OLLAMA_DEFAULT_MODEL = "qwen3:14b"
OLLAMA_DEFAULT_URL = "http://localhost:11434"
LITELLM_DEFAULT_ROUTE = "deep"


def get_provider() -> str:
    """Return the active LLM provider name (lowercase)."""
    return os.getenv("LLM_PROVIDER", "litellm").lower()


def check_credentials() -> None:
    """Raise SystemExit with a clear message if required credentials are missing."""
    provider = get_provider()
    if provider == "litellm":
        from script_scaffold.search import resolve_ai_config

        if resolve_ai_config() is None:
            raise SystemExit(
                "No AI backend available. Start ai-dev-stack LiteLLM (bash start.sh), "
                "set OPENAI_API_KEY for direct fallback, or set LLM_PROVIDER=openai/ollama."
            )
        return
    if provider == "ollama":
        return
    if provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file or "
            "set LLM_PROVIDER=openai/ollama."
        )
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is not set. Add it to your .env file or "
            "set LLM_PROVIDER=anthropic/ollama."
        )


def _resolve_model(provider: str, route: str | None) -> str:
    """Return the model/route name to pass to the LangChain client."""
    cli_override = os.getenv("LLM_MODEL")
    if cli_override:
        return cli_override

    if provider == "litellm":
        from script_scaffold.search import resolve_route, route_to_model, resolve_ai_config

        config = resolve_ai_config()
        via_litellm = config is not None and config[1] is not None
        resolved = resolve_route(route, default=LITELLM_DEFAULT_ROUTE)
        return route_to_model(resolved, via_litellm=via_litellm)

    if provider == "anthropic":
        return os.getenv("ANTHROPIC_MODEL", ANTHROPIC_DEFAULT_MODEL)
    if provider == "ollama":
        return os.getenv("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)
    return os.getenv("OPENAI_MODEL", OPENAI_DEFAULT_MODEL)


def get_llm(temperature: float = 0.1, route: str | None = None):
    """Return a configured LangChain chat model for the active provider.

    ``route`` selects a LiteLLM load type when LLM_PROVIDER=litellm (default route: deep).
    """
    provider = get_provider()
    model = _resolve_model(provider, route)

    if provider == "litellm":
        from script_scaffold.search import resolve_ai_config

        config = resolve_ai_config()
        if config is None:
            raise SystemExit(
                "No AI backend available. Start ai-dev-stack LiteLLM or set OPENAI_API_KEY."
            )
        api_key, base_url = config
        try:
            from langchain_openai import ChatOpenAI  # noqa: PLC0415
        except ImportError:
            raise SystemExit(
                "langchain-openai is not installed. Run: pip install langchain-openai"
            )
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
        )

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic  # noqa: PLC0415
        except ImportError:
            raise SystemExit(
                "langchain-anthropic is not installed. Run: pip install langchain-anthropic"
            )
        return ChatAnthropic(model=model, temperature=temperature)

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama  # noqa: PLC0415
        except ImportError:
            raise SystemExit(
                "langchain-ollama is not installed. Run: pip install langchain-ollama"
            )
        base_url = os.getenv("OLLAMA_BASE_URL", OLLAMA_DEFAULT_URL)
        return ChatOllama(model=model, base_url=base_url, temperature=temperature)

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI  # noqa: PLC0415
        except ImportError:
            raise SystemExit(
                "langchain-openai is not installed. Run: pip install langchain-openai"
            )
        return ChatOpenAI(model=model, temperature=temperature)

    raise SystemExit(
        f"Unknown LLM_PROVIDER {provider!r}. Valid options: litellm, openai, anthropic, ollama."
    )


def apply_options(provider: str | None, model: str | None) -> None:
    """Apply --provider and --model CLI overrides to the environment."""
    if provider:
        os.environ["LLM_PROVIDER"] = provider
    if model:
        os.environ["LLM_MODEL"] = model


def describe() -> str:
    """Return a short human-readable description of the active LLM configuration."""
    provider = get_provider()
    model = _resolve_model(provider, route=None)
    if provider == "litellm":
        from script_scaffold.search import resolve_ai_config

        config = resolve_ai_config()
        if config:
            _, base_url = config
            return f"litellm  route={model}  url={base_url or 'openai-direct'}"
        return "litellm  (no backend available)"
    if provider == "ollama":
        url = os.getenv("OLLAMA_BASE_URL", OLLAMA_DEFAULT_URL)
        return f"ollama  model={model}  url={url}"
    return f"{provider}  model={model}"
