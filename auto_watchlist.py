"""Select an available stock feed before running the unchanged watchlist simulation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import pandas as pd
from alpaca_backtest import Alpaca
from engine import features
from watchlist_backtest import read_watchlist


def choose_feed(client,roots,start,end):
    start,end=pd.Timestamp(start),pd.Timestamp(end)
    attempts=[]
    for feed in ("sip","iex"):
        try:
            calendars=[]
            for root in roots:
                bars=client.bars([root],start-pd.Timedelta(days=150),end,stock=True,stock_feed=feed)
                f=features(bars)
                dates=pd.to_datetime(f.date).dt.normalize()
                if (dates<start).sum()<50 or not ((dates>=start)&(dates<=end)).any():
                    raise ValueError("Insufficient warmup/test coverage for "+root)
                calendars.append(set(dates[(dates>=start)&(dates<=end)]))
            if any(c!=calendars[0] for c in calendars):
                raise ValueError("Inconsistent stock-session coverage across watchlist")
            attempts.append(dict(feed=feed,status="selected",tickers_checked=roots))
            return feed,attempts
        except Exception as exc:
            attempts.append(dict(feed=feed,status="unavailable",reason=str(exc)))
            if "HTTP 401" in str(exc):
                return None,attempts
    return None,attempts


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--start",required=True)
    parser.add_argument("--end",required=True)
    parser.add_argument("--allocation",type=float,default=.25)
    args=parser.parse_args()
    out=Path("results")
    out.mkdir(exist_ok=True)
    metadata={"policy":"SIP first, IEX fallback; availability only, never P&L selection","selected_feed":None,"attempts":[]}
    try:
        start,end=pd.Timestamp(args.start),pd.Timestamp(args.end)
        if start>end or end.date()>=pd.Timestamp.now(tz="America/New_York").date() or (end-start).days>180 or not 0<args.allocation<=1:
            raise ValueError("Use completed dates up to 180 days and allocation in (0,1]")
        roots,_,_,_,_=read_watchlist()
        chosen,attempts=choose_feed(Alpaca(),roots,start,end)
        metadata.update(selected_feed=chosen,attempts=attempts)
        (out/"stock_feed_selection.json").write_text(json.dumps(metadata,indent=2))
        if chosen is None:
            raise ValueError("Neither stock feed passed coverage/access checks; inspect stock_feed_selection.json")
        command=[sys.executable,str(Path(__file__).with_name("watchlist_backtest.py")),"--start",args.start,"--end",args.end,"--allocation",str(args.allocation),"--stock-feed",chosen]
        result=subprocess.run(command,check=False)
        report=out/"report.md"
        with report.open("a") as handle:
            handle.write("\n\n## Automatic stock-feed selection\n\n```json\n"+json.dumps(metadata,indent=2)+"\n```\n")
        summary=out/"summary.json"
        if summary.exists() and result.returncode==0:
            payload=json.loads(summary.read_text())
            payload["config"]["stock_feed_selection"]=metadata
            summary.write_text(json.dumps(payload,indent=2,allow_nan=False))
        raise SystemExit(result.returncode)
    except Exception as exc:
        (out/"report.md").write_text("# Automatic feed/backtest failed\n\nNo valid final performance is reported.\n\n"+str(exc))
        raise SystemExit("Automatic stock-feed selection failed; inspect report artifacts") from None
    finally:
        (out/"stock_feed_selection.json").write_text(json.dumps(metadata,indent=2))

if __name__=="__main__":
    main()
