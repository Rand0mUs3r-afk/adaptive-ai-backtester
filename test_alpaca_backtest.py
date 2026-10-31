import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from alpaca_backtest import simulate, report

class MockAlpaca:
    def __init__(self, no_options=False, missing=False, declining=False):
        self.no_options, self.missing, self.declining = no_options, missing, declining
    def candidates(self, symbol, day, price):
        return [] if self.no_options else [dict(contract="TEST241220C00100000", expiry="2024-12-20", strike=100)]
    def bars(self, symbols, start, end, stock=False, **kwargs):
        dates = pd.bdate_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize())
        rows = []
        for day in dates:
            n = (day-pd.Timestamp("2024-05-01")).days
            price = max(.1, 2 + n*(-.02 if self.declining else .02))
            if not stock and self.missing and day == pd.Timestamp("2024-05-10"):
                continue
            rows.append(dict(date=day.date().isoformat(), symbol=symbols[0], open=100 if stock else price, high=101 if stock else price+.1, low=99 if stock else price-.1, close=100 if stock else price, volume=1000, slow=90, floor=80))
        return pd.DataFrame(rows)

class WorkflowTests(unittest.TestCase):
    def run_model(self, client, **kwargs):
        # Synthetic fixtures test accounting only; not actual trading performance.
        with patch("alpaca_backtest.features", side_effect=lambda x:x), patch("alpaca_backtest.signal", return_value=True):
            return simulate(client, "TEST", "2024-05-01", "2024-05-31", **kwargs)
    def test_reconciles_2000(self):
        t, e, skipped, m = self.run_model(MockAlpaca())
        self.assertGreater(len(t), 0)
        self.assertAlmostEqual(m["starting_equity"], 2000)
        self.assertAlmostEqual(t.pnl.sum(), m["equity_change"])
        self.assertAlmostEqual(e.equity.iloc[-1], m["final_equity"])
        self.assertTrue((t.entry_cost <= t.equity_before*.25+1e-8).all())
        self.assertTrue((e.cash >= 0).all())
        self.assertIn("Every closed trade", report(t,m,{}))
    def test_no_trades(self):
        t, e, skipped, m = self.run_model(MockAlpaca(no_options=True))
        self.assertTrue(t.empty)
        self.assertEqual(m["final_equity"], 2000)
        self.assertIsNone(m["win_rate_pct"])
    def test_missing_held_bar_fails(self):
        with self.assertRaises(ValueError):
            self.run_model(MockAlpaca(missing=True))
    def test_losses_reduce_equity(self):
        t, e, skipped, m = self.run_model(MockAlpaca(declining=True))
        self.assertGreater(len(t),0)
        self.assertLess(m["final_equity"],2000)
        self.assertLess(m["max_drawdown_pct"],0)
    def test_no_forced_affordability(self):
        t, e, skipped, m = self.run_model(MockAlpaca(), allocation=.001)
        self.assertTrue(t.empty)
        self.assertGreater(len(skipped),0)
    def test_rejects_bad_dates(self):
        with self.assertRaises(ValueError):
            simulate(MockAlpaca(), "TEST", "2020-01-01", "2020-01-31")

if __name__ == "__main__":
    unittest.main()
