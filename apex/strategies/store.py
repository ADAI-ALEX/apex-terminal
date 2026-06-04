"""Strategy storage + dynamic scanning for the backtester.

Two on-disk folders hold user-selectable algorithms:

* ``apex/strategies/default/`` — pre-built strategies shipped with the app
  (empty for now; a complex tutorial algo will be dropped in later).
* ``apex/strategies/custom/`` — strategies authored in the web code editor and
  written here by the auto-save flow.

Each file is a ``.py`` snippet evaluated per-bar by
:mod:`apex.backtest.custom_runner` against the local historical data array. An
optional metadata header is read for display:

    # name: Mean-Reversion + Fear/Greed
    # description: Buy capitulation, sell euphoria

On top of the scanned files, a small set of **built-in** strategies (the live
strategy book) is always offered so the dropdown is never empty.

Everything here is path-safe: names are validated to a strict slug so a request
can never read or write outside the two managed folders.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from loguru import logger

_BASE = Path(__file__).resolve().parent
DEFAULT_DIR = _BASE / "default"
CUSTOM_DIR = _BASE / "custom"

#: Strict slug for a strategy name → blocks path traversal and odd filenames.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,48}$")

#: Starter shown when the user clicks "+ Create Custom Strategy".
STARTER_CODE = '''# name: My Strategy
# description: Describe what this algorithm does
#
# Runs once per bar. Set `signal` to "BUY", "SELL", "FLAT" or "HOLD".
#   BUY / SELL -> open a long / short (ATR-sized, with stop + target)
#   FLAT       -> close any open position now
#   HOLD       -> do nothing; let the stop / target manage the trade
# Available: open, high, low, close, volume, price, fear_and_greed, vix, sentiment,
#            sma(p), ema(p), rsi(p), macd(), atr(p), bollinger(p, s), adx(p),
#            crossover(a, b), crossunder(a, b), highest(p), lowest(p)

upper, mid, lower = bollinger(20, 2)

if rsi(14) < 30 and close < lower and fear_and_greed < 30:
    signal = "BUY"          # oversold capitulation
elif rsi(14) > 70 and close > upper and fear_and_greed > 75:
    signal = "SELL"         # overbought euphoria
else:
    signal = "HOLD"
'''


@dataclass
class StrategyMeta:
    name: str             # slug / id (also the filename stem for file strategies)
    label: str            # human display name
    description: str
    kind: str             # "builtin" | "default" | "custom"
    editable: bool        # can the UI edit/delete it?
    code: str = ""        # source (empty for built-ins)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Built-in strategies (the live strategy book) ───────────────────────────
BUILTINS: list[StrategyMeta] = [
    StrategyMeta(
        name="book", label="Strategy Book (built-in)",
        description="The live multi-strategy book: EMA-trend, RSI-reversion and "
                    "ATR-breakout, gated by the regime detector. Same logic the engine trades.",
        kind="builtin", editable=False,
    ),
]
_BUILTIN_NAMES = {b.name for b in BUILTINS}


def is_valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name or ""))


def _safe_path(folder: Path, name: str) -> Path:
    if not is_valid_name(name):
        raise ValueError(f"Invalid strategy name: {name!r}")
    path = (folder / f"{name}.py").resolve()
    if path.parent != folder.resolve():  # belt-and-braces against traversal
        raise ValueError(f"Refusing path outside {folder}: {name!r}")
    return path


def _parse_meta(name: str, code: str, kind: str) -> StrategyMeta:
    label, description = name, ""
    for line in code.splitlines()[:8]:
        s = line.strip()
        if s.lower().startswith("# name:"):
            label = s.split(":", 1)[1].strip() or name
        elif s.lower().startswith("# description:"):
            description = s.split(":", 1)[1].strip()
    return StrategyMeta(name=name, label=label, description=description,
                        kind=kind, editable=(kind == "custom"), code=code)


def _scan(folder: Path, kind: str) -> list[StrategyMeta]:
    out: list[StrategyMeta] = []
    if not folder.exists():
        return out
    for path in sorted(folder.glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            code = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read strategy {}: {}", path, exc)
            continue
        out.append(_parse_meta(path.stem, code, kind))
    return out


def ensure_dirs() -> None:
    DEFAULT_DIR.mkdir(parents=True, exist_ok=True)
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)


def list_strategies() -> list[StrategyMeta]:
    """Built-ins + every file under ``default/`` and ``custom/`` (scanned fresh)."""
    ensure_dirs()
    return [*BUILTINS, *_scan(DEFAULT_DIR, "default"), *_scan(CUSTOM_DIR, "custom")]


def list_dicts() -> list[dict]:
    return [m.to_dict() for m in list_strategies()]


def get(name: str) -> StrategyMeta | None:
    """Resolve a strategy by name across built-ins, default and custom folders."""
    if name in _BUILTIN_NAMES:
        return next(b for b in BUILTINS if b.name == name)
    if not is_valid_name(name):
        return None
    for folder, kind in ((CUSTOM_DIR, "custom"), (DEFAULT_DIR, "default")):
        path = folder / f"{name}.py"
        if path.exists():
            return _parse_meta(name, path.read_text(encoding="utf-8"), kind)
    return None


def save(name: str, code: str) -> StrategyMeta:
    """Create/overwrite a **custom** strategy file. Returns its fresh metadata."""
    ensure_dirs()
    path = _safe_path(CUSTOM_DIR, name)
    path.write_text(code, encoding="utf-8")
    logger.info("Saved custom strategy '{}' ({} chars).", name, len(code))
    return _parse_meta(name, code, "custom")


def delete(name: str) -> bool:
    """Delete a custom strategy. Built-ins and default strategies are protected."""
    path = _safe_path(CUSTOM_DIR, name)
    if path.exists():
        path.unlink()
        logger.info("Deleted custom strategy '{}'.", name)
        return True
    return False
