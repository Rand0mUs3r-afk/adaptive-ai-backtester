import unittest
import numpy as np
import pandas as pd
from engine import Config, backtest, features, prepare_quotes

class EngineTests(unittest.TestCase):
    def bars(self):
        # Synthetic fixtures for software tests ONLY; not performance evidence.
        n = 85
        c = np.arange(n, dtype=float) + 100
        return pd.DataFrame(dict(date=pd.bdate_range("2020-01-01", periods=n), symbol="TEST", open=c, high=c+0.2, low=c-0.2, close=c, volume=np.arange(n)+1000))

    def test_accounting(self):
        t, e, m = backtest(self.bars(), Config(strategy="breakout"))
        self.assertGreater(len(t), 0)
        self.assertAlmostEqual(t.pnl.sum(), m["net_profit"])
        self.assertEqual(e.positions.iloc[-1], 0)
        self.assertGreaterEqual(e.cash.min(), 0)
        self.assertTrue((t.exit > t.entry).all())

    def test_no_future_features(self):
        b = self.bars()
        a = features(b).iloc[:65].reset_index(drop=True)
        b.loc[65:, ["open", "high", "low", "close"]] *= 3
        pd.testing.assert_frame_equal(a, features(b).iloc[:65].reset_index(drop=True))

    def test_duplicate_rejected(self):
        b = self.bars()
        with self.assertRaises(ValueError):
            backtest(pd.concat([b, b.iloc[:1]]))

    def test_options_require_quotes(self):
        with self.assertRaises(ValueError):
            backtest(self.bars(), Config(instrument="call"))

    def test_options_accounting(self):
        b = self.bars()
        rows = []
        for i, d in enumerate(b.date):
            for strike in (100, 200, 300):
                rows.append(dict(date=d, symbol="TEST", contract=f"C{strike}", expiry="2021-01-01", strike=strike, right="C", bid=10+i/10, ask=10.1+i/10, multiplier=100))
        t, e, m = backtest(b, Config(strategy="breakout", instrument="call"), pd.DataFrame(rows))
        self.assertGreater(len(t), 0)
        self.assertAlmostEqual(t.pnl.sum(), m["net_profit"])

    def test_spread_accounting(self):
        b = self.bars()
        rows = []
        for i, d in enumerate(b.date):
            for strike in (100, 200, 300):
                premium = {100: 30, 200: 20, 300: 10}[strike] + i/100
                rows.append(dict(date=d, symbol="TEST", contract=f"C{strike}", expiry="2021-01-01", strike=strike, right="C", bid=premium, ask=premium+.1, multiplier=100))
        t, e, m = backtest(b, Config(strategy="breakout", instrument="call_spread"), pd.DataFrame(rows))
        self.assertGreater(len(t), 0)
        self.assertAlmostEqual(t.pnl.sum(), m["net_profit"])

if __name__ == "__main__":
    unittest.main()
