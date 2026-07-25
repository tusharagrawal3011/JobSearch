"""Pluggable LLM provider registry.

Each provider is a builder that returns a LangChain chat model for a given tier
('fast' | 'smart'), temperature, and token budget. To add a NEW provider:

    from backend.llm.providers import register_provider

    @register_provider("myprovider", search_capable=False)
    def _build(tier, temperature, max_tokens, json_mode):
        from langchain_x import ChatX
        return ChatX(model=..., temperature=temperature, ...)

...then add its name to LLM_CHAIN in .env. That's the whole extension surface.

Builders should raise ProviderUnavailable when the provider is not configured (missing
key, etc.) so the client cleanly skips it and moves to the next in the chain.
"""
from __future__ import annotations

from typing import Callable

from backend import config

Builder = Callable[[str, float, int, bool], object]

_BUILDERS: dict[str, Builder] = {}
SEARCH_CAPABLE: set[str] = set()


class ProviderUnavailable(RuntimeError):
    """Raised when a provider can't be built (not installed / not configured)."""


def register_provider(name: str, search_capable: bool = False):
    def deco(fn: Builder) -> Builder:
        _BUILDERS[name] = fn
        if search_capable:
            SEARCH_CAPABLE.add(name)
        return fn
    return deco


def build_chat_model(provider: str, tier: str, temperature: float, max_tokens: int,
                     json_mode: bool = False, json_schema: dict | None = None):
    builder = _BUILDERS.get(provider)
    if builder is None:
        raise ProviderUnavailable(f"unknown provider '{provider}' (not registered)")
    try:
        return builder(tier, temperature, max_tokens, json_mode, json_schema)
    except ProviderUnavailable:
        raise
    except ImportError as e:
        raise ProviderUnavailable(f"{provider}: package not installed ({e})") from e


def _pick(fast: str, smart: str, tier: str) -> str:
    return fast if tier == "fast" else smart


# ---------------- Ollama (local) ----------------

@register_provider("ollama")
def _build_ollama(tier, temperature, max_tokens, json_mode, json_schema=None):
    from langchain_ollama import ChatOllama

    kwargs = dict(
        model=_pick(config.OLLAMA_MODEL_FAST, config.OLLAMA_MODEL_SMART, tier),
        base_url=config.OLLAMA_BASE_URL,
        temperature=temperature,
        num_ctx=config.OLLAMA_NUM_CTX,
        num_predict=max(max_tokens, 512),
    )
    # A JSON schema (Ollama structured outputs) constrains the model to the exact shape —
    # critical for smaller local models that otherwise collapse arrays to a single object.
    if json_schema is not None:
        kwargs["format"] = json_schema
    elif json_mode:
        kwargs["format"] = "json"  # looser JSON-constrained decoding
    return ChatOllama(**kwargs)


# ---------------- Gemini ----------------

@register_provider("gemini", search_capable=True)
def _build_gemini(tier, temperature, max_tokens, json_mode, json_schema=None):
    from langchain_google_genai import ChatGoogleGenerativeAI

    if not config.GEMINI_API_KEY:
        raise ProviderUnavailable("gemini: GEMINI_API_KEY not set")
    kwargs = dict(
        model=_pick(config.GEMINI_MODEL_FAST, config.GEMINI_MODEL_SMART, tier),
        google_api_key=config.GEMINI_API_KEY,
        temperature=temperature,
        max_output_tokens=max(max_tokens, 8192),
    )
    # Disable "thinking" on the fast tier: for high-volume JSON extraction it only burns
    # output tokens (billed) and adds latency. Keep it on the smart tier where reasoning
    # helps tailoring/outreach quality. Guarded so an unsupported param can't break builds.
    if tier == "fast" and config.GEMINI_DISABLE_THINKING_FAST:
        try:
            return ChatGoogleGenerativeAI(thinking_budget=0, **kwargs)
        except Exception:  # noqa: BLE001 — param not supported in this SDK version
            pass
    return ChatGoogleGenerativeAI(**kwargs)


# ---------------- Anthropic ----------------

@register_provider("anthropic", search_capable=True)
def _build_anthropic(tier, temperature, max_tokens, json_mode, json_schema=None):
    from langchain_anthropic import ChatAnthropic

    if not config.ANTHROPIC_API_KEY:
        raise ProviderUnavailable("anthropic: ANTHROPIC_API_KEY not set")
    return ChatAnthropic(
        model=_pick(config.ANTHROPIC_MODEL_FAST, config.ANTHROPIC_MODEL_SMART, tier),
        api_key=config.ANTHROPIC_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# ---------------- OpenAI / OpenAI-compatible ----------------

@register_provider("openai")
def _build_openai(tier, temperature, max_tokens, json_mode, json_schema=None):
    from langchain_openai import ChatOpenAI

    if not config.OPENAI_API_KEY:
        raise ProviderUnavailable("openai: OPENAI_API_KEY not set")
    kwargs = dict(
        model=_pick(config.OPENAI_MODEL_FAST, config.OPENAI_MODEL_SMART, tier),
        api_key=config.OPENAI_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if config.OPENAI_BASE_URL:
        kwargs["base_url"] = config.OPENAI_BASE_URL
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatOpenAI(**kwargs)


def available() -> list[str]:
    """Names of all registered providers (not necessarily configured)."""
    return sorted(_BUILDERS)
