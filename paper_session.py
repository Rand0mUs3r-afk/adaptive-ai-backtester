"""Alpaca PAPER-only options runner. Default: observe, never submit orders."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pandas as pd
from alpaca_backtest import Alpaca
from engine import features, signal
from watchlist_backtest import read_watchlist

PAPER = "https://paper-api.alpaca.markets"
DATA = "https://data.alpaca.markets"
PREFIX = "romie-"
STRATEGIES = ("breakout", "momentum", "reversion", "blend", "adaptive")


class Halt(ValueError):
    pass


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise Halt("nonfinite_number")
    return value


def quote_values(quote, now, entry=False):
    timestamp = pd.Timestamp(quote["t"])
    if timestamp.tzinfo is None or not -5 <= (now-timestamp).total_seconds() <= 120:
        raise Halt("stale_or_future_quote")
    bid, ask = number(quote["bp"]), number(quote["ap"])
    if bid <= 0 or ask < bid:
        raise Halt("invalid_or_zero_bid_quote")
    if entry and ((ask-bid)/ask > .20 or number(quote.get("as",0)) < 1):
        raise Halt("entry_spread_or_size_rejected")
    return bid, ask


def order_id(symbol, side, session):
    digest = hashlib.sha256((symbol+side+session).encode()).hexdigest()[:32]
    return PREFIX+side+"-"+digest


class Client:
    def __init__(self):
        self.headers = {"APCA-API-KEY-ID":os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY":os.environ["ALPACA_SECRET_KEY"]}
        self.calls = 0

    def request(self, path, params=None, method="GET", payload=None, data=False):
        if method not in ("GET","POST","DELETE") or (method != "GET" and (data or not path.startswith("/v2/orders"))):
            raise Halt("endpoint_not_allowed")
        if method == "POST" and path != "/v2/orders":
            raise Halt("endpoint_not_allowed")
        if method == "DELETE" and not re.fullmatch(r"/v2/orders/[a-zA-Z0-9-]+", path):
            raise Halt("endpoint_not_allowed")
        url = (DATA if data else PAPER)+path
        if params:
            url += "?"+urlencode(params)
        headers = dict(self.headers, **{"Content-Type":"application/json"})
        for attempt in range(3 if method == "GET" else 1):
            self.calls += 1
            if self.calls > 100:
                raise Halt("cycle_request_budget")
            try:
                body = json.dumps(payload).encode() if payload is not None else None
                with urlopen(Request(url, headers=headers, data=body, method=method), timeout=20) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else None
            except HTTPError as exc:
                status = exc.code
                exc.close()
                if method == "GET" and status in (429,500,502,503,504) and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise Halt("broker_http_"+str(status)+"_"+method) from None
            except (OSError,ValueError):
                if method == "GET" and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise Halt("broker_response_unknown_reconcile_before_retry") from None

    def quotes(self, symbols):
        if not symbols or len(symbols)>100:
            raise Halt("invalid_quote_batch")
        return self.request("/v1beta1/options/quotes/latest", dict(symbols=",".join(symbols),feed="opra"), data=True)["quotes"]


def cycle(client, log):
    account = client.request("/v2/account")
    armed = os.getenv("PAPER_ORDERS_ENABLED", "false").lower() == "true"
    if account.get("status") != "ACTIVE" or account.get("trading_blocked") or account.get("account_blocked"):
        raise Halt("account_not_tradeable")
    log["orders_enabled"] = armed
    log["account_verified"] = account.get("id") == os.getenv("PAPER_ACCOUNT_ID")
    if armed and (not log["account_verified"] or not os.getenv("PAPER_ACCOUNT_ID")):
        raise Halt("paper_account_id_not_verified")
    clock = client.request("/v2/clock")
    now = pd.Timestamp(clock["timestamp"])
    today = now.tz_convert("America/New_York").date().isoformat()
    if armed and os.getenv("PAPER_ARM_DATE") != today:
        raise Halt("paper_arming_date_missing_or_expired")
    if not clock["is_open"]:
        log["status"] = "market_closed_no_orders"
        return
    log["session"] = today
    close = pd.Timestamp(clock["next_close"])
    roots,pins,mode,_,_ = read_watchlist()
    if mode != "manual" or any(v is not None for v in pins.values()):
        raise Halt("manual_underlying_watchlist_required")
    positions = client.request("/v2/positions")
    orders = client.request("/v2/orders", dict(status="all", limit=500,
        after=(now-pd.Timedelta(days=90)).isoformat(), direction="desc"))
    if len(orders)>=500:
        raise Halt("order_history_truncated")
    terminal = {"filled","canceled","expired","rejected","replaced"}
    pending = [o for o in orders if o["status"] not in terminal]
    if any(not o.get("client_order_id","").startswith(PREFIX) for o in pending):
        raise Halt("unrelated_open_orders_use_dedicated_paper_account")
    own_buys = {o["symbol"]:o for o in reversed(orders) if o.get("client_order_id","").startswith(PREFIX)
        and o["side"]=="buy" and number(o.get("filled_qty",0))>0}
    if any(p["symbol"] not in own_buys or number(p["qty"])<=0 for p in positions):
        raise Halt("unowned_or_short_position_use_dedicated_paper_account")
    log["positions"],log["pending_orders"] = len(positions),len(pending)
    if pending:
        log["status"] = "pending_orders_no_new_orders"
        if armed:
            for order in pending:
                if (now-pd.Timestamp(order["created_at"])).total_seconds()>900:
                    client.request("/v2/orders/"+order["id"],method="DELETE")
                    log["actions"].append(dict(action="cancel_stale_order",id=order["id"]))
        return
    if int(account.get("options_trading_level",0))<2:
        raise Halt("long_call_options_permission_required")
    if positions:
        quotes = client.quotes([p["symbol"] for p in positions])
        for position in positions:
            symbol = position["symbol"]
            if not number(position["qty"]).is_integer():
                raise Halt("noninteger_option_position")
            bid,ask = quote_values(quotes[symbol],pd.Timestamp.now(tz="UTC"))
            match = re.fullmatch(r"([A-Z]{1,5})(\d{6})C(\d{8})",symbol)
            if not match:
                raise Halt("unsupported_held_contract")
            expiry = pd.to_datetime(match.group(2),format="%y%m%d").date()
            avg = number(position["avg_entry_price"])
            change = bid/avg-1
            age = (now-pd.Timestamp((own_buys[symbol].get("filled_at") or own_buys[symbol]["created_at"]))).total_seconds()/86400
            reason = ("pre_expiration" if (expiry-now.date()).days<=7 else "maximum_holding" if age>=14 else
                "loss_signal" if change<=-.25 else "profit_signal" if change>=.15 else None)
            if reason:
                submit(client,log,dict(symbol=symbol,qty=position["qty"],side="sell",type="limit",
                    time_in_force="day",limit_price=format(max(.05, math.floor(bid/(.05 if bid<3 else .10)+1e-9)*(.05 if bid<3 else .10)),".2f"),
                    client_order_id=order_id(symbol,"sell",today+"-"+str(int(now.timestamp()//900))),position_intent="sell_to_close"),armed,orders,reason)
        log["status"] = "positions_managed_no_new_entry"
        return
    if (close-now).total_seconds()<1800:
        log["status"] = "near_close_no_entry"
        return
    equity,cash = number(account["equity"]),number(account["cash"])
    if number(account["last_equity"])>0 and equity/number(account["last_equity"])-1<=-.03:
        raise Halt("daily_account_loss_entry_lockout")
    if any(o["side"]=="buy" and o.get("client_order_id","").startswith(PREFIX)
            and pd.Timestamp(o["created_at"]).tz_convert("America/New_York").date().isoformat()==today for o in orders):
        log["status"] = "daily_entry_limit"
        return
    calendar = client.request("/v2/calendar",dict(start=(now-pd.Timedelta(days=14)).date().isoformat(),end=today))
    previous = [s["date"] for s in calendar if s["date"]<today]
    if not previous:
        raise Halt("calendar_missing_previous_session")
    previous = max(previous)
    stocks = Alpaca()
    candidates = []
    for root in roots:
        frame = features(stocks.bars([root],pd.Timestamp(previous)-pd.Timedelta(days=150),previous,stock=True,stock_feed="iex"))
        row = frame.sort_values("date").iloc[-1]
        if row.date.date().isoformat()!=previous or pd.isna(row.slow):
            raise Halt("stale_or_insufficient_stock_history")
        signals = {s:bool(signal(row,s)) for s in STRATEGIES}
        log["signals"].append(dict(ticker=root,as_of=previous,strategies=signals))
        if sum(signals.values())>=2:
            candidates.append((root,float(row.close)))
    for root,price in candidates:
        payload = client.request("/v2/options/contracts",dict(underlying_symbols=root,status="active",type="call",
            root_symbol=root,expiration_date_gte=(now+pd.Timedelta(days=30)).date().isoformat(),
            expiration_date_lte=(now+pd.Timedelta(days=60)).date().isoformat(),
            strike_price_gte=round(price*.9,2),strike_price_lte=round(price*1.1,2),limit=1000))
        if payload.get("next_page_token"):
            raise Halt("contract_inventory_truncated")
        contracts = [c for c in payload["option_contracts"] if c.get("tradable") is True and number(c.get("size",0))==100
            and re.fullmatch(re.escape(root)+r"\d{6}C\d{8}",c["symbol"])]
        contracts.sort(key=lambda c:(c["expiration_date"],abs(number(c["strike_price"])-price),c["symbol"]))
        contracts = contracts[:30]
        if not contracts:
            continue
        quotes = client.quotes([c["symbol"] for c in contracts])
        for contract in contracts:
            symbol = contract["symbol"]
            try:
                bid,ask = quote_values(quotes[symbol],pd.Timestamp.now(tz="UTC"),entry=True)
            except (Halt,KeyError):
                continue
            tick = .05 if ask<3 else .10
            limit = round(math.ceil(ask/tick-1e-9)*tick,2)
            if limit*100+.65>min(200.,max(0.,cash),max(0.,equity)*.10):
                continue
            submit(client,log,dict(symbol=symbol,qty="1",side="buy",type="limit",time_in_force="day",
                limit_price=format(limit,".2f"),client_order_id=order_id(root,"buy",today),
                position_intent="buy_to_open"),armed,orders,"two_or_more_daily_rules; not independent probability estimates")
            log["status"] = "entry_proposed_or_submitted"
            return
    log["status"] = "no_qualifying_entry"


def submit(client,log,order,armed,orders,reason):
    if any(o.get("client_order_id")==order["client_order_id"] for o in orders):
        log["actions"].append(dict(action="duplicate_id_no_resubmit",symbol=order["symbol"]))
        return
    log["actions"].append(dict(action="paper_order" if armed else "dry_run_proposal",order=order,reason=reason))
    if armed:
        clock = client.request("/v2/clock")
        session = pd.Timestamp(clock["timestamp"]).tz_convert("America/New_York").date().isoformat()
        if not clock["is_open"] or os.getenv("PAPER_ARM_DATE") != session:
            raise Halt("market_closed_or_arming_expired_before_submission")
        result = client.request("/v2/orders",method="POST",payload=order)
        log["actions"].append(dict(action="broker_acknowledgment",id=result.get("id"),status=result.get("status")))


def main():
    out = Path("paper_results")
    out.mkdir(exist_ok=True)
    log = dict(status="starting",signals=[],actions=[],paper_only=True,
        warning="No profit guarantee. Daily signals polled every 15 minutes, not an intraday-validated strategy. OPRA required; no indicative fallback. Limit exits can remain unfilled. Scheduler can be delayed.")
    try:
        cycle(Client(),log)
    except Exception as exc:
        log["status"],log["error_category"] = "halted",str(exc) if isinstance(exc,Halt) else type(exc).__name__
        raise SystemExit("Paper cycle halted; inspect paper_cycle.json") from None
    finally:
        (out/"paper_cycle.json").write_text(json.dumps(log,indent=2,allow_nan=False))


if __name__ == "__main__":
    main()
