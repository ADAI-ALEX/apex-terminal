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
        self._enabled = self.s.has_anthropic_key and _anthropic_available()
        if not self._enabled:
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
            text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
            return _extract_json(text)
        except Exception as exc:  # never let an AI error reach the trading loop
            logger.error("Claude call failed ({}): {}", type(exc).__name__, exc)
            return None


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
