import hashlib
import json
from dataclasses import asdict
from pathlib import Path
import pandas as pd
import streamlit as st
from engine import Config, backtest

st.set_page_config(page_title="Adaptive Backtester", layout="wide")
st.title("Adaptive stock / options research lab")
st.warning("Research MVP: rule-based adaptive routing, not trained AI. No validated performance claims. Not for live execution.")
st.caption("Signals use the prior completed daily bar; fills use the next session close / synchronized option snapshot. Exits are close-scheduled, not intraday stops.")
bars_file = st.file_uploader("Daily bars CSV", type="csv")
quotes_file = st.file_uploader("Historical options snapshots CSV (required for options)", type="csv")
strategy = st.selectbox("Strategy", ["adaptive", "breakout", "momentum", "reversion", "blend"])
instrument = st.selectbox("Implementation", ["stock", "call", "call_spread"])
cash = st.number_input("Starting cash", min_value=1000.0, value=100000.0)
allocation = st.slider("Maximum entry allocation (% of equity, NOT stop-loss risk)", 1, 50, 10) / 100
hold = st.slider("Maximum holding sessions", 1, 30, 10)
dte = st.slider("Minimum calendar days to expiration", 40, 120, 45)
mode = st.radio("Evaluation", ["Single fixed configuration", "Development search + held-out evaluation"])
st.caption("Search evaluates five routing policies on the first 65% of dates, chooses by net profit, then evaluates the selected policy once on the remaining dates. Both blocks independently warm up for 50 sessions. This is a basic split, NOT full purged walk-forward validation. Do not repeatedly tune against the holdout.")
if st.button("Run research", disabled=bars_file is None):
    try:
        raw = bars_file.getvalue()
        bars = pd.read_csv(bars_file)
        quotes_raw = quotes_file.getvalue() if quotes_file is not None else b""
        quotes = pd.read_csv(quotes_file) if quotes_file is not None else None
        cfg = Config(strategy=strategy, instrument=instrument, cash=cash, allocation=allocation, hold_days=hold, dte=dte)
        trials = []
        if mode.startswith("Development"):
            dates = sorted(pd.to_datetime(bars.date).dt.normalize().unique())
            cut = int(len(dates) * .65)
            if cut < 52 or len(dates) - cut < 52:
                raise ValueError("Each split needs at least 52 sessions; provide more history")
            normalized = pd.to_datetime(bars.date).dt.normalize()
            development, evaluation = bars[normalized < dates[cut]], bars[normalized >= dates[cut]]
            for policy in ("breakout", "momentum", "reversion", "blend", "adaptive"):
                candidate = Config(**{**asdict(cfg), "strategy": policy})
                _, _, stats = backtest(development, candidate, quotes)
                trials.append({**asdict(candidate), **stats})
            chosen = max(trials, key=lambda t: t["net_profit"])["strategy"]
            cfg.strategy = chosen
            st.write("Selected on development only:", chosen)
            st.dataframe(pd.DataFrame(trials))
            trades, equity, metrics = backtest(evaluation, cfg, quotes)
            st.subheader("Held-out evaluation (selected policy only)")
        else:
            trades, equity, metrics = backtest(bars, cfg, quotes)
        st.json(metrics)
        st.line_chart(equity.set_index("date")[["equity"]])
        st.dataframe(trades)
        registry = {"config": asdict(cfg), "mode": mode, "trials": trials, "metrics": metrics, "bars_sha256": hashlib.sha256(raw).hexdigest(), "quotes_sha256": hashlib.sha256(quotes_raw).hexdigest(), "engine_sha256": hashlib.sha256(Path("engine.py").read_bytes()).hexdigest(), "limitations": "Rule-based router; basic holdout only; standard contracts only; no intraday stops, assignment, corporate-action accounting or live trading"}
        st.download_button("Trade ledger CSV", trades.to_csv(index=False), "trades.csv", "text/csv")
        st.download_button("Equity CSV", equity.to_csv(index=False), "equity.csv", "text/csv")
        st.download_button("Experiment registry JSON", json.dumps(registry, indent=2, allow_nan=False), "experiment.json", "application/json")
    except Exception as exc:
        st.error(str(exc))
