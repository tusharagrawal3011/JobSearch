"""Backward-compatibility shim. The real implementation now lives in client.py and is
provider-agnostic (Gemini or Anthropic). Prefer `from backend.llm import client`.
"""
from backend.llm.client import (  # noqa: F401
    complete,
    complete_json,
    complete_with_web_search,
    _parse_json,
)
