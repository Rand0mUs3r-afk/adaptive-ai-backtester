"""Offline exact-contract recovery and secret-redaction regressions."""
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import portfolio_verified as v

CONTRACT="IBIT260904C00040000"
DAY="2026-08-11"
KEY=("IBIT",DAY,40.)
GOOD=dict(contract=CONTRACT,date=DAY,strike=40.,expiry="2026-09-04",bid=.2,ask=.22)
OTHER=dict(GOOD,contract="IBIT260918C00040000",expiry="2026-09-18")


class Missing(ValueError):pass


def quality(q,limit):
    return "invalid_quote" if q.get("bid",-1)<0 or q.get("ask",0)<=0 or q["bid"]>q["ask"] else None


class VerificationTests(unittest.TestCase):
    def fixture(self,folder):
        adapter=SimpleNamespace(cache={KEY:[OTHER]},audit=[])
        path=Path(folder)/"cached.json";path.write_text("old partial chain")
        saved=[]
        cache=SimpleNamespace(cache_path=lambda key:path,save_quote=lambda key,rows:saved.append((key,rows)))
        calls=[]
        def original(frames,quotes,start,end,names,quality,strikes,state,checkpoint=None):
            calls.append(dict(start=start,end=end,names=names))
            state.update(status="running",cash=2000.)
            if not any(q["contract"]==CONTRACT for q in quotes["IBIT"].cache[KEY]):
                raise Missing("missing_held_position_quote:"+CONTRACT+":"+DAY)
            state.update(status="completed",starting_equity=2000.)
            return state
        return adapter,cache,path,saved,calls,original

    def test_fresh_exact_quote_recovers_same_simulation_once(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter,cache,path,saved,calls,original=self.fixture(folder)
            fresh=[]
            def fetch(q,*key):
                fresh.append(key);q.cache[key]=[GOOD];return [GOOD]
            state={}
            result=v.run_verified(original,Missing,fetch,cache,{},dict(IBIT=adapter),"2026-08-03","2026-10-30",("rsi14_recovery",),quality,lambda price:[40.],state)
            self.assertEqual(len(fresh),1)
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[0],calls[1])
            self.assertEqual(result["starting_equity"],2000.)
            self.assertEqual(state["quote_verification"][0]["status"],"recovered_exact_quote")
            self.assertEqual(saved[0][1],[GOOD])

    def test_persistent_gap_does_not_loop_substitute_or_persist_bad_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter,cache,path,saved,calls,original=self.fixture(folder)
            fresh=[]
            def fetch(q,*key):fresh.append(key);q.cache[key]=[OTHER];return [OTHER]
            state={}
            with self.assertRaisesRegex(Missing,CONTRACT):
                v.run_verified(original,Missing,fetch,cache,{},dict(IBIT=adapter),"start","end",("rule",),quality,lambda x:[40.],state)
            self.assertEqual(len(fresh),1)
            self.assertEqual(len(calls),1)
            self.assertFalse(path.exists())
            self.assertEqual(saved,[])
            self.assertNotIn("metrics",state)
            self.assertEqual(state["quote_verification"][0]["status"],"exact_contract_still_unavailable")

    def test_duplicate_wrong_date_and_expiry_quotes_are_rejected(self):
        self.assertFalse(v.valid_exact([GOOD,GOOD],*KEY,CONTRACT,quality))
        self.assertFalse(v.valid_exact([dict(GOOD,date="2026-08-10")],*KEY,CONTRACT,quality))
        self.assertFalse(v.valid_exact([dict(GOOD,expiry="2026-09-18")],*KEY,CONTRACT,quality))
        self.assertFalse(v.valid_exact([dict(GOOD,contract="SPY260904C00040000")],*KEY,CONTRACT,quality))
        self.assertTrue(v.valid_exact([GOOD],*KEY,CONTRACT,quality))

    def test_request_failure_retains_original_gap_without_raw_error(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter,cache,path,saved,calls,original=self.fixture(folder)
            state={}
            def fetch(*args):raise ValueError("DO_NOT_EXPORT")
            with self.assertRaises(Missing):
                v.run_verified(original,Missing,fetch,cache,{},dict(IBIT=adapter),"start","end",("rule",),quality,lambda x:[40.],state)
            self.assertNotIn("DO_NOT_EXPORT",json.dumps(state))
            self.assertEqual(state["quote_verification"][0]["error_category"],"ValueError")

    def test_provider_warning_is_redacted_but_original_payload_preserved(self):
        payload=[dict(warning="API_KEY=DO_NOT_EXPORT https://example.invalid/?token=DO_NOT_EXPORT"),dict(data=1)]
        quote=SimpleNamespace(audit=[{}])
        with patch.dict(os.environ,{"PROVIDER_API_KEY":"DO_NOT_EXPORT"}):
            result=v.ObservedJSON(dict(quote=quote)).load(BytesIO(json.dumps(payload).encode()))
        self.assertEqual(result,payload)
        self.assertNotIn("DO_NOT_EXPORT",json.dumps(quote.audit))
        self.assertNotIn("example.invalid",json.dumps(quote.audit))

    def test_console_reports_exact_failure_and_last_valid_equity(self):
        with tempfile.TemporaryDirectory() as folder:
            old=os.getcwd()
            try:
                os.chdir(folder);Path("portfolio_results").mkdir()
                data=dict(status="incomplete",error_code="missing_held_position_quote:"+CONTRACT+":"+DAY,
                    equity=[dict(date="2026-08-10",cash=1669.15,equity=1898.30,positions=2)],quote_audits={})
                Path("portfolio_results/portfolio_bundle.json").write_text(json.dumps(data))
                Path("portfolio_results/report.md").write_text("Report\n## Final account summary\nN/A")
                with patch("builtins.print") as printed:v.publish_diagnostics()
                self.assertIn(CONTRACT,str(printed.call_args_list))
                report=Path("portfolio_results/report.md").read_text()
                self.assertIn("Final equity/P&L remain unknown",report)
                self.assertTrue(report.endswith("N/A"))
            finally:os.chdir(old)


if __name__=="__main__":unittest.main()
