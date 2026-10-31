import copy
import unittest
from unittest.mock import patch
import pandas as pd
from onclick_backtest import normalize, quantity, simulate

SAMPLE = {"osi-key":"TSLA--250117C00300000","ticker":"TSLA","date":"2025-01-13","expiration":"2025-01-17","strike":300,"type":"call","bid":103.25,"ask":104.65,"mark":103.95,"realistic_bid":1,"realistic_ask":1}

class Stocks:
    def bars(self,symbols,start,end,**kwargs):
        return pd.DataFrame([dict(date=d,symbol="TEST",close=100,slow=90,floor=80) for d in pd.bdate_range(start,end)])

class Quotes:
    def __init__(self,missing=False,expensive=False):
        self.missing,self.expensive=missing,expensive
    def chain(self,ticker,day):
        if self.missing and day=="2025-01-15":
            return []
        n=(pd.Timestamp(day)-pd.Timestamp("2025-01-01")).days
        ask=104.65 if self.expensive else 2+n*.01
        return [dict(contract="TEST250221C00100000",expiry="2025-02-21",strike=100,bid=ask-.1,ask=ask,date=day,provider="onclickmedia")]

class EODTests(unittest.TestCase):
    def test_supplied_schema_uses_raw_quotes(self):
        rows,rejected=normalize([SAMPLE],"TSLA","2025-01-13")
        self.assertEqual(rows[0]["contract"],"TSLA250117C00300000")
        self.assertEqual(rows[0]["bid"],103.25)
        self.assertEqual(rows[0]["ask"],104.65)
        self.assertEqual(rejected,0)
        self.assertEqual(quantity(rows[0]["ask"],2000,1),0)
    def test_wrong_date_fails(self):
        with self.assertRaises(ValueError):
            normalize([SAMPLE],"TSLA","2025-01-14")
    def test_crossed_quote_fails(self):
        r=copy.deepcopy(SAMPLE)
        r["bid"]=200
        with self.assertRaises(ValueError):
            normalize([r],"TSLA","2025-01-13")
    def test_zero_bid_allowed_for_losses(self):
        r=copy.deepcopy(SAMPLE)
        r["bid"]=0
        self.assertEqual(normalize([r],"TSLA","2025-01-13")[0][0]["bid"],0)
    def test_duplicate_fails(self):
        with self.assertRaises(ValueError):
            normalize([SAMPLE,SAMPLE],"TSLA","2025-01-13")
    def run_model(self,q):
        # Mock signals/quotes are software fixtures, not performance evidence.
        with patch("onclick_backtest.features",side_effect=lambda b:b),patch("onclick_backtest.signal",return_value=True):
            return simulate(Stocks(),q,"TEST","2025-01-13","2025-01-31")
    def test_bid_ask_accounting(self):
        t,e,s,m=self.run_model(Quotes())
        self.assertGreater(len(t),0)
        self.assertAlmostEqual(t.pnl.sum(),m["equity_change"])
        self.assertAlmostEqual(e.equity.iloc[-1],m["final_equity"])
        self.assertTrue((t.signal_date<t.entry_date).all())
        self.assertTrue((t.entry_date<t.exit_date).all())
        self.assertTrue((t.provider=="onclickmedia").all())
        self.assertTrue((t.entry_cost<=t.equity_before*.25+1e-8).all())
    def test_missing_held_quote_fails(self):
        with self.assertRaises(ValueError):
            self.run_model(Quotes(missing=True))
    def test_expensive_contracts_skipped(self):
        t,e,s,m=self.run_model(Quotes(expensive=True))
        self.assertTrue(t.empty)
        self.assertEqual(m["final_equity"],2000)
        self.assertGreater(len(s),0)

if __name__=="__main__":
    unittest.main()
