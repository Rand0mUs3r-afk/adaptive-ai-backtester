# Adaptive AI Backtester

Runnable research MVP for stock setups, historical call/debit-spread evaluation, strategy blending, and rule-based situation-dependent routing. Not a trained AI trader, not production software, and not evidence of profitability.

## Run

Python 3.11+ recommended. From the repository root:

```sh
python -m venv .venv
# Activate your virtual environment, then:
pip install -r requirements.txt
python -m unittest -v
streamlit run app.py
```

Upload your own historical CSVs. No paid data account is connected, no live orders are submitted, and no real-market performance result is bundled. The tests use clearly labeled synthetic fixtures only to check software behavior.

## Working features

- Three signals: 20-session resistance breakout with above-average volume, Bollinger/stochastic trend momentum, and lower-band recovery.
- Blend: at least two signals must agree. Adaptive: breakout OR momentum in a defined rising-average state; otherwise lower-band recovery. This is a fixed heuristic, not learned regime discovery.
- Stock, long call, and same-expiration bull call debit spread simulations. Instrument is selected per experiment; automatic instrument routing is future work.
- Shared cash, whole-unit sizing, maximum positions, per-unit/per-leg fees, executable bid/ask option marks, trade ledger and equity curve.
- Signals from completed daily bars execute at the NEXT session close or fixed options snapshot. Close-based invalidation and maximum holding time; final-session liquidation. No intraday stops or profit targets.
- Development search across five strategy policies, followed by a selected-policy holdout run. Registry download records trial results, configuration, and input/engine hashes.
- CSV exports, six engine tests, and GitHub Actions.

## Data contract

Bars: `date,symbol,open,high,low,close,volume`. One regular-session row per symbol/date, ISO dates, consistent split treatment. At least 52 sessions per run, substantially more for useful research. No universe is downloaded: uploaded membership is your responsibility and can introduce survivorship bias.

Options: `date,symbol,contract,expiry,strike,right,bid,ask,multiplier`. One row per contract/date at the SAME documented daily snapshot; `right=C` for calls. Input preparation must align all legs to that snapshot and eliminate stale records. Use actual historical option chains, not prices inferred from stock returns. Contracts must have stable identity, multiplier, strike, and deliverables throughout a run. Adjusted contracts and corporate-action windows are unsupported.

The earliest expiry at least the configured calendar DTE away is selected. The long strike is nearest the previous session close; the spread sells the next higher available strike of the same expiry/multiplier. These are research conventions, not optimized recommendations. Quotes are required on every date a contract is held; missing or zero-bid quotes cause a fail-closed error, not a stale fill. Runs may therefore require additional data cleaning and cannot measure worthless options robustly yet.

Entry uses ask for long legs and bid for short legs; liquidation reverses those sides. All legs are assumed to execute simultaneously with full fills. Fees default to 0.65 per unit per leg per side, including shares in stock mode; configure through `Config` for your actual broker. Stock spread/slippage, option price improvement, market impact, partial fills and assignment are not modeled. The simulator must not be used for live risk decisions.

## Evaluation limits

The dashboard split is 65% development and 35% evaluation by unique dates, with independent warmup and flat starting portfolios. Every development policy is recorded. It chooses by development net profit, not holdout results. Repeatedly looking at the holdout and changing parameters contaminates it. This is NOT nested/purged walk-forward validation or multiple-testing correction. Win rate is historical frequency, not a calibrated forecast or guarantee. Small samples, fees, selection bias, shared market shocks and missing corporate actions can materially affect results.

Allocation is a fraction of equity spent at entry, NOT maximum portfolio loss or stop-based risk sizing. Simultaneous signals are processed alphabetically; no optimal allocation is claimed. Router changes affect new entries; open positions keep the same exit policy. The breakout is rolling resistance, NOT the exact custom Darvas algorithm discussed in the project.

See `docs/BLUEPRINT.md` for architecture, safeguards and the remaining build plan. No licensed market data or secrets should be committed.
