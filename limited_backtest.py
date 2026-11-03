"""Explicit limited-chain research. No orders or full-chain claims."""
import argparse
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import pandas as pd
import onclick_backtest as eod
from alpaca_backtest import Alpaca
from auto_watchlist import choose_feed
from watchlist_backtest import read_watchlist

NOTICE = "LIMITED-DATA RESEARCH: provider-restricted strike universe; not a full-chain backtest. Independent $2,000 accounts per symbol/strategy, not a shared portfolio. Buy raw ask, sell raw bid, fees included. EOD estimates, no guaranteed fills. No out-of-sample validation."
STRATEGIES = ("breakout", "momentum", "reversion", "blend", "adaptive")


def target_strikes(price):
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Invalid stock reference close")
    center = math.floor(price / 5 + .5) * 5
    return sorted({float(k) for k in (center - 5, center, center + 5) if k > 0})


class LimitedQuotes:
    def __init__(self, frames):
        self.references = {(root, pd.Timestamp(r.date).date().isoformat()): float(r.close)
            for root, frame in frames.items() for r in frame.itertuples()}
        self.cache, self.seen_strikes, self.audit = {}, {}, []

    def fetch(self, ticker, day, strike):
        key = (ticker, day, strike)
        if key in self.cache:
            return self.cache[key]
        params = dict(ticker=ticker, date=day, strike=format(strike, "g"),
            type="call", data="all", output="json-v1")
        request = Request(eod.Onclick.ENDPOINT + "?" + urlencode(params),
            headers={"Accept": "application/json", "User-Agent": "adaptive-ai-backtester/limited-research"})
        record = dict(ticker=ticker, date=day, strike=strike, status="failed")
        self.audit.append(record)
        for attempt in range(1, 4):
            record["attempts"] = attempt
            time.sleep(1.1 * 2 ** (attempt - 1))
            try:
                with urlopen(request, timeout=60) as response:
                    record["http_status"] = response.status
                    payload = json.load(response)
                break
            except HTTPError as exc:
                status = exc.code
                exc.close()
                record["http_status"] = status
                if status in (408, 429, 500, 502, 503, 504) and attempt < 3:
                    continue
                raise ValueError(f"Options access failed: {ticker} {day} strike={strike:g} HTTP={status}; no performance for this run") from None
            except (OSError, ValueError):
                if attempt < 3:
                    continue
                raise ValueError(f"Options transport/JSON failed: {ticker} {day} strike={strike:g}") from None
        if not isinstance(payload, list):
            raise ValueError("Unsupported options response")
        warnings = [r for r in payload if isinstance(r, dict) and "warning" in r]
        record["provider_warning_count"] = len(warnings)
        raw = [r for r in payload if not (isinstance(r, dict) and set(r) == {"warning"})]
        if not raw:
            record.update(status="no_quotes", valid_calls=0)
            self.cache[key] = []
            return []
        rows, rejected = eod.normalize(raw, ticker, day)
        if any(q["strike"] != strike for q in rows):
            raise ValueError("Provider ignored requested strike")
        record.update(status="success", valid_calls=len(rows), rejected_records=rejected,
            contracts=[q["contract"] for q in rows])
        self.cache[key] = rows
        return rows

    def chain(self, ticker, day):
        key = (ticker, day)
        if key not in self.references:
            raise ValueError("Missing dated stock reference")
        strikes = self.seen_strikes.setdefault(ticker, set())
        strikes.update(target_strikes(self.references[key]))
        rows = {}
        # Keep querying earlier strikes so a held contract is never silently replaced.
        for strike in sorted(strikes):
            for q in self.fetch(ticker, day, strike):
                if q["contract"] in rows and rows[q["contract"]] != q:
                    raise ValueError("Conflicting duplicate quote")
                rows[q["contract"]] = q
        return list(rows.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--allocation", type=float, default=.25)
    args = parser.parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    if start > end or end.date() >= pd.Timestamp.now(tz="America/New_York").date() or (end-start).days > 180 or not 0 < args.allocation <= 1:
        raise SystemExit("Use completed dates, max 180 days, allocation in (0,1]")
    out = Path("results")
    out.mkdir(exist_ok=True)
    results, failed = [], False
    (out / "report.md").write_text("# Limited-data options research\n\n" + NOTICE + "\n")
    try:
        roots, pins, mode, _, _ = read_watchlist()
        if mode != "manual" or any(value is not None for value in pins.values()):
            raise ValueError("Limited research requires a manual underlying-ticker watchlist; pins/active mode are not silently ignored")
        client = Alpaca()
        feed, attempts = choose_feed(client, roots, start, end)
        (out / "stock_feed_selection.json").write_text(json.dumps(dict(selected_feed=feed, attempts=attempts), indent=2))
        if feed is None:
            raise ValueError("No stock feed passed coverage checks")
        frames = {root: client.bars([root], start-pd.Timedelta(days=150), end, stock=True, stock_feed=feed) for root in roots}
        class CachedStocks:
            def bars(self, symbols, *unused, **kwargs):
                return frames[symbols[0]].copy()
        for root in roots:
            for strategy in STRATEGIES:
                quotes = LimitedQuotes({root: frames[root]})
                dest = out / root / strategy
                dest.mkdir(parents=True, exist_ok=True)
                result = dict(ticker=root, strategy=strategy, coverage="limited", status="failed")
                try:
                    trades, equity, skips, metrics = eod.simulate(CachedStocks(), quotes, root,
                        args.start, args.end, strategy, args.allocation, feed, run_preflight=False)
                    metrics["warning"] = NOTICE
                    for frame, name in ((trades, "trades"), (equity, "equity"), (skips, "skipped_signals")):
                        frame.to_csv(dest / (name + ".csv"), index=False)
                    result.update(status="completed", metrics=metrics)
                except Exception:
                    failed = True
                    result["error"] = "Incomplete run; inspect request_audit.json. No final performance reported."
                finally:
                    (dest / "request_audit.json").write_text(json.dumps(quotes.audit, indent=2, allow_nan=False))
                    (dest / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False))
                results.append(result)
    except Exception:
        failed = True
        results.append(dict(status="failed", error="Setup failed; inspect stock-feed artifact and workflow step. No valid performance."))
    finally:
        (out / "limited_summary.json").write_text(json.dumps(dict(warning=NOTICE, config=vars(args), runs=results), indent=2, allow_nan=False))
        with (out / "report.md").open("a") as handle:
            handle.write("\n|Ticker|Strategy|Status|Trades|Return %|Max drawdown %|\n|---|---|---|---:|---:|---:|\n")
            for r in results:
                m = r.get("metrics", {})
                handle.write(f"|{r.get('ticker','-')}|{r.get('strategy','-')}|{r['status']}|{m.get('trades','N/A')}|{m.get('return_pct','N/A')}|{m.get('max_drawdown_pct','N/A')}|\n")
    if failed:
        raise SystemExit("One or more limited runs failed; inspect artifacts")


if __name__ == "__main__":
    main()
