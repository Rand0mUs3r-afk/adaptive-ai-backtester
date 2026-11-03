"""Diagnostic entry point; existing strategy, sizing and execution rules stay unchanged."""
import json
from pathlib import Path
import pandas as pd
import limited_backtest as limited


def skip_records(frame):
    """Missing optional identifiers become null; invalid numeric data stays strict."""
    records = frame.to_dict("records")
    for row in records:
        if "contract" in row and pd.isna(row["contract"]):
            row["contract"] = None
    return records


def selection_counts(rows, day, close, budget):
    dated = [q for q in rows if 30 <= (pd.Timestamp(q["expiry"]) - pd.Timestamp(day)).days <= 60]
    nearby = [q for q in dated if abs(q["strike"] / close - 1) <= .1]
    affordable = [q for q in nearby if q["ask"] * 100 + .65 <= budget]
    reason = ("no_returned_quotes" if not rows else "no_30_60_dte_quotes" if not dated else
        "no_strikes_within_10_percent" if not nearby else "premium_exceeds_allocation" if not affordable else
        "eligible_prior_quotes_present_check_entry_ask")
    return dict(returned_quotes=len(rows), dte_matches=len(dated), nearby_matches=len(nearby),
        affordable_matches=len(affordable), premium_budget=budget, detail_reason=reason)


def main():
    original = limited.eod.simulate
    diagnostics = []
    def inspected(stocks, quotes, ticker, start, end, strategy="adaptive", allocation=.25,
            stock_feed="iex", run_preflight=False):
        item = dict(ticker=ticker, strategy=strategy, coverage="limited", daily_contract_quotes=[], skipped_entries=[])
        diagnostics.append(item)
        raw = stocks.bars([ticker], pd.Timestamp(start)-pd.Timedelta(days=150), pd.Timestamp(end),
            stock=True, stock_feed=stock_feed).sort_values("date").reset_index(drop=True)
        raw["date"] = pd.to_datetime(raw.date).dt.normalize()
        sessions = raw[(raw.date >= pd.Timestamp(start)) & (raw.date <= pd.Timestamp(end))]
        item["test_sessions"] = len(sessions)
        if len(sessions) < 2:
            item["error_code"] = "insufficient_test_sessions"
            raise ValueError("At least two actual stock sessions are required; no one-day performance")
        try:
            trades, equity, skips, metrics = original(stocks, quotes, ticker, start, end,
                strategy, allocation, stock_feed, run_preflight=run_preflight)
            for row in skip_records(skips):
                date = pd.Timestamp(row["date"])
                prior = raw[raw.date < date].iloc[-1]
                day = prior.date.date().isoformat()
                prior_equity = equity[pd.to_datetime(equity.date) < date]
                account = float(prior_equity.iloc[-1].equity) if len(prior_equity) else 2000.
                snapshot = {q["contract"]: q for (root, d, strike), rows in quotes.cache.items()
                    if root == ticker and d == day for q in rows}
                detail = selection_counts(list(snapshot.values()), day, float(prior.close), account * allocation)
                row.update(ticker=ticker, strategy=strategy, signal_date=day, **detail)
                item["skipped_entries"].append(row)
            for trade in trades.to_dict("records"):
                for (root, day, strike), rows in quotes.cache.items():
                    if root != ticker or not trade["entry_date"] <= day <= trade["exit_date"]:
                        continue
                    for q in rows:
                        if q["contract"] == trade["contract"]:
                            item["daily_contract_quotes"].append(dict(ticker=ticker, strategy=strategy,
                                entry_date=trade["entry_date"], date=day, contract=q["contract"], bid=q["bid"],
                                ask=q["ask"], spread=q["ask"]-q["bid"], contracts=trade["contracts"]))
            item["outcome_status"] = "completed_with_trades" if len(trades) else "completed_no_trades"
            return trades, equity, skips, metrics
        except Exception as exc:
            item.setdefault("error_code", type(exc).__name__)
            raise
    limited.eod.simulate = inspected
    try:
        limited.main()
    finally:
        limited.eod.simulate = original
        out = Path("results")
        out.mkdir(exist_ok=True)
        tables = []
        for path in sorted(out.glob("*/*/*.csv")):
            ticker, strategy = path.parts[-3:-1]
            frame = pd.read_csv(path)
            frame["ticker"], frame["strategy"] = ticker, strategy
            frame.to_csv(path, index=False)
            tables.append(dict(ticker=ticker, strategy=strategy, table=path.stem,
                rows=json.loads(frame.to_json(orient="records", date_format="iso"))))
        summary_path = out / "limited_summary.json"
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        for run in summary.get("runs", []):
            if run["status"] == "completed":
                run["status"] = "completed_with_trades" if run["metrics"]["trades"] else "completed_no_trades"
                per_run = out / run["ticker"] / run["strategy"] / "summary.json"
                per_run.write_text(json.dumps(run, indent=2, allow_nan=False))
        if summary:
            summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False))
        audits = [dict(ticker=p.parts[-3], strategy=p.parts[-2], requests=json.loads(p.read_text()))
            for p in sorted(out.glob("*/*/request_audit.json"))]
        (out / "diagnostic_bundle.json").write_text(json.dumps(dict(summary=summary,
            diagnostics=diagnostics, tables=tables, request_audits=audits), indent=2, allow_nan=False))
        report = out / "report.md"
        text = report.read_text() if report.exists() else "# Limited-data diagnostics\n"
        text = text.replace("|completed|0|", "|completed_no_trades|0|")
        for item in diagnostics:
            if item.get("error_code"):
                text += f"\n{item['ticker']}/{item['strategy']}: {item['error_code']}\n"
        report.write_text(text + "\nUpload diagnostic_bundle.json only; it includes all trade tables, skip details, request audits and fetched held-contract bid/ask history. No stale prices are fabricated.\n")


if __name__ == "__main__":
    main()
