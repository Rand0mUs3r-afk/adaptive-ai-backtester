"""Offline shared-account accounting and execution-guard fixtures."""
import unittest
import pandas as pd
import portfolio_backtest as p

START="2026-08-03"
END="2026-08-06"
NAMES=("rsi14_recovery","ema20_pullback")


def frames(roots,names=NAMES,signal=True):
    dates=pd.bdate_range(end=END,periods=210)
    result={}
    for root in roots:
        f=pd.DataFrame(dict(date=dates,symbol=root,close=100.,floor=90.))
        for name in names:f["sig_"+name]=signal
        result[root]=f
    return result


def quality(q,limit):
    if q["ask"]<=0 or q["bid"]<0 or q["bid"]>q["ask"]:return "invalid_quote"
    if q["bid"]==0:return "zero_bid_entry"
    if (q["ask"]-q["bid"])/q["ask"]>limit:return "spread_exceeds_limit"
    return None


class Quotes:
    def __init__(self,missing=None):self.missing=missing;self.calls=0
    def fetch(self,root,day,strike):
        self.calls+=1
        if day==self.missing:return []
        return [dict(date=day,strike=strike,contract=root+"260918C00100000",expiry="2026-09-18",bid=1.9,ask=1.9)]


class PortfolioTests(unittest.TestCase):
    def run_portfolio(self,roots,signal=True,missing=None):
        data=frames(roots,signal=signal);quotes={root:Quotes(missing) for root in roots};state={}
        result=p.simulate(data,quotes,START,END,NAMES,quality,lambda price:[100.],state)
        return result,quotes

    def test_no_signals_one_starting_account_and_no_quote_calls(self):
        result,quotes=self.run_portfolio(["A","B"],signal=False)
        self.assertEqual(result["metrics"]["starting_equity"],2000.)
        self.assertEqual(result["metrics"]["final_equity"],2000.)
        self.assertEqual(result["trades"],[])
        self.assertTrue(all(q.calls==0 for q in quotes.values()))

    def test_shared_cash_budget_and_exit_fee_reserve(self):
        roots=list("ABCDEFGHIJKLMNOPQRST")
        result,_=self.run_portfolio(roots)
        self.assertEqual(result["metrics"]["total_trades"],10)
        self.assertAlmostEqual(result["metrics"]["final_equity"],1987.)
        self.assertAlmostEqual(sum(t["pnl"] for t in result["trades"]),-13.)
        self.assertTrue(all(r["cash"]>=r["reserved_exit_fees"]-1e-6 for r in result["equity"]))
        self.assertTrue(all(t["entry_cost"]<=200. for t in result["trades"]))
        self.assertEqual(max(r["positions"] for r in result["equity"]),10)

    def test_overlapping_strategies_do_not_duplicate_position(self):
        result,_=self.run_portfolio(["A"])
        self.assertEqual(len(result["trades"]),1)
        trade=result["trades"][0]
        self.assertEqual(trade["strategy"],NAMES[0])
        self.assertEqual(trade["supporting_signals"],list(NAMES))
        self.assertEqual(trade["exit_date"],END)
        self.assertEqual(len(result["equity"]),4)
        self.assertEqual(result["metrics"]["total_fees"],1.3)

    def test_missing_held_quote_invalidates_account(self):
        state={}
        with self.assertRaisesRegex(p.PortfolioError,"missing_held_position_quote"):
            p.simulate(frames(["A"]),{"A":Quotes("2026-08-04")},START,END,NAMES,quality,lambda price:[100.],state)
        self.assertNotIn("metrics",state)
        self.assertIn("A",state["positions"])
        self.assertEqual(state["status"],"running")

    def test_missing_entry_quote_does_not_invent_fill(self):
        state={}
        with self.assertRaisesRegex(p.PortfolioError,"missing_entry_execution_quote"):
            p.simulate(frames(["A"]),{"A":Quotes(START)},START,END,NAMES,quality,lambda price:[100.],state)
        self.assertEqual(state["cash"],2000.)
        self.assertEqual(state["positions"],{})

    def test_inconsistent_stock_sessions_fail_before_account_runs(self):
        data=frames(["A","B"])
        data["B"]=data["B"][data["B"].date!=pd.Timestamp("2026-08-04")]
        with self.assertRaisesRegex(p.PortfolioError,"inconsistent_stock_sessions"):
            p.simulate(data,{r:Quotes() for r in data},START,END,NAMES,quality,lambda price:[100.],{})


if __name__=="__main__":unittest.main()
