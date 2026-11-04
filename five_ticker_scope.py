"""Literal first-five candidate scope; never backfill excluded candidates."""
import argparse
import json
import os
from pathlib import Path
import pandas as pd
import expanded_universe as u
import filtered_research as policy


def prepare(args):
    u.suite.windows(args.start,args.split,args.end)
    candidates=u.REQUESTED[:5]
    if len(candidates)!=5 or len(set(candidates))!=5:
        raise ValueError("Original list must start with five distinct symbols")
    manifest=dict(scope="5",selection_policy="Literal first five original candidates; no backfill or watchlist/source additions",
        source_url=None,source_symbols=[],source_sha256=None,
        fetched_at=pd.Timestamp.now(tz="UTC").isoformat(),requested_symbols=candidates,
        candidates=candidates,eligible=[],checks=[],
        warning="First-five smoke test, not a full-universe performance test. SPX/XSP are unsupported by this simulator, not optionless. Inventory verification is not historical quote coverage.",
        config=dict(start=args.start,split=args.split,end=args.end))
    client=u.Alpaca()
    for i,symbol in enumerate(candidates,1):
        try:status=u.inventory(client,symbol,args.start,args.end)
        except Exception:status="unverified_access_or_provider_error"
        manifest["checks"].append(dict(ticker=symbol,status=status))
        if status=="options_inventory_verified":manifest["eligible"].append(symbol)
        u.suite.checkpoint(Path("universe.json"),manifest)
        print(f"First-five inventory {i}/5 {symbol}: {status}",flush=True)
    if not manifest["eligible"]:
        raise SystemExit("No supported verified first-five tickers; inspect universe.json")
    manifest["batches"]=[[symbol] for symbol in manifest["eligible"]]
    manifest["simulations_per_symbol"]=len(u.suite.NAMES)*4
    manifest["planned_simulations"]=len(manifest["eligible"])*manifest["simulations_per_symbol"]
    u.suite.checkpoint(Path("universe.json"),manifest)
    with open(os.environ["GITHUB_OUTPUT"],"a") as out:
        out.write("batches="+json.dumps(list(range(len(manifest["batches"]))))+"\n")
    summary=(f"Scope 5: literal candidates {', '.join(candidates)}; eligible {len(manifest['eligible'])}/5; "
        f"jobs {len(manifest['batches'])}; simulations {manifest['planned_simulations']}. "
        "Unsupported/unverified candidates are not replaced. At most two jobs run concurrently.")
    print(summary,flush=True)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a") as out:out.write(summary+"\n")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--start",default="2026-08-03")
    p.add_argument("--split",default="2026-10-01")
    p.add_argument("--end",default="2026-10-30")
    args=p.parse_args()
    policy.install(u.suite)
    prepare(args)


if __name__=="__main__":main()
