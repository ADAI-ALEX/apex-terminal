"""Portfolio Reviewer (Tier 3).

Every 30 minutes it reviews all open positions against funding, correlation and
upcoming events, and returns per-position recommendations plus a portfolio health
score. On Claude failure it returns an empty recommendation set (no action).
"""

from __future__ import annotations

import json

from loguru import logger
from pydantic import BaseModel, Field

from apex.agents.claude_client import ClaudeClient
from apex.models import Position

_SYSTEM = """You are the Portfolio Reviewer for an IG spread-betting system.
Every 30 minutes you assess all OPEN positions holistically. You do not open new trades.
You may recommend: closing a position early, trailing/tightening a stop, or holding.
Consider correlation (e.g. FTSE/DAX move together), overnight funding cost, upcoming
scheduled events, and whether the original thesis still holds.

Respond with ONLY this JSON, no prose:
{
  "health_score": 0-100,
  "summary": "one sentence",
  "recommendations": [
    {"deal_id": "...", "action": "CLOSE"|"TRAIL_STOP"|"HOLD", "new_stop": number|null, "reason": "..."}
  ]
}"""


class Recommendation(BaseModel):
    deal_id: str
    action: str = "HOLD"
    new_stop: float | None = None
    reason: str = ""


class PortfolioReview(BaseModel):
    health_score: int = 100
    summary: str = ""
    recommendations: list[Recommendation] = Field(default_factory=list)


class PortfolioReviewer:
    def __init__(self, client: ClaudeClient | None = None) -> None:
        self.client = client or ClaudeClient()

    def review(self, positions: list[Position], macro_note: str = "") -> PortfolioReview:
        if not positions:
            return PortfolioReview(summary="No open positions.")
        if not self.client.enabled:
            return PortfolioReview(summary="Claude disabled — holding all positions.")

        payload = {
            "positions": [
                {
                    "deal_id": p.deal_id, "market": p.market_key, "direction": p.direction.value,
                    "size": p.size, "entry": p.entry_price, "current": p.current_price,
                    "stop": p.stop_price, "target": p.target_price,
                    "unrealised_pnl": round(p.unrealised_pnl, 2),
                    "unrealised_points": round(p.unrealised_points, 1), "strategy": p.strategy,
                }
                for p in positions
            ],
            "macro_note": macro_note or "none",
        }
        data = self.client.ask_json(_SYSTEM, "Review the portfolio.\n\n" + json.dumps(payload, indent=2),
                                    max_tokens=900)
        if data is None:
            return PortfolioReview(summary="Claude unavailable — holding all positions.")
        try:
            review = PortfolioReview.model_validate(data)
        except Exception:
            return PortfolioReview(summary="Malformed AI response — holding all positions.")
        logger.info("Portfolio review: health {} — {}", review.health_score, review.summary)
        return review
