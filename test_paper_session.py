"""Offline paper-adapter checks; no broker orders are submitted by tests."""
import os
import unittest
from unittest.mock import patch, Mock
import pandas as pd
import paper_session as p


class PaperTests(unittest.TestCase):
    def test_fresh_quote_and_spread(self):
        now = pd.Timestamp("2026-11-04T14:32:00Z")
        q = dict(t="2026-11-04T14:31:59Z",bp=1.9,ap=2.,**{"as":1})
        self.assertEqual(p.quote_values(q,now,entry=True),(1.9,2.))
        q["bp"] = .5
        with self.assertRaises(p.Halt):
            p.quote_values(q,now,entry=True)
        self.assertEqual(p.quote_values(q,now,entry=False),(.5,2.))

    def test_stale_future_and_nonfinite(self):
        now = pd.Timestamp("2026-11-04T14:32:00Z")
        for t,bid in (("2026-11-04T14:00:00Z",1.),("2026-11-04T14:33:00Z",1.),
                ("2026-11-04T14:31:59Z",float("nan"))):
            with self.assertRaises(p.Halt):
                p.quote_values(dict(t=t,bp=bid,ap=2.),now)

    def test_deterministic_order_identity(self):
        self.assertEqual(p.order_id("SPY","buy","2026-11-04"),p.order_id("SPY","buy","2026-11-04"))
        self.assertNotEqual(p.order_id("SPY","buy","2026-11-04"),p.order_id("QQQ","buy","2026-11-04"))

    def test_dry_run_never_calls_broker(self):
        client,log = Mock(),dict(actions=[])
        p.submit(client,log,dict(symbol="SPY",client_order_id="romie-test"),False,[],"test")
        client.request.assert_not_called()
        self.assertEqual(log["actions"][0]["action"],"dry_run_proposal")

    def test_duplicate_never_resubmits(self):
        client,log = Mock(),dict(actions=[])
        order = dict(symbol="SPY",client_order_id="romie-test")
        p.submit(client,log,order,True,[order],"test")
        client.request.assert_not_called()

    def test_closed_market_no_orders(self):
        client,log = Mock(),dict(actions=[],signals=[])
        client.request.side_effect=[dict(status="ACTIVE",id="paper-test"),
            dict(is_open=False,timestamp="2026-11-04T14:00:00Z")]
        with patch.dict(os.environ,{"PAPER_ORDERS_ENABLED":"false"}):
            p.cycle(client,log)
        self.assertEqual(log["status"],"market_closed_no_orders")
        self.assertEqual(client.request.call_count,2)

    def test_arming_requires_expected_account(self):
        client = Mock()
        client.request.return_value = dict(status="ACTIVE",id="other-account")
        with patch.dict(os.environ,{"PAPER_ORDERS_ENABLED":"true","PAPER_ACCOUNT_ID":"expected"}):
            with self.assertRaisesRegex(p.Halt,"account_id_not_verified"):
                p.cycle(client,dict(actions=[],signals=[]))

    def test_close_rechecked_before_post(self):
        client,log = Mock(),dict(actions=[])
        client.request.return_value=dict(is_open=False,timestamp="2026-11-04T21:00:00Z")
        with patch.dict(os.environ,{"PAPER_ARM_DATE":"2026-11-04"}):
            with self.assertRaises(p.Halt):
                p.submit(client,log,dict(symbol="SPY",client_order_id="romie-test"),True,[],"test")
        self.assertEqual(client.request.call_count,1)

    def test_real_money_host_not_configurable(self):
        self.assertEqual(p.PAPER,"https://paper-api.alpaca.markets")
        with patch.dict(os.environ,{"ALPACA_API_KEY":"fixture","ALPACA_SECRET_KEY":"fixture"}):
            client=p.Client()
        with self.assertRaises(p.Halt):
            client.request("/v2/account",method="POST",payload={})


if __name__ == "__main__":
    unittest.main()
