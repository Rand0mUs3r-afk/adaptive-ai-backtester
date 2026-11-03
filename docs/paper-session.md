# Paper-session runner: preflight required, no profit or readiness guarantee

This adds a separate PAPER-only adapter. It never targets the real-money broker
host. Existing historical strategy-comparison workflows remain available.
Nine offline adapter tests passed during preparation; no broker/account/OPRA
access, fills, full integration or market-open deployment has been verified.

## Before enabling orders

1. Use a dedicated Alpaca paper account with long-call permission. Do not mix
   manual positions or other trading bots in it. Verify its account ID.
2. Prefer Actions secrets ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY.
   Existing ALPACA_API_KEY/ALPACA_SECRET_KEY are fallbacks, but must authenticate
   to the hardcoded paper host. Live keys are different; never send keys in chat.
3. Run Paper session - 15 minute options scan manually first. Default is dry-run.
   Inspect paper_cycle.json during an open market, including current OPRA access,
   quote freshness, watchlist signals, and account state. Closed-market success
   verifies only account/clock reads, not options access or order readiness.
4. Only after checks, set repository Actions variables PAPER_ACCOUNT_ID to that
   paper ID, PAPER_ARM_DATE to the intended New York session YYYY-MM-DD, and
   PAPER_ORDERS_ENABLED=true. The date gate expires each day; daily re-arming is
   intentional. No variable/key changes or actual orders are made by this commit.
5. Confirm a paper order and its fill/rejection in Alpaca; a workflow finishing
   does not establish that an order filled. Disable PAPER_ORDERS_ENABLED to stop
   all automated writes, including exits/cancellations; then manage positions
   manually. Disabling a workflow does not cancel existing broker orders.

## Timing

Cron attempts every 15 minutes at :02/:17/:32/:47, weekdays 13-20 UTC, covering
US regular hours in both daylight/standard time. The broker clock gates actions
for holidays and early closes; do not hardcode an assumed opening date/time.
GitHub Actions may delay/drop schedules. This is NOT an execution SLA, immediate
stop monitor, or guarantee of an opening-bell run. Use a supervised always-on
scheduler if strict timing is required. Dry-run scans start automatically after
merge onto the default branch; paper writes remain disabled until separately armed.

## Rules and risk boundaries

Use only completed previous-session daily stock bars, with IEX explicitly
identified. Evaluate breakout, momentum, reversion, blend and adaptive rules.
Require at least two triggered rule labels for a candidate; these labels overlap
and are NOT independent evidence or calibrated win probabilities. Watchlist
order is deterministic, not a P&L-trained strategy ranking. These are daily
signals polled every 15 minutes, not validated 15-minute-bar strategies.

Only current Alpaca OPRA bid/ask quotes can drive orders. No OnclickMedia EOD,
midpoint, delayed or modified indicative-feed fallback. Missing OPRA permission
halts rather than silently weakening data quality. Quotes must be <=120 seconds
old, no more than 5 seconds future-dated, finite and noncrossed with positive bid.
Entry spread <=20% of ask and positive displayed ask size. Standard 100-share
long calls only, 30-60 DTE, within 10% of prior stock close; at most the first
30 deterministically ranked contracts are inspected. This is a bounded universe,
not an exhaustive full-chain search. No short options or multi-leg orders.

One contract per entry, <=$200 premium+estimated fee, also <=10% account equity
and available cash. At most one new buy order per New York day across the bot;
existing positions prevent new entries. No entries in final 30 minutes. Account
loss >=3% versus last_equity stops entries, not exit management. These are
engineering defaults, not optimized or validated trading advice. Actual paper
account balance can differ from historical independent $2,000 accounts.

Manage broker-reconciled long positions before entries, with +15%/-25% bid-based
signals, 14 calendar day holding limit and seven-day expiration buffer. Every
order is a DAY limit order. Use conservative $0.05/$0.10 price increments;
limits may not fill. No force-liquidation/midpoint fiction or guaranteed stop.
Pending/partial orders block new orders; aged pending orders are canceled after
15 minutes when armed, with reconciliation on a later cycle. Broker IDs prevent
duplicate daily buys; sell IDs use 15-minute buckets for later exit retries.
POST is never automatically retried after an ambiguous response. Broker history
is re-read next cycle; truncation, unknown positions, permission failures and
unsafe state cause a halt. OPRA outage also prevents automated exits: monitor
manually, especially around expiration. Assignment/exercise and corporate-action
risk are not eliminated by a polling bot.

## Provider references

https://docs.alpaca.markets/us/docs/paper-trading
https://docs.alpaca.markets/us/reference/optionlatestquotes
https://docs.alpaca.markets/us/reference/get-options-contracts
https://docs.alpaca.markets/us/reference/postorder
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
