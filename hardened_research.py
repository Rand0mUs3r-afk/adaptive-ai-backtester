"""Bounded limited-data research; no claim of exhaustive safety or profitability."""
import math
import os
from pathlib import Path
import json
import re
import pandas as pd
import limited_backtest as limited
from engine import features, signal


class ResearchError(ValueError):
    pass


def setting(name, default, low, high):
    value = float(os.getenv(name, str(default)))
    if not math.isfinite(value) or not low <= value <= high:
        raise ResearchError("invalid_setting:" + name)
    return value


def entry_reason(quote, max_spread):
    try:
        bid, ask = float(quote["bid"]), float(quote["ask"])
    except (KeyError, TypeError, ValueError):
        return "invalid_quote"
    if not math.isfinite(bid) or not math.isfinite(ask) or bid < 0 or ask <= 0 or bid > ask:
        return "invalid_quote"
    if bid == 0:
        return "zero_bid_entry"
    if (ask - bid) / ask > max_spread + 1e-12:
        return "spread_exceeds_limit"
    return None


def simulate(stocks, quotes, ticker, start, end, strategy="adaptive", allocation=.25,
        stock_feed="iex", run_preflight=False):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    mode = os.getenv("RESEARCH_MODE", "guarded")
    if mode not in ("guarded", "baseline") or strategy not in limited.STRATEGIES:
        raise ResearchError("unsupported_mode_or_strategy")
    if not re.fullmatch(r"[A-Z]{1,5}", ticker) or start.tzinfo or end.tzinfo or start != start.normalize() or end != end.normalize():
        raise ResearchError("invalid_symbol_or_dates")
    if start >= end or (end-start).days > 180 or end.date() >= pd.Timestamp.now(tz="America/New_York").date() or not math.isfinite(allocation) or not 0 < allocation <= 1:
        raise ResearchError("invalid_test_window_or_allocation")
    spread_limit = setting("MAX_SPREAD_FRACTION", .20, 0, 1) if mode == "guarded" else 1.
    jump_limit = setting("MAX_ENTRY_ASK_INCREASE", .25, 0, 10) if mode == "guarded" else float("inf")
    fee, initial = .65, 2000.
    raw = stocks.bars([ticker], start-pd.Timedelta(days=150), end, stock=True, stock_feed=stock_feed)
    if set(raw.symbol) != {ticker}:
        raise ResearchError("wrong_stock_symbol")
    frame = features(raw).sort_values("date").reset_index(drop=True)
    frame["date"] = pd.to_datetime(frame.date).dt.normalize()
    selected = frame.index[(frame.date >= start) & (frame.date <= end)].tolist()
    if len(selected) < 2 or selected[0] == 0 or pd.isna(frame.iloc[selected[0]-1].slow):
        raise ResearchError("insufficient_warmup_or_test_sessions")
    cash, position, trades, curve, skips = initial, None, [], [], []
    events = []
    quotes.events = events
    quotes.run_config = dict(mode=mode, max_spread_fraction=spread_limit,
        max_entry_ask_increase=jump_limit if mode == "guarded" else None,
        strike_policy="prior close nearest $5 plus/minus $5 only", fee_per_contract=fee,
        coverage="limited", timestamps_verified=False, corporate_actions_modeled=False)

    def skip(day, reason, **extra):
        skips.append(dict(date=day, reason=reason, ticker=ticker, strategy=strategy, **extra))

    def fetch(day, strike):
        rows = quotes.fetch(ticker, day, strike)
        if not isinstance(rows, list):
            raise ResearchError("invalid_normalized_response")
        seen = set()
        for q in rows:
            if q["date"] != day or q["strike"] != strike or q["contract"] in seen:
                raise ResearchError("quote_identity_or_duplicate_error")
            seen.add(q["contract"])
            if entry_reason(q, 1.) == "invalid_quote":
                raise ResearchError("invalid_quote")
        return rows

    def exact(day, contract, strike):
        matches = [q for q in fetch(day, strike) if q["contract"] == contract]
        if len(matches) != 1:
            raise ResearchError("missing_selected_or_held_contract:" + contract + ":" + day)
        return matches[0]

    for n, index in enumerate(selected):
        row, prior = frame.iloc[index], frame.iloc[index-1]
        day, prior_day = row.date.date().isoformat(), prior.date.date().isoformat()
        final, closed = n == len(selected)-1, False
        events.append(dict(date=day, event="signal_check", triggered=bool(signal(prior, strategy)),
            signal_date=prior_day, position_open=position is not None))
        quote = None
        if position is not None:
            quote = exact(day, position["contract"], position["strike"])
            reason = "end_of_test" if final else position["pending"] or (
                "maximum_holding" if n-position["index"] >= 10 else
                "pre_expiration" if row.date >= pd.Timestamp(position["expiry"])-pd.Timedelta(days=7) else None)
            if reason:
                proceeds = position["qty"] * (quote["bid"] * 100 - fee)
                cash += proceeds
                pnl = proceeds-position["cost"]
                trades.append(dict(contract=position["contract"], underlying=ticker, ticker=ticker,
                    strategy=strategy, signal_date=position["signal"], entry_date=position["entry"],
                    exit_date=day, contracts=position["qty"], entry_premium=position["ask"],
                    exit_premium=quote["bid"], entry_bid=position["bid"], entry_ask=position["ask"],
                    entry_spread=position["ask"]-position["bid"], entry_cost=position["cost"],
                    net_proceeds=proceeds, total_fees=2*fee*position["qty"], pnl=pnl,
                    return_pct=100*pnl/position["cost"], outcome="WIN" if pnl>0 else "LOSS" if pnl<0 else "FLAT",
                    exit_reason=reason, equity_before=position["before"], equity_after=cash,
                    holding_sessions=n-position["index"], provider="onclickmedia"))
                position, closed = None, True
        if position is None and not closed and not final and signal(prior, strategy):
            candidates = []
            for strike in limited.target_strikes(float(prior.close)):
                candidates.extend(fetch(prior_day, strike))
            stages = [("no_returned_quotes", lambda q: True),
                ("no_30_60_dte_quotes", lambda q: 30 <= (pd.Timestamp(q["expiry"])-prior.date).days <= 60),
                ("no_strikes_within_10_percent", lambda q: abs(q["strike"]/prior.close-1) <= .1),
                ("no_entry_quality_quotes", lambda q: entry_reason(q, spread_limit) is None),
                ("premium_exceeds_allocation", lambda q: q["ask"]*100+fee <= cash*allocation)]
            rejected = False
            for reason, predicate in stages:
                before = len(candidates)
                candidates = [q for q in candidates if predicate(q)]
                events.append(dict(date=day, event="selection_filter", filter=reason,
                    input_count=before, output_count=len(candidates)))
                if not candidates:
                    skip(day, reason)
                    rejected = True
                    break
            if not rejected:
                candidates.sort(key=lambda q: (q["expiry"], abs(q["strike"]-prior.close), q["contract"]))
                chosen = candidates[0]
                quote = exact(day, chosen["contract"], chosen["strike"])
                reason = entry_reason(quote, spread_limit)
                if reason:
                    skip(day, "execution_"+reason, contract=chosen["contract"])
                elif quote["ask"] > chosen["ask"]*(1+jump_limit):
                    skip(day, "entry_ask_increase_exceeds_limit", contract=chosen["contract"])
                elif (pd.Timestamp(quote["expiry"])-row.date).days <= 7:
                    skip(day, "insufficient_expiry_buffer")
                else:
                    qty = int(min(cash, cash*allocation)//(quote["ask"]*100+fee))
                    if qty < 1:
                        skip(day, "execution_premium_exceeds_allocation")
                    else:
                        cost = qty*(quote["ask"]*100+fee)
                        position = dict(quote, qty=qty, cost=cost, before=cash, index=n,
                            entry=day, signal=prior_day, pending=None)
                        cash -= cost
        marked = 0.
        if position is not None:
            marked = position["qty"]*(quote["bid"]*100-fee)
            change = marked/position["cost"]-1
            position["pending"] = ("profit_close_signal" if change >= .15 else
                "loss_close_signal" if change <= -.25 else "underlying_floor" if row.close < row.floor else None)
            events.append(dict(date=day, event="held_quote", contract=position["contract"],
                bid=quote["bid"], ask=quote["ask"], pending_exit=position["pending"]))
        if not math.isfinite(cash+marked) or cash < -1e-6:
            raise ResearchError("invalid_equity_or_cash")
        curve.append(dict(date=day, cash=cash, position_liquidation_estimate=marked, equity=cash+marked))
    if position is not None or abs(sum(t["pnl"] for t in trades)-(cash-initial)) > 1e-5:
        raise ResearchError("portfolio_reconciliation_failed")
    columns = ["contract", "underlying", "ticker", "strategy", "signal_date", "entry_date", "exit_date",
        "contracts", "entry_premium", "exit_premium", "entry_bid", "entry_ask", "entry_spread", "entry_cost",
        "net_proceeds", "total_fees", "pnl", "return_pct", "outcome", "exit_reason", "equity_before",
        "equity_after", "holding_sessions", "provider"]
    t, e = pd.DataFrame(trades, columns=columns), pd.DataFrame(curve)
    wins, losses = t[t.pnl>0], t[t.pnl<0]
    baseline = pd.Series([initial]+e.equity.tolist())
    metrics = dict(starting_equity=initial, final_equity=cash, equity_change=cash-initial,
        return_pct=100*(cash/initial-1), trades=len(t), wins=len(wins), losses=len(losses),
        win_rate_pct=100*len(wins)/len(t) if len(t) else None,
        max_drawdown_pct=float((baseline/baseline.cummax()-1).min()*100),
        total_fees=float(t.total_fees.sum()), skipped_signals=len(skips),
        warning=limited.NOTICE, execution_config=quotes.run_config)
    return t, e, pd.DataFrame(skips, columns=["date","reason","ticker","strategy","contract"]), metrics


class BoundedQuotes(limited.LimitedQuotes):
    instances = []

    def __init__(self, frames):
        super().__init__(frames)
        self.instances.append(self)

    def fetch(self, ticker, day, strike):
        if (ticker, day, strike) not in self.cache and len(self.audit) >= 400:
            raise ResearchError("request_budget_exceeded")
        try:
            return super().fetch(ticker, day, strike)
        except Exception as exc:
            if self.audit:
                status = self.audit[-1].get("http_status")
                self.audit[-1]["error_code"] = ("access_or_date_entitlement" if status in (401,403) else
                    "endpoint_not_found" if status == 404 else "rate_limit" if status == 429 else
                    "transport_or_schema_error")
            if isinstance(exc, ResearchError):
                raise
            raise ResearchError("options_request_failed; inspect safe request audit") from None


def main():
    import limited_diagnostics
    BoundedQuotes.instances = []
    original_sim, original_quotes = limited.eod.simulate, limited.LimitedQuotes
    limited.eod.simulate, limited.LimitedQuotes = simulate, BoundedQuotes
    try:
        limited_diagnostics.main()
    finally:
        limited.eod.simulate, limited.LimitedQuotes = original_sim, original_quotes
        path = Path("results/diagnostic_bundle.json")
        if path.exists():
            bundle = json.loads(path.read_text())
            bundle["execution_audits"] = [dict(events=getattr(q, "events", []),
                config=getattr(q, "run_config", {}), requests=q.audit) for q in BoundedQuotes.instances]
            bundle["hardening"] = dict(mode=os.getenv("RESEARCH_MODE","guarded"),
                max_spread_fraction=os.getenv("MAX_SPREAD_FRACTION","0.20"),
                max_entry_ask_increase=os.getenv("MAX_ENTRY_ASK_INCREASE","0.25"),
                git_sha=os.getenv("GITHUB_SHA","local"), request_budget_per_run=400,
                limitations=["partial chains", "unverified quote timestamps", "no corporate-action modeling",
                    "EOD stops do not cap losses", "no out-of-sample evidence", "not exhaustive scenario coverage"])
            path.write_text(json.dumps(bundle, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
