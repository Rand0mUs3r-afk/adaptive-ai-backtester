"""Offline checks for explicit scope selection and workload counts."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import research_progress as r


class ProgressTests(unittest.TestCase):
    def test_scope_sizes_and_unknown_scope(self):
        self.assertEqual(r.batch_size("requested"),1)
        self.assertEqual(r.batch_size("full"),5)
        with self.assertRaises(ValueError):r.batch_size("unknown")

    def test_requested_scope_does_not_fetch_sp500(self):
        with tempfile.TemporaryDirectory() as folder:
            old=os.getcwd()
            try:
                os.chdir(folder)
                args=SimpleNamespace(scope="requested",start="2026-08-03",split="2026-10-01",end="2026-10-30")
                with patch.dict(os.environ,{"GITHUB_OUTPUT":str(Path(folder)/"outputs"),"GITHUB_STEP_SUMMARY":str(Path(folder)/"summary")}), \
                        patch.object(r.u,"REQUESTED",["SPY"]),patch.object(r.u.suite,"read_watchlist",return_value=(["CNQ"],)), \
                        patch.object(r.u,"Alpaca"),patch.object(r.u,"inventory",return_value="options_inventory_verified"), \
                        patch.object(r.u,"prepare") as full:
                    r.prepare(args)
                full.assert_not_called()
                data=json.loads(Path("universe.json").read_text())
                self.assertEqual(data["source_symbols"],[])
                self.assertIsNone(data["source_url"])
                self.assertEqual(data["planned_simulations"],168)
                self.assertEqual(data["batches"],[["SPY"],["CNQ"]])
            finally:os.chdir(old)

    def test_full_scope_keeps_entire_frozen_universe(self):
        with tempfile.TemporaryDirectory() as folder:
            old=os.getcwd()
            try:
                os.chdir(folder)
                args=SimpleNamespace(scope="full",start="2026-08-03",split="2026-10-01",end="2026-10-30")
                manifest=dict(eligible=["SPY","QQQ","IWM","AAPL","TSLA","CNQ"])
                def prepare(unused):Path("universe.json").write_text(json.dumps(manifest))
                with patch.dict(os.environ,{"GITHUB_OUTPUT":str(Path(folder)/"outputs"),"GITHUB_STEP_SUMMARY":str(Path(folder)/"summary")}),patch.object(r.u,"prepare",side_effect=prepare):
                    r.prepare(args)
                data=json.loads(Path("universe.json").read_text())
                self.assertEqual(sum(data["batches"],[]),manifest["eligible"])
                self.assertEqual(data["planned_simulations"],504)
            finally:os.chdir(old)


if __name__=="__main__":unittest.main()
