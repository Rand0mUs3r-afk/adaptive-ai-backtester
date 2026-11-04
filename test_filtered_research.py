"""Offline policy tests; no broker or data requests."""
from pathlib import Path
from types import SimpleNamespace
import unittest
import pandas as pd
import filtered_research as p

ALL=("breakout","momentum","reversion","blend","adaptive","sma20_50_cross",
    "ema9_21_cross","macd_cross","rsi14_recovery","rsi2_pullback","donchian55",
    "bollinger_reentry","bollinger_breakout","keltner_breakout","stochastic_recovery",
    "roc20_trend","ema20_pullback","trend_vote","reversion_vote","regime_mix","volume_breakout")


class FilterTests(unittest.TestCase):
    def fixture(self):
        suite=SimpleNamespace(NAMES=ALL,NOTICE="original",checkpoints=[])
        def signals(raw):
            self.assertEqual(suite.NAMES,ALL)
            return pd.DataFrame({"sig_"+n:[True] for n in suite.NAMES})
        suite.signals=signals
        suite.checkpoint=lambda path,payload:suite.checkpoints.append(payload.copy())
        return suite

    def test_transitive_dependencies_disabled(self):
        excluded=set(p.excluded_names(ALL))
        self.assertEqual(len(excluded),9)
        self.assertTrue(set(p.BASE_DISABLED)<=excluded)
        self.assertTrue({"blend","adaptive","trend_vote","regime_mix"}<=excluded)
        self.assertNotIn("reversion_vote",excluded)

    def test_disabled_signals_cannot_leak_into_active_runs(self):
        suite=self.fixture()
        p.install(suite)
        frame=suite.signals(None)
        self.assertEqual(len(suite.NAMES),12)
        self.assertEqual(set(frame.columns),{"sig_"+n for n in suite.NAMES})
        self.assertNotIn("sig_breakout",frame)
        self.assertNotIn("sig_regime_mix",frame)
        self.assertEqual(suite.NAMES[:2],("momentum","reversion"))

    def test_policy_audit_counts_and_idempotence(self):
        suite=self.fixture()
        metadata=p.install(suite)
        self.assertEqual(metadata["simulations_per_symbol"],48)
        suite.checkpoint(Path("unused.json"),{})
        self.assertEqual(suite.checkpoints[-1]["research_policy"]["version"],p.VERSION)
        notice=suite.NOTICE
        p.install(suite)
        self.assertEqual(suite.NOTICE,notice)
        self.assertIn("no longer untouched validation",notice)

    def test_unexpected_definitions_fail_closed(self):
        suite=self.fixture()
        suite.NAMES=("reversion",)
        with self.assertRaises(ValueError):p.install(suite)


if __name__=="__main__":unittest.main()
