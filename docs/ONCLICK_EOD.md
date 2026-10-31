# OnclickMedia EOD quote integration

Use Actions > Options backtest - EOD quotes ($2,000) > Run workflow, with pricing=auto-eod. The original Alpaca workflow remains unchanged. This capability-based fallback routes option pricing to OnclickMedia because our Alpaca adapter lacks historical bid/ask; it does NOT claim to try a nonexistent Alpaca quote endpoint. Stock signals still require Alpaca credentials in Actions secrets ALPACA_API_KEY and ALPACA_SECRET_KEY.

Only public read-only GET requests are used. The documented options endpoint is https://api.onclickmedia.com/ with ticker, date, type=call, data=greeks and output=json-v1. No OnclickMedia credential is included: public docs currently say no key. If your account requires authentication, this run will fail until a documented authentication method is added; it will not bypass access restrictions. Live API retrieval could not be verified in this environment.

## Quote schema

The user-supplied example is parsed as a JSON array. osi-key TSLA--250117C00300000 becomes TSLA250117C00300000 after removing root padding. Contract identity must agree with ticker, expiration, call type and strike. Wrong snapshot dates, duplicate contracts, unsupported shapes and empty snapshots fail. Invalid/crossed records are rejected and counted. Zero bids remain valid so losing/worthless holdings are not silently discarded. The parser uses ONLY raw bid and ask, never last, mark, realistic_bid, realistic_ask or theoretical Greek-derived prices. Standard 100-share deliverables are assumed, not independently verified.

The supplied TSLA ask of 104.65 implies $10,465 per standard contract before fees. It is unaffordable even with the full $2,000 account and must not force a trade. At the default allocation only $500 is initially available per position. Eight isolated tests cover sample normalization, affordability, raw-field selection, zero bids, duplicates, wrong dates, crossed quotes, missing held quotes and portfolio accounting. Mocked simulations are not performance evidence.

## EOD execution convention

Signals use the previous completed Alpaca stock session. Contract selection uses that session's OnclickMedia snapshot: standard calls, 30-60 calendar DTE, within 10% of underlying price, earliest expiry then nearest affordable strike. Entry is at the next-session EOD ask plus $0.65 per contract. Exit/valuation uses raw EOD bid minus $0.65 per contract. One long-call position at a time; fixed $2,000 starting equity and configurable premium allocation (default 25%). No fractional contracts or leverage.

The same option quote provider is locked throughout a trade. A missing required held-contract or selected-entry quote aborts the run. There is NO silent switch to Alpaca bars or midpoint estimates when quote coverage fails. A prior-close +15%/-25% net liquidation signal schedules exit at the NEXT EOD bid, not the same historical opening price. Holding limit is 10 sessions; exit also occurs within seven calendar days before expiry or at the final test-session bid. Underlying floor invalidation schedules the next EOD exit. These are not intraday stop/limit executions or guaranteed fills. Quote time synchronization, quote sizes, corporate actions and stale-within-day quotes are not independently verified; results remain research estimates.

Choose pricing=alpaca-bars explicitly to run the existing, different daily-open/trade-bar simulation. Its slippage default remains 2% each side. The two modes are NOT interchangeable execution assumptions and their performance must not be pooled without disclosure. Auto EOD is not a per-record blend of providers, and it is not an automatic fallback for missing Alpaca stock data.

## Outputs and limitations

GitHub summary shows every closed trade and final equity change. Artifacts retain trades.csv, equity.csv, skipped_signals.csv, summary.json, report.md and (EOD mode) quote_provenance.json for seven days. Provenance records fetched dates, valid/rejected record counts and response hashes. Trade rows retain provider and entry/exit snapshot dates. No raw option archive is republished. Failed coverage returns an error report rather than invented equity. Successful no-trade runs retain $2,000 equity.

This adds no trained AI, puts, spreads, corporate-action engine, live order submission or walk-forward model validation. Public docs and a user-supplied sample establish the expected schema, not the accuracy/completeness of the provider's history. Date coverage and any account/plan restrictions must be verified with the first real workflow run. No keys or workflow execution are configured by this commit.

Documentation: https://www.onclickmedia.com/Documentation
