"""One chronological $2,000 cash portfolio. Research only; no orders."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
from unittest.mock import patch
import pandas as pd

INITIAL=2000.
FEE=.65
ALLOCATION=.10
WARNING="Shared-cash post-hoc research, not deployment approval. Daily ask/bid estimates and partial chains; timestamps/corporate actions not modeled. Inspected dates are not fresh validation. Missing required quotes invalidate the whole portfolio."


class PortfolioError(ValueError):pass


def simulate(frames,quotes,start,end,names,entry_quality,strikes,state,checkpoint=None):
    start,end=pd.Timestamp(start),pd.Timestamp(end)
    if not frames or len(set(names))!=len(names) or not names:raise PortfolioError("invalid_universe")
    prepared={root:f.sort_values("date").reset_index(drop=True).copy() for root,f in frames.items()}
    sessions=None;indices={};priors={}
    for root,f in prepared.items():
        f["date"]=pd.to_datetime(f.date).dt.normalize()
        if f.date.duplicated().any() or set(f.symbol)!={root}:raise PortfolioError("stock_identity_or_duplicate")
        selected=f.index[(f.date>=start)&(f.date<=end)].tolist()
        days=f.loc[selected,"date"].tolist()
        if len(selected)<2 or selected[0]<200:raise PortfolioError("insufficient_warmup_or_sessions")
        if sessions is not None and days!=sessions:raise PortfolioError("inconsistent_stock_sessions")
        sessions=days
        indices[root]={f.iloc[i].date.date().isoformat():i for i in selected}
        priors[root]=[f.iloc[i-1].date for i in selected]
    if any(v!=next(iter(priors.values())) for v in priors.values()):raise PortfolioError("inconsistent_previous_sessions")
    state.update(status="running",starting_equity=INITIAL,cash=INITIAL,positions={},trades=[],equity=[],skipped=[],signals=Counter())
    def reject(day,root,name,reason):state["skipped"].append(dict(date=day,ticker=root,strategy=name,reason=reason))
    def fetch(root,day,strike):
        rows=quotes[root].fetch(root,day,strike)
        seen=set()
        if not isinstance(rows,list):raise PortfolioError("invalid_quote_response")
        for q in rows:
            if q["date"]!=day or q["strike"]!=strike or q["contract"] in seen or entry_quality(q,1.)=="invalid_quote":
                raise PortfolioError("quote_identity_duplicate_or_invalid")
            seen.add(q["contract"])
        return rows
    def exact(root,day,p,stage):
        matches=[q for q in fetch(root,day,p["strike"]) if q["contract"]==p["contract"]]
        if len(matches)!=1:raise PortfolioError("missing_"+stage+"_quote:"+p["contract"]+":"+day)
        return matches[0]
    for n,stamp in enumerate(sessions):
        day=stamp.date().isoformat();final=n==len(sessions)-1
        budget_equity=state["equity"][-1]["equity"] if state["equity"] else INITIAL
        current={r:f.iloc[indices[r][day]] for r,f in prepared.items()}
        prior={r:f.iloc[indices[r][day]-1] for r,f in prepared.items()}
        held_quotes={};closed=set()
        for root,p in list(state["positions"].items()):
            q=exact(root,day,p,"held_position");held_quotes[root]=q
            reason="end_of_test" if final else p["pending"] or ("maximum_holding" if n-p["index"]>=10 else "pre_expiration" if stamp>=pd.Timestamp(p["expiry"])-pd.Timedelta(days=7) else None)
            if reason:
                proceeds=p["qty"]*(q["bid"]*100-FEE)
                state["cash"]+=proceeds
                pnl=proceeds-p["cost"]
                state["trades"].append(dict(ticker=root,strategy=p["strategy"],supporting_signals=p["supporting_signals"],contract=p["contract"],
                    signal_date=p["signal"],entry_date=p["entry"],exit_date=day,contracts=p["qty"],entry_premium=p["ask"],exit_premium=q["bid"],
                    entry_cost=p["cost"],net_proceeds=proceeds,total_fees=2*FEE*p["qty"],pnl=pnl,outcome="WIN" if pnl>0 else "LOSS" if pnl<0 else "FLAT",exit_reason=reason))
                del state["positions"][root];closed.add(root)
        choices=[]
        if not final:
            for root in sorted(prepared):
                triggered=[name for name in names if bool(prior[root]["sig_"+name])]
                for name in triggered:state["signals"][name]+=1
                if not triggered:continue
                name=triggered[0]
                if root in state["positions"] or root in closed:
                    reject(day,root,name,"existing_position_or_closed_today");continue
                choices.append((names.index(name),root,name,triggered))
        for _,root,name,triggered in sorted(choices):
            before=prior[root];prior_day=before.date.date().isoformat()
            reserved=sum(p["qty"]*FEE for p in state["positions"].values())
            budget=min(max(0.,budget_equity)*ALLOCATION,max(0.,state["cash"]-reserved))
            candidates=[]
            for strike in strikes(float(before.close)):candidates.extend(fetch(root,prior_day,strike))
            stages=[("no_returned_quotes",lambda q:True),
                ("no_30_60_dte_quotes",lambda q:30<=(pd.Timestamp(q["expiry"])-before.date).days<=60),
                ("no_strikes_within_10_percent",lambda q:abs(q["strike"]/before.close-1)<=.1),
                ("no_entry_quality_quotes",lambda q:entry_quality(q,.20) is None),
                ("premium_exceeds_portfolio_budget",lambda q:q["ask"]*100+FEE<=budget)]
            for reason,predicate in stages:
                candidates=[q for q in candidates if predicate(q)]
                if not candidates:reject(day,root,name,reason);break
            if not candidates:continue
            candidates.sort(key=lambda q:(q["expiry"],abs(q["strike"]-before.close),q["contract"]))
            chosen=candidates[0];q=exact(root,day,chosen,"entry_execution")
            reason=entry_quality(q,.20)
            if reason:reject(day,root,name,"execution_"+reason);continue
            if q["ask"]>chosen["ask"]*1.25:reject(day,root,name,"entry_ask_increase_exceeds_limit");continue
            if (pd.Timestamp(q["expiry"])-stamp).days<=7:reject(day,root,name,"insufficient_expiry_buffer");continue
            unit=q["ask"]*100+FEE
            qty=int(min(budget//unit,max(0.,state["cash"]-reserved)//(unit+FEE)))
            if qty<1:reject(day,root,name,"execution_budget_or_exit_fee_reserve");continue
            cost=qty*unit;state["cash"]-=cost
            state["positions"][root]=dict(q,qty=qty,cost=cost,index=n,entry=day,signal=prior_day,pending=None,strategy=name,supporting_signals=triggered)
            held_quotes[root]=q
        marked=0.
        for root,p in state["positions"].items():
            q=held_quotes[root];value=p["qty"]*(q["bid"]*100-FEE);marked+=value
            change=value/p["cost"]-1
            p["pending"]="profit_close_signal" if change>=.15 else "loss_close_signal" if change<=-.25 else "underlying_floor" if current[root].close<current[root].floor else None
        reserve=sum(p["qty"]*FEE for p in state["positions"].values())
        if state["cash"]+1e-6<reserve or not math.isfinite(state["cash"]+marked):raise PortfolioError("cash_or_fee_reserve_violation")
        state["equity"].append(dict(date=day,cash=state["cash"],reserved_exit_fees=reserve,positions=len(state["positions"]),position_liquidation_estimate=marked,equity=state["cash"]+marked))
        if checkpoint:checkpoint(state)
        print(f"Portfolio {day}: cash={state['cash']:.2f}; equity={state['cash']+marked:.2f}; positions={len(state['positions'])}; closed trades={len(state['trades'])}",flush=True)
    if state["positions"] or abs(state["cash"]-INITIAL-sum(t["pnl"] for t in state["trades"]))>1e-5:raise PortfolioError("portfolio_reconciliation_failed")
    curve=pd.Series([INITIAL]+[r["equity"] for r in state["equity"]])
    trades=state["trades"]
    state.update(status="completed",metrics=dict(starting_equity=INITIAL,final_equity=state["cash"],net_pnl=state["cash"]-INITIAL,return_pct=100*(state["cash"]/INITIAL-1),
        total_trades=len(trades),winning_trades=sum(t["pnl"]>0 for t in trades),lost_trades=sum(t["pnl"]<0 for t in trades),flat_trades=sum(t["pnl"]==0 for t in trades),
        total_fees=sum(t["total_fees"] for t in trades),max_drawdown_pct=float((curve/curve.cummax()-1).min()*100)))
    return state


def main():
    import strategy_suite as suite
    import shortlist_research as shortlist
    import expanded_universe as universe
    import research_progress as progress
    import five_ticker_scope as five
    import hardened_research as h
    import research_repairs as repairs
    p=argparse.ArgumentParser()
    p.add_argument("--scope",choices=["5","requested","full"],default="requested")
    p.add_argument("--start",default="2026-08-03");p.add_argument("--split",default="2026-10-01");p.add_argument("--end",default="2026-10-30")
    args=p.parse_args();suite.windows(args.start,args.split,args.end)
    out=Path("portfolio_results");out.mkdir(exist_ok=True)
    state=dict(status="starting",warning=WARNING,config=vars(args),starting_equity=INITIAL,strategies=list(shortlist.NAMES),trades=[],equity=[],positions={})
    original=suite.checkpoint
    def plan_checkpoint(path,payload):
        if "planned_simulations" in payload:
            payload["planned_simulations"]=1;payload["simulations_per_symbol"]=None;payload["batches"]=[payload["eligible"]]
        payload["capital_model"]="One shared $2,000 account; no split reset"
        original(path,payload)
    original(out/"portfolio_bundle.json",state)
    quotes={}
    try:
        with patch.object(suite,"checkpoint",side_effect=plan_checkpoint):
            five.prepare(args) if args.scope=="5" else progress.prepare(args)
        manifest=json.loads(Path("universe.json").read_text());state["universe"]=manifest
        if any(c["status"]=="unverified_access_or_provider_error" for c in manifest["checks"]):raise PortfolioError("unverified_candidate_universe")
        roots=manifest["eligible"];client=suite.Alpaca()
        feed,attempts=suite.choose_feed(client,roots,args.start,args.end);state["stock_feed"]=dict(selected=feed,attempts=attempts)
        if feed is None:raise PortfolioError("no_stock_feed")
        raw=client.bars(roots,pd.Timestamp(args.start)-pd.Timedelta(days=400),args.end,stock=True,stock_feed=feed)
        state["stock_data_sha256"]=hashlib.sha256(raw.to_json(orient="records").encode()).hexdigest()
        frames={root:suite.signals(raw[raw.symbol==root].copy()) for root in roots}
        class Quotes(h.BoundedQuotes):
            def fetch(self,ticker,day,strike):
                key=(ticker,day,strike)
                if key not in self.cache:
                    cached=repairs.load_quote(key)
                    if cached:self.cache[key]=cached[0];self.disk_hits+=1
                if key not in self.cache and sum(len(q.audit) for q in quotes.values())>=4000:raise PortfolioError("portfolio_request_budget")
                before=len(self.audit);rows=super().fetch(ticker,day,strike)
                if len(self.audit)>before and rows:repairs.save_quote(key,rows)
                return rows
        for root in roots:
            quotes[root]=Quotes({root:frames[root]});quotes[root].disk_hits=0
        state["execution_policy"]=dict(initial_equity=INITIAL,allocation=.1,allocation_basis="prior-close portfolio equity capped by free cash; exit fees reserved",
            priority=list(shortlist.NAMES),tie_break="strategy priority, then ticker alphabetically; one position per ticker; no same-session reentry after exit",
            split_policy="No reset or forced close at split; positions/cash carry through",fees_per_contract_side=FEE,signal_timing="previous completed session; daily EOD ask/bid estimates")
        simulate(frames,quotes,args.start,args.end,shortlist.NAMES,h.entry_reason,h.limited.target_strikes,state,
            checkpoint=lambda payload:original(out/"portfolio_bundle.json",payload))
    except Exception as exc:
        state.update(status="incomplete",error_code=str(exc) if isinstance(exc,PortfolioError) else type(exc).__name__)
        state["metrics"]=dict(starting_equity=INITIAL,final_equity=None,net_pnl=None,total_trades=len(state["trades"]),winning_trades=sum(t["pnl"]>0 for t in state["trades"]),lost_trades=sum(t["pnl"]<0 for t in state["trades"]))
    finally:
        state["quote_audits"]={root:dict(requests=q.audit,disk_hits=q.disk_hits) for root,q in quotes.items()}
        original(out/"portfolio_bundle.json",state)
        pd.DataFrame(state["trades"]).to_csv(out/"trades.csv",index=False)
        pd.DataFrame(state["equity"]).to_csv(out/"equity.csv",index=False)
        metrics=state.get("metrics",dict(starting_equity=INITIAL,final_equity=None,net_pnl=None,total_trades=0,winning_trades=0,lost_trades=0))
        text="# Single-account portfolio backtest\n\n"+WARNING+"\n\nStatus: "+state["status"]+".\n\nOne $2,000 starting balance for all tickers and strategies. No deposits, leverage, per-strategy replenishment, or reset at split. Priority follows the fixed shortlist, not observed returns.\n"
        if state["status"]!="completed":text+="\nRun incomplete: "+state.get("error_code","unknown")+". Closed-trade counts are partial; final equity/P&L are unknown.\n"
        text+="\n## Final account summary\n\n|Starting Equity|Final Equity|Net P&L|Total Trades|Winning Trades|Lost Trades|\n|---:|---:|---:|---:|---:|---:|\n"
        values=[metrics[k] for k in ("starting_equity","final_equity","net_pnl","total_trades","winning_trades","lost_trades")]
        text+="|"+"|".join("N/A" if v is None else str(round(v,2)) for v in values)+"|\n"
        (out/"report.md").write_text(text)
    if state["status"]!="completed":raise SystemExit("Shared portfolio incomplete; inspect portfolio_bundle.json")


if __name__=="__main__":main()
