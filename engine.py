from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass
class Config:
    strategy: str = "adaptive"
    instrument: str = "stock"
    cash: float = 100000
    allocation: float = 0.1
    max_positions: int = 5
    hold_days: int = 10
    dte: int = 30
    fee: float = 0.65


def features(bars):
    b = bars.copy()
    required = {"date", "symbol", "open", "high", "low", "close", "volume"}
    if not required <= set(b):
        raise ValueError(f"Missing bar columns: {required - set(b)}")
    b["date"] = pd.to_datetime(b.date).dt.normalize()
    if b.duplicated(["date", "symbol"]).any():
        raise ValueError("Duplicate bars")
    numeric = ["open", "high", "low", "close", "volume"]
    b[numeric] = b[numeric].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(b[numeric].to_numpy()).all() or (b[numeric] < 0).any().any():
        raise ValueError("Invalid numeric bars")
    if (b[["open", "close", "low"]].max(axis=1) > b.high).any() or (b[["open", "close", "high"]].min(axis=1) < b.low).any() or (b.close <= 0).any():
        raise ValueError("Invalid OHLC")
    out = []
    for symbol, g in b.groupby("symbol"):
        g = g.sort_values("date").copy()
        c = g.close
        g["ma"] = c.rolling(20).mean()
        g["slow"] = c.rolling(50).mean()
        g["sd"] = c.rolling(20).std(ddof=0)
        g["upper"] = g.ma + 2 * g.sd
        g["lower"] = g.ma - 2 * g.sd
        g["ceiling"] = g.high.rolling(20).max().shift(1)
        g["floor"] = g.low.rolling(10).min().shift(1)
        g["vavg"] = g.volume.rolling(20).mean().shift(1)
        lo = g.low.rolling(14).min()
        hi = g.high.rolling(14).max()
        g["k"] = 100 * (c - lo) / (hi - lo).replace(0, np.nan)
        g["breakout"] = (c > g.ceiling) & (g.volume > g.vavg)
        g["momentum"] = (c > g.ma) & (g.ma > g.slow) & (g.k > g.k.shift()) & (c < g.upper)
        g["reversion"] = (c.shift() < g.lower.shift()) & (c > g.lower)
        g["trending"] = (g.ma > g.slow) & (g.ma > g.ma.shift(5))
        out.append(g)
    if not out:
        raise ValueError("Empty bars")
    return pd.concat(out).sort_values(["date", "symbol"])


def signal(row, strategy):
    if pd.isna(row.slow):
        return False
    if strategy in ("breakout", "momentum", "reversion"):
        return bool(row[strategy])
    if strategy == "blend":
        return sum(bool(row[k]) for k in ("breakout", "momentum", "reversion")) >= 2
    if strategy == "adaptive":
        return bool(row.breakout or row.momentum) if row.trending else bool(row.reversion)
    raise ValueError("Unknown strategy")


def prepare_quotes(quotes):
    required = {"date", "symbol", "contract", "expiry", "strike", "right", "bid", "ask", "multiplier"}
    if quotes is None or not required <= set(quotes):
        raise ValueError("Options require historical quotes: " + ",".join(sorted(required)))
    q = quotes.copy()
    q["date"] = pd.to_datetime(q.date).dt.normalize()
    q["expiry"] = pd.to_datetime(q.expiry).dt.normalize()
    for col in ("strike", "bid", "ask", "multiplier"):
        q[col] = pd.to_numeric(q[col], errors="raise")
    nums = q[["strike", "bid", "ask", "multiplier"]]
    if q.duplicated(["date", "contract"]).any() or not np.isfinite(nums.to_numpy()).all():
        raise ValueError("Duplicate or invalid quotes")
    if ((q.bid <= 0) | (q.ask < q.bid) | (q.strike <= 0) | (q.multiplier <= 0) | (q.expiry < q.date)).any():
        raise ValueError("Invalid/zero-bid quotes")
    return q


def backtest(bars, cfg=None, quotes=None):
    cfg = cfg or Config()
    if cfg.instrument not in ("stock", "call", "call_spread") or cfg.strategy not in ("breakout", "momentum", "reversion", "blend", "adaptive"):
        raise ValueError("Unsupported configuration")
    if cfg.cash <= 0 or not 0 < cfg.allocation <= 1 or cfg.max_positions < 1 or cfg.hold_days < 1 or cfg.fee < 0 or cfg.dte <= cfg.hold_days + 7:
        raise ValueError("Invalid capital, sizing, holding period, fee or DTE")
    f = features(bars)
    dates = sorted(f.date.unique())
    if len(dates) < 52:
        raise ValueError("Need at least 52 sessions for warmup and execution")
    q = prepare_quotes(quotes) if cfg.instrument != "stock" else None
    cash, positions, trades, curve = cfg.cash, {}, [], []

    def quote(contract, date):
        found = q[(q.contract == contract) & (q.date == date)]
        if len(found) != 1:
            raise ValueError(f"Missing executable quote: {contract} {date}; refusing stale marks")
        return found.iloc[0]

    def mark(p, date, current):
        if not p["legs"]:
            if p["symbol"] not in current.index:
                raise ValueError("Missing held-stock bar")
            return float(current.loc[p["symbol"], "close"])
        value = 0.0
        for contract, direction in p["legs"]:
            r = quote(contract, date)
            value += direction * float(r.bid if direction == 1 else r.ask) * p["multiplier"]
        if value < 0:
            raise ValueError("Negative executable spread value; reject this quote snapshot")
        return value

    previous = None
    for i, date in enumerate(dates):
        current = f[f.date == date].set_index("symbol", drop=False)
        final = i == len(dates) - 1
        if previous is not None:
            for symbol, p in list(positions.items()):
                prior = previous.loc[symbol] if symbol in previous.index else None
                exit_now = final or i - p["entry_i"] >= cfg.hold_days or (prior is not None and prior.close < prior.floor)
                value = mark(p, date, current)
                if exit_now:
                    fees = cfg.fee * p["qty"] * max(1, len(p["legs"]))
                    proceeds = value * p["qty"] - fees
                    cash += proceeds
                    trades.append({"symbol": symbol, "entry": p["entry_date"], "exit": date, "qty": p["qty"], "instrument": cfg.instrument, "strategy": cfg.strategy, "cost": p["cost"], "pnl": proceeds - p["cost"], "return": (proceeds - p["cost"]) / p["cost"]})
                    del positions[symbol]
            if not final:
                equity = cash + sum(mark(p, date, current) * p["qty"] for p in positions.values())
                for symbol, row in previous.sort_index().iterrows():
                    if symbol in positions or symbol not in current.index or len(positions) >= cfg.max_positions or not signal(row, cfg.strategy):
                        continue
                    legs, multiplier = [], 1
                    if q is None:
                        price = float(current.loc[symbol, "close"])
                    else:
                        chain = q[(q.date == date) & (q.symbol == symbol) & (q.right.str.upper() == "C") & (q.expiry >= pd.Timestamp(date) + pd.Timedelta(days=cfg.dte))]
                        if chain.empty:
                            continue
                        chain = chain[chain.expiry == chain.expiry.min()].copy()
                        chain["distance"] = (chain.strike - row.close).abs()
                        long = chain.sort_values(["distance", "strike", "contract"]).iloc[0]
                        multiplier = float(long.multiplier)
                        legs = [(long.contract, 1)]
                        price = float(long.ask) * multiplier
                        if cfg.instrument == "call_spread":
                            shorts = chain[(chain.strike > long.strike) & (chain.multiplier == multiplier)].sort_values(["strike", "contract"])
                            if shorts.empty:
                                continue
                            short = shorts.iloc[0]
                            legs.append((short.contract, -1))
                            price -= float(short.bid) * multiplier
                            if price <= 0 or price >= (short.strike - long.strike) * multiplier:
                                continue
                        # Contract selection must be supportable for the full potential holding window.
                        if any(pd.Timestamp(quote(c, date).expiry) <= pd.Timestamp(dates[min(i + cfg.hold_days, len(dates)-1)]) for c, _ in legs):
                            continue
                    unit_cost = price + cfg.fee * max(1, len(legs))
                    qty = int(min(cash, equity * cfg.allocation) // unit_cost)
                    if qty < 1:
                        continue
                    cost = qty * unit_cost
                    cash -= cost
                    positions[symbol] = dict(symbol=symbol, qty=qty, legs=legs, multiplier=multiplier, entry_i=i, entry_date=date, cost=cost)
        value = cash + sum(mark(p, date, current) * p["qty"] for p in positions.values())
        curve.append({"date": date, "equity": value, "cash": cash, "positions": len(positions)})
        previous = current
    t = pd.DataFrame(trades, columns=["symbol", "entry", "exit", "qty", "instrument", "strategy", "cost", "pnl", "return"])
    e = pd.DataFrame(curve)
    drawdown = e.equity / e.equity.cummax() - 1
    metrics = {"trades": len(t), "win_rate": float((t.pnl > 0).mean()) if len(t) else None, "mean_net_pnl": float(t.pnl.mean()) if len(t) else None, "net_profit": float(e.equity.iloc[-1] - cfg.cash), "total_return": float(e.equity.iloc[-1] / cfg.cash - 1), "max_drawdown": float(drawdown.min())}
    return t, e, metrics
