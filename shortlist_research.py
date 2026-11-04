"""Focused research only: five post-hoc candidate setups, 10% allocation."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pandas as pd

VERSION="five-setup-shortlist-v1"
PRIMARY=("rsi14_recovery","reversion_vote")
SECONDARY=("ema9_21_cross","ema20_pullback","stochastic_recovery")
NAMES=PRIMARY+SECONDARY
ALLOCATION=.10
PHASES=("development","validation")
SPEC=dict(version=VERSION,primary=list(PRIMARY),secondary=list(SECONDARY),
    active_strategies=list(NAMES),allocations=[ALLOCATION],simulations_per_symbol=10,
    warning="Post-hoc research shortlist, not deployment approval. Previously inspected development/validation dates are not fresh evidence. Tiny trade samples and failed histories remain unresolved. Non-shortlisted entry rules are archived; existing composite definitions are unchanged.")


def freeze(payload):
    payload["shortlist"]=SPEC
    if "eligible" in payload:
        payload["simulations_per_symbol"]=10
        if "planned_simulations" in payload:payload["planned_simulations"]=len(payload["eligible"])*10


def validate_bundle(bundle,manifest):
    config=bundle.get("config",{})
    if config.get("symbol") not in manifest["eligible"] or any(config.get(k)!=v for k,v in manifest["config"].items()):
        raise ValueError("Ticker/date manifest mismatch")
    if bundle.get("shortlist")!=SPEC or bundle.get("strategy_names")!=list(NAMES) or bundle.get("allocations")!=[ALLOCATION] or bundle.get("expected_runs")!=10:
        raise ValueError("Refusing old or incompatible shortlist results")
    keys=[(r["phase"],r["strategy"],r["allocation"]) for r in bundle["runs"]]
    allowed={(phase,name,ALLOCATION) for phase in PHASES for name in NAMES}
    if len(keys)!=len(set(keys)) or not set(keys)<=allowed or any(r["ticker"]!=config["symbol"] for r in bundle["runs"]):
        raise ValueError("Duplicate or unauthorized experiment")


def run_symbol(suite,manifest,symbol):
    args=SimpleNamespace(symbol=symbol,**manifest["config"])
    periods=suite.windows(args.start,args.split,args.end)
    out=Path("suite_results");out.mkdir(exist_ok=True)
    path=out/(symbol+".json")
    payload=dict(warning=suite.NOTICE,config=vars(args),strategy_names=list(NAMES),allocations=[ALLOCATION],
        expected_runs=10,runs=[],provider_audit=[],git_sha=os.getenv("GITHUB_SHA","local"))
    suite.checkpoint(path,payload)
    try:
        client=suite.Alpaca()
        feed,attempts=suite.choose_feed(client,[symbol],args.start,args.end)
        payload["stock_feed"]=dict(selected=feed,attempts=attempts)
        if feed is None:raise ValueError("No stock coverage")
        raw=client.bars([symbol],pd.Timestamp(args.start)-pd.Timedelta(days=400),args.end,stock=True,stock_feed=feed)
        payload["stock_data_sha256"]=hashlib.sha256(raw.to_json(orient="records").encode()).hexdigest()
        frame=suite.signals(raw)
        for _,start,end in periods:
            if len(frame[frame.date<start])<200 or len(frame[(frame.date>=start)&(frame.date<=end)])<2:
                raise ValueError("Insufficient warmup or phase sessions")
        class Stocks:
            def bars(self,symbols,start,end,**kwargs):
                if symbols!=[symbol]:raise ValueError("Unexpected symbol")
                return frame[(frame.date>=pd.Timestamp(start))&(frame.date<=pd.Timestamp(end))].copy()
        suite.SuiteQuotes.shared,suite.SuiteQuotes.failures,suite.SuiteQuotes.network={},{},[]
        with patch.dict(os.environ,{"RESEARCH_MODE":"guarded","MAX_SPREAD_FRACTION":"0.20","MAX_ENTRY_ASK_INCREASE":"0.25"}),patch.object(suite.h,"features",side_effect=lambda x:x):
            for phase,start,end in periods:
                for name in NAMES:
                    quote=suite.SuiteQuotes({symbol:frame})
                    mask=(frame.date>=start)&(frame.date<=end)
                    result=dict(ticker=symbol,phase=phase,strategy=name,allocation=ALLOCATION,status="failed",
                        signal_fingerprint=hashlib.sha256(frame.loc[mask,"sig_"+name].to_numpy().tobytes()).hexdigest())
                    try:
                        with patch.object(suite.h,"signal",side_effect=lambda row,unused,n=name:bool(row["sig_"+n])):
                            trades,equity,skips,metrics=suite.h.simulate(Stocks(),quote,symbol,str(start.date()),str(end.date()),"adaptive",ALLOCATION,feed)
                        for data in (trades,skips):data["strategy"]=name
                        metrics["warning"]=suite.NOTICE
                        result.update(status="completed_with_trades" if len(trades) else "completed_no_trades",metrics=metrics,
                            trades=suite.records(trades),equity=suite.records(equity),skipped_entries=suite.records(skips),
                            rejection_counts=dict(Counter(skips.reason)),event_counts=dict(Counter(e["event"] for e in quote.events)))
                    except Exception as exc:
                        result["error_code"]=str(exc) if isinstance(exc,suite.h.ResearchError) else type(exc).__name__
                        result["request_audit"]=quote.audit
                    payload["runs"].append(result)
                    payload["provider_audit"]=suite.SuiteQuotes.network
                    suite.checkpoint(path,payload)
    except Exception as exc:
        payload["setup_error"]=type(exc).__name__
        suite.checkpoint(path,payload)
        raise
    if any(r["status"]=="failed" for r in payload["runs"]):raise SystemExit("Incomplete shortlist; checkpoints retained")


def merge(suite,universe,repairs,folder,manifest):
    bundles={}
    for path in sorted(Path(folder).rglob("*.json")):
        bundle=json.loads(path.read_text())
        if "runs" not in bundle:continue
        validate_bundle(bundle,manifest)
        symbol=bundle["config"]["symbol"]
        if symbol in bundles:raise ValueError("Duplicate ticker artifact")
        bundles[symbol]=bundle
    rows=[r for b in bundles.values() for r in b["runs"]]
    roots=manifest["eligible"]
    summaries=[];groups=[]
    for name in NAMES:
        group=dict(strategy=name,allocation=ALLOCATION,tier="primary" if name in PRIMARY else "secondary")
        for phase in PHASES:
            part=[r for r in rows if r["strategy"]==name and r["phase"]==phase]
            total=universe.totals(part,len(roots))
            summaries.append(dict(strategy=name,allocation=ALLOCATION,phase=phase,tier=group["tier"],**total))
            done=[r for r in part if r["status"].startswith("completed")]
            group[phase]=dict(complete=total["complete"],completed_symbols=len(done),trades=total["total_trades"],
                mean_return_pct=sum(r["metrics"]["return_pct"] for r in done)/len(roots) if total["complete"] else None,
                worst_account_drawdown_pct=min((r["metrics"]["max_drawdown_pct"] for r in done),default=None))
        groups.append(group)
    unknown=any(c["status"]=="unverified_access_or_provider_error" for c in manifest["checks"])
    candidates=[g for g in groups if not unknown and g["development"]["complete"] and g["development"]["trades"]>=20 and g["development"]["mean_return_pct"]>0]
    candidates.sort(key=lambda g:(-g["development"]["mean_return_pct"],g["strategy"]))
    missing=sorted(set(roots)-set(bundles))
    payload=dict(warning=suite.NOTICE,universe=manifest,expected_symbols=roots,missing_symbols=missing,comparisons=groups,
        capital_summary=summaries,development_selected=candidates[0] if candidates else None,universe_incomplete=unknown,
        selection_rule="Complete symbols, >=20 development trades, positive development mean return; development-only ranking; no deployment approval",
        symbol_summary={s:dict(status_counts=dict(Counter(r["status"] for r in b["runs"])),setup_error=b.get("setup_error"),stock_data_sha256=b.get("stock_data_sha256")) for s,b in bundles.items()},
        run_diagnostics=repairs.compact_diagnostics(bundles),
        trade_runs=[{k:v for k,v in r.items() if k not in ("equity","skipped_entries","request_audit")} for r in rows if r.get("trades")],
        failed_runs=[{k:v for k,v in r.items() if k!="request_audit"} for r in rows if r["status"]=="failed"],
        detail_location="Full equity/skip/provider histories remain in universe-batch artifacts.")
    out=Path("suite_final");out.mkdir(exist_ok=True)
    suite.checkpoint(out/"experiment_bundle.json",payload)
    pd.DataFrame(summaries).to_csv(out/"capital_summary.csv",index=False)
    pd.DataFrame([dict(strategy=g["strategy"],allocation=ALLOCATION,tier=g["tier"],phase=p,**g[p]) for g in groups for p in PHASES]).to_csv(out/"leaderboard.csv",index=False)
    text="# Shortlist strategy research\n\n"+suite.NOTICE+"\n\n"+SPEC["warning"]+"\n\n"
    text+="Primary: "+", ".join(PRIMARY)+". Secondary: "+", ".join(SECONDARY)+". All entries use 10% allocation; 25% setups are not run.\n\n"
    text+="No qualifying development winner.\n" if not candidates else "Development-selected: "+candidates[0]["strategy"]+". Not approved for deployment.\n"
    text+=f"\nTicker scope: {manifest['scope']}; candidates: {len(manifest['candidates'])}; eligible: {len(roots)}. Upload experiment_bundle.json only.\n"
    if unknown:text+="\nSome inventory checks were unverified; selection withheld.\n"
    text+="\n## Final capital and trade summary\n\nRows sum separate $2,000 ticker accounts for one setup and phase, not one shared portfolio. Phase accounts reset. Never sum alternative rows. N/A means incomplete; trade totals then cover completed accounts only. Flat trades are neither wins nor losses.\n\n"
    text+="|Tier|Strategy|Allocation|Period|Accounts|Starting Equity|Final Equity|Total Trades|Winning Trades|Lost Trades|\n|---|---|---:|---|---|---:|---:|---:|---:|---:|\n"
    for r in summaries:
        start="N/A" if r["starting_equity"] is None else f"{r['starting_equity']:.2f}"
        end="N/A" if r["final_equity"] is None else f"{r['final_equity']:.2f}"
        text+=f"|{r['tier']}|{r['strategy']}|0.10|{r['phase']}|{r['completed_accounts']}/{len(roots)}|{start}|{end}|{r['total_trades']}|{r['winning_trades']}|{r['lost_trades']}|\n"
    (out/"report.md").write_text(text)
    if missing or unknown or any(not r["complete"] for r in summaries):raise SystemExit("Incomplete shortlist; inspect preserved results")


def main():
    import strategy_suite as suite
    import filtered_research as policy
    import research_repairs as repairs
    import expanded_universe as universe
    import research_progress as progress
    import five_ticker_scope as five
    metadata=policy.install(suite)
    suite.NAMES=NAMES
    metadata.update(active_strategies=list(NAMES),allocations=[ALLOCATION],simulations_per_symbol=10,shortlist=SPEC)
    suite.NOTICE+=" "+SPEC["warning"]
    repairs.install(suite)
    original=suite.checkpoint
    def checkpoint(path,payload):freeze(payload);original(path,payload)
    suite.checkpoint=checkpoint
    p=argparse.ArgumentParser()
    p.add_argument("--prepare",action="store_true")
    p.add_argument("--scope",choices=["5","requested","full"],default="requested")
    p.add_argument("--batch",type=int)
    p.add_argument("--merge")
    p.add_argument("--start",default="2026-08-03")
    p.add_argument("--split",default="2026-10-01")
    p.add_argument("--end",default="2026-10-30")
    args=p.parse_args()
    if args.prepare:return five.prepare(args) if args.scope=="5" else progress.prepare(args)
    manifest=json.loads(Path("universe.json").read_text())
    if manifest.get("shortlist")!=SPEC:raise ValueError("Prepare a new shortlist manifest; old runs cannot be mixed")
    if args.merge:
        try:return merge(suite,universe,repairs,args.merge,manifest)
        finally:repairs.update_report()
    if args.batch is None or not 0<=args.batch<len(manifest["batches"]):raise ValueError("Invalid batch")
    failed=False
    for symbol in manifest["batches"][args.batch]:
        try:run_symbol(suite,manifest,symbol)
        except (Exception,SystemExit):failed=True
    if failed:raise SystemExit("Batch contains incomplete shortlist results")


if __name__=="__main__":main()
