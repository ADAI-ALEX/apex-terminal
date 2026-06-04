# Default strategies

This folder is currently **empty** — strategies now live in `../custom/` so they're
viewable and editable from the app (the "Riptide - Trend Pullback" and an editable
port of the built-in "Strategy Book" ship there).

Any `.py` file placed here is still **automatically discovered** on startup/reset by
`apex/strategies/store.py` and appears in the Backtesting strategy dropdown as a
read-only default. See `../custom/` and `../store.py` for the strategy contract and
the full list of variables/functions available to a snippet.
