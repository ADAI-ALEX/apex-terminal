"""Thin Anthropic API wrapper used by all three agents.

Design goals:
* **Fail safe.** Any error (missing key, timeout, malformed JSON) returns ``None``
  so callers fall back to the conservative default (NO_TRADE / no change).
* **Prompt caching.** The long, static system prompt is sent with a
  ``cache_control`` breakpoint so repeated Tier-2 calls are cheap.
* **Structured output.** Helpers extract the first JSON object from the reply.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from apex.config import get_settings


class ClaudeClient:
    def __init__(self) -> None:
        self.s = get_settings()
        self._client = None
        self._enabled = self.s.ai_enabled and self.s.has_anthropic_key and _anthropic_available()
        if not self.s.ai_enabled:
            logger.info("AI brain OFF (ai_enabled=false) — agents return safe defaults, zero Claude cost.")
        elif not self._enabled:
            logger.warning("Claude disabled (no ANTHROPIC_API_KEY or sdk) — agents return safe defaults.")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _ensure(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.s.anthropic_api_key)
        return self._client

    def ask_json(
        self, system: str, user: str, max_tokens: int = 700, temperature: float = 0.2
    ) -> dict[str, Any] | None:
        """Send one structured request; return the parsed JSON object, or None on failure."""
        if not self._enabled:
            return None
        try:
            client = self._ensure()
            resp = client.messages.create(
                model=self.s.claude_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=[{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user}],
            )
            _record_usage(resp, self.s.claude_model)
            text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
            return _extract_json(text)
        except Exception as exc:  # never let an AI error reach the trading loop
            logger.error("Claude call failed ({}): {}", type(exc).__name__, exc)
            return None


# Approximate Anthropic list prices, USD per 1M tokens (input, output). Matched by
# substring so model-id suffixes don't matter. Used only for a cost *estimate*.
_PRICING: dict[str, tuple[float, float]] = {
    "opus": (15.0, 75.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
}


def _price_for(model: str) -> tuple[float, float]:
    for key, price in _PRICING.items():
        if key in (model or "").lower():
            return price
    return (3.0, 15.0)  # default to Sonnet-class pricing


def _record_usage(resp, model: str) -> None:  # type: ignore[no-untyped-def]
    """Accumulate token usage + estimated cost into shared state (best-effort)."""
    try:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        in_price, out_price = _price_for(model)
        cost = (in_tok / 1_000_000) * in_price + (out_tok / 1_000_000) * out_price
        from apex.core.state import STATE

        STATE.record_claude_usage(in_tok, out_tok, cost)
    except Exception:  # usage tracking must never break the loop
        pass


def _anthropic_available() -> bool:
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first balanced JSON object out of a model reply."""
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None
