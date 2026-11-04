"""Offline shortlist tests, including exact simulation count and allocation."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import pandas as pd
import shortlist_research as s

CONFIG=dict(start="2026-08-03",split="2026-10-01",end="2026-10-30")


class ShortlistTests(unittest.TestCase):
    def bundle(self):
        return dict(config=dict(symbol="SPY",**CONFIG),shortlist=s.SPEC,strategy_names=list(s.NAMES),allocations=[.1],expected_runs=10,
            runs=[dict(ticker="SPY",phase=p,strategy=n,allocation=.1,status="completed_no_trades") for p in s.PHASES for n in s.NAMES])

    def test_names_tiers_and_frozen_counts(self):
        self.assertEqual(len(s.NAMES),5)
        self.assertEqual(set(s.PRIMARY),{"rsi14_recovery","reversion_vote"})
        self.assertEqual(set(s.SECONDARY),{"ema9_21_cross","ema20_pullback","stochastic_recovery"})
        payload=dict(eligible=[str(i) for i in range(25)],planned_simulations=1200)
        s.freeze(payload)
        self.assertEqual(payload["planned_simulations"],250)
        self.assertEqual(payload["simulations_per_symbol"],10)
        self.assertEqual(payload["shortlist"]["allocations"],[.1])

    def test_reject_archived_allocations_and_duplicate_runs(self):
        manifest=dict(eligible=["SPY"],config=CONFIG)
        b=self.bundle();s.validate_bundle(b,manifest)
        b["runs"][0]["allocation"]=.25
        with self.assertRaises(ValueError):s.validate_bundle(b,manifest)
        b=self.bundle();b["runs"].append(b["runs"][0].copy())
        with self.assertRaises(ValueError):s.validate_bundle(b,manifest)

    def test_reject_old_profile_and_wrong_dates(self):
        manifest=dict(eligible=["SPY"],config=CONFIG)
        b=self.bundle();b["shortlist"]={}
        with self.assertRaises(ValueError):s.validate_bundle(b,manifest)
        b=self.bundle();b["config"]["end"]="2026-10-29"
        with self.assertRaises(ValueError):s.validate_bundle(b,manifest)

    def test_reject_mislabeled_ticker(self):
        b=self.bundle();b["runs"][0]["ticker"]="QQQ"
        with self.assertRaises(ValueError):s.validate_bundle(b,dict(eligible=["SPY"],config=CONFIG))

    def test_runner_executes_only_ten_real_simulations_at_ten_percent(self):
        frame=pd.DataFrame(dict(date=pd.bdate_range("2025-04-01","2026-10-30")))
        frame["symbol"]="SPY"
        for n in s.NAMES:frame["sig_"+n]=True
        allocations=[]
        class Quotes:
            network=[]
            def __init__(self,frames):self.events=[];self.audit=[]
        def simulate(stocks,q,ticker,start,end,strategy,allocation,feed):
            allocations.append(allocation)
            q.events=[dict(event="signal_check",triggered=True)]
            return pd.DataFrame(columns=["strategy"]),pd.DataFrame([dict(equity=2000.)]),pd.DataFrame(columns=["reason"]),dict(starting_equity=2000.,final_equity=2000.,return_pct=0.,trades=0,wins=0,losses=0,max_drawdown_pct=0.)
        def checkpoint(path,payload):
            s.freeze(payload)
            path.write_text(json.dumps(payload))
        suite=SimpleNamespace(NOTICE="fixture",SuiteQuotes=Quotes,
            windows=lambda a,b,c:[("development",pd.Timestamp(a),pd.Timestamp(b)-pd.Timedelta(days=1)),("validation",pd.Timestamp(b),pd.Timestamp(c))],
            checkpoint=checkpoint,Alpaca=lambda:SimpleNamespace(bars=lambda *a,**k:frame.copy()),choose_feed=lambda *a:("iex",[]),
            signals=lambda raw:raw,records=lambda f:json.loads(f.to_json(orient="records")),
            h=SimpleNamespace(features=lambda x:x,signal=lambda *a:True,simulate=simulate,ResearchError=ValueError))
        with tempfile.TemporaryDirectory() as folder:
            old=os.getcwd()
            try:
                os.chdir(folder)
                s.run_symbol(suite,dict(config=CONFIG),"SPY")
                data=json.loads(Path("suite_results/SPY.json").read_text())
                self.assertEqual(len(data["runs"]),10)
                self.assertEqual(allocations,[.1]*10)
                self.assertEqual(data["expected_runs"],10)
                self.assertEqual(data["allocations"],[.1])
                self.assertEqual(set(r["strategy"] for r in data["runs"]),set(s.NAMES))
            finally:os.chdir(old)


if __name__=="__main__":unittest.main()
