"""Alpha Vantage daily research collector; credentials never enter cache keys."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo
import pandas as pd

class AlphaVantage:
    def __init__(self, key=None, cache="data/cache", pause=1.1):
        self.key = key or os.environ.get("ALPHAVANTAGE_API_KEY", "")
        if not self.key:
            raise ValueError("Set ALPHAVANTAGE_API_KEY locally; historical options require a premium entitlement")
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.pause = max(float(pause), 1.1)
        self.last_call = 0.0

    def get(self, function, **params):
        public = dict(function=function, **params)
        path = self.cache / (hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest() + ".json")
        historical = function == "HISTORICAL_OPTIONS"
        if path.exists() and (historical or time.time() - path.stat().st_mtime < 86400):
            return json.loads(path.read_text())
        for attempt in range(3):
            time.sleep(max(0, self.pause - (time.monotonic() - self.last_call)))
            self.last_call = time.monotonic()
            try:
                url = "https://www.alphavantage.co/query?" + urlencode({**public, "apikey": self.key})
                with urlopen(url, timeout=60) as response:
                    payload = json.load(response)
            except Exception:
                if attempt == 2:
                    raise ValueError("Data request failed; check connectivity/provider availability (URL redacted)") from None
                time.sleep(2 ** attempt)
                continue
            if not isinstance(payload, dict):
                raise ValueError("Unexpected provider response")
            if any(k in payload for k in ("Error Message", "Information", "Note")):
                raise ValueError("Provider denied/throttled request. Check your key, premium entitlement and plan limits. No partial dataset will be used.")
            if function == "HISTORICAL_OPTIONS" and (payload.get("message") != "success" or not payload.get("data")):
                raise ValueError("No historical chain returned for requested trading date")
            if function == "TIME_SERIES_DAILY_ADJUSTED" and not payload.get("Time Series (Daily)"):
                raise ValueError("Daily adjusted response missing; check premium access")
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload))
            temporary.replace(path)
            return payload
        raise ValueError("Data request failed")


def stock_frame(payload, symbol, start, end):
    rows = []
    for date, values in payload["Time Series (Daily)"].items():
        if start <= date <= end:
            if float(values.get("8. split coefficient", 1)) != 1:
                raise ValueError(f"{symbol}: split in requested interval; corporate-action accounting is not supported")
            rows.append(dict(date=date, symbol=symbol, open=float(values["1. open"]), high=float(values["2. high"]), low=float(values["3. low"]), close=float(values["4. close"]), volume=float(values["6. volume"])))
    if not rows:
        raise ValueError(f"No stock bars for {symbol} in interval")
    return pd.DataFrame(rows).sort_values("date")


def option_frame(payload, symbol, date):
    rows, rejected = [], 0
    standard = re.compile(re.escape(symbol) + r"\d{6}C\d{8}$")
    for r in payload["data"]:
        if str(r["type"]).lower() != "call":
            continue
        if str(r["date"]) != date or str(r["symbol"]) != symbol:
            raise ValueError("Provider chain timestamp/symbol mismatch")
        bid, ask = float(r["bid"]), float(r["ask"])
        if not standard.fullmatch(str(r["contractID"])) or not 0 < bid <= ask:
            rejected += 1
            continue
        rows.append(dict(date=date, symbol=symbol, contract=r["contractID"], expiry=r["expiration"], strike=float(r["strike"]), right="C", bid=bid, ask=ask, multiplier=100))
    if not rows:
        raise ValueError("No eligible standard call quotes on " + date)
    return pd.DataFrame(rows), rejected


def collect(symbols, start, end, options=True, client=None, max_chains=500, progress=None):
    client = client or AlphaVantage()
    symbols = sorted(set(s.strip().upper() for s in symbols if s.strip()))
    if not symbols or any(not re.fullmatch(r"[A-Z]{1,5}", s) for s in symbols):
        raise ValueError("Use standard US ticker roots of 1-5 letters")
    start, end = pd.Timestamp(start).date().isoformat(), pd.Timestamp(end).date().isoformat()
    today = pd.Timestamp.now(tz=ZoneInfo("America/New_York")).date().isoformat()
    if start > end or end >= today:
        raise ValueError("Choose a valid interval ending before today's New York session")
    bars = pd.concat([stock_frame(client.get("TIME_SERIES_DAILY_ADJUSTED", symbol=s, outputsize="full"), s, start, end) for s in symbols], ignore_index=True)
    count = len(bars) if options else 0
    if count > max_chains:
        raise ValueError(f"Needs {count} daily chain lookups; exceeds cap {max_chains}. Reduce dates/tickers or explicitly increase cap.")
    quotes, rejected = [], 0
    if options:
        for i, row in enumerate(bars.itertuples(), 1):
            frame, dropped = option_frame(client.get("HISTORICAL_OPTIONS", symbol=row.symbol, date=row.date), row.symbol, row.date)
            quotes.append(frame)
            rejected += dropped
            if progress:
                progress(i, count)
    result = pd.concat(quotes, ignore_index=True) if quotes else None
    metadata = dict(provider="Alpha Vantage", start=start, end=end, symbols=symbols, chain_lookups=count, excluded_call_records=rejected, note="Daily provider snapshots; not verified synchronized intraday quotes. Standard 100-share calls only. Zero bids/adjusted roots excluded; missing held quotes stop engine. Dividends and assignment not modeled. Live provider integration not independently validated.")
    return bars, result, metadata

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--stocks-only", action="store_true")
    parser.add_argument("--max-chains", type=int, default=500)
    args = parser.parse_args()
    b, q, m = collect(args.symbols, args.start, args.end, options=not args.stocks_only, max_chains=args.max_chains)
    Path("data").mkdir(exist_ok=True)
    b.to_csv("data/bars.csv", index=False)
    if q is not None:
        q.to_csv("data/options.csv", index=False)
    Path("data/manifest.json").write_text(json.dumps(m, indent=2))
