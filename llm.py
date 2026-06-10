"""LangChain provider factory for structured-output LLM pipelines.

Supported providers (set via LLM_PROVIDER env var):
  openai     — ChatOpenAI (default). Requires OPENAI_API_KEY.
  anthropic  — ChatAnthropic. Requires ANTHROPIC_API_KEY.
  ollama     — ChatOllama pointed at a local/remote Ollama server. No API key needed.

Model selection (in priority order):
  1. LLM_MODEL env var           — overrides everything
  2. Provider-specific env var   — OPENAI_MODEL / ANTHROPIC_MODEL / OLLAMA_MODEL
  3. Built-in default            — gpt-4o-mini / claude-haiku-4-5-20251001 / qwen3:14b

Ollama-specific env vars:
  OLLAMA_BASE_URL   Base URL of the Ollama server (default: http://localhost:11434)

Usage::

    from script_scaffold.llm import get_llm, check_credentials, apply_options

    # Check credentials before starting a long pipeline
    check_credentials()

    # Get a chat model ready for .with_structured_output() or plain .invoke()
    llm = get_llm(temperature=0.1)
    structured = llm.with_structured_output(MyPydanticSchema)
    result = structured.invoke("Analyse this: ...")

    # Apply --provider / --model CLI flags before any LLM call
    apply_options(provider="anthropic", model="claude-sonnet-4-6")
"""

import os

OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
OLLAMA_DEFAULT_MODEL = "qwen3:14b"
OLLAMA_DEFAULT_URL = "http://localhost:11434"


def get_provider() -> str:
    """Return the active LLM provider name (lowercase)."""
    return os.getenv("LLM_PROVIDER", "openai").lower()


def check_credentials() -> None:
    """Raise SystemExit with a clear message if required credentials are missing."""
    provider = get_provider()
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


def _resolve_model(provider: str) -> str:
    """Return the model name to use, respecting the LLM_MODEL generic override."""
    override = os.getenv("LLM_MODEL")
    if override:
        return override
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_MODEL", ANTHROPIC_DEFAULT_MODEL)
    if provider == "ollama":
        return os.getenv("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)
    return os.getenv("OPENAI_MODEL", OPENAI_DEFAULT_MODEL)


def get_llm(temperature: float = 0.1):
    """Return a configured LangChain chat model for the active provider.

    Raises SystemExit if the required LangChain integration package is not installed.
    """
    provider = get_provider()
    model = _resolve_model(provider)

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
        f"Unknown LLM_PROVIDER {provider!r}. Valid options: openai, anthropic, ollama."
    )


def apply_options(provider: str | None, model: str | None) -> None:
    """Apply --provider and --model CLI overrides to the environment.

    Call this before the first get_llm() call when processing CLI flags.
    """
    if provider:
        os.environ["LLM_PROVIDER"] = provider
    if model:
        os.environ["LLM_MODEL"] = model


def describe() -> str:
    """Return a short human-readable description of the active LLM configuration."""
    provider = get_provider()
    model = _resolve_model(provider)
    if provider == "ollama":
        url = os.getenv("OLLAMA_BASE_URL", OLLAMA_DEFAULT_URL)
        return f"ollama  model={model}  url={url}"
    return f"{provider}  model={model}"
