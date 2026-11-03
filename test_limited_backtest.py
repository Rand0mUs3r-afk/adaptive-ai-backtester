"""Offline logic checks; these do not certify provider access or profitability."""
import unittest
from unittest.mock import patch
import pandas as pd
from limited_backtest import LimitedQuotes, target_strikes


class LimitedTests(unittest.TestCase):
    def test_fixed_grid(self):
        self.assertEqual(target_strikes(363.2), [360., 365., 370.])
        self.assertEqual(target_strikes(367.5), [365., 370., 375.])

    def test_invalid_reference(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                target_strikes(value)

    def test_keeps_prior_strikes_for_held_contracts(self):
        frames = {"TSLA": pd.DataFrame([dict(date="2026-09-10", close=363.2),
            dict(date="2026-09-11", close=390.)])}
        q = LimitedQuotes(frames)
        with patch.object(q, "fetch", return_value=[]) as fetch:
            self.assertEqual(q.chain("TSLA", "2026-09-10"), [])
            first = {call.args[2] for call in fetch.call_args_list}
            fetch.reset_mock()
            q.chain("TSLA", "2026-09-11")
            second = {call.args[2] for call in fetch.call_args_list}
        self.assertEqual(first, {360., 365., 370.})
        self.assertTrue(first.issubset(second))
        self.assertTrue({385., 390., 395.}.issubset(second))

    def test_missing_reference_fails(self):
        with self.assertRaises(ValueError):
            LimitedQuotes({}).chain("TSLA", "2026-09-10")

    def test_duplicate_quotes_conflict(self):
        q = LimitedQuotes({"TSLA": pd.DataFrame([dict(date="2026-09-10", close=363.2)])})
        with patch.object(q, "fetch", side_effect=[[dict(contract="same", bid=1)],
                [dict(contract="same", bid=2)], []]):
            with self.assertRaises(ValueError):
                q.chain("TSLA", "2026-09-10")


if __name__ == "__main__":
    unittest.main()
