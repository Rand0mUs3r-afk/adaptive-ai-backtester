# Guarded limited-data research

No backtester handles every scenario or guarantees profit. This workflow is
research-only, submits no orders, and reports incomplete provider coverage.
Original strict and legacy simulator source files remain unchanged.

## Deliberate policy changes

The Limited-data options research workflow now runs hardened_research.py.
It selects from a fixed, bounded universe: the signal-day stock close rounded
to $5, plus the adjacent $5 strikes. It never uses execution-day stock prices
to choose a different contract. Only the already-chosen strike is queried on
entry and during holding. It does not paginate around provider entitlements.
Independent $2,000 accounts per ticker/strategy remain in effect.

Guarded defaults (engineering limits, not optimized or validated trading advice):
- Reject zero bids, invalid/crossed/non-finite entry quotes.
- Reject (ask-bid)/ask above 0.20 both before selection and at execution.
- Skip an entry if its ask rose more than 0.25 from the selection snapshot.
- Preserve fee-inclusive allocation, raw ask entries, and raw bid exits.
- Never apply entry-spread guards to prevent liquidation of an existing holding.

Baseline mode disables only the spread and ask-jump guards, not validation.
Its name does not mean byte-identical behavior to the older accumulated-strike
simulator. Compare guarded/baseline on identical dates with the new fixed universe.
No parameter or best strategy is selected from realized profits automatically.

## Failure and boundary policies

Reject invalid dates/allocations/configuration, wrong stock symbols, inadequate
warmup and fewer than two test sessions. The existing feature calculator checks
OHLC values, duplicates and finite numbers. It cannot certify an exchange calendar
or detect every missing session; this remains a limitation.

Record every evaluated signal and stage-by-stage candidate rejection counts.
Missing selected/held contracts, duplicate identities, date/strike mismatch,
transport/schema errors, or failed cash/P&L reconciliation invalidate that run.
No stale-price carry-forward, midpoint substitution, or fabricated fills.
Zero-bid holdings may liquidate at zero less fees; zero-bid entries are rejected.
A final-session close is explicitly end_of_test, not a normal strategy exit.
Exit conditions are EOD signals with later execution and do not cap loss size.

The provider client retains bounded retries/backoff and per-date/strike caching.
HTTP 401/403, 404 and 429 are classified in safe request audits. A run stops at
400 distinct uncached requests, rather than issuing unbounded chain scans.
Other symbol/strategy runs may continue, but failed runs receive no final metrics.
GitHub limits wall time and serializes concurrent runs on the same branch.
No unverified API-key authentication scheme is added; public access is still used.

## Evidence and artifacts

Upload only diagnostic_bundle.json. It includes identified trades, skips, fetched
held-contract quote history, per-signal events, request audits, guard settings,
mode, and Git SHA. A no-trade completion is not a provider-coverage certificate.

Twelve offline fixture tests passed for guards, the previously observed wide
spread, zero bids, execution rechecks, ask jumps, missing held quotes, date
mismatches, one-day rejection, fees/reconciliation, prior-date selection,
baseline costs, invalid settings, invalid quote numbers, and request budgeting.
These test software logic, not actual market performance. Full repository tests
run in Actions; no authenticated/live provider run was performed here.

## Known limitations (not solved by this patch)

Partial chains, no verified intraday quote timestamps, no corporate-action or
adjusted-contract modeling, no early-exercise/assignment model, no guaranteed
fills or slippage calibration, no survival-bias correction or walk-forward
validation. The 100-share long-call convention is an assumption, not verified
contract metadata. Unsupported/missing data should fail rather than manufacture
an answer. The short uploaded diagnostic window cannot validate profitability.
