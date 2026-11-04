"""Research-only expanded universe and explicitly labeled capital summaries."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from urllib.request import Request,urlopen
from unittest.mock import patch
import pandas as pd
import strategy_suite as suite
from alpaca_backtest import Alpaca

SOURCE="https://stockanalysis.com/list/sp-500-stocks/"
REQUESTED="SPY QQQ IWM SPX XSP NVDA TSLA AAPL META MU INTC AMZN AMD GOOGL PLTR SMH XLK IBIT TLT GLD HYG EWZ SOXL TQQQ SOFI WOLF".split()


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables=[]
        self.table=None
        self.row=None
        self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=="table": self.table=[]
        elif tag=="tr" and self.table is not None: self.row=[]
        elif tag in ("td","th") and self.row is not None: self.cell=[]
    def handle_data(self,data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None:
            self.row.append("".join(self.cell).strip());self.cell=None
        elif tag=="tr" and self.row is not None:
            self.table.append(self.row);self.row=None
        elif tag=="table" and self.table is not None:
            self.tables.append(self.table);self.table=None


def parse_symbols(html,minimum=450):
    parser=Tables();parser.feed(html)
    for table in parser.tables:
        if table and "Symbol" in table[0]:
            col=table[0].index("Symbol")
            symbols=list(dict.fromkeys(row[col].upper() for row in table[1:] if len(row)>col))
            if not minimum<=len(symbols)<=600 or any(not re.fullmatch(r"[A-Z]{1,5}(?:[.-][A-Z])?",s) for s in symbols):
                raise ValueError("Incomplete or unsupported source symbol table")
            return symbols
    raise ValueError("Source Symbol table not found")


def inventory(client,symbol,start,end):
    if symbol in ("SPX","XSP"):
        return "unsupported_index_adapter"
    if not re.fullmatch(r"[A-Z]{1,5}",symbol):
        return "unsupported_share_class_symbol_adapter"
    for status in ("active","inactive"):
        token,seen=None,set()
        for _ in range(10):
            params=dict(underlying_symbols=symbol,root_symbol=symbol,type="call",status=status,
                expiration_date_gte=(pd.Timestamp(start)+pd.Timedelta(days=30)).date().isoformat(),
                expiration_date_lte=(pd.Timestamp(end)+pd.Timedelta(days=60)).date().isoformat(),limit=1000)
            if token: params["page_token"]=token
            payload=client.get("https://paper-api.alpaca.markets/v2/options/contracts",params)
            rows=payload.get("option_contracts")
            if not isinstance(rows,list): raise ValueError("Invalid option inventory schema")
            for row in rows:
                if float(row.get("size",0))==100 and re.fullmatch(re.escape(symbol)+r"\d{6}C\d{8}",row.get("symbol","")):
                    return "options_inventory_verified"
            token=payload.get("next_page_token")
            if not token: break
            if token in seen: raise ValueError("Repeated inventory cursor")
            seen.add(token)
        else:
            raise ValueError("Inventory pagination cap")
    return "no_supported_calls_found_in_inventory_window"


def prepare(args):
    suite.windows(args.start,args.split,args.end)
    with urlopen(Request(SOURCE,headers={"User-Agent":"adaptive-ai-backtester/research"}),timeout=60) as response:
        raw=response.read(3000000)
    source_symbols=parse_symbols(raw.decode("utf-8"))
    existing=suite.read_watchlist()[0]
    candidates=list(dict.fromkeys(REQUESTED+existing+source_symbols))
    manifest=dict(source_url=SOURCE,source_sha256=hashlib.sha256(raw).hexdigest(),
        fetched_at=pd.Timestamp.now(tz="UTC").isoformat(),source_symbols=source_symbols,
        requested_symbols=REQUESTED,candidates=candidates,eligible=[],checks=[],
        warning="Current source membership is not historical point-in-time membership; survivorship/selection bias. Inventory availability does not certify historical quotes, affordability, or broker execution support.",
        config=dict(start=args.start,split=args.split,end=args.end))
    client=Alpaca()
    path=Path("universe.json")
    for symbol in candidates:
        try:
            status=inventory(client,symbol,args.start,args.end)
        except Exception as exc:
            status="unverified_access_or_provider_error"
        manifest["checks"].append(dict(ticker=symbol,status=status))
        if status=="options_inventory_verified": manifest["eligible"].append(symbol)
        suite.checkpoint(path,manifest)
    if not manifest["eligible"]:
        raise SystemExit("No verified supported options inventory; inspect universe.json")
    # Batch matrix avoids GitHub's per-matrix job ceiling without truncating symbols.
    batches=[manifest["eligible"][i:i+5] for i in range(0,len(manifest["eligible"]),5)]
    with open(os.environ["GITHUB_OUTPUT"],"a") as output:
        output.write("batches="+json.dumps(list(range(len(batches))))+"\n")
    manifest["batches"]=batches
    suite.checkpoint(path,manifest)


def manifest_watchlist(manifest):
    roots=manifest["eligible"]
    return roots,{s:None for s in roots},"manual",5,"\n".join(roots)


def totals(runs,expected):
    complete=[r for r in runs if r["status"].startswith("completed")]
    valid=len(runs)==expected and len(complete)==expected
    metrics=[r["metrics"] for r in complete]
    return dict(complete=valid,completed_accounts=len(complete),expected_accounts=expected,
        starting_equity=sum(m["starting_equity"] for m in metrics) if valid else None,
        final_equity=sum(m["final_equity"] for m in metrics) if valid else None,
        total_trades=sum(m["trades"] for m in metrics),winning_trades=sum(m["wins"] for m in metrics),
        lost_trades=sum(m["losses"] for m in metrics))


def combine(args,manifest):
    incomplete=False
    with patch.object(suite,"read_watchlist",return_value=manifest_watchlist(manifest)):
        try: suite.merge(args.merge)
        except SystemExit: incomplete=True
    path=Path("suite_final/experiment_bundle.json")
    payload=json.loads(path.read_text())
    payload["universe"]=manifest
    unknown=any(c["status"]=="unverified_access_or_provider_error" for c in manifest["checks"])
    if unknown:
        payload["development_selected"]=None
        payload["universe_incomplete"]=True
    rows=[r for b in payload["symbol_results"].values() for r in b["runs"]]
    summaries=[]
    for name in suite.NAMES:
        for allocation in (.10,.25):
            for phase in ("development","validation"):
                part=[r for r in rows if r["strategy"]==name and r["allocation"]==allocation and r["phase"]==phase]
                summaries.append(dict(strategy=name,allocation=allocation,phase=phase,**totals(part,len(manifest["eligible"])) ))
    payload["capital_summary"]=summaries
    payload["symbol_summary"]={root:dict(status_counts=dict(__import__("collections").Counter(r["status"] for r in data["runs"])),
        stock_data_sha256=data.get("stock_data_sha256"),setup_error=data.get("setup_error"))
        for root,data in payload["symbol_results"].items()}
    payload["trade_runs"]=[{k:v for k,v in r.items() if k not in ("equity","skipped_entries","request_audit")}
        for r in rows if r.get("trades")]
    payload["failed_runs"]=[{k:v for k,v in r.items() if k!="request_audit"} for r in rows if r["status"]=="failed"]
    payload["detail_location"]="Full per-experiment metrics, equity, skips and provider audits remain in universe-batch artifacts."
    del payload["symbol_results"]
    suite.checkpoint(path,payload)
    pd.DataFrame(summaries).to_csv("suite_final/capital_summary.csv",index=False)
    report=Path("suite_final/report.md")
    text=report.read_text()
    text+="\n## Expanded universe\n\nCandidates: "+str(len(manifest["candidates"]))+"; inventory-verified supported tickers: "+str(len(manifest["eligible"]))+". See universe checks for every exclusion.\n"
    if unknown: text+="\nUniverse access checks were incomplete; no development-selected configuration is approved.\n"
    text+="\n## Final capital and trade summary\n\nEach row sums independently funded $2,000 ticker accounts for ONE rule/allocation/phase. These are not one shared $2,000 portfolio. Do not sum alternative rows. Incomplete rows show N/A equity; trade counts are completed-account subtotals. Flat trades are in Total Trades but not wins/losses.\n\n"
    text+="|Strategy|Allocation|Period|Accounts completed/expected|Starting Equity|Final Equity|Total Trades|Winning Trades|Lost Trades|\n|---|---:|---|---|---:|---:|---:|---:|---:|\n"
    for row in summaries:
        start="N/A" if row["starting_equity"] is None else f"{row['starting_equity']:.2f}"
        final="N/A" if row["final_equity"] is None else f"{row['final_equity']:.2f}"
        text+=f"|{row['strategy']}|{row['allocation']}|{row['phase']}|{row['completed_accounts']}/{row['expected_accounts']}|{start}|{final}|{row['total_trades']}|{row['winning_trades']}|{row['lost_trades']}|\n"
    report.write_text(text)
    if incomplete or unknown: raise SystemExit("Incomplete research or universe; results preserved")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--prepare",action="store_true")
    p.add_argument("--batch",type=int)
    p.add_argument("--merge")
    p.add_argument("--start",default="2026-08-03")
    p.add_argument("--split",default="2026-10-01")
    p.add_argument("--end",default="2026-10-30")
    args=p.parse_args()
    if args.prepare: return prepare(args)
    manifest=json.loads(Path("universe.json").read_text())
    if args.merge: return combine(args,manifest)
    failed=False
    with patch.object(suite,"read_watchlist",return_value=manifest_watchlist(manifest)):
        for symbol in manifest["batches"][args.batch]:
            run_args=SimpleNamespace(symbol=symbol,merge=None,**manifest["config"])
            try: suite.run(run_args)
            except (Exception,SystemExit): failed=True
    if failed: raise SystemExit("Batch has incomplete experiments; checkpoints retained")


if __name__=="__main__":
    main()
