"""Offline fixtures exercise guards; never evidence of market profitability."""
import os
import unittest
from unittest.mock import patch
import pandas as pd
import hardened_research as h


class Stocks:
    def bars(self, *args, **kwargs):
        dates = ["2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14"]
        return pd.DataFrame([dict(date=pd.Timestamp(d), symbol="SPY", close=100., slow=90.,
            floor=80., trigger=(i == 0)) for i, d in enumerate(dates)])


class Quotes:
    def __init__(self, variant="normal"):
        self.variant, self.audit, self.cache, self.calls = variant, [], {}, []

    def fetch(self, ticker, day, strike):
        self.calls.append((ticker, day, strike))
        rows = []
        if strike == 100.:
            bid, ask = (3.25, 3.30)
            if self.variant == "wide" or (self.variant == "entry_wide" and day == "2026-09-10"):
                bid, ask = 1.25, 3.30
            if self.variant == "jump" and day == "2026-09-10":
                bid, ask = 4.45, 4.50
            if self.variant == "zero":
                bid = 0.
            rows = [dict(contract="SPY261016C00100000", date=day, expiry="2026-10-16",
                strike=strike, bid=bid, ask=ask, provider="fixture")]
            if self.variant == "missing_held" and day == "2026-09-11":
                rows = []
            if self.variant == "mismatch":
                rows[0]["date"] = "2026-09-08"
        self.cache[ticker, day, strike] = rows
        return rows


class HardeningTests(unittest.TestCase):
    def run_case(self, variant="normal", end="2026-09-14", mode="guarded"):
        q = Quotes(variant)
        with patch.dict(os.environ, {"RESEARCH_MODE":mode,"MAX_SPREAD_FRACTION":"0.2",
                "MAX_ENTRY_ASK_INCREASE":"0.25"}), patch.object(h, "features", side_effect=lambda x:x), \
                patch.object(h, "signal", side_effect=lambda r,s: bool(r.trigger)):
            result = h.simulate(Stocks(), q, "SPY", "2026-09-10", end, "momentum")
        return q, result

    def test_known_wide_spread_rejected(self):
        _, (t,e,s,m) = self.run_case("wide")
        self.assertEqual(len(t), 0)
        self.assertIn("no_entry_quality_quotes", set(s.reason))
        self.assertEqual(m["final_equity"], 2000.)

    def test_execution_spread_rechecked(self):
        _, (t,e,s,m) = self.run_case("entry_wide")
        self.assertEqual(len(t), 0)
        self.assertIn("execution_spread_exceeds_limit", set(s.reason))

    def test_ask_jump_skipped(self):
        _, (t,e,s,m) = self.run_case("jump")
        self.assertIn("entry_ask_increase_exceeds_limit", set(s.reason))

    def test_zero_bid_entry_rejected(self):
        _, (t,e,s,m) = self.run_case("zero")
        self.assertEqual(len(t), 0)

    def test_held_quote_missing_fails(self):
        with self.assertRaisesRegex(h.ResearchError, "missing_selected_or_held_contract"):
            self.run_case("missing_held")

    def test_date_mismatch_fails(self):
        with self.assertRaisesRegex(h.ResearchError, "quote_identity"):
            self.run_case("mismatch")

    def test_one_session_rejected(self):
        with self.assertRaisesRegex(h.ResearchError, "invalid_test_window_or_allocation"):
            self.run_case(end="2026-09-10")

    def test_reconciliation_fees_and_prior_only_selection(self):
        q, (t,e,s,m) = self.run_case()
        self.assertEqual(len(t), 1)
        self.assertAlmostEqual(float(t.pnl.sum()), m["final_equity"]-2000.)
        self.assertAlmostEqual(float(t.total_fees.sum()), 1.30)
        self.assertEqual(q.calls[0][1], "2026-09-09")
        self.assertTrue(all(c[2] == 100. for c in q.calls if c[1] > "2026-09-09"))
        self.assertEqual(t.iloc[0].exit_reason, "end_of_test")

    def test_baseline_preserves_wide_spread_cost(self):
        _, (t,e,s,m) = self.run_case("wide", mode="baseline")
        self.assertEqual(len(t), 1)
        self.assertAlmostEqual(float(t.iloc[0].pnl), -206.30)

    def test_bad_settings_rejected(self):
        with patch.dict(os.environ, {"MAX_SPREAD_FRACTION":"nan"}):
            with self.assertRaises(h.ResearchError):
                h.setting("MAX_SPREAD_FRACTION", .2, 0, 1)

    def test_invalid_quote_numbers(self):
        for bid,ask in ((float("nan"),1.),(2.,1.),(-1.,1.),(1.,float("inf"))):
            self.assertEqual(h.entry_reason(dict(bid=bid,ask=ask), .2), "invalid_quote")

    def test_quote_request_budget(self):
        q = h.BoundedQuotes({})
        q.audit = [{} for _ in range(400)]
        with self.assertRaisesRegex(h.ResearchError, "request_budget_exceeded"):
            q.fetch("SPY", "2026-09-10", 100.)


if __name__ == "__main__":
    unittest.main()
