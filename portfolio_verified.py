"""Bounded same-source verification; never substitute contract or fill price."""
import builtins
import functools
import html
import json
import os
from pathlib import Path
import re
from unittest.mock import patch

MAX_REFRESH_KEYS=3


def redact(value):
    text=str(value)
    for key,secret in os.environ.items():
        if secret and any(word in key.upper() for word in ("KEY","SECRET","TOKEN","PASSWORD")):
            text=text.replace(secret,"[redacted]")
    text=re.sub(r"https?://\S+","[url]",text)
    text=re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+",r"\1=[redacted]",text)
    return html.escape(" ".join(text.replace("`","'").split()))[:500]


class ObservedJSON:
    def __init__(self,current):self.current=current
    def __getattr__(self,name):return getattr(json,name)
    def load(self,response):
        payload=json.load(response)
        quote=self.current.get("quote")
        if isinstance(payload,list) and quote is not None and quote.audit:
            warnings=[redact(r["warning"]) for r in payload if isinstance(r,dict) and "warning" in r][:3]
            if warnings:quote.audit[-1]["provider_warnings_redacted"]=warnings
        return payload


def valid_exact(rows,root,day,strike,contract,quality):
    if not isinstance(rows,list):return False
    seen=set()
    for q in rows:
        if not isinstance(q,dict) or q.get("date")!=day or q.get("strike")!=strike or q.get("contract") in seen:return False
        if not re.fullmatch(re.escape(root)+r"\d{6}C\d{8}",q.get("contract","")) or quality(q,1.)=="invalid_quote":return False
        seen.add(q.get("contract"))
    matches=[q for q in rows if q.get("contract")==contract]
    if len(matches)!=1:return False
    match=re.fullmatch(re.escape(root)+r"(\d{2})(\d{2})(\d{2})C(\d{8})",contract)
    return bool(match and matches[0].get("expiry")=="20"+"-".join(match.groups()[:3]) and int(match.group(4))/1000==strike)


def run_verified(original,error_type,fresh_fetch,cache,frames,quotes,start,end,names,quality,strikes,state,checkpoint=None):
    attempted=set();events=[]
    state["quote_verification"]=events
    while True:
        try:return original(frames,quotes,start,end,names,quality,strikes,state,checkpoint=checkpoint)
        except error_type as exc:
            parts=str(exc).split(":")
            if len(parts)!=3 or parts[0] not in ("missing_held_position_quote","missing_entry_execution_quote"):raise
            stage,contract,day=parts
            match=re.fullmatch(r"([A-Z]{1,5})\d{6}C(\d{8})",contract)
            if not match or match.group(1) not in quotes:raise
            root=match.group(1);strike=int(match.group(2))/1000;key=(root,day,strike)
            if key in attempted or len(attempted)>=MAX_REFRESH_KEYS:
                state["quote_verification_limit_reached"]=True
                print("Bounded verification limit reached; preserving incomplete result",flush=True)
                raise
            attempted.add(key)
            event=dict(ticker=root,date=day,strike=strike,contract=contract,stage=stage,status="verifying")
            events.append(event)
            adapter=quotes[root]
            adapter.cache.pop(key,None)
            try:cache.cache_path(key).unlink(missing_ok=True)
            except OSError:event["cache_delete_failed"]=True
            if sum(len(q.audit) for q in quotes.values())>=4000:
                event["status"]="request_budget_exhausted";raise
            print(f"Verifying exact contract once, bypassing caches: {contract} on {day}",flush=True)
            try:
                rows=fresh_fetch(adapter,root,day,strike)
                recovered=valid_exact(rows,root,day,strike,contract,quality)
            except Exception as refresh_error:
                event.update(status="verification_request_or_schema_failed",error_category=type(refresh_error).__name__)
                raise exc from None
            event["returned_contracts"]=[q.get("contract") for q in rows[:30] if isinstance(q,dict)] if isinstance(rows,list) else []
            if not recovered:
                event["status"]="exact_contract_still_unavailable"
                try:cache.cache_path(key).unlink(missing_ok=True)
                except OSError:pass
                print(f"Required quote still unavailable: {contract} on {day}; portfolio remains incomplete",flush=True)
                raise exc from None
            adapter.cache[key]=rows
            cache.save_quote(key,rows)
            event["status"]="recovered_exact_quote"
            print("Exact quote recovered; replaying the SAME $2,000 simulation using cached history, not adding capital",flush=True)


def publish_diagnostics():
    path=Path("portfolio_results/portfolio_bundle.json")
    report=Path("portfolio_results/report.md")
    if not path.exists():return
    data=json.loads(path.read_text())
    code=redact(data.get("error_code","none"))
    print("Shared portfolio status: "+data.get("status","unknown")+"; exact error: "+code,flush=True)
    last=data.get("equity",[])
    text="\n## Exact-contract verification and failure details\n\n"
    if data.get("status")!="completed":
        text+="Error: "+code+". Final equity/P&L remain unknown; open holdings are not silently removed.\n\n"
    if last:
        row=last[-1]
        line=f"Last fully valued session: {row['date']}; equity {row['equity']:.2f}; cash {row['cash']:.2f}; open positions {row['positions']}. This is not a final result for an incomplete run."
        print(line,flush=True);text+=line+"\n\n"
    for event in data.get("quote_verification",[]):
        text+="- "+redact(event["contract"])+" / "+redact(event["date"])+": "+event["status"]+"\n"
    warnings={}
    for root,detail in data.get("quote_audits",{}).items():
        for request in detail.get("requests",[]):
            for warning in request.get("provider_warnings_redacted",[]):
                key=redact(warning)
                item=warnings.setdefault(key,dict(count=0,first_context=f"{root} {request.get('date')}"))
                item["count"]+=1
    for warning,item in list(warnings.items())[:20]:
        message=f"Provider warning ({item['count']} responses; first {item['first_context']}): {warning}"
        print(message,flush=True);text+="\n- "+message+"\n"
    if len(warnings)>20:text+="\nAdditional warnings retained in portfolio_bundle.json.\n"
    text+="\nRecovery uses only a fresh response for the same ticker/date/strike and exact contract. No alternate expiry, stale mark, synthetic fill, entitlement bypass or subscription purchase.\n"
    if report.exists():
        content=report.read_text();marker="\n## Final account summary"
        report.write_text(content.replace(marker,text+marker,1) if marker in content else content+text)


def plan_print(*args,**kwargs):
    if args and isinstance(args[0],str) and args[0].startswith(("Scope:","Scope 5:")):
        message=args[0].replace("Two jobs run at a time. Full scope may take hours/days.","One sequential shared-account simulation.")
        message=message.replace("At most two jobs run concurrently.","One sequential shared-account simulation.")
        args=(message,)+args[1:]
    builtins.print(*args,**kwargs)


def main():
    import portfolio_backtest as portfolio
    import hardened_research as h
    import research_repairs as cache
    import research_progress as progress
    import five_ticker_scope as five
    current={};original_fetch=h.BoundedQuotes.fetch
    def observed_fetch(self,*args,**kwargs):
        previous=current.get("quote");current["quote"]=self
        try:return original_fetch(self,*args,**kwargs)
        finally:current["quote"]=previous
    runner=functools.partial(run_verified,portfolio.simulate,portfolio.PortfolioError,observed_fetch,cache)
    try:
        with patch.object(portfolio,"simulate",side_effect=runner),patch.object(h.BoundedQuotes,"fetch",observed_fetch), \
                patch.object(h.limited,"json",ObservedJSON(current)),patch.object(progress,"print",plan_print,create=True),patch.object(five,"print",plan_print,create=True):
            portfolio.main()
    finally:
        publish_diagnostics()


if __name__=="__main__":main()
