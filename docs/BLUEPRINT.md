# Adaptive research platform blueprint

## Objective

Support all three research paths: underlying setup discovery, direct historical options evaluation, and combined stock/options portfolio research. Blend signals, select appropriate strategies, and eventually choose instruments based on observable conditions. No achievable winning probability has been established.

## Current implementation

The MVP implements daily stock signals, calls, debit spreads, a fixed adaptive signal router, cash-constrained positions, a dashboard, basic development/holdout evaluation, trial exports, six engine tests, and CI. It does not implement trained AI, automatic switching between instruments, intraday execution, or production risk management.

## Target architecture

1. Data adapters and security master: point-in-time universes, delistings, corporate actions, timestamped stock/option quotes and events.
2. Strategy registry: exact versioned setup, entry, exit, sizing and calendar rules. Preserve every attempted variant, including failures.
3. Feature pipeline: compute only information available at the decision time. Fit transformations on training data only.
4. Deterministic simulator: portfolio accounting, executable synchronized quotes, orders, costs, gaps and contract mechanics.
5. Adaptive controller: rank eligible strategy/instrument candidates using prior observations; abstain when evidence or liquidity is insufficient.
6. Hard risk controller: exposure, capital, concentration and loss limits cannot be overridden by a model score.
7. Research interface: trial history, trade inspection, uncertainty, model/data hashes and exports.

## AI roadmap

Start with fixed-policy baselines. Add simple trained numeric models only after data and labeling are verified. A language-model assistant can suggest structured experiments and explain results; its narrative confidence is not a probability estimate. Forecast the exact event, such as positive net option P&L under fixed exits, not an ambiguous stock-direction label.

Evaluate forecast calibration, Brier score and log loss on unseen chronological observations. Compare the learned selector with every fixed strategy and a fixed allocation baseline. Include no-trade decisions and report how selectivity reduces the number of trades. Do not change the rationale of an existing losing trade to hide a failed setup.

## Validation roadmap

Implement grouped chronological walk-forward splits with outcome-interval purging, nested development selection and an untouched final test. Keep all observations from the same market date on one side of a boundary. Labels become available only after completion. Count all parameter/strategy searches and add selection-bias diagnostics; a holdout alone is insufficient for unrestricted search.

Report net expectancy, average win/loss, trade counts, drawdown, capital exposure, turnover, execution sensitivity, performance by state/time, and uncertainty alongside win rate. Use time-block uncertainty estimates for clustered trades. No arbitrary high-win-rate target qualifies a system for deployment.

## Build order

1. Harden schemas, corporate-action accounting, missing-data policy and broker-specific costs.
2. Add the exact custom Darvas state machine, independent strategies and ablation comparisons.
3. Add point-in-time data adapters, option quote-quality checks and assignment/exercise-aware accounting.
4. Implement robust walk-forward evaluation and calibrated models.
5. Add instrument routing, constrained strategy portfolios and explicit switching costs.
6. Run forward paper-trading with immutable decision logs and manual review before considering live orders.

## Source documentation

- Backtest search and overfitting: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
- Chronological evaluation: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- Probability calibration: https://scikit-learn.org/stable/modules/calibration.html
- Leakage prevention: https://scikit-learn.org/stable/common_pitfalls.html
- Historical quote fields: https://datashop.cboe.com/option-quote-intervals
- Modular execution architecture: https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview

These sources informed the design; listing them does not mean the MVP implements all safeguards described there.
