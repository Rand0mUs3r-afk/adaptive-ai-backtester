"""Watchlist-only, shared-$2,000, rule-scored EOD options research."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import pandas as pd
import alpaca_backtest as alpaca
import onclick_backtest as eod
from engine import features, signal


def read_watchlist(path="watchlist.txt"):
    text=Path(path).read_text()
    mode,top,roots,pins="manual",5,[],{}
    for raw in text.splitlines():
        line=raw.split("#",1)[0].strip().upper()
        if not line:
            continue
        if line.startswith("MODE="):
            mode=line.split("=",1)[1].lower()
            continue
        if line.startswith("TOP="):
            top=int(line.split("=",1)[1])
            continue
        compact=line.replace("-", "").replace(" ", "")
        match=re.fullmatch(r"([A-Z]{1,5})(\d{6})C(\d{8})",compact)
        if re.fullmatch(r"[A-Z]{1,5}",line):
            root=line
            pins[root]=None
        elif match:
            root=match.group(1)
            pd.to_datetime(match.group(2),format="%y%m%d",errors="raise")
            if root not in pins:
                pins[root]=set()
            if pins[root] is not None:
                pins[root].add(compact)
        else:
            raise ValueError("Unsupported watchlist entry: "+line+"; use underlying tickers or standard call symbols")
        if root not in roots:
            roots.append(root)
    if mode not in ("manual","active") or not 1<=top<=10 or not 1<=len(roots)<=10:
        raise ValueError("Watchlist needs MODE=manual/active, TOP=1..10 and 1..10 underlying roots")
    return roots,pins,mode,top,text


def assess(row):
    scores={name:0.0 for name in ("breakout","momentum","reversion","blend","adaptive")}
    if pd.isna(row.slow):
        return None,0.0,scores
    trend=bool(row.trending)
    if signal(row,"breakout"):
        scores["breakout"]=65+10*trend+10*bool(row.volume>=1.5*row.vavg)
    if signal(row,"momentum"):
        scores["momentum"]=60+15*trend+5*bool(20<=row.k<=80)
    if signal(row,"reversion"):
        scores["reversion"]=60+15*(not trend)
    if signal(row,"blend"):
        scores["blend"]=min(90,max(scores.values())+3)
    if signal(row,"adaptive"):
        scores["adaptive"]=max(scores["breakout"],scores["momentum"]) if trend else scores["reversion"]
    chosen=max(scores,key=scores.get)
    return (chosen if scores[chosen]>=65 else None),scores[chosen],scores


def active_subset(client,frames,roots,pins,start,top):
    ranks=[]
    for root in roots:
        past=frames[root][frames[root].date<start]
        if past.empty:
            raise ValueError("No prior session for activity ranking")
        row=past.iloc[-1]
        day=row.date.date().isoformat()
        contracts=[c["contract"] for c in client.candidates(root,day,float(row.close)) if pins[root] is None or c["contract"] in pins[root]]
        bars=client.bars(contracts,day,day) if contracts else pd.DataFrame()
        volume=float(bars.volume.sum()) if len(bars) else 0.0
        ranks.append(dict(ticker=root,as_of=day,eligible_call_volume=volume))
    ranks.sort(key=lambda r:(-r["eligible_call_volume"],r["ticker"]))
    chosen=[r["ticker"] for r in ranks if r["eligible_call_volume"]>0][:top]
    if not chosen:
        raise ValueError("No positive historical eligible-call volume in watchlist candidate pool")
    return chosen,ranks


def simulate(client,quotes,roots,pins,start,end,allocation=.25,mode="manual",top=5,stock_feed="iex"):
    start,end=pd.Timestamp(start),pd.Timestamp(end)
    if start>end or end.date()>=pd.Timestamp.now(tz="America/New_York").date() or (end-start).days>180 or not 0<allocation<=1:
        raise ValueError("Use completed dates up to 180 days and allocation in (0,1]")
    frames={}
    for root in roots:
        f=features(client.bars([root],start-pd.Timedelta(days=150),end,stock=True,stock_feed=stock_feed)).sort_values("date")
        f["date"]=pd.to_datetime(f.date).dt.normalize()
        frames[root]=f.reset_index(drop=True)
    roots,ranks=active_subset(client,frames,roots,pins,start,top) if mode=="active" else (roots,[])
    days=sorted(set(d for root in roots for d in frames[root].date if start<=d<=end))
    if not days:
        raise ValueError("No trading sessions in requested period")
    cash,p,trades,curve,audit,skips=2000.0,None,[],[],[],[]
    fee=.65
    for n,day in enumerate(days):
        date=day.date().isoformat()
        current,previous={},{}
        for root in roots:
            f=frames[root]
            indices=f.index[f.date==day].tolist()
            if len(indices)!=1 or indices[0]==0:
                raise ValueError("Missing current/prior stock session for "+root+" "+date)
            i=indices[0]
            current[root],previous[root]=f.iloc[i],f.iloc[i-1]
            if pd.isna(previous[root].slow):
                raise ValueError("Insufficient warmup for "+root)
        candidates=[]
        for root in roots:
            setup,score,scores=assess(previous[root])
            audit.append(dict(date=date,ticker=root,setup=setup,quality_score=score,all_setup_scores=json.dumps(scores),position_open=p is not None))
            if setup:
                candidates.append((root,setup,score))
        candidates.sort(key=lambda item:(-item[2],item[0],item[1]))
        final,closed=n==len(days)-1,False
        snapshot=None
        if p is not None:
            snapshot=quotes.chain(p["root"],date)
            matches=[q for q in snapshot if q["contract"]==p["contract"]]
            if len(matches)!=1:
                raise ValueError("Missing held-contract EOD quote; no provider substitution")
            q=matches[0]
            reason="end_of_test" if final else p["pending"] or ("maximum_holding" if n-p["index"]>=10 else "pre_expiration" if day>=pd.Timestamp(p["expiry"])-pd.Timedelta(days=7) else None)
            if reason:
                proceeds=p["qty"]*(q["bid"]*100-fee)
                cash+=proceeds
                pnl=proceeds-p["cost"]
                trades.append(dict(contract=p["contract"],underlying=p["root"],setup=p["setup"],quality_score=p["score"],signal_date=p["signal"],entry_date=p["entry"],exit_date=date,contracts=p["qty"],entry_premium=p["ask"],exit_premium=q["bid"],entry_cost=p["cost"],net_proceeds=proceeds,total_fees=2*fee*p["qty"],pnl=pnl,return_pct=100*pnl/p["cost"],outcome="WIN" if pnl>0 else "LOSS" if pnl<0 else "FLAT",exit_reason=reason,equity_before=p["before"],equity_after=cash,holding_sessions=n-p["index"],provider="onclickmedia"))
                p,closed=None,True
        if p is None and not closed and not final:
            for root,setup,score in candidates:
                prior=previous[root]
                prior_day=prior.date.date().isoformat()
                chain=quotes.chain(root,prior_day)
                eligible=[q for q in chain if (pins[root] is None or q["contract"] in pins[root]) and 30<=(pd.Timestamp(q["expiry"])-prior.date).days<=60 and abs(q["strike"]/prior.close-1)<=.1 and eod.quantity(q["ask"],cash,allocation)>0]
                eligible.sort(key=lambda q:(q["expiry"],abs(q["strike"]-prior.close),q["contract"]))
                if not eligible:
                    skips.append(dict(date=date,ticker=root,setup=setup,reason="No eligible affordable prior-snapshot call"))
                    continue
                snapshot=quotes.chain(root,date)
                found=[q for q in snapshot if q["contract"]==eligible[0]["contract"]]
                if len(found)!=1:
                    raise ValueError("Missing selected entry contract; no hindsight substitution")
                q=found[0]
                qty=eod.quantity(q["ask"],cash,allocation)
                if qty<1:
                    skips.append(dict(date=date,ticker=root,setup=setup,reason="Current ask exceeds allocation"))
                    continue
                cost=qty*(q["ask"]*100+fee)
                p=dict(**q,root=root,setup=setup,score=score,qty=qty,cost=cost,before=cash,index=n,entry=date,signal=prior_day,pending=None)
                cash-=cost
                break
        marked=0.0
        if p is not None:
            q=next(q for q in snapshot if q["contract"]==p["contract"])
            marked=p["qty"]*(q["bid"]*100-fee)
            change=marked/p["cost"]-1
            row=current[p["root"]]
            p["pending"]="profit_close_signal" if change>=.15 else "loss_close_signal" if change<=-.25 else "underlying_floor" if row.close<row.floor else None
        curve.append(dict(date=date,cash=cash,equity=cash+marked,held_ticker=p["root"] if p else ""))
    cols=["contract","underlying","setup","quality_score","signal_date","entry_date","exit_date","contracts","entry_premium","exit_premium","entry_cost","net_proceeds","total_fees","pnl","return_pct","outcome","exit_reason","equity_before","equity_after","holding_sessions","provider"]
    t,e=pd.DataFrame(trades,columns=cols),pd.DataFrame(curve)
    baseline=pd.Series([2000.0]+e.equity.tolist())
    wins,losses=t.loc[t.pnl>0,"pnl"],t.loc[t.pnl<0,"pnl"]
    metrics=dict(starting_equity=2000.0,final_equity=float(cash),equity_change=float(cash-2000),return_pct=100*(cash/2000-1),trades=len(t),wins=len(wins),losses=len(losses),win_rate_pct=100*len(wins)/len(t) if len(t) else None,average_net_pnl=float(t.pnl.mean()) if len(t) else None,total_fees=float(t.total_fees.sum()),max_drawdown_pct=float((baseline/baseline.cummax()-1).min()*100),profit_factor=float(wins.sum()/abs(losses.sum())) if len(losses) else None,skipped_signals=len(skips),scoring="Fixed setup-quality heuristic; NOT a win probability")
    if p is not None or abs(float(t.pnl.sum())-(cash-2000))>1e-5:
        raise ValueError("Portfolio reconciliation failed")
    return t,e,pd.DataFrame(audit),pd.DataFrame(skips,columns=["date","ticker","setup","reason"]),metrics,roots,ranks


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--start",required=True)
    parser.add_argument("--end",required=True)
    parser.add_argument("--allocation",type=float,default=.25)
    parser.add_argument("--stock-feed",choices=["iex","sip"],default="iex")
    args=parser.parse_args()
    out=Path("results")
    out.mkdir(exist_ok=True)
    q=eod.Onclick()
    try:
        roots,pins,mode,top,text=read_watchlist()
        t,e,a,s,m,resolved,ranks=simulate(alpaca.Alpaca(),q,roots,pins,args.start,args.end,args.allocation,mode,top,args.stock_feed)
        config={**vars(args),"watchlist_mode":mode,"resolved_tickers":resolved,"activity_ranking":ranks,"watchlist_sha256":hashlib.sha256(text.encode()).hexdigest(),"starting_equity":2000,"shared_portfolio":True,"scoring":"heuristic, not probability","options_source":"onclickmedia EOD raw bid/ask","git_sha":os.getenv("GITHUB_SHA","local")}
        for frame,name in ((t,"trades"),(e,"equity"),(a,"setup_audit"),(s,"skipped_signals")):
            frame.to_csv(out/(name+".csv"),index=False)
        (out/"watchlist_used.txt").write_text(text)
        (out/"resolved_watchlist.txt").write_text("\n".join(resolved)+"\n")
        (out/"summary.json").write_text(json.dumps(dict(config=config,metrics=m),indent=2,allow_nan=False))
        report=alpaca.report(t,m,config).replace(alpaca.WARNING,eod.WARNING).replace("# Alpaca options backtest","# Watchlist shared-portfolio backtest")
        report+="\n## Selected setups (scores are not probabilities)\n\n|Contract|Entry|Setup|Quality score|\n|---|---|---|---:|\n"
        for r in t.itertuples():
            report+=f"|{r.contract}|{r.entry_date}|{r.setup}|{r.quality_score}|\n"
        (out/"report.md").write_text(report)
    except Exception as exc:
        (out/"report.md").write_text("# Watchlist backtest failed\n\nNo valid final outcome.\n\n"+str(exc))
        raise SystemExit("Watchlist backtest failed; inspect report artifact") from None
    finally:
        (out/"quote_provenance.json").write_text(json.dumps(q.audit,indent=2))

if __name__=="__main__":
    main()
