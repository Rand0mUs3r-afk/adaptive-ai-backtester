"""Regression: optional contract cells must not leak NaN into strict JSON."""
import json
import unittest
import pandas as pd
from limited_diagnostics import skip_records


class SerializationTests(unittest.TestCase):
    def test_reproduce_and_fix_optional_contract_nan(self):
        frame = pd.DataFrame([dict(date="2026-09-10", reason="no_entry_quality_quotes"),
            dict(date="2026-09-11", reason="execution_spread_exceeds_limit", contract="SPY261016C00100000")])
        with self.assertRaises(ValueError):
            json.dumps(frame.to_dict("records"), allow_nan=False)
        records = skip_records(frame)
        payload = json.loads(json.dumps(dict(diagnostics=[dict(skipped_entries=records)]), allow_nan=False))
        self.assertIsNone(payload["diagnostics"][0]["skipped_entries"][0]["contract"])
        self.assertEqual(records[1]["contract"], "SPY261016C00100000")
        self.assertEqual(records[0]["reason"], "no_entry_quality_quotes")

    def test_empty_skips(self):
        self.assertEqual(skip_records(pd.DataFrame(columns=["date","reason","contract"])), [])

    def test_absent_contract_column(self):
        self.assertEqual(skip_records(pd.DataFrame([dict(reason="no_returned_quotes")])),
            [dict(reason="no_returned_quotes")])

    def test_numeric_corruption_not_silently_sanitized(self):
        records = skip_records(pd.DataFrame([dict(contract=None, bid=float("nan"))]))
        with self.assertRaises(ValueError):
            json.dumps(records, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
