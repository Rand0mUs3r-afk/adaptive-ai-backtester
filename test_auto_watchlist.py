import unittest
from unittest.mock import patch
import pandas as pd
from auto_watchlist import choose_feed

class Client:
    def __init__(self,fail=(),empty=()):
        self.fail,self.empty,self.calls=fail,empty,[]
    def bars(self,roots,start,end,stock=False,stock_feed="iex"):
        self.calls.append(stock_feed)
        if stock_feed in self.fail:
            raise ValueError("Alpaca HTTP 403; unavailable")
        dates=pd.bdate_range(start,end) if stock_feed not in self.empty else pd.DatetimeIndex([])
        return pd.DataFrame({"date":dates})

class AutoFeedTests(unittest.TestCase):
    def pick(self,client):
        # Mock data tests selection policy, not actual entitlements or P&L.
        with patch("auto_watchlist.features",side_effect=lambda b:b):
            return choose_feed(client,["SPY"],"2025-01-01","2025-01-31")
    def test_prefers_available_sip(self):
        c=Client()
        selected,audit=self.pick(c)
        self.assertEqual(selected,"sip")
        self.assertEqual(c.calls,["sip"])
    def test_falls_back_to_iex(self):
        selected,audit=self.pick(Client(fail=("sip",)))
        self.assertEqual(selected,"iex")
        self.assertEqual([a["feed"] for a in audit],["sip","iex"])
    def test_both_unavailable(self):
        selected,audit=self.pick(Client(fail=("sip","iex")))
        self.assertIsNone(selected)
        self.assertEqual(len(audit),2)
    def test_empty_sip_falls_back(self):
        self.assertEqual(self.pick(Client(empty=("sip",)))[0],"iex")
    def test_bad_credentials_not_feed_issue(self):
        c=Client()
        with patch.object(c,"bars",side_effect=ValueError("Alpaca HTTP 401")):
            selected,audit=self.pick(c)
        self.assertIsNone(selected)
        self.assertEqual(len(audit),1)

if __name__=="__main__":
    unittest.main()
