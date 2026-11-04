"""Explicit research scopes and progress; never silently truncate a full universe."""
import argparse
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
import pandas as pd
import expanded_universe as u


def batch_size(scope):
    if scope not in ("requested","full"):
        raise ValueError("Unknown research scope")
    return 1 if scope=="requested" else 5


def prepare(args):
    batch_size(args.scope)
    if args.scope=="full":
        u.prepare(args)
        manifest=json.loads(Path("universe.json").read_text())
    else:
        u.suite.windows(args.start,args.split,args.end)
        candidates=list(dict.fromkeys(u.REQUESTED+u.suite.read_watchlist()[0]))
        manifest=dict(source_url=None,source_symbols=[],source_sha256=None,
            fetched_at=pd.Timestamp.now(tz="UTC").isoformat(),requested_symbols=u.REQUESTED,
            candidates=candidates,eligible=[],checks=[],
            warning="Requested-tickers scope: S&P 500 source is intentionally NOT included. Inventory verification is not historical quote coverage.",
            config=dict(start=args.start,split=args.split,end=args.end))
        client=u.Alpaca()
        for i,symbol in enumerate(candidates,1):
            try: status=u.inventory(client,symbol,args.start,args.end)
            except Exception: status="unverified_access_or_provider_error"
            manifest["checks"].append(dict(ticker=symbol,status=status))
            if status=="options_inventory_verified":manifest["eligible"].append(symbol)
            u.suite.checkpoint(Path("universe.json"),manifest)
            print(f"Inventory {i}/{len(candidates)} {symbol}: {status}",flush=True)
        if not manifest["eligible"]:
            raise SystemExit("No verified supported tickers; inspect universe.json")
    size=batch_size(args.scope)
    manifest["scope"]=args.scope
    manifest["batches"]=[manifest["eligible"][i:i+size] for i in range(0,len(manifest["eligible"]),size)]
    manifest["planned_simulations"]=len(manifest["eligible"])*len(u.suite.NAMES)*4
    manifest["simulations_per_symbol"]=len(u.suite.NAMES)*4
    u.suite.checkpoint(Path("universe.json"),manifest)
    with open(os.environ["GITHUB_OUTPUT"],"a") as output:
        output.write("batches="+json.dumps(list(range(len(manifest["batches"]))))+"\n")
    summary=(f"Scope: {args.scope}; tickers: {len(manifest['eligible'])}; jobs: {len(manifest['batches'])}; "
        f"simulations: {manifest['planned_simulations']}. Two jobs run at a time. Full scope may take hours/days.")
    print(summary,flush=True)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a") as out:out.write(summary+"\n")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--prepare",action="store_true")
    p.add_argument("--scope",choices=["requested","full"],default="requested")
    p.add_argument("--batch",type=int)
    p.add_argument("--start",default="2026-08-03")
    p.add_argument("--split",default="2026-10-01")
    p.add_argument("--end",default="2026-10-30")
    args=p.parse_args()
    if args.prepare:return prepare(args)
    manifest=json.loads(Path("universe.json").read_text())
    if args.batch is None or not 0<=args.batch<len(manifest["batches"]):
        raise ValueError("Invalid batch")
    original=u.suite.checkpoint
    began=time.monotonic()
    def progress(path,payload):
        original(path,payload)
        if "runs" in payload:
            runs=payload["runs"]
            last=runs[-1] if runs else {}
            print(f"{payload['config']['symbol']}: {len(runs)}/{payload['expected_runs']} simulations; "
                f"{last.get('phase','setup')} {last.get('strategy','')} {last.get('status','starting')}; "
                f"network snapshots={len(payload.get('provider_audit',[]))}; "
                f"elapsed={time.monotonic()-began:.0f}s",flush=True)
    failed=False
    with patch.object(u.suite,"read_watchlist",return_value=u.manifest_watchlist(manifest)),patch.object(u.suite,"checkpoint",side_effect=progress):
        for symbol in manifest["batches"][args.batch]:
            print(f"Starting {symbol}: 84 simulations (21 rules x 2 allocations x 2 periods)",flush=True)
            run_args=u.SimpleNamespace(symbol=symbol,merge=None,**manifest["config"])
            try:u.suite.run(run_args)
            except (Exception,SystemExit):failed=True
    if failed:raise SystemExit("Batch incomplete; checkpoints retained")


if __name__=="__main__":main()
