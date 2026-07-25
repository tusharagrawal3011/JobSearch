"""Provider-agnostic LLM client with an ordered fallback chain.

Behavior (per the config.LLM_CHAIN order, e.g. 'ollama,gemini'):
  * For each provider: try up to LLM_MAX_RETRIES times with exponential backoff + jitter.
  * If all retries for a provider fail (server down, timeout, rate limit, etc.), fall
    through to the NEXT provider in the chain.
  * If every provider fails, raise AllProvidersFailed with a per-provider breakdown.

Agents call by TIER ('fast' | 'smart') via `complete`, `complete_json`,
`complete_with_web_search`. They never name a provider or model.
"""
from __future__ import annotations

import json
import random
import sys
import time
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from backend import config
from backend.llm import providers


class AllProvidersFailed(RuntimeError):
    pass


def _log(msg: str) -> None:
    if config.LLM_VERBOSE:
        print(f"[llm] {msg}", file=sys.stderr)


def _messages(prompt: str, system: str):
    return ([SystemMessage(content=system)] if system else []) + [HumanMessage(content=prompt)]


def _text(resp: Any) -> str:
    """Flatten a LangChain AIMessage's content (str or list of blocks) to text."""
    content = getattr(resp, "content", resp)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, str):
                out.append(block)
            elif isinstance(block, dict):
                out.append(block.get("text", ""))
        return "".join(out)
    return str(content)


def _chain(search: bool) -> list[str]:
    chain = [p for p in config.LLM_CHAIN if (not search or p in providers.SEARCH_CAPABLE)]
    return chain


def _backoff(attempt: int) -> float:
    base = min(config.LLM_BACKOFF_MAX, config.LLM_BACKOFF_BASE * (2 ** attempt))
    return base + random.uniform(0, base * 0.25)  # full-ish jitter


def _run(tier: str, temperature: float, max_tokens: int, json_mode: bool,
         invoke: Callable[[Any, str], Any], search: bool = False,
         json_schema: dict | None = None) -> Any:
    """Core fallback loop. `invoke(model, provider) -> result` (text or parsed JSON).
    Any exception from `invoke` (network error, bad JSON, failed validation) counts as
    a failure: retried with backoff, then failed over to the next provider."""
    chain = _chain(search)
    if not chain:
        raise AllProvidersFailed(
            "No suitable providers in LLM_CHAIN"
            + (" (web search needs a search-capable provider: "
               + ", ".join(sorted(providers.SEARCH_CAPABLE)) + ")" if search else ""))

    errors: list[str] = []
    for provider in chain:
        try:
            model = providers.build_chat_model(provider, tier, temperature, max_tokens,
                                               json_mode, json_schema)
        except providers.ProviderUnavailable as e:
            _log(f"skip {provider}: {e}")
            errors.append(f"{provider}: unavailable ({e})")
            continue

        last: Exception | None = None
        for attempt in range(config.LLM_MAX_RETRIES):
            try:
                return invoke(model, provider)
            except Exception as e:  # noqa: BLE001 — retry/fallback on any invoke failure
                last = e
                if attempt < config.LLM_MAX_RETRIES - 1:
                    wait = _backoff(attempt)
                    _log(f"{provider} attempt {attempt + 1}/{config.LLM_MAX_RETRIES} "
                         f"failed ({type(e).__name__}); retrying in {wait:.1f}s")
                    time.sleep(wait)
        _log(f"{provider} exhausted {config.LLM_MAX_RETRIES} retries "
             f"({type(last).__name__}); falling through")
        errors.append(f"{provider}: failed after {config.LLM_MAX_RETRIES} retries "
                      f"({type(last).__name__}: {str(last)[:120]})")

    raise AllProvidersFailed("All LLM providers failed → " + " | ".join(errors))


# ---------------- Public API ----------------

def complete(prompt: str, system: str = "", tier: str = "fast",
             max_tokens: int = 2048, temperature: float = 0.2) -> str:
    messages = _messages(prompt, system)
    return _run(tier, temperature, max_tokens, False,
                lambda model, provider: _text(model.invoke(messages)))


def complete_json(prompt: str, system: str = "", tier: str = "fast",
                  max_tokens: int = 2048, temperature: float = 0.1,
                  coerce: "Callable[[Any], Any] | None" = None,
                  json_schema: dict | None = None) -> Any:
    """JSON completion with in-loop parse + optional coercion, and optional structured
    output.

    * `json_schema` — for local providers (Ollama), constrains decoding to the exact
      shape so smaller models can't collapse an array into a single object.
    * `coerce(parsed) -> cleaned` — runs INSIDE the retry/fallback loop; it may normalize
      the result (e.g. unwrap `{"jobs": [...]}` to a bare list) and MUST raise on an
      unusable shape. A raise triggers retry, then failover to the next provider — so a
      weak model's malformed output is never silently accepted.
    """
    system = (system + "\n\nRespond with ONLY valid JSON. No prose, no code fences.").strip()
    messages = _messages(prompt, system)

    def invoke(model, provider):
        parsed = _parse_json(_text(model.invoke(messages)))
        return coerce(parsed) if coerce is not None else parsed

    return _run(tier, temperature, max_tokens, True, invoke, json_schema=json_schema)


def complete_with_web_search(prompt: str, system: str = "", tier: str = "fast",
                             max_tokens: int = 2048, max_searches: int = 4) -> str:
    """Completion with web-search grounding (public web only). Only search-capable
    providers in the chain are used (Ollama has no web search, so it's skipped here)."""
    messages = _messages(prompt, system)

    def invoke(model, provider):
        if provider == "anthropic":
            bound = model.bind_tools([{"type": "web_search_20250305",
                                       "name": "web_search", "max_uses": max_searches}])
            return _text(bound.invoke(messages))
        # gemini: native Google Search grounding
        return _text(model.invoke(messages, tools=[{"google_search": {}}]))

    return _run(tier, 0.2, max_tokens, False, invoke, search=True)


def _parse_json(raw: str) -> Any:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip("`").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = min((i for i in (raw.find("{"), raw.find("[")) if i != -1), default=-1)
        end = max(raw.rfind("}"), raw.rfind("]"))
        if start != -1 and end != -1:
            return json.loads(raw[start:end + 1])
        raise
