"""Offline rejection-classification tests, not market-performance tests."""
import unittest
from limited_diagnostics import selection_counts


class DiagnosticTests(unittest.TestCase):
    def test_rejection_reasons(self):
        quote = dict(expiry="2026-10-16", strike=100., ask=2.)
        cases = [([], "no_returned_quotes"),
            ([dict(quote, expiry="2026-09-11")], "no_30_60_dte_quotes"),
            ([dict(quote, strike=120.)], "no_strikes_within_10_percent"),
            ([dict(quote, ask=6.)], "premium_exceeds_allocation"),
            ([quote], "eligible_prior_quotes_present_check_entry_ask")]
        for rows, expected in cases:
            with self.subTest(expected=expected):
                result = selection_counts(rows, "2026-09-10", 100., 500.)
                self.assertEqual(result["detail_reason"], expected)
                self.assertEqual(result["returned_quotes"], len(rows))


if __name__ == "__main__":
    unittest.main()
