# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md
"""Getting a JSON object back out of a model that was asked for one.

Models wrap JSON in prose, in ``` fences, or in both, and every agent that asks
for structured output needs the same three recovery steps. Recovery stops at
*structurally* recoverable: nothing here guesses at contents, because a
half-parsed object silently filled in is worse than a typed failure.
"""

from __future__ import annotations

import json
import re
from typing import Any

from genesis.errors import DegradedError

__all__ = ["json_object"]

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def json_object(raw: str, *, who: str = "the model") -> dict[str, Any]:
    """Parse a JSON object, unwrapping a code fence or surrounding prose."""
    text = (raw or "").strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise DegradedError(f"{who} did not return JSON: {text[:120]!r}") from None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise DegradedError(f"{who} returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise DegradedError(f"{who} returned {type(value).__name__}, not an object")
    return value
