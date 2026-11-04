"""Offline first-five universe checks; no broker requests."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import five_ticker_scope as f


class FiveScopeTests(unittest.TestCase):
    def run_fixture(self,fail_symbol=None):
        with tempfile.TemporaryDirectory() as folder:
            old=os.getcwd()
            try:
                os.chdir(folder)
                def inventory(client,symbol,start,end):
                    if symbol==fail_symbol:raise ValueError("fixture transport error")
                    return "unsupported_index_adapter" if symbol in ("SPX","XSP") else "options_inventory_verified"
                with patch.dict(os.environ,{"GITHUB_OUTPUT":str(Path(folder)/"outputs"),"GITHUB_STEP_SUMMARY":str(Path(folder)/"summary")}), \
                        patch.object(f.u,"Alpaca"),patch.object(f.u,"inventory",side_effect=inventory) as calls, \
                        patch.object(f.u.suite,"NAMES",tuple(str(i) for i in range(12))), \
                        patch.object(f.u.suite,"read_watchlist",side_effect=AssertionError("Must not read watchlist")):
                    f.prepare(SimpleNamespace(start="2026-08-03",split="2026-10-01",end="2026-10-30"))
                data=json.loads(Path("universe.json").read_text())
                return data,[c.args[1] for c in calls.call_args_list]
            finally:os.chdir(old)

    def test_literal_five_no_backfill_and_honest_counts(self):
        data,calls=self.run_fixture()
        self.assertEqual(calls,["SPY","QQQ","IWM","SPX","XSP"])
        self.assertEqual(data["candidates"],calls)
        self.assertEqual(data["eligible"],["SPY","QQQ","IWM"])
        self.assertEqual(data["batches"],[["SPY"],["QQQ"],["IWM"]])
        self.assertEqual(data["planned_simulations"],144)
        self.assertEqual(data["scope"],"5")
        self.assertEqual(data["source_symbols"],[])

    def test_access_failure_is_not_optionless_or_backfilled(self):
        data,calls=self.run_fixture("IWM")
        self.assertEqual(len(calls),5)
        self.assertEqual(data["eligible"],["SPY","QQQ"])
        self.assertEqual(data["checks"][2]["status"],"unverified_access_or_provider_error")
        self.assertEqual(data["planned_simulations"],96)


if __name__=="__main__":unittest.main()
