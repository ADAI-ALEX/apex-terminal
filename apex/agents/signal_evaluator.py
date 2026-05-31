"""Signal Evaluator (Tier 2).

Receives a pre-screened :class:`Signal` plus full market context and returns an
:class:`AgentDecision` (ENTER / NO_TRADE + confidence + reasoning). On any Claude
failure the decision defaults to NO_TRADE — the system never enters a trade just
because the AI was unreachable.
"""

from __future__ import annotations

import json

from loguru import logger

from apex.agents.claude_client import ClaudeClient
from apex.models import AgentDecision, IndicatorSnapshot, Position, Signal

_SYSTEM = """You are the Signal Evaluator for a disciplined IG spread-betting system.
A Python strategy has already produced a candidate trade that passed mechanical screening.
Your job is a final qualitative gate: approve only high-quality entries.

You NEVER place orders. You only return a JSON recommendation. Python executes and the
RiskEngine still has final say on sizing. Be conservative: when context is ambiguous,
prefer NO_TRADE. Reject trades that fight the regime, chase extended moves, or sit just
before a major scheduled event.

Respond with ONLY a JSON object, no prose:
{
  "action": "ENTER" | "NO_TRADE",
  "confidence": 0.0-1.0,
  "reasoning": "one concise sentence",
  "adjusted_stop": number | null,
  "adjusted_target": number | null
}
Rules for adjustments: you may TIGHTEN a stop (reduce risk) or REDUCE a target, never widen
risk. Use null to keep the strategy's levels."""


class SignalEvaluator:
    def __init__(self, client: ClaudeClient | None = None) -> None:
        self.client = client or ClaudeClient()

    def evaluate(
        self,
        signal: Signal,
        snapshot: IndicatorSnapshot,
        open_positions: list[Position],
        macro_note: str = "",
    ) -> AgentDecision:
        # Fail-safe default if Claude is disabled/unreachable.
        if not self.client.enabled:
            return AgentDecision(
                action="ENTER" if signal.confidence >= 0.6 else "NO_TRADE",
                confidence=signal.confidence,
                reasoning="Claude disabled — using strategy confidence as gate.",
            )

        user = self._build_prompt(signal, snapshot, open_positions, macro_note)
        data = self.client.ask_json(_SYSTEM, user)
        if data is None:
            logger.warning("Signal Evaluator fell back to NO_TRADE for {}", signal.market_key)
            return AgentDecision(action="NO_TRADE", reasoning="Claude unavailable — safe default.")

        try:
            decision = AgentDecision.model_validate(data)
        except Exception:
            return AgentDecision(action="NO_TRADE", reasoning="Malformed AI response — safe default.")

        # Guardrail: never let an adjustment widen risk beyond the strategy's stop.
        decision = self._sanitise(signal, decision)
        logger.info("Signal Evaluator: {} {} (conf {:.2f}) — {}",
                    decision.action, signal.market_key, decision.confidence, decision.reasoning)
        return decision

    @staticmethod
    def _sanitise(signal: Signal, d: AgentDecision) -> AgentDecision:
        if d.adjusted_stop is not None:
            widened = (signal.direction.value == "BUY" and d.adjusted_stop < signal.stop) or \
                      (signal.direction.value == "SELL" and d.adjusted_stop > signal.stop)
            if widened:
                d.adjusted_stop = None  # ignore risk-widening suggestion
        return d

    @staticmethod
    def _build_prompt(
        signal: Signal, snap: IndicatorSnapshot, positions: list[Position], macro_note: str
    ) -> str:
        payload = {
            "candidate": {
                "market": signal.market_key,
                "strategy": signal.strategy,
                "direction": signal.direction.value,
                "entry": signal.entry,
                "stop": signal.stop,
                "target": signal.target,
                "reward_risk": signal.target_rr,
                "strategy_confidence": signal.confidence,
                "rationale": signal.rationale,
            },
            "indicators": {
                "regime": snap.regime.value if snap.regime else None,
                "price": snap.price,
                "ema9": snap.ema_fast, "ema21": snap.ema_mid, "ema55": snap.ema_slow,
                "rsi": snap.rsi, "macd_hist": snap.macd_hist, "atr": snap.atr, "adx": snap.adx,
                "bb_upper": snap.bb_upper, "bb_lower": snap.bb_lower,
            },
            "open_positions": [
                {"market": p.market_key, "direction": p.direction.value,
                 "unrealised_pnl": round(p.unrealised_pnl, 2)} for p in positions
            ],
            "macro_note": macro_note or "none",
        }
        return "Evaluate this candidate trade.\n\n" + json.dumps(payload, indent=2)
