# One-run strategy laboratory

Run Actions -> Batch strategy laboratory - one run. Default development window:
2026-08-03 through 2026-09-30; separate validation window: 2026-10-01 through
2026-10-30. Change all three dates once if desired; availability is not promised.
One dispatch runs all 21 rules, two allocations (10% and 25%), two periods, and
all manual-watchlist tickers. With eight symbols that is 672 independent runs,
not 672 independent statistical observations or portfolios to sum together.
Upload only experiment_bundle.json from the strategy-lab-final artifact.

## Fixed entry-rule manifest (not parameter optimization)

Original breakout, momentum, reversion, blend, adaptive; SMA20/50 cross;
EMA9/21 cross; MACD12/26 with EMA9 signal cross and SMA50 filter; RSI14 recovery
above 30; RSI2 below 10 with price above SMA200; Donchian55 breakout;
Bollinger20/2 lower re-entry and upper breakout; EMA20+2*ATR20 Keltner breakout;
stochastic14 recovery above 20 with SMA50 filter; positive ROC20 above SMA50;
EMA20 pullback cross above SMA50; volume-confirmed20 breakout at 1.5x prior
20-session mean volume; 2-of-3 trend vote; 2-of-3 reversion vote; SMA50/200
regime-selected vote. Exact formulas are in strategy_suite.signals.

These are explicit bullish stock-entry rules adapted to long calls with the
SAME existing guarded option exits, costs, spread checks, and prior-close strike
grid. They are NOT faithful replications of every named author's complete system
or proven profitable options strategies. No puts, short options, iron condors,
credit spreads, synthetic fills or intraday/VWAP claims are added. RSI uses
causal Wilder-style exponential smoothing. Every rule has a common 200-session
warmup; 400 calendar days of stock history are requested before development.

## Automatic experiment discipline

Dates and formulas are fixed before either phase. Both phases run automatically
with independent $2,000 resets and end-of-phase liquidation. No position crosses
the split. No thresholds are fitted on validation; no auto-deployment. Training
and validation warmup may include earlier observations (never future prices).
This is one chronological split, not walk-forward or statistical validation.
Previously inspected periods cannot be made genuinely unseen by this code.
Trying many rules increases multiple-testing risk; identical signal fingerprints
help identify duplicates, not independent confirmations. Partial provider chains
and fixed strike queries still limit the results.

Rank configurations only on development mean return across all watchlist symbols.
Require every symbol to complete, at least 20 development trades in total, and
positive mean return for a development-selected candidate. This count cutoff is
an engineering reporting heuristic, not a significance test or proof of an edge.
If none qualifies, report no qualifying development winner. Validation never
chooses the winner. Cash return is zero; no-trade rows are not trading successes.
Worst individual-account drawdown is labeled separately from mean account return;
the output is not a shared-portfolio equity curve.

## Runtime, caching, failures

Two symbol jobs at most run concurrently. Reuse normalized historical snapshots
within each symbol across all strategies/allocations/phases so repeated requests
are cached. Cache failures to avoid retry storms, never to fabricate prices.
Provider retry/backoff remains unchanged. Limits: 400 new requests per individual
run, 800 per symbol suite. Every experiment checkpoints atomically; failed runs
have no invented metrics and cause incomplete-suite status. A 120-minute symbol
job timeout remains possible. Final aggregation runs even when experiments fail
and flags missing/incomplete symbols. Cached records are not certified full chains.

Outputs include config, stock-data hash, Git SHA, per-phase metrics, trade ledgers,
equity curves, skip reasons, fingerprints and shared provider audit. Aggregation
rejects mismatched date/strategy manifests. Legacy and paper workflows are
unchanged. No trading permissions, account variables or secrets are modified.
Eight new offline fixture tests passed during preparation for signal causality,
warmup, RSI boundary cases, crossover transitions, chronological splitting,
strict checkpoint writes and cached-failure handling. Full repository tests run
before the matrix; no actual historical suite was run here.

## Background, not profit guarantees

https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies
https://chartschool.stockcharts.com/table-of-contents/overview/john-murphys-charting-made-easy-ebook
https://chartschool.stockcharts.com/table-of-contents/overview/multicollinearity
https://www.quantstart.com/articles/successful-backtesting-of-algorithmic-trading-strategies-part-i/
