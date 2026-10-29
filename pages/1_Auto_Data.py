from datetime import date, timedelta
import pandas as pd
import streamlit as st
from collector import collect

st.title("Automatic historical data")
st.info("Requires ALPHAVANTAGE_API_KEY in the app environment and a plan entitled to daily adjusted/full history and historical options. No subscription is purchased by this app.")
symbols = st.text_input("US tickers (comma-separated)", "SPY")
start = st.date_input("Start (include indicator warmup)", date.today() - timedelta(days=365))
end = st.date_input("End (completed sessions only)", date.today() - timedelta(days=1))
options = st.checkbox("Collect historical calls for options backtests", True)
cap = st.number_input("Maximum daily chain lookups", min_value=1, max_value=5000, value=500)
st.caption("One chain lookup per ticker per trading day; uncached calls consume your provider quota. Re-running resumes from local cache. No scheduling/background service is installed.")
if st.button("Collect data and use in backtester"):
    st.session_state.pop("auto_market_data", None)
    progress = st.progress(0.0)
    try:
        bars, quotes, manifest = collect(symbols.split(","), start, end, options=options, max_chains=int(cap), progress=lambda done, total: progress.progress(done / total))
        raw = bars.to_csv(index=False).encode()
        quotes_raw = quotes.to_csv(index=False).encode() if quotes is not None else b""
        st.session_state["auto_market_data"] = (raw, quotes_raw, manifest)
        progress.progress(1.0)
        st.success("Data ready. Configure and run the backtest below; no CSV upload needed.")
        st.json(manifest)
        st.download_button("Optional bars export", raw, "bars.csv", "text/csv")
        if quotes_raw:
            st.download_button("Optional options export", quotes_raw, "options.csv", "text/csv")
    except Exception as exc:
        st.error(str(exc))

if "auto_market_data" in st.session_state:
    import io
    from engine import Config, backtest
    raw, quotes_raw, manifest = st.session_state["auto_market_data"]
    st.subheader("Backtest collected data")
    st.caption("Fixed daily-snapshot simulation only. No trained AI or validated probability estimates. Provider snapshots are not verified synchronized intraday execution quotes.")
    policy = st.selectbox("Policy", ["adaptive", "breakout", "momentum", "reversion", "blend"])
    instrument = st.selectbox("Instrument", ["stock", "call", "call_spread"])
    if st.button("Backtest automatically collected data"):
        try:
            if instrument != "stock" and not quotes_raw:
                raise ValueError("Recollect with historical calls enabled")
            bars = pd.read_csv(io.BytesIO(raw))
            quotes = pd.read_csv(io.BytesIO(quotes_raw)) if quotes_raw else None
            trades, equity, metrics = backtest(bars, Config(strategy=policy, instrument=instrument), quotes)
            st.json(metrics)
            st.line_chart(equity.set_index("date")[["equity"]])
            st.dataframe(trades)
            st.download_button("Trade ledger", trades.to_csv(index=False), "trades.csv", "text/csv")
            st.download_button("Equity curve", equity.to_csv(index=False), "equity.csv", "text/csv")
        except Exception as exc:
            st.error(str(exc))
