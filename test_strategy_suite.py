"""Synthetic OHLC fixtures test causality/logic only, never trading performance."""
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import strategy_suite as s


def bars(n=280):
    x=np.arange(n)
    c=100+x*.03+3*np.sin(x/4)
    return pd.DataFrame(dict(date=pd.bdate_range("2025-01-02",periods=n),symbol="SPY",
        open=c,high=c+1,low=c-1,close=c,volume=1000+x))


class SuiteTests(unittest.TestCase):
    def test_manifest_and_warmup(self):
        f=s.signals(bars())
        self.assertEqual(len(s.NAMES),21)
        self.assertEqual(len(set(s.NAMES)),21)
        for name in s.NAMES:
            self.assertEqual(f["sig_"+name].dtype,bool)
            self.assertFalse(f["sig_"+name].iloc[:199].any())

    def test_no_future_leakage(self):
        raw=bars()
        full=s.signals(raw)
        prefix=s.signals(raw.iloc[:240])
        pd.testing.assert_frame_equal(full[["sig_"+n for n in s.NAMES]].iloc[:240],
            prefix[["sig_"+n for n in s.NAMES]])

    def test_flat_rsi_is_finite(self):
        r=s.rsi(pd.Series([100.]*40),14).dropna()
        self.assertTrue((r==50).all())

    def test_up_down_rsi_boundaries(self):
        self.assertEqual(s.rsi(pd.Series(np.arange(50,dtype=float)),14).iloc[-1],100.)
        self.assertEqual(s.rsi(pd.Series(np.arange(50,0,-1,dtype=float)),14).iloc[-1],0.)

    def test_cross_requires_transition(self):
        self.assertEqual(s.cross(pd.Series([0,2,3]),pd.Series([1,1,1])).tolist(),[False,True,False])

    def test_separate_phase_windows(self):
        periods=s.windows("2026-08-03","2026-10-01","2026-10-30")
        self.assertLess(periods[0][2],periods[1][1])
        with self.assertRaises(ValueError):
            s.windows("2026-10-01","2026-08-03","2026-10-30")

    def test_checkpoint_strict_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"result.json"
            s.checkpoint(path,dict(status="completed"))
            with self.assertRaises(ValueError):
                s.checkpoint(path,dict(value=float("nan")))
            self.assertEqual(json.loads(path.read_text()),dict(status="completed"))

    def test_failing_request_is_not_retried_across_strategies(self):
        s.SuiteQuotes.shared,s.SuiteQuotes.failures,s.SuiteQuotes.network={},{},[]
        with patch.object(s.h.BoundedQuotes,"fetch",side_effect=ValueError("fixture")) as fetch:
            q=s.SuiteQuotes({})
            for _ in range(2):
                with self.assertRaises(Exception):
                    q.fetch("SPY","2026-09-10",100.)
            self.assertEqual(fetch.call_count,1)


if __name__=="__main__":
    unittest.main()
