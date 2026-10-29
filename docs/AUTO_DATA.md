# Automatic historical-data collection

## Setup

This adapter uses Alpha Vantage's TIME_SERIES_DAILY_ADJUSTED and HISTORICAL_OPTIONS endpoints. Historical options and full daily history require the relevant premium entitlement. The app does not buy a subscription, create an account, or include a key. Provider documentation: https://www.alphavantage.co/documentation/

Configure ALPHAVANTAGE_API_KEY in the local process or hosting environment. Do not paste keys into chat, code, commits, or shared logs. Existing .gitignore excludes .env and data/. No extra Python dependency is needed beyond the existing requirements. A .env file is NOT automatically loaded.

Run `streamlit run app.py`, then open Auto Data in the sidebar. Choose tickers and completed-session dates, collect, and run a stock/call/call-spread backtest on that same page. No upload is required. The original upload page remains available. This new page uses fixed engine defaults for holding, capital and sizing; advanced controls and holdout search remain on the original page using optional exports.

## CLI alternative

With the environment variable already set:

```sh
python collector.py --symbols SPY --start 2025-01-01 --end 2025-12-31
```

The CLI writes data/bars.csv, data/options.csv and data/manifest.json. Add --stocks-only to skip chains. Default cap is 500 daily chain lookups; --max-chains changes it explicitly. The CLI does not run a backtest automatically.

## Requests and caching

Collection is on demand, not an always-running scheduler. One chain request is made per ticker per returned trading date, subject to cache. Default uncached request spacing is at least 1.1 seconds; adjust AlphaVantage(pause=...) in code to respect your plan. Quota/premium errors stop collection rather than produce partial backtest inputs. Network errors are retried three times. Provider denial messages are redacted and never cached. Daily stock responses expire after 24 hours; dated historical chains persist until local cache is deleted. Delete cache when provider corrections need refreshing. No API key enters cache filenames.

Cache files remain on your computer/server; they are not uploaded to GitHub. Chain collection resumes from cached successful dates after an interruption. No billing, plan upgrade, background job, or credential configuration is performed by this commit.

## Research limitations

Only 1-5 letter US ticker roots and standard-root calls are supported. The adapter assumes standard 100-share deliverables; it does not verify a security master. Adjusted roots, zero bids and invalid bid/ask records are excluded and counted. This is a restrictive research universe and not proof of unbiased performance. Missing held-contract quotes still stop the engine; a losing contract is not silently given a stale mark. Requested intervals containing stock splits are refused. Dividends and early assignment remain unmodeled.

Provider daily chains are not independently verified to be synchronized executable intraday snapshots. Do not use this adapter for intraday target/stop tests or live trading. Data normalization and error handling have five mocked tests, but real authenticated API retrieval and end-to-end provider compatibility have NOT been verified. A valid, entitled account and an integration smoke test are still required. No options data or performance result is fabricated.
