"""Offline quote-cache and diagnostic regressions; no data or order calls."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import research_repairs as r

KEY=("SPY","2026-09-01",500.)
ROWS=[dict(date=KEY[1],strike=500.,contract="SPY261016C00500000",bid=1.,ask=1.1)]


class RepairTests(unittest.TestCase):
    @contextmanager
    def folder(self):
        with tempfile.TemporaryDirectory() as folder:
            old=os.getcwd()
            try:
                os.chdir(folder)
                yield
            finally:os.chdir(old)

    def test_cache_positive_roundtrip_expiry_and_corruption(self):
        with self.folder():
            r.save_quote(KEY,ROWS)
            self.assertEqual(r.load_quote(KEY)[0],ROWS)
            with patch.object(r.time,"time",return_value=r.time.time()+r.TTL+1):
                self.assertIsNone(r.load_quote(KEY))
            path=r.cache_path(KEY)
            data=json.loads(path.read_text());data["rows"][0]["bid"]=99
            path.write_text(json.dumps(data))
            self.assertIsNone(r.load_quote(KEY))

    def test_empty_quote_response_never_persisted(self):
        with self.folder():
            r.save_quote(KEY,[])
            self.assertFalse(r.cache_path(KEY).exists())

    def test_missing_entry_and_held_quote_are_distinguished(self):
        result=dict(status="failed",error_code="missing_selected_or_held_contract:fixture")
        q=SimpleNamespace(events=[dict(event="signal_check",triggered=True,position_open=False)],audit=[])
        self.assertEqual(r.diagnostics(result,q)["missing_quote_stage"],"entry_execution")
        q.events[-1]["position_open"]=True
        d=r.diagnostics(result,q)
        self.assertEqual(d["missing_quote_stage"],"held_position")
        self.assertIsNone(d["zero_trade_reason"])

    def test_no_signal_differs_from_rejected_entry_and_audits_are_safe(self):
        result=dict(status="completed_no_trades",rejection_counts={"premium_exceeds_allocation":4})
        q=SimpleNamespace(events=[dict(event="signal_check",triggered=False)],audit=[dict(status="failed",http_status=403,secret="DO_NOT_EXPORT")])
        self.assertEqual(r.diagnostics(result,q)["zero_trade_reason"],"no_strategy_signal")
        q.events[0]["triggered"]=True
        d=r.diagnostics(result,q)
        self.assertEqual(d["zero_trade_reason"],"entry_checks_rejected_or_no_executable_entry")
        self.assertEqual(d["rejection_counts"],result["rejection_counts"])
        self.assertNotIn("DO_NOT_EXPORT",json.dumps(d))

    def test_disk_cache_avoids_transport_and_checkpoint_retains_zero_runs(self):
        class Quotes:
            def __init__(self):self.cache={};self.audit=[];self.network_calls=0
            def fetch(self,*key):
                if key not in self.cache:
                    self.network_calls+=1
                    self.cache[key]=ROWS
                    self.audit.append(dict(status="success"))
                return self.cache[key]
        saved=[]
        suite=SimpleNamespace(SuiteQuotes=Quotes,checkpoint=lambda path,payload:saved.append(payload.copy()))
        with self.folder():
            r.install(suite)
            first=Quotes();first.fetch(*KEY)
            second=Quotes();self.assertEqual(second.fetch(*KEY),ROWS)
            self.assertEqual(second.network_calls,0)
            self.assertEqual(second.reuse["disk_hits"],1)
            second.events=[dict(event="signal_check",triggered=True)]
            run=dict(ticker="SPY",phase="development",strategy="momentum",allocation=.1,status="completed_no_trades",rejection_counts={"no_returned_quotes":2},metrics=dict(trades=0))
            suite.checkpoint(Path("unused"),dict(runs=[run]))
            suite.checkpoint(Path("unused"),dict(symbol_results={"SPY":dict(runs=[run])}))
            self.assertEqual(saved[-1]["run_diagnostics"][0]["diagnostics"]["rejection_counts"],{"no_returned_quotes":2})
            self.assertEqual(first.network_calls,1)


if __name__=="__main__":unittest.main()
