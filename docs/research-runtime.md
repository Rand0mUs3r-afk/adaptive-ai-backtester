# Runtime scopes and visible progress

The 103 items in a full-universe Actions matrix are batch jobs, not 103 single
strategy tests. Full jobs contain up to five tickers, each with 84 simulations:
21 rules x two allocations x two chronological phases. Two full jobs can cover
840 simulations while the UI shows only two running entries. Actual provider
latency, retries and unique historical snapshot requests still dominate runtime.

The workflow now asks for an explicit scope:
- requested (default): the 26 user-requested tickers plus the existing watchlist,
  deduplicated and options-checked. It intentionally excludes the S&P 500 page.
  One eligible ticker/job gives earlier individual completion and artifact visibility.
- full: all requested candidates plus the linked S&P 500 source, unchanged options
  checks and five-ticker batching. No symbols are silently truncated.

Both retain all 21 rules, allocations, phase dates and guard thresholds. Scope
is stored in universe.json and propagated into the final bundle. The plan prints
eligible count, batch count and actual planned simulation count. Unbuffered logs
show progress after every completed simulation, elapsed seconds and fetched
snapshot count. Existing shared quote caching and provider throttling remain;
this patch does not claim a faster identical full-universe computation.

Requested mode is a smaller experiment, not the full S&P 500 backtest. It is
intended for quick iteration before committing resources to the full universe.
Wall-time improvements are not benchmarked or guaranteed. Increasing workers or
removing rate limits blindly could worsen the free-provider bottleneck, so two
concurrent jobs and request safeguards remain unchanged.

To switch an already-running workflow, cancel that run in Actions first and start
a NEW run on main with scope=requested. A commit does not modify a running job,
and the workflow concurrency policy otherwise queues a new run behind the old one.
Old partial artifacts remain separate; this patch does not resume/cache across
workflow runs. Keep useful partial artifacts before cancelling if available.
Upload the final experiment_bundle.json after the replacement run completes.
