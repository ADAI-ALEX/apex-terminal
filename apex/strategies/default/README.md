# Default strategies

Pre-built algorithms shipped with Apex. This folder is intentionally **empty for
now** — a complex quantitative algorithm (from a trading tutorial) will be dropped
in here later.

Any `.py` file placed here is **automatically discovered** on startup/reset by
`apex/strategies/store.py` and appears as a selectable option in the Backtesting
tab's strategy dropdown. Default strategies are read-only in the UI (they can be
selected and run, but not edited or deleted from the web editor).

## Strategy contract

A strategy file is a Python snippet evaluated **once per bar** against the local
historical data array (see `apex/backtest/custom_runner.py`). Set `signal` to one
of `"BUY"`, `"SELL"`, `"FLAT"` or `"HOLD"`.

Optional metadata header (used for the dropdown label):

```python
# name: Golden Cross Trend
# description: Long when the 50-day EMA crosses above the 200-day EMA
```

### Available variables & functions

| Name | Meaning |
| --- | --- |
| `open` `high` `low` `close` `volume` `price` | current bar OHLCV (`price` = `close`) |
| `fear_and_greed` | Fear & Greed index, 0–100 |
| `vix` | CBOE Volatility Index |
| `sentiment` | short-horizon sentiment, −100…+100 |
| `sma(p)` `ema(p)` `rsi(p)` | moving averages / RSI |
| `macd()` | `(line, signal, hist)` namedtuple |
| `atr(p)` `adx(p)` | volatility / trend strength |
| `bollinger(p, s)` | `(upper, mid, lower)` namedtuple |
| `highest(p)` `lowest(p)` | rolling high / low |
| `crossover(a, b)` `crossunder(a, b)` | cross detection (indicator outputs carry the previous bar) |
| `i` `n` | bar index / total bars |

Imports, dunder access and filesystem/eval calls are blocked. Any error inside the
snippet is treated as `HOLD`, so a backtest never crashes on a typo.
