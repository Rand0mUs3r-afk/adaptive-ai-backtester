"""Research-only quote reuse and compact diagnostics; never fabricate prices."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
import time

VERSION="quote-diagnostics-v1"
TTL=86400
SAFE_AUDIT=("ticker","date","strike","status","http_status","error_code","attempts","valid_calls")


def cache_path(key):
    name=hashlib.sha256(json.dumps(list(key),separators=(",",":")).encode()).hexdigest()
    return Path("quote_cache")/(name+".json")


def load_quote(key):
    try:
        data=json.loads(cache_path(key).read_text())
        age=time.time()-data["fetched_at"]
        rows=data["rows"]
        digest=hashlib.sha256(json.dumps(rows,sort_keys=True,allow_nan=False).encode()).hexdigest()
        if data["version"]!=VERSION or data["key"]!=list(key) or not 0<=age<=TTL or not rows or digest!=data["sha256"]:
            return None
        if any(q["date"]!=key[1] or float(q["strike"])!=float(key[2]) or
                not math.isfinite(float(q["bid"])) or not math.isfinite(float(q["ask"])) for q in rows):
            return None
        return rows,data["fetched_at"]
    except (OSError,ValueError,TypeError,KeyError):
        return None


def save_quote(key,rows):
    if not rows:return
    path=cache_path(key)
    try:
        path.parent.mkdir(exist_ok=True)
        digest=hashlib.sha256(json.dumps(rows,sort_keys=True,allow_nan=False).encode()).hexdigest()
        data=dict(version=VERSION,key=list(key),fetched_at=time.time(),sha256=digest,rows=rows)
        temp=path.with_suffix(".tmp")
        temp.write_text(json.dumps(data,allow_nan=False))
        temp.replace(path)
    except (OSError,ValueError,TypeError):
        pass


def diagnostics(result,quotes):
    events=getattr(quotes,"events",[])
    signals=[e for e in events if e["event"]=="signal_check"]
    triggered=sum(bool(e.get("triggered")) for e in signals)
    error=result.get("error_code","")
    stage=None
    if error.startswith("missing_selected_or_held_contract:"):
        stage="held_position" if signals and signals[-1].get("position_open") else "entry_execution"
    rejected=result.get("rejection_counts",{})
    zero_reason=None
    if result["status"]=="completed_no_trades":
        zero_reason="no_strategy_signal" if triggered==0 else "entry_checks_rejected_or_no_executable_entry"
    audit=getattr(quotes,"audit",[])
    failures=[{k:a[k] for k in SAFE_AUDIT if k in a} for a in audit if a.get("status")=="failed"][-5:]
    return dict(signal_checks=len(signals),signals_triggered=triggered,
        rejection_counts=rejected,rejection_count_scope="complete_run" if result["status"].startswith("completed") else "unavailable_for_failed_run",
        zero_trade_reason=zero_reason,missing_quote_stage=stage,
        failed_request_audit=failures,cache_counts=dict(getattr(quotes,"reuse",{})),
        cache_sources=getattr(quotes,"cache_sources",[]),
        note="Counts repeat across strategies/allocations; not independent market opportunities. Failed histories are not zero-trade results.")


def compact_diagnostics(bundles):
    rows=[]
    for ticker,bundle in bundles.items():
        for run in bundle["runs"]:
            rows.append(dict(ticker=ticker,phase=run["phase"],strategy=run["strategy"],allocation=run["allocation"],
                status=run["status"],error_code=run.get("error_code"),metrics=run.get("metrics"),
                diagnostics=run.get("diagnostics",dict(availability="not_recorded_in_older_artifact"))))
    return rows


def install(suite):
    if getattr(suite,"quote_repair_version",None)==VERSION:return
    current={}
    original_init=suite.SuiteQuotes.__init__
    original_fetch=suite.SuiteQuotes.fetch
    original_checkpoint=suite.checkpoint
    def init(self,*args,**kwargs):
        original_init(self,*args,**kwargs)
        self.reuse=Counter()
        self.cache_sources=[]
        current["quote"]=self
    def fetch(self,ticker,day,strike):
        key=(ticker,day,strike)
        if key in self.cache:
            self.reuse["memory_hits"]+=1
        else:
            cached=load_quote(key)
            if cached:
                self.cache[key]=cached[0]
                self.reuse["disk_hits"]+=1
                self.cache_sources.append(dict(ticker=ticker,date=day,strike=strike,fetched_at=cached[1]))
            else:self.reuse["uncached_lookups"]+=1
        before=len(self.audit)
        rows=original_fetch(self,ticker,day,strike)
        if len(self.audit)>before and rows:save_quote(key,rows)
        return rows
    def checkpoint(path,payload):
        runs=payload.get("runs",[])
        if runs and "diagnostics" not in runs[-1] and "quote" in current:
            runs[-1]["diagnostics"]=diagnostics(runs[-1],current["quote"])
        if "symbol_results" in payload:
            payload["run_diagnostics"]=compact_diagnostics(payload["symbol_results"])
        payload["research_repairs"]=dict(version=VERSION,positive_quote_cache_ttl_seconds=TTL,
            empty_or_failed_responses_persisted=False,
            missing_quotes_policy="Still incomplete; no synthetic/stale fills or automatic exclusion of difficult trades",
            performance_note="Warm cache can reduce network calls. First cold run and genuine provider gaps are not fixed by caching.")
        original_checkpoint(path,payload)
    suite.SuiteQuotes.__init__=init
    suite.SuiteQuotes.fetch=fetch
    suite.checkpoint=checkpoint
    suite.quote_repair_version=VERSION


def update_report():
    path=Path("suite_final/experiment_bundle.json")
    report=Path("suite_final/report.md")
    if not path.exists() or not report.exists():return
    payload=json.loads(path.read_text())
    rows=payload.get("run_diagnostics",[])
    text="\n## Entry and data diagnostics\n\nAll per-run metrics and rejection counts are now in experiment_bundle.json. "
    text+="Signal counts below repeat across strategy/size simulations; they are not unique opportunities. "
    text+="Missing entry/held quotes remain failed rather than invented fills.\n\n"
    text+="|Ticker|Completed, no trades|Completed, with trades|Failed|Triggered signal checks|Rejections|\n|---|---:|---:|---:|---:|---|\n"
    for ticker in payload.get("expected_symbols",[]):
        part=[r for r in rows if r["ticker"]==ticker]
        statuses=Counter(r["status"] for r in part)
        rejects=Counter()
        for r in part:rejects.update(r["diagnostics"].get("rejection_counts",{}))
        causes=", ".join(k+": "+str(v) for k,v in rejects.most_common()) or "none recorded"
        text+=f"|{ticker}|{statuses['completed_no_trades']}|{statuses['completed_with_trades']}|{statuses['failed']}|{sum(r['diagnostics'].get('signals_triggered',0) for r in part)}|{causes}|\n"
    existing=report.read_text()
    if "## Entry and data diagnostics" not in existing:
        marker="\n## Final capital and trade summary"
        if marker in existing:existing=existing.replace(marker,text+marker,1)
        else:existing+=text
        report.write_text(existing)


def main():
    import strategy_suite as suite
    import filtered_research as policy
    import expanded_universe as universe
    import research_progress as progress
    policy.install(suite)
    install(suite)
    try:
        if "--batch" in sys.argv or "--merge" in sys.argv:universe.main()
        else:progress.main()
    finally:
        if "--merge" in sys.argv:update_report()


if __name__=="__main__":main()
