import tempfile
import unittest
from unittest.mock import patch
from collector import AlphaVantage, collect, option_frame, stock_frame

class CollectorTests(unittest.TestCase):
    def test_key_required(self):
        with patch.dict("os.environ", {"ALPHAVANTAGE_API_KEY": ""}):
            with self.assertRaises(ValueError):
                AlphaVantage()

    def test_conversion(self):
        # Mock payload, not real financial data or performance evidence.
        payload = {"data": [dict(type="call", date="2020-01-02", symbol="IBM", contractID="IBM200117C00100000", bid="2", ask="2.1", expiration="2020-01-17", strike="100")]}
        q, excluded = option_frame(payload, "IBM", "2020-01-02")
        self.assertEqual(q.multiplier.iloc[0], 100)
        self.assertEqual(excluded, 0)
        payload["data"][0]["date"] = "2020-01-03"
        with self.assertRaises(ValueError):
            option_frame(payload, "IBM", "2020-01-02")

    def test_split_rejected(self):
        with self.assertRaises(ValueError):
            stock_frame({"Time Series (Daily)": {"2020-01-02": {"8. split coefficient": "2"}}}, "IBM", "2020-01-01", "2020-02-01")

    def test_today_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = AlphaVantage(key="mock-not-a-real-key", cache=tmp)
            with self.assertRaises(ValueError):
                collect(["IBM"], "2020-01-01", "2099-01-01", client=c)

    def test_provider_denial_not_cached(self):
        import io
        with tempfile.TemporaryDirectory() as tmp:
            c = AlphaVantage(key="mock-not-a-real-key", cache=tmp)
            with patch("collector.urlopen", return_value=io.BytesIO(b'{"Information":"premium required"}')):
                with self.assertRaises(ValueError):
                    c.get("HISTORICAL_OPTIONS", symbol="IBM", date="2020-01-02")
            self.assertEqual(list(c.cache.glob("*.json")), [])

if __name__ == "__main__":
    unittest.main()
