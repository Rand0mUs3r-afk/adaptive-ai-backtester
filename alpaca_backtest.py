"""Read-only Alpaca bar-based research. Never submits an order."""
import argparse
from datetime import date
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import pandas as pd
from engine import features, signal

WARNING = "ESTIMATED DAILY-BAR FILLS, not historical bid/ask execution. No live orders. Not calibrated probabilities. Historical contract inventory may be incomplete; splits/dividends/assignment not modeled."

class Alpaca:
    def __init__(self):
        key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise ValueError("Add ALPACA_API_KEY and ALPACA_SECRET_KEY as repository Actions secrets")
        self.headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        self.requests = 0
        self.cache = {}

    def get(self, endpoint, params):
        if not endpoint.startswith(("https://data.alpaca.markets/", "https://paper-api.alpaca.markets/v2/options/contracts")):
            raise ValueError("Read-only endpoint not allowed")
        url = endpoint + "?" + urlencode(params)
        if url in self.cache:
            return self.cache[url]
        for attempt in range(4):
            self.requests += 1
            if self.requests > 10000:
                raise ValueError("Research request cap reached; narrow the interval")
            time.sleep(.35)
            try:
                with urlopen(Request(url, headers=self.headers), timeout=60) as response:
                    payload = json.load(response)
                self.cache[url] = payload
                return payload
            except HTTPError as exc:
                if exc.code == 429 or exc.code >= 500:
                    time.sleep(min(60, 2 ** (attempt + 1)))
                    continue
                raise ValueError(f"Alpaca HTTP {exc.code}; check credentials, entitlement and requested dates") from None
            except Exception:
                if attempt == 3:
                    raise ValueError("Alpaca network/response failure; no partial performance is reported") from None
                time.sleep(2 ** attempt)
        raise ValueError("Alpaca retry limit reached")

    def pages(self, endpoint, params, field):
        rows, token, seen = [], None, set()
        while True:
            payload = self.get(endpoint, {**params, **({"page_token": token} if token else {})})
            part = payload.get(field)
            if part is None:
                raise ValueError("Alpaca response missing " + field)
            rows.extend(part)
            token = payload.get("next_page_token")
            if not token:
                return rows
            if token in seen:
                raise ValueError("Repeated pagination token")
            seen.add(token)

    def bars(self, symbols, start, end, stock=False, stock_feed="iex"):
        all_rows = []
        endpoint = "https://data.alpaca.markets/" + ("v2/stocks/bars" if stock else "v1beta1/options/bars")
        for offset in range(0, len(symbols), 100):
            params = dict(symbols=",".join(symbols[offset:offset+100]), timeframe="1Day", start=pd.Timestamp(str(start)[:10]).tz_localize("America/New_York").isoformat(), end=(pd.Timestamp(str(end)[:10])+pd.Timedelta(days=1)-pd.Timedelta(seconds=1)).tz_localize("America/New_York").isoformat(), limit=10000, sort="asc")
            if stock:
                params.update(feed=stock_feed, adjustment="raw")
            token, seen = None, set()
            while True:
                payload = self.get(endpoint, {**params, **({"page_token": token} if token else {})})
                if not isinstance(payload.get("bars"), dict):
                    raise ValueError("Historical bars missing; verify data entitlement")
                for symbol, items in payload["bars"].items():
                    for r in items:
                        d = pd.Timestamp(r["t"]).tz_convert("America/New_York").date().isoformat()
                        if str(start)[:10] <= d <= str(end)[:10]:
                            values = [float(r[k]) for k in ("o", "h", "l", "c", "v")]
                            o, h, l, c, v = values
                            if not all(math.isfinite(x) for x in values) or min(o,l,c) <= 0 or h < max(o,l,c) or l > min(o,h,c) or v < 0:
                                raise ValueError("Invalid historical bar")
                            all_rows.append(dict(date=d, symbol=symbol, open=o, high=h, low=l, close=c, volume=v))
                token = payload.get("next_page_token")
                if not token:
                    break
                if token in seen:
                    raise ValueError("Repeated bars pagination token")
                seen.add(token)
        frame = pd.DataFrame(all_rows, columns=["date", "symbol", "open", "high", "low", "close", "volume"])
        if frame.duplicated(["date", "symbol"]).any():
            raise ValueError("Duplicate historical bars")
        return frame.sort_values(["date", "symbol"])

    def candidates(self, symbol, day, price):
        result = {}
        for status in ("active", "inactive"):
            params = dict(underlying_symbols=symbol, status=status, type="call", root_symbol=symbol, expiration_date_gte=(pd.Timestamp(day)+pd.Timedelta(days=30)).date().isoformat(), expiration_date_lte=(pd.Timestamp(day)+pd.Timedelta(days=60)).date().isoformat(), strike_price_gte=round(price*.9, 2), strike_price_lte=round(price*1.1, 2), limit=1000)
            rows = self.pages("https://paper-api.alpaca.markets/v2/options/contracts", params, "option_contracts")
            if len(rows) > 5000:
                raise ValueError("Contract inventory cap exceeded")
            for r in rows:
                if float(r.get("size", 0)) == 100 and re.fullmatch(re.escape(symbol)+r"\d{6}C\d{8}", r["symbol"]):
                    result[r["symbol"]] = dict(contract=r["symbol"], expiry=r["expiration_date"], strike=float(r["strike_price"]))
        return list(result.values())


def simulate(client, symbol, start, end, strategy="adaptive", allocation=.25, slippage=.02, fee=.65, hold=10, stock_feed="iex"):
    if not re.fullmatch(r"[A-Z]{1,5}", symbol) or strategy not in ("adaptive", "breakout", "momentum", "reversion", "blend"):
        raise ValueError("Unsupported ticker or strategy")
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    today = pd.Timestamp.now(tz="America/New_York").date()
    if start < pd.Timestamp("2024-02-01") or start > end or end.date() >= today or (end-start).days > 180:
        raise ValueError("Use a completed historical interval since February 2024, at most 180 calendar days")
    if not 0 < allocation <= 1 or not 0 <= slippage < .5 or fee < 0 or not 1 <= hold <= 20:
        raise ValueError("Invalid sizing, costs or holding time")
    raw = client.bars([symbol], start-pd.Timedelta(days=150), end, stock=True, stock_feed=stock_feed)
    f = features(raw)
    f["date"] = pd.to_datetime(f.date).dt.normalize()
    f = f.sort_values("date").reset_index(drop=True)
    cash, position, trades, curve, skipped = 2000.0, None, [], [], []
    for i, row in f.iterrows():
        day = row.date
        if day < start or day > end:
            continue
        if i == 0 or pd.isna(f.iloc[i-1].slow):
            raise ValueError("Insufficient underlying warmup")
        final = i == len(f)-1
        closed = False
        if position is not None:
            p = position
            found = p["bars"][p["bars"].date == day.date().isoformat()]
            if len(found) != 1 or found.iloc[0].volume <= 0:
                raise ValueError("Missing traded bar for held contract; aborting rather than hiding loss")
            bar = found.iloc[0]
            reason = p["pending"]
            if not reason and i-p["index"] >= hold:
                reason = "maximum_holding"
            if not reason and day >= pd.Timestamp(p["expiry"])-pd.Timedelta(days=7):
                reason = "pre_expiration"
            if final:
                reason = "end_of_test"
            if reason:
                exit_price = float(bar.close if final else bar.open)*(1-slippage)
                proceeds = p["qty"]*(exit_price*100-fee)
                cash += proceeds
                pnl = proceeds-p["cost"]
                trades.append(dict(contract=p["contract"], underlying=symbol, signal_date=p["signal"], entry_date=p["entry"], exit_date=day.date().isoformat(), contracts=p["qty"], entry_premium=p["premium"], exit_premium=exit_price, entry_cost=p["cost"], net_proceeds=proceeds, total_fees=2*fee*p["qty"], pnl=pnl, return_pct=100*pnl/p["cost"], outcome="WIN" if pnl>0 else "LOSS" if pnl<0 else "FLAT", exit_reason=reason, equity_before=p["before"], equity_after=cash, holding_sessions=i-p["index"]))
                position, closed = None, True
        if position is None and not closed and not final and signal(f.iloc[i-1], strategy):
            prior = f.iloc[i-1]
            prior_day = prior.date.date().isoformat()
            candidates = client.candidates(symbol, prior_day, float(prior.close))
            snapshot = client.bars([c["contract"] for c in candidates], prior_day, prior_day) if candidates else pd.DataFrame()
            lookup = {r.symbol: r for r in snapshot.itertuples()} if len(snapshot) else {}
            eligible = [c for c in candidates if c["contract"] in lookup and lookup[c["contract"]].volume > 0 and lookup[c["contract"]].close*100*(1+slippage)+fee <= cash*allocation]
            eligible.sort(key=lambda c: (c["expiry"], abs(c["strike"]-prior.close), c["contract"]))
            if not eligible:
                skipped.append(dict(date=day.date().isoformat(), reason="No prior-day traded, affordable eligible call"))
            else:
                selected = eligible[0]
                history = client.bars([selected["contract"]], day, end)
                found = history[history.date == day.date().isoformat()]
                if len(found) != 1 or found.iloc[0].volume <= 0:
                    skipped.append(dict(date=day.date().isoformat(), reason="Selected contract lacks entry-day traded bar; no hindsight substitution"))
                else:
                    premium = float(found.iloc[0].open)*(1+slippage)
                    unit = premium*100+fee
                    qty = int(cash*allocation//unit)
                    if qty < 1:
                        skipped.append(dict(date=day.date().isoformat(), reason="Entry gap makes selected contract unaffordable"))
                    else:
                        position = dict(**selected, bars=history, qty=qty, premium=premium, cost=qty*unit, before=cash, index=i, entry=day.date().isoformat(), signal=prior_day, pending=None)
                        cash -= qty*unit
        marked = 0.0
        if position is not None:
            p = position
            bar = p["bars"][p["bars"].date == day.date().isoformat()].iloc[0]
            marked = p["qty"]*(float(bar.close)*(1-slippage)*100-fee)
            change = marked/p["cost"]-1
            p["pending"] = "profit_close_signal" if change >= .15 else "loss_close_signal" if change <= -.25 else "underlying_floor" if row.close < row.floor else None
        curve.append(dict(date=day.date().isoformat(), cash=cash, position_liquidation_estimate=marked, equity=cash+marked))
    if not curve or position is not None:
        raise ValueError("No completed simulation interval")
    ledger = pd.DataFrame(trades, columns=["contract","underlying","signal_date","entry_date","exit_date","contracts","entry_premium","exit_premium","entry_cost","net_proceeds","total_fees","pnl","return_pct","outcome","exit_reason","equity_before","equity_after","holding_sessions"])
    equity = pd.DataFrame(curve)
    baseline = pd.Series([2000.0] + equity.equity.tolist())
    losses = ledger.loc[ledger.pnl < 0, "pnl"]
    wins = ledger.loc[ledger.pnl > 0, "pnl"]
    summary = dict(starting_equity=2000.0, final_equity=float(cash), equity_change=float(cash-2000), return_pct=float((cash/2000-1)*100), trades=len(ledger), wins=len(wins), losses=len(losses), flat=int((ledger.pnl==0).sum()), win_rate_pct=float(len(wins)/len(ledger)*100) if len(ledger) else None, average_net_pnl=float(ledger.pnl.mean()) if len(ledger) else None, best_trade=float(ledger.pnl.max()) if len(ledger) else None, worst_trade=float(ledger.pnl.min()) if len(ledger) else None, total_fees=float(ledger.total_fees.sum()), max_drawdown_pct=float((baseline/baseline.cummax()-1).min()*100), profit_factor=float(wins.sum()/abs(losses.sum())) if len(losses) else None, skipped_signals=len(skipped), warning=WARNING)
    if abs(float(ledger.pnl.sum())-summary["equity_change"]) > .00001:
        raise ValueError("Portfolio reconciliation failed")
    return ledger, equity, pd.DataFrame(skipped, columns=["date","reason"]), summary


def report(ledger, summary, config):
    text = "# Alpaca options backtest — $2,000 starting equity\n\n" + WARNING + "\n\n## Configuration\n\n```json\n" + json.dumps(config, indent=2) + "\n```\n\n## Final outcome\n\n|Metric|Value|\n|---|---|\n"
    for k, v in summary.items():
        if k != "warning":
            text += f"|{k}|{v if v is not None else 'N/A'}|\n"
    text += "\n## Every closed trade\n\n|Contract|Entry|Exit|Qty|Entry premium|Exit premium|Fees|Net P&L|Return %|Outcome|Equity after|Reason|\n|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|\n"
    for r in ledger.itertuples():
        text += f"|{r.contract}|{r.entry_date}|{r.exit_date}|{r.contracts}|{r.entry_premium:.4f}|{r.exit_premium:.4f}|{r.total_fees:.2f}|{r.pnl:.2f}|{r.return_pct:.2f}|{r.outcome}|{r.equity_after:.2f}|{r.exit_reason}|\n"
    if ledger.empty:
        text += "\nNo trades qualified. No profits or trades have been invented.\n"
    return text


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="SPY")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--strategy", default="adaptive")
    p.add_argument("--allocation", type=float, default=.25)
    p.add_argument("--slippage", type=float, default=.02)
    p.add_argument("--stock-feed", choices=["iex","sip"], default="iex")
    args = p.parse_args()
    out = Path("results")
    out.mkdir(exist_ok=True)
    config = {**vars(args), "starting_equity":2000, "instrument":"long_call", "fee_per_contract_side":.65, "hold_sessions":10, "target_close_signal":.15, "stop_close_signal":-.25, "option_data":"Alpaca historical trade bars; provider-default entitlement; not bid/ask", "git_sha":os.getenv("GITHUB_SHA", "local")}
    try:
        t, e, s, m = simulate(Alpaca(), args.symbol, args.start, args.end, strategy=args.strategy, allocation=args.allocation, slippage=args.slippage, stock_feed=args.stock_feed)
        t.to_csv(out/"trades.csv", index=False)
        e.to_csv(out/"equity.csv", index=False)
        s.to_csv(out/"skipped_signals.csv", index=False)
        (out/"summary.json").write_text(json.dumps({"config":config,"metrics":m}, indent=2, allow_nan=False))
        (out/"report.md").write_text(report(t,m,config))
    except Exception as exc:
        (out/"report.md").write_text("# Backtest failed\n\nNo valid final equity is reported.\n\n" + str(exc) + "\n")
        raise SystemExit("Backtest failed; see report artifact (no credentials logged)") from None

if __name__ == "__main__":
    main()
