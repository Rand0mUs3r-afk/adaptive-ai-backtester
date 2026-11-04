"""One-dispatch, fixed-grid strategy research. No orders and no profit claims."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd
from unittest.mock import patch
import engine
import hardened_research as h
from alpaca_backtest import Alpaca
from auto_watchlist import choose_feed
from watchlist_backtest import read_watchlist

NAMES = ("breakout","momentum","reversion","blend","adaptive","sma20_50_cross",
    "ema9_21_cross","macd_cross","rsi14_recovery","rsi2_pullback","donchian55",
    "bollinger_reentry","bollinger_breakout","keltner_breakout","stochastic_recovery",
    "roc20_trend","ema20_pullback","trend_vote","reversion_vote","regime_mix","volume_breakout")
NOTICE = "EXPERIMENTAL LONG-CALL ADAPTATIONS, not proven profitable systems. Partial options chains; EOD ask/bid estimates; same guarded exits for every entry rule. Independent $2,000 accounts per symbol/rule/allocation/phase. Multiple-testing and prior data inspection bias remain. No paper or live orders."


def cross(a,b):
    return (a>b)&(a.shift(1)<=b.shift(1))


def rsi(close,n):
    change=close.diff()
    up=change.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    down=(-change.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    result=100-100/(1+up/down.replace(0,np.nan))
    result=result.mask((down==0)&(up>0),100).mask((up==0)&(down>0),0)
    return result.mask((up==0)&(down==0),50)


def signals(raw):
    f=engine.features(raw).sort_values("date").reset_index(drop=True)
    c=f.close
    sma20,sma50,sma200=(c.rolling(n,min_periods=n).mean() for n in (20,50,200))
    ema9,ema12,ema20,ema21,ema26=(c.ewm(span=n,adjust=False,min_periods=n).mean() for n in (9,12,20,21,26))
    r14,r2=rsi(c,14),rsi(c,2)
    macd=ema12-ema26
    macd_signal=macd.ewm(span=9,adjust=False,min_periods=9).mean()
    tr=pd.concat([f.high-f.low,(f.high-c.shift()).abs(),(f.low-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/20,adjust=False,min_periods=20).mean()
    values={s:f.apply(lambda row:engine.signal(row,s),axis=1) for s in NAMES[:5]}
    values.update(sma20_50_cross=cross(sma20,sma50),ema9_21_cross=cross(ema9,ema21),
        macd_cross=cross(macd,macd_signal)&(c>sma50),
        rsi14_recovery=(r14>30)&(r14.shift()<=30),
        rsi2_pullback=(r2<10)&(c>sma200),
        donchian55=c>f.high.rolling(55,min_periods=55).max().shift(),
        bollinger_reentry=(c>f.lower)&(c.shift()<=f.lower.shift()),
        bollinger_breakout=(c>f.upper)&(c.shift()<=f.upper.shift()),
        keltner_breakout=cross(c,ema20+2*atr),
        stochastic_recovery=(f.k>20)&(f.k.shift()<=20)&(c>sma50),
        roc20_trend=(c.pct_change(20)>0)&(c>sma50),
        ema20_pullback=cross(c,ema20)&(ema20>sma50),
        volume_breakout=f.breakout&(f.volume>1.5*f.vavg))
    values["trend_vote"]=(pd.concat([values["breakout"],values["momentum"],values["macd_cross"]],axis=1).sum(axis=1)>=2)
    values["reversion_vote"]=(pd.concat([values["rsi14_recovery"],values["bollinger_reentry"],values["stochastic_recovery"]],axis=1).sum(axis=1)>=2)
    values["regime_mix"]=values["trend_vote"].where(sma50>sma200,values["reversion_vote"])
    # Uniform 200-session warmup prevents comparing rules on unequal indicator readiness.
    ready=sma200.notna()
    for name in NAMES:
        f["sig_"+name]=(values[name].fillna(False)&ready).astype(bool)
    return f


def records(frame):
    return json.loads(frame.to_json(orient="records",date_format="iso"))


def windows(start,split,end):
    a,b,c=map(pd.Timestamp,(start,split,end))
    if any(d.tzinfo or d!=d.normalize() or pd.isna(d) for d in (a,b,c)) or not a<b<c:
        raise ValueError("Invalid chronological windows")
    if (c-a).days>180 or c.date()>=pd.Timestamp.now(tz="America/New_York").date():
        raise ValueError("Use completed dates spanning at most 180 calendar days")
    return [("development",a,b-pd.Timedelta(days=1)),("validation",b,c)]


class SuiteQuotes(h.BoundedQuotes):
    shared={}
    failures={}
    network=[]

    def __init__(self,frames):
        super().__init__(frames)
        self.cache=self.shared

    def fetch(self,ticker,day,strike):
        key=(ticker,day,strike)
        if key in self.failures:
            raise h.ResearchError("previous_request_failed_no_retry_storm")
        if key not in self.cache and len(self.network)>=800:
            raise h.ResearchError("suite_symbol_request_budget")
        before=len(self.audit)
        try:
            return super().fetch(ticker,day,strike)
        except Exception:
            self.failures[key]=True
            raise
        finally:
            self.network.extend(self.audit[before:])


def checkpoint(path,payload):
    temporary=path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload,indent=2,allow_nan=False))
    temporary.replace(path)


def run(args):
    roots,pins,mode,_,_=read_watchlist()
    if mode!="manual" or any(v is not None for v in pins.values()) or args.symbol not in roots:
        raise ValueError("Use an underlying ticker from the manual watchlist")
    periods=windows(args.start,args.split,args.end)
    out=Path("suite_results")
    out.mkdir(exist_ok=True)
    payload=dict(warning=NOTICE,config=vars(args),strategy_names=list(NAMES),allocations=[.10,.25],
        git_sha=os.getenv("GITHUB_SHA","local"),expected_runs=len(NAMES)*4,runs=[],provider_audit=[])
    path=out/(args.symbol+".json")
    checkpoint(path,payload)
    try:
        client=Alpaca()
        feed,attempts=choose_feed(client,[args.symbol],args.start,args.end)
        payload["stock_feed"]=dict(selected=feed,attempts=attempts)
        if feed is None:
            raise ValueError("No stock coverage")
        raw=client.bars([args.symbol],pd.Timestamp(args.start)-pd.Timedelta(days=400),args.end,stock=True,stock_feed=feed)
        payload["stock_data_sha256"]=hashlib.sha256(raw.to_json(orient="records").encode()).hexdigest()
        f=signals(raw)
        for _,start,end in periods:
            prior=f[f.date<start]
            if prior.empty or len(prior)<200 or f[(f.date>=start)&(f.date<=end)].shape[0]<2:
                raise ValueError("Insufficient indicator warmup or phase sessions")
        class Stocks:
            def bars(self,symbols,start,end,**kwargs):
                if symbols!=[args.symbol]:
                    raise ValueError("Unexpected stock symbol")
                return f[(f.date>=pd.Timestamp(start))&(f.date<=pd.Timestamp(end))].copy()
        SuiteQuotes.shared,SuiteQuotes.failures,SuiteQuotes.network={},{},[]
        with patch.dict(os.environ,{"RESEARCH_MODE":"guarded","MAX_SPREAD_FRACTION":"0.20","MAX_ENTRY_ASK_INCREASE":"0.25"}), patch.object(h,"features",side_effect=lambda x:x):
            for phase,start,end in periods:
                for name in NAMES:
                    mask=(f.date>=start)&(f.date<=end)
                    fingerprint=hashlib.sha256(f.loc[mask,"sig_"+name].to_numpy().tobytes()).hexdigest()
                    for allocation in (.10,.25):
                        q=SuiteQuotes({args.symbol:f})
                        result=dict(ticker=args.symbol,phase=phase,strategy=name,allocation=allocation,
                            signal_fingerprint=fingerprint,status="failed")
                        try:
                            with patch.object(h,"signal",side_effect=lambda row,unused,n=name:bool(row["sig_"+n])):
                                t,e,s,m=h.simulate(Stocks(),q,args.symbol,str(start.date()),str(end.date()),"adaptive",allocation,feed)
                            for frame in (t,s):
                                frame["strategy"]=name
                            m["warning"]=NOTICE
                            result.update(status="completed_with_trades" if len(t) else "completed_no_trades",
                                metrics=m,trades=records(t),equity=records(e),skipped_entries=records(s),
                                rejection_counts=dict(Counter(s.reason)),event_counts=dict(Counter(x["event"] for x in q.events)))
                        except Exception as exc:
                            result["error_code"]=str(exc) if isinstance(exc,h.ResearchError) else type(exc).__name__
                            result["request_audit"]=q.audit
                        payload["runs"].append(result)
                        payload["provider_audit"]=SuiteQuotes.network
                        checkpoint(path,payload)
    except Exception as exc:
        payload["setup_error"]=type(exc).__name__
        checkpoint(path,payload)
        raise
    if any(r["status"]=="failed" for r in payload["runs"]):
        raise SystemExit("Incomplete experiments; checkpoints preserved")


def merge(folder):
    files=sorted(Path(folder).rglob("*.json"))
    bundles=[json.loads(p.read_text()) for p in files]
    roots=read_watchlist()[0]
    by_root={b.get("config",{}).get("symbol"):b for b in bundles if "runs" in b}
    configs={(b["config"]["start"],b["config"]["split"],b["config"]["end"]) for b in by_root.values()}
    if len(configs)>1 or any(b.get("strategy_names")!=list(NAMES) for b in by_root.values()):
        raise ValueError("Mismatched suite manifests; refusing mixed experiments")
    rows=[r for b in by_root.values() for r in b["runs"]]
    groups=[]
    for name in NAMES:
        for allocation in (.10,.25):
            group=dict(strategy=name,allocation=allocation)
            for phase in ("development","validation"):
                part=[r for r in rows if r["strategy"]==name and r["allocation"]==allocation and r["phase"]==phase]
                done=[r for r in part if r["status"].startswith("completed")]
                complete=len(done)==len(roots) and len(part)==len(roots)
                group[phase]=dict(complete=complete,completed_symbols=len(done),
                    trades=sum(r["metrics"]["trades"] for r in done),
                    mean_return_pct=float(np.mean([r["metrics"]["return_pct"] for r in done])) if complete else None,
                    worst_account_drawdown_pct=min((r["metrics"]["max_drawdown_pct"] for r in done),default=None))
            groups.append(group)
    # Freeze research ranking using development only; validation never chooses the winner.
    eligible=[g for g in groups if g["development"]["complete"] and g["development"]["trades"]>=20 and g["development"]["mean_return_pct"]>0]
    eligible.sort(key=lambda g:(-g["development"]["mean_return_pct"],g["strategy"],g["allocation"]))
    winner=eligible[0] if eligible else None
    out=Path("suite_final")
    out.mkdir(exist_ok=True)
    checkpoint(out/"experiment_bundle.json",dict(warning=NOTICE,expected_symbols=roots,
        missing_symbols=sorted(set(roots)-set(by_root)),comparisons=groups,
        development_selected=winner,selection_rule="Complete symbols, >=20 development trades and positive mean development return; rank development only; not statistical validation",symbol_results=by_root))
    flat=[dict(strategy=g["strategy"],allocation=g["allocation"],phase=phase,**g[phase]) for g in groups for phase in ("development","validation")]
    pd.DataFrame(flat).to_csv(out/"leaderboard.csv",index=False)
    report="# Batch strategy research\n\n"+NOTICE+"\n\n"
    report+="No qualifying development winner.\n" if winner is None else "Development-selected configuration: "+winner["strategy"]+" / "+str(winner["allocation"])+". Not approved for deployment.\n"
    report+="\nUpload experiment_bundle.json only. Failed runs are not converted to zero returns. Trade-count cutoff is a reporting heuristic, not proof of an edge.\n"
    (out/"report.md").write_text(report)
    if set(roots)-set(by_root) or any(not g[p]["complete"] for g in groups for p in ("development","validation")):
        raise SystemExit("Incomplete suite; inspect experiment bundle")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--symbol")
    parser.add_argument("--start",default="2026-08-03")
    parser.add_argument("--split",default="2026-10-01")
    parser.add_argument("--end",default="2026-10-30")
    parser.add_argument("--merge")
    args=parser.parse_args()
    merge(args.merge) if args.merge else run(args)


if __name__=="__main__":
    main()
