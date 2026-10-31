# Manual Alpaca options backtest

## Browser setup

In repository Settings > Secrets and variables > Actions, add ALPACA_API_KEY and ALPACA_SECRET_KEY using paper credentials. Do not send keys in chat or workflow inputs. Codespaces secrets are separate.

Open Actions > Options backtest ($2,000) > Run workflow. Select main, enter one ticker, start/end dates and strategy. Dates must be completed historical dates since February 2024, at most 180 calendar days. Choose a short interval for the first authenticated smoke test. This commit does not execute the workflow or configure secrets.

The job fetches stock and option data from Alpaca and simulates a SEPARATE $2,000 portfolio. It does not read your brokerage cash as starting equity and never submits orders. No scheduler is installed. Provider entitlements and GitHub Actions usage limits still apply.

## Outputs

Every closed trade and the final outcome appear in the GitHub run summary. Download the results artifact for trades.csv, equity.csv, skipped_signals.csv, summary.json and report.md; retention is seven days. Trade rows include premiums, quantities, costs, fees, P&L, percentage return, WIN/LOSS/FLAT, exit reason and equity before/after. Final metrics include starting/final equity, dollar and percentage change, wins/losses, win rate, average/best/worst trade, fees, drawdown and profit factor. Undefined ratios show N/A. Zero trades is a valid outcome, not a fabricated profit. Failed data/accounting checks abort without valid final performance.

## Rules and assumptions

Long calls only, one position at a time; no puts/spreads or trained AI in this workflow. Signals reuse existing fixed strategy functions. Indicators warm up before the requested interval. Prior completed stock/option bars select contracts; estimated entry is the next session's option open plus configurable adverse slippage (default 2%). Exit estimates subtract that slippage. Fees are $0.65 per contract per side. These are DAILY-TRADE-BAR ESTIMATES, not historical bid/ask-verified executable fills.

Default maximum allocation is 25% of available equity ($500 initially), not stop-based risk. Whole contracts only; unaffordable signals are skipped. Searches active and inactive metadata for standard-root 100-share calls, 30-60 calendar DTE and strikes within 10% of prior underlying close. Requires prior-day traded bars, selects earliest expiry then nearest affordable strike. Missing entry-day bars or unaffordable gaps are logged without hindsight substitution.

A +15%/-25% estimated net outcome at a daily close schedules the next-session-open exit; these are NOT intraday targets or guaranteed stops. Underlying-floor invalidation also schedules exit. Maximum hold is 10 underlying sessions. Exits occur when seven calendar days remain before expiry, or at the final test-session close. End-boundary liquidation is imposed by the test. Missing positive-volume held-contract bars abort the run.

Stock feed defaults to IEX, not consolidated-market volume; SIP requires appropriate access. Option bars use provider-default historical entitlement; no claim is made that free/derived data equals OPRA. No latest quotes or simulated option prices are substituted for historical bars. Raw underlying prices avoid mixing adjusted shares with raw option strikes, but corporate actions are NOT fully handled: avoid split/adjusted-contract intervals. Dividends, deliverables verification, historical contract-listing completeness and exercise are not modeled. Today's active/inactive contract inventory is not a guaranteed complete point-in-time universe.

The workflow is fixed-policy research, not purged walk-forward validation. Manual repeated strategy selection can overfit. Six new local execution tests use mocked signals/data to check accounting and failure behavior, not real profitability. Authenticated Alpaca integration has NOT been verified here; account access and expired-contract coverage must pass the first real run. No credentials, subscription or order permissions are configured by this commit.

API references: https://docs.alpaca.markets/us/reference/optionbars ; https://docs.alpaca.markets/us/reference/get-options-contracts ; https://docs.alpaca.markets/us/docs/historical-option-data
