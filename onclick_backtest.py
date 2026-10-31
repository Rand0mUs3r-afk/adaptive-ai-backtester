"""EOD bid/ask research; stock signals from Alpaca, option quotes from OnclickMedia."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from urllib.request import urlopen
import pandas as pd
import alpaca_backtest as legacy
from engine import features, signal

WARNING = "ONCLICKMEDIA EOD QUOTE ESTIMATES: buy raw ask, sell raw bid. Snapshot dates have no verified intraday timestamps. No guaranteed fills, no orders, no trained AI. Standard 100-share calls assumed; corporate actions not modeled."


def normalize(payload, ticker, day):
    if not isinstance(payload, list) or not payload:
        raise ValueError("Missing/unsupported OnclickMedia snapshot; refusing partial coverage")
    rows, rejected, seen = [], 0, set()
    for r in payload:
        if r.get("ticker") != ticker or r.get("date") != day:
            raise ValueError("Quote ticker/date mismatch")
        if r.get("type") != "call":
            continue
        try:
            strike, bid, ask = float(r["strike"]), float(r["bid"]), float(r["ask"])
            expiry = pd.Timestamp(r["expiration"]).date().isoformat()
            contract = r["osi-key"].replace("-", "").replace(" ", "")
            expected = ticker + pd.Timestamp(expiry).strftime("%y%m%d") + "C" + f"{round(strike*1000):08d}"
            valid = all(math.isfinite(x) for x in (strike,bid,ask)) and strike>0 and 0<=bid<=ask and ask>0 and expiry>=day and contract==expected
        except (KeyError, TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            rejected += 1
            continue
        if contract in seen:
            raise ValueError("Duplicate normalized contract")
        seen.add(contract)
        rows.append(dict(contract=contract, expiry=expiry, strike=strike, bid=bid, ask=ask, date=day, provider="onclickmedia"))
    if not rows:
        raise ValueError("No valid raw call quotes in snapshot")
    return rows, rejected


class Onclick:
    def __init__(self):
        self.cache, self.audit = {}, []
    def chain(self, ticker, day):
        key = (ticker, day)
        if key in self.cache:
            return self.cache[key]
        url = "https://api.onclickmedia.com/?" + urlencode(dict(ticker=ticker, date=day, type="call", data="greeks", output="json-v1"))
        for attempt in range(3):
            time.sleep(1.1 * (attempt+1))
            try:
                with urlopen(url, timeout=60) as response:
                    payload = json.load(response)
                break
            except Exception:
                if attempt == 2:
                    raise ValueError("OnclickMedia request failed; no trade-bar or midpoint fallback permitted") from None
        rows, rejected = normalize(payload, ticker, day)
        self.cache[key] = rows
        self.audit.append(dict(ticker=ticker, date=day, valid_calls=len(rows), rejected_records=rejected, sha256=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()))
        return rows


def quantity(ask, equity, allocation=.25, fee=.65):
    return int(equity*allocation//(ask*100+fee))


def simulate(stocks, quotes, ticker, start, end, strategy="adaptive", allocation=.25, stock_feed="iex"):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if not re.fullmatch(r"[A-Z]{1,5}", ticker) or strategy not in ("adaptive","breakout","momentum","reversion","blend") or not 0<allocation<=1:
        raise ValueError("Invalid ticker, policy or allocation")
    if start>end or end.date()>=pd.Timestamp.now(tz="America/New_York").date() or (end-start).days>180:
        raise ValueError("Use completed historical dates, at most 180 calendar days")
    raw = stocks.bars([ticker],start-pd.Timedelta(days=150),end,stock=True,stock_feed=stock_feed)
    f = features(raw).sort_values("date").reset_index(drop=True)
    f["date"] = pd.to_datetime(f.date).dt.normalize()
    cash, p, trades, curve, skipped = 2000.0, None, [], [], []
    fee = .65
    for i,row in f.iterrows():
        day = row.date.date().isoformat()
        if row.date<start or row.date>end:
            continue
        if i==0 or pd.isna(f.iloc[i-1].slow):
            raise ValueError("Insufficient stock warmup")
        final, closed = i==len(f)-1, False
        snapshot = None
        if p is not None:
            snapshot = quotes.chain(ticker,day)
            matches = [q for q in snapshot if q["contract"]==p["contract"]]
            if len(matches)!=1:
                raise ValueError("Missing held-contract EOD quote: " + p["contract"] + " " + day)
            q = matches[0]
            reason = "end_of_test" if final else p["pending"] or ("maximum_holding" if i-p["index"]>=10 else "pre_expiration" if row.date>=pd.Timestamp(p["expiry"])-pd.Timedelta(days=7) else None)
            if reason:
                proceeds = p["qty"]*(q["bid"]*100-fee)
                cash += proceeds
                pnl = proceeds-p["cost"]
                trades.append(dict(contract=p["contract"],underlying=ticker,signal_date=p["signal"],entry_date=p["entry"],exit_date=day,contracts=p["qty"],entry_premium=p["ask"],exit_premium=q["bid"],entry_cost=p["cost"],net_proceeds=proceeds,total_fees=2*fee*p["qty"],pnl=pnl,return_pct=100*pnl/p["cost"],outcome="WIN" if pnl>0 else "LOSS" if pnl<0 else "FLAT",exit_reason=reason,equity_before=p["before"],equity_after=cash,holding_sessions=i-p["index"],provider="onclickmedia",entry_snapshot=p["entry"],exit_snapshot=day))
                p,closed = None,True
        if p is None and not closed and not final and signal(f.iloc[i-1],strategy):
            prior = f.iloc[i-1]
            prior_day = prior.date.date().isoformat()
            previous = quotes.chain(ticker,prior_day)
            eligible = [q for q in previous if 30<=(pd.Timestamp(q["expiry"])-prior.date).days<=60 and abs(q["strike"]/prior.close-1)<=.1 and quantity(q["ask"],cash,allocation)>0]
            eligible.sort(key=lambda q:(q["expiry"],abs(q["strike"]-prior.close),q["contract"]))
            if not eligible:
                skipped.append(dict(date=day,reason="No prior-snapshot affordable 30-60 DTE call"))
            else:
                chosen = eligible[0]
                snapshot = snapshot if snapshot is not None else quotes.chain(ticker,day)
                matches = [q for q in snapshot if q["contract"]==chosen["contract"]]
                if len(matches)!=1:
                    raise ValueError("Selected contract lacks entry snapshot; refusing silent substitution")
                q=matches[0]
                qty=quantity(q["ask"],cash,allocation)
                if qty<1:
                    skipped.append(dict(date=day,reason="Selected ask now exceeds allocation"))
                else:
                    cost=qty*(q["ask"]*100+fee)
                    p=dict(**q,qty=qty,cost=cost,before=cash,index=i,entry=day,signal=prior_day,pending=None)
                    cash-=cost
        marked=0.0
        if p is not None:
            q=next(q for q in snapshot if q["contract"]==p["contract"])
            marked=p["qty"]*(q["bid"]*100-fee)
            change=marked/p["cost"]-1
            p["pending"]="profit_close_signal" if change>=.15 else "loss_close_signal" if change<=-.25 else "underlying_floor" if row.close<row.floor else None
        curve.append(dict(date=day,cash=cash,position_liquidation_estimate=marked,equity=cash+marked))
    if not curve or p is not None:
        raise ValueError("Incomplete simulation")
    columns=["contract","underlying","signal_date","entry_date","exit_date","contracts","entry_premium","exit_premium","entry_cost","net_proceeds","total_fees","pnl","return_pct","outcome","exit_reason","equity_before","equity_after","holding_sessions","provider","entry_snapshot","exit_snapshot"]
    t,e=pd.DataFrame(trades,columns=columns),pd.DataFrame(curve)
    wins,losses=t.loc[t.pnl>0,"pnl"],t.loc[t.pnl<0,"pnl"]
    baseline=pd.Series([2000.0]+e.equity.tolist())
    m=dict(starting_equity=2000.0,final_equity=float(cash),equity_change=float(cash-2000),return_pct=100*(cash/2000-1),trades=len(t),wins=len(wins),losses=len(losses),flat=int((t.pnl==0).sum()),win_rate_pct=100*len(wins)/len(t) if len(t) else None,average_net_pnl=float(t.pnl.mean()) if len(t) else None,best_trade=float(t.pnl.max()) if len(t) else None,worst_trade=float(t.pnl.min()) if len(t) else None,total_fees=float(t.total_fees.sum()),max_drawdown_pct=float((baseline/baseline.cummax()-1).min()*100),profit_factor=float(wins.sum()/abs(losses.sum())) if len(losses) else None,skipped_signals=len(skipped),warning=WARNING)
    if abs(float(t.pnl.sum())-(cash-2000))>1e-5:
        raise ValueError("Equity reconciliation failed")
    return t,e,pd.DataFrame(skipped,columns=["date","reason"]),m


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--symbol",default="SPY")
    parser.add_argument("--start",required=True)
    parser.add_argument("--end",required=True)
    parser.add_argument("--strategy",default="adaptive")
    parser.add_argument("--allocation",type=float,default=.25)
    parser.add_argument("--stock-feed",choices=["iex","sip"],default="iex")
    args=parser.parse_args()
    out=Path("results")
    out.mkdir(exist_ok=True)
    quotes=Onclick()
    config={**vars(args),"starting_equity":2000,"execution":"next-session EOD ask/bid","options_provider":"onclickmedia","stock_provider":"alpaca","routing_reason":"Alpaca adapter has no historical bid/ask capability; route EOD quote runs to OnclickMedia","git_sha":os.getenv("GITHUB_SHA","local")}
    try:
        t,e,s,m=simulate(legacy.Alpaca(),quotes,args.symbol,args.start,args.end,args.strategy,args.allocation,args.stock_feed)
        t.to_csv(out/"trades.csv",index=False)
        e.to_csv(out/"equity.csv",index=False)
        s.to_csv(out/"skipped_signals.csv",index=False)
        (out/"summary.json").write_text(json.dumps(dict(config=config,metrics=m),indent=2,allow_nan=False))
        text=legacy.report(t,m,config).replace(legacy.WARNING,WARNING).replace("# Alpaca options backtest","# EOD quote options backtest")
        (out/"report.md").write_text(text)
    except Exception as exc:
        (out/"report.md").write_text("# EOD backtest failed\n\nNo valid final outcome.\n\n"+str(exc))
        raise SystemExit("EOD quote backtest failed; inspect report artifact") from None
    finally:
        (out/"quote_provenance.json").write_text(json.dumps(quotes.audit,indent=2))

if __name__=="__main__":
    main()
