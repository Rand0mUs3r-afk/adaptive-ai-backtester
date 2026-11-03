"""Offline transport fixtures test diagnostics, never historical performance."""
from contextlib import contextmanager
from email.message import Message
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import pandas as pd
from onclick_backtest import Onclick, simulate
import watchlist_backtest as watchlist


SAMPLE = {"osi-key": "SPY--250221C00100000", "ticker": "SPY",
    "date": "2025-01-13", "expiration": "2025-02-21", "strike": 100,
    "type": "call", "bid": 2, "ask": 2.1}


def response(payload, content_type="application/json"):
    stream = BytesIO(json.dumps(payload).encode())
    stream.status = 200
    stream.headers = {"Content-Type": content_type}
    return stream


def http_error(code):
    headers = Message()
    headers["Content-Type"] = "application/json"
    return HTTPError("https://example.invalid/?apikey=DO_NOT_LOG", code,
        "DO_NOT_LOG", headers, BytesIO(b'{"error":"DO_NOT_LOG"}'))


class Stocks:
    def bars(self, symbols, start, end, **kwargs):
        return pd.DataFrame([dict(date=d, symbol=symbols[0], close=100,
            slow=90, floor=80) for d in pd.bdate_range(start, end)])


class ConnectionTests(unittest.TestCase):
    @contextmanager
    def transport(self, side_effect=None, result=None):
        with patch("onclick_backtest.time.sleep"), patch("onclick_backtest.urlopen",
                side_effect=side_effect, return_value=result) as opened:
            yield opened

    def test_success_headers_raw_prices_and_cache(self):
        q = Onclick()
        with self.transport(result=response([SAMPLE])) as opened:
            first = q.chain("SPY", "2025-01-13")
            self.assertIs(first, q.chain("SPY", "2025-01-13"))
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(opened.call_args.args[0].get_header("Accept"), "application/json")
        self.assertTrue(opened.call_args.args[0].get_header("User-agent"))
        self.assertEqual((first[0]["bid"], first[0]["ask"]), (2, 2.1))
        self.assertEqual(q.requests[0]["category"], "success")
        self.assertEqual(len(q.audit), 1)

    def test_permanent_http_errors_fail_once_without_leaking(self):
        for code in (401, 403, 404):
            with self.subTest(code=code), self.transport(side_effect=http_error(code)) as opened:
                q = Onclick()
                with self.assertRaisesRegex(ValueError, f"ticker=SPY, date=2025-01-13, HTTP={code}") as caught:
                    q.chain("SPY", "2025-01-13")
                self.assertEqual(opened.call_count, 1)
                self.assertNotIn("DO_NOT_LOG", str(caught.exception) + json.dumps(q.requests))
                self.assertEqual(q.requests[0]["category"], "http_error")
                self.assertEqual(q.requests[0]["content_type"], "application/json")
                self.assertEqual(q.audit, [])

    def test_transient_http_retries_then_success(self):
        with self.transport(side_effect=[http_error(429), http_error(503), response([SAMPLE])]) as opened:
            q = Onclick()
            q.chain("SPY", "2025-01-13")
        self.assertEqual(opened.call_count, 3)
        self.assertEqual([x["http_status"] for x in q.requests], [429, 503, 200])

    def test_network_error_is_bounded_and_redacted(self):
        with self.transport(side_effect=URLError("DO_NOT_LOG")) as opened:
            q = Onclick()
            with self.assertRaisesRegex(ValueError, "network_error") as caught:
                q.chain("SPY", "2025-01-13")
        self.assertEqual(opened.call_count, 3)
        self.assertNotIn("DO_NOT_LOG", str(caught.exception) + json.dumps(q.requests))

    def test_timeout_classification(self):
        with self.transport(side_effect=URLError(TimeoutError("DO_NOT_LOG"))):
            q = Onclick()
            with self.assertRaisesRegex(ValueError, "timeout"):
                q.chain("SPY", "2025-01-13")

    def test_invalid_json_fails_once(self):
        stream = BytesIO(b"<html>DO_NOT_LOG</html>")
        stream.status, stream.headers = 200, {"Content-Type": "text/html"}
        with self.transport(result=stream) as opened:
            q = Onclick()
            with self.assertRaisesRegex(ValueError, "invalid_json"):
                q.chain("SPY", "2025-01-13")
        self.assertEqual(opened.call_count, 1)
        self.assertNotIn("DO_NOT_LOG", json.dumps(q.requests))

    def test_unexpected_content_type_and_schema_fail_closed(self):
        cases = [([SAMPLE], "text/html", "unexpected_content_type"),
            ({"error": "DO_NOT_LOG"}, "application/json", "invalid_snapshot"),
            ([{"unexpected": "DO_NOT_LOG"}], "application/json", "invalid_snapshot")]
        for payload, content_type, category in cases:
            with self.subTest(category=category), self.transport(result=response(payload, content_type)):
                q = Onclick()
                with self.assertRaisesRegex(ValueError, category):
                    q.chain("SPY", "2025-01-13")
                self.assertEqual(q.audit, [])

    def test_invalid_request_parameters_make_no_network_call(self):
        with self.transport() as opened:
            for ticker, day in (("SPY?key=secret", "2025-01-13"), ("SPY", "2025-01-13&key=secret")):
                with self.assertRaises(ValueError):
                    Onclick().chain(ticker, day)
        opened.assert_not_called()

    def test_failed_preflight_persists_artifacts_with_unchecked_dates(self):
        q = Onclick()
        with self.transport(side_effect=http_error(404)):
            with self.assertRaises(ValueError):
                q.preflight({"SPY": ["2025-01-13", "2025-01-14"], "QQQ": ["2025-01-13"]})
        with tempfile.TemporaryDirectory() as tmp:
            q.save_diagnostics(tmp)
            audit = json.loads((Path(tmp)/"options_preflight.json").read_text())
            requests = json.loads((Path(tmp)/"options_request_diagnostics.json").read_text())
            self.assertEqual(audit["status"], "failed")
            self.assertEqual([r["status"] for r in audit["checks"]], ["failed", "not_checked", "not_checked"])
            self.assertEqual(requests[0]["http_status"], 404)
            self.assertEqual(json.loads((Path(tmp)/"quote_provenance.json").read_text()), [])

    def test_cli_failure_still_saves_diagnostics_and_no_performance(self):
        q = Onclick()
        with tempfile.TemporaryDirectory() as tmp:
            old = Path.cwd()
            try:
                os.chdir(tmp)
                Path("watchlist.txt").write_text("MODE=manual\nSPY\n")
                with self.transport(side_effect=http_error(403)), \
                        patch("sys.argv", ["watchlist_backtest.py", "--start", "2025-01-13", "--end", "2025-01-31"]), \
                        patch("watchlist_backtest.eod.Onclick", return_value=q), \
                        patch("watchlist_backtest.alpaca.Alpaca", return_value=Stocks()), \
                        patch("watchlist_backtest.features", side_effect=lambda b: b):
                    with self.assertRaises(SystemExit):
                        watchlist.main()
                self.assertIn("HTTP=403", Path("results/report.md").read_text())
                self.assertTrue(Path("results/options_request_diagnostics.json").exists())
                self.assertEqual(json.loads(Path("results/options_preflight.json").read_text())["status"], "failed")
                self.assertFalse(Path("results/summary.json").exists())
                self.assertFalse(Path("results/trades.csv").exists())
            finally:
                os.chdir(old)

    def test_successful_preflight_is_explicitly_sampled(self):
        q = Onclick()
        with patch.object(q, "chain", return_value=[SAMPLE]) as chain:
            q.preflight({"SPY": ["2025-01-13", "2025-01-13", "2025-01-14"]})
        self.assertEqual(chain.call_count, 2)
        self.assertEqual(q.preflight_audit["status"], "passed")
        self.assertIn("not complete", q.preflight_audit["scope"])

    def test_single_simulation_preflight_blocks_signals(self):
        q = Mock()
        q.preflight.side_effect = ValueError("Provider unavailable")
        with patch("onclick_backtest.features", side_effect=lambda b: b), patch("onclick_backtest.signal") as signal:
            with self.assertRaisesRegex(ValueError, "Provider unavailable"):
                simulate(Stocks(), q, "SPY", "2025-01-13", "2025-01-31", run_preflight=True)
        signal.assert_not_called()
        self.assertEqual(q.preflight.call_args.args[0]["SPY"], ["2025-01-10", "2025-01-13", "2025-01-31"])

    def test_watchlist_preflight_covers_every_root_and_blocks_trades(self):
        q = Mock()
        q.preflight.side_effect = ValueError("Provider unavailable")
        with patch("watchlist_backtest.features", side_effect=lambda b: b), patch("watchlist_backtest.assess") as assess:
            with self.assertRaisesRegex(ValueError, "Provider unavailable"):
                watchlist.simulate(Stocks(), q, ["SPY", "QQQ"], {"SPY": None, "QQQ": None},
                    "2025-01-13", "2025-01-31", run_preflight=True)
        assess.assert_not_called()
        checks = q.preflight.call_args.args[0]
        self.assertEqual(set(checks), {"SPY", "QQQ"})
        self.assertEqual(checks["QQQ"], ["2025-01-10", "2025-01-13", "2025-01-31"])


if __name__ == "__main__":
    unittest.main()
