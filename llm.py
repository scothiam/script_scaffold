"""LangChain provider factory for structured-output LLM pipelines.

Supported providers (set via LLM_PROVIDER env var):
  litellm    — ChatOpenAI via ai-dev-stack LiteLLM proxy (default, and the only
               provider that reaches cloud models). Load-type routes (fast, batch,
               standard, deep, code, audit); the proxy itself handles local vs.
               cloud fallback server-side. No API keys are read by this module.
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
                "LiteLLM proxy is unavailable. Start it with 'bash start.sh' in "
                "ai-dev-stack, or set LLM_PROVIDER=ollama for a local-only run."
            )
        return
    if provider == "ollama":
        return
    raise SystemExit(
        f"Unknown LLM_PROVIDER {provider!r}. Valid options: litellm, ollama."
    )


def _resolve_model(provider: str, route: str | None) -> str:
    """Return the model/route name to pass to the LangChain client."""
    cli_override = os.getenv("LLM_MODEL")
    if cli_override:
        return cli_override

    if provider == "litellm":
        from script_scaffold.search import resolve_route

        return resolve_route(route, default=LITELLM_DEFAULT_ROUTE)

    return os.getenv("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)


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
                "LiteLLM proxy is unavailable. Start it with 'bash start.sh' in "
                "ai-dev-stack, or set LLM_PROVIDER=ollama for a local-only run."
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

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama  # noqa: PLC0415
        except ImportError:
            raise SystemExit(
                "langchain-ollama is not installed. Run: pip install langchain-ollama"
            )
        base_url = os.getenv("OLLAMA_BASE_URL", OLLAMA_DEFAULT_URL)
        return ChatOllama(model=model, base_url=base_url, temperature=temperature)

    raise SystemExit(
        f"Unknown LLM_PROVIDER {provider!r}. Valid options: litellm, ollama."
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
            return f"litellm  route={model}  url={base_url}"
        return "litellm  (no backend available)"
    if provider == "ollama":
        url = os.getenv("OLLAMA_BASE_URL", OLLAMA_DEFAULT_URL)
        return f"ollama  model={model}  url={url}"
    return f"{provider}  model={model}"
