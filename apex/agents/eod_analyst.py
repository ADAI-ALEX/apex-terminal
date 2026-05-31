"""EOD Analyst (post-market ~18:00).

Reads the day's trade journal and returns a structured debrief: best/worst
decisions, suggested parameter flags, and a 0-100 day score. Stored for the
dashboard's Performance panel. Degrades gracefully when Claude is unavailable.
"""

from __future__ import annotations

import json

from loguru import logger
from pydantic import BaseModel, Field

from apex.agents.claude_client import ClaudeClient

_SYSTEM = """You are the End-of-Day Analyst for an IG spread-betting system.
Given today's closed trades and summary stats, produce a concise, actionable debrief.
Be specific and honest; flag parameters that look mis-tuned. You never place trades.

Respond with ONLY this JSON:
{
  "day_score": 0-100,
  "summary": "2-3 sentences",
  "best_decision": "...",
  "worst_decision": "...",
  "parameter_flags": ["..."],
  "tomorrow_focus": "..."
}"""


class EodReport(BaseModel):
    day_score: int = 50
    summary: str = ""
    best_decision: str = ""
    worst_decision: str = ""
    parameter_flags: list[str] = Field(default_factory=list)
    tomorrow_focus: str = ""


class EodAnalyst:
    def __init__(self, client: ClaudeClient | None = None) -> None:
        self.client = client or ClaudeClient()

    def analyse(self, trades: list[dict], stats: dict) -> EodReport:
        if not self.client.enabled:
            return EodReport(summary="Claude disabled — no AI debrief generated.",
                             day_score=_score_from_stats(stats))
        payload = {"stats": stats, "trades": trades[:50]}
        data = self.client.ask_json(_SYSTEM, "Debrief today's trading.\n\n" + json.dumps(payload, indent=2),
                                    max_tokens=900, temperature=0.4)
        if data is None:
            return EodReport(summary="Claude unavailable — no AI debrief.",
                             day_score=_score_from_stats(stats))
        try:
            report = EodReport.model_validate(data)
        except Exception:
            return EodReport(summary="Malformed AI response.", day_score=_score_from_stats(stats))
        logger.info("EOD report: score {} — {}", report.day_score, report.summary)
        return report


def _score_from_stats(stats: dict) -> int:
    pnl = stats.get("total_pnl", 0.0)
    return max(0, min(100, int(50 + pnl / 20)))
