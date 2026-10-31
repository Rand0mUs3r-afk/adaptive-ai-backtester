# Watchlist-only multi-setup options research

Both manual options workflows now run watchlist_backtest.py. There is NO ticker, strategy or pricing input in either Run workflow form. Dates, allocation and Alpaca stock feed remain inputs. This supersedes the older single-ticker workflow instructions; old standalone scripts/dashboard remain available but are not used by these manual jobs.

## Edit in your browser

Open watchlist.txt in GitHub, click the pencil, enter one symbol per line and commit. Default is SPY. Entries may be underlying roots (e.g. SPY) or complete standard call symbols. A complete call symbol pins that underlying to the listed contract(s); it does not bypass expiration, affordability or other eligibility checks. Puts and adjusted/nonstandard contracts are not supported. Empty/missing lists fail, never fall back silently. Maximum 10 underlying roots; comments begin with #.

MODE=manual tests the listed universe. MODE=active ranks eligible calls within that same candidate pool using the last available stock session BEFORE the test starts, retains the top TOP roots, and freezes that resolved list for the run. It does not discover the global most-active option universe. It uses Alpaca historical option volume over discoverable standard 30-60 DTE, near-the-money calls, not stock volume. Historical contract metadata may be incomplete. Failures stop ranking rather than substitute today's screener or yfinance chain. Today's stock/option activity is not used as a historical ranking. Add multiple roots to the file for meaningful automatic selection.

The checked-in watchlist is never rewritten automatically. Artifacts contain watchlist_used.txt, resolved_watchlist.txt, ranking dates/volumes and the watchlist hash. Thus the FILE is always the source of the universe, including auto-selection mode. Alpaca's most-active STOCK screener is deliberately not labeled a most-active OPTIONS screener.

## All implemented setups, not every possible strategy

Every listed ticker is evaluated against breakout, momentum, reversion, blend and adaptive policies using ONLY the prior completed stock session. These are the existing engine's rules; the custom Darvas state machine, puts and spreads are not added by this change. The scorer is a fixed quality heuristic, NOT trained AI, a calibrated probability, or a proven edge.

Breakout scores 65 plus 10 for the rising-average regime plus 10 for volume at least 1.5x prior average. Momentum scores 60 plus 15 for that regime plus 5 when stochastic is 20-80. Reversion scores 60 plus 15 outside the trending regime. Triggered blend gets the maximum base score plus 3 (capped at 90); adaptive uses its regime-eligible base score. Non-triggered setups score zero. Minimum qualifying score is 65. Fixed ordering breaks setup ties; ticker alphabet breaks cross-ticker ties. Blend/adaptive are derived policies, not independent confirmations.

When flat, the highest-ranked currently triggered setup/ticker is considered first. If it has no affordable eligible call, another signaled ticker may be considered using the same prior-session evidence. There is no hindsight selection of whichever strategy later wins. Setup scores and all evaluated tickers are recorded in setup_audit.csv. While a position is open, setups are still audited but do not change the held trade's rationale.

## One shared $2,000 account

All tickers share ONE $2,000 balance, not $2,000 each. One long-call position at a time, no leverage or fractional contracts. Default premium allocation is 25% of equity ($500 initially), not stop-based maximum loss. Entry is next-session OnclickMedia EOD RAW ask; valuation/exit is RAW bid, with $0.65 fees per contract per side. No midpoint, realistic_* or theoretical-option substitution.

Calls remain 30-60 DTE at selection, strikes within 10% of prior underlying close, earliest expiry then nearest affordable strike. A +15%/-25% net liquidation signal or underlying-floor invalidation at a close schedules the NEXT EOD exit. Maximum hold is 10 sessions; near-expiry and final-test liquidation also apply. These are daily quote estimates, not intraday stop/limit executions or guaranteed fills. Missing held quotes, selected-entry quotes or required stock sessions abort rather than hide losses. No automatic provider mixing.

## Results and limits

GitHub summary shows closed trades, final shared equity and selected setup/quality scores. Downloads include trades.csv, equity.csv, setup_audit.csv, skipped_signals.csv, summary.json, quote_provenance.json and both watchlist snapshots. Results retain provider/source hashes from the EOD adapter. Five new isolated tests check parsing/pins, empty-list rejection, triggered-only scoring, past-date activity ranking and shared-account reconciliation. Fixtures are not performance evidence; authenticated end-to-end operation remains unverified here.

This is fixed-rule multi-setup routing, not strategy optimization or purged walk-forward learning. There is no claimed winning probability. User-selected universes, incomplete contracts, quote timestamp/size limitations, corporate actions and repeated manual searches remain limitations. The workflows still require Alpaca Actions secrets and OnclickMedia coverage. This commit does not run a job, configure secrets or place orders. Existing dashboard controls are not changed.
