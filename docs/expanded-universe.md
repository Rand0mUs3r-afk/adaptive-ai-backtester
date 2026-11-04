# Expanded options-research universe and final summary

The existing Batch strategy laboratory - one run workflow now freezes the union
of the 26 explicitly requested tickers, existing manual watchlist, and Symbol
column from https://stockanalysis.com/list/sp-500-stocks/ at run time. It validates
the source table (450..600 distinct symbol rows), deduplicates, records source
hash and UTC fetch time, and reuses the frozen universe across all jobs.
A source-fetch/parser failure stops rather than silently testing a partial list.
This current constituent list is NOT historical point-in-time membership;
survivorship and universe-selection bias remain material.

## Conditional inclusion, not a claim that every symbol is supported

Verify standard 100-share call inventory with Alpaca's read-only contract API,
checking active and inactive contracts whose expiration dates overlap the research
window plus its holding/selection range. Pagination is bounded and audited.
Only options_inventory_verified symbols enter the research matrix. This checks
contract existence, not available historical bid/ask quotes or affordability.
An empty inventory response is distinct from permission/provider errors. Unknown
checks are recorded, make the final universe incomplete and withhold selection.
If no supported symbols are verified, do not run an empty successful backtest.

SPX and XSP are retained in the candidate manifest but explicitly excluded with
unsupported_index_adapter: the existing equity-bar, standard-delivery simulation
cannot certify index/cash-settled contracts. This does NOT mean they lack options.
Share-class tickers such as BRK.B/BF.B are likewise explicitly marked unsupported
rather than silently renaming provider or contract roots. Delisted/reorganized
symbols such as WOLF are not assumed historically continuous; downstream stock
warmup and actual quote checks still govern completion. The paper-trading
watchlist and its 10-root safety bound remain unchanged.

## Scale and costs

Every eligible ticker runs 21 rules x 2 allocations x 2 periods = 84 experiments.
Hundreds of tickers mean tens of thousands of separate simulations. Source-table
count is not an eligible count. Matrix jobs contain five symbols, keeping job
count below the platform matrix ceiling without dropping tickers. At most two
jobs run concurrently; each can run up to six hours. Preparation can run up to
one hour. Large full-universe runs may consume substantial Actions minutes and
take hours or days; this is manual-dispatch only, not a background recurring job.
Provider permissions, request limits, runner capacity and data gaps may prevent
completion. No subscription or permission upgrade is purchased or bypassed.

## Final summary at the bottom

The final report ends with Starting Equity, Final Equity, Total Trades, Winning
Trades, Lost Trades, plus rule/allocation/period and completed-account counts.
Each row totals independently funded ticker accounts for ONE configuration and
phase. Example: two $2,000 accounts start at $4,000, not $2,000. Alternative
strategies, allocations and phase resets are never presented as one investable
portfolio. Flat trades are counted in Total Trades, not wins/losses. Incomplete
rows show N/A equity and clearly labeled completed-account trade subtotals.

capital_summary.csv contains the same final table. Upload only the compact
experiment_bundle.json: universe checks, comparisons, capital summary, per-symbol
completion counts, trade-bearing experiments and failures. Complete per-run
metrics, equity/skip histories and provider audits remain in universe-batch
artifacts for deep inspection. The compact bundle avoids forcing users to
upload hundreds of folders or enormous all-zero equity histories.

Eight offline fixture tests passed for source parsing/deduplication, incomplete
source rejection, explicit index/share-class exclusion, inventory verification,
access-error distinction and honest capital aggregation. Real provider access,
the live source HTML parser and the full expanded backtest were not executed in
this environment; Actions runs the full repository tests before preparation.
No guaranteed profitable strategy or complete historical chain is claimed.
