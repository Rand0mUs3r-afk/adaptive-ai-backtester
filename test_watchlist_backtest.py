import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import pandas as pd
from watchlist_backtest import read_watchlist,assess,active_subset,simulate

class Client:
    def bars(self,symbols,start,end,stock=False,**kwargs):
        if not stock:
            return pd.DataFrame(dict(volume=[500 if symbols[0].startswith("AAA") else 100]))
        return pd.DataFrame([dict(date=d,symbol=symbols[0],close=100,slow=90,floor=80) for d in pd.bdate_range(start,end)])
    def candidates(self,root,day,price):
        return [dict(contract=root+"250221C00100000")]

class Quotes:
    def chain(self,root,day):
        return [dict(contract=root+"250221C00100000",expiry="2025-02-21",strike=100,bid=2,ask=2.1,date=day,provider="onclickmedia")]

class WatchlistTests(unittest.TestCase):
    def test_file_only_parser_and_call_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"watchlist.txt"
            p.write_text("# comment\nMODE=active\nTOP=2\nAAA\nAAA\nBBB250221C00100000\n")
            roots,pins,mode,top,text=read_watchlist(p)
            self.assertEqual(roots,["AAA","BBB"])
            self.assertIsNone(pins["AAA"])
            self.assertIn("BBB250221C00100000",pins["BBB"])
            self.assertEqual((mode,top),("active",2))
    def test_empty_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"watchlist.txt"
            p.write_text("# empty")
            with self.assertRaises(ValueError):
                read_watchlist(p)
    def test_scoring_uses_triggered_rules_only(self):
        row=pd.Series(dict(slow=90,trending=True,volume=200,vavg=100,k=50))
        with patch("watchlist_backtest.signal",side_effect=lambda r,s:s in ("breakout","adaptive")):
            name,score,scores=assess(row)
            self.assertEqual(name,"breakout")
            self.assertEqual(score,85)
            self.assertEqual(scores["reversion"],0)
        with patch("watchlist_backtest.signal",return_value=False):
            self.assertIsNone(assess(row)[0])
    def test_prior_date_activity_ranking(self):
        frames={r:Client().bars([r],"2025-01-01","2025-01-31",stock=True) for r in ("AAA","BBB")}
        roots,ranks=active_subset(Client(),frames,["BBB","AAA"],dict(AAA=None,BBB=None),pd.Timestamp("2025-01-13"),1)
        self.assertEqual(roots,["AAA"])
        self.assertTrue(all(r["as_of"]<"2025-01-13" for r in ranks))
    def test_shared_2000_portfolio(self):
        # Mock prices/signals check software behavior, not profitability.
        with patch("watchlist_backtest.features",side_effect=lambda b:b),patch("watchlist_backtest.assess",return_value=("breakout",75,{"breakout":75})):
            t,e,a,s,m,roots,ranks=simulate(Client(),Quotes(),["AAA","BBB"],dict(AAA=None,BBB=None),"2025-01-13","2025-01-31")
        self.assertGreater(len(t),0)
        self.assertEqual(m["starting_equity"],2000)
        self.assertAlmostEqual(t.pnl.sum(),m["equity_change"])
        self.assertAlmostEqual(e.equity.iloc[-1],m["final_equity"])
        self.assertTrue((e.cash>=0).all())
        self.assertTrue((t.entry_cost<=t.equity_before*.25+1e-8).all())
        self.assertEqual(set(a.ticker),{"AAA","BBB"})
        for i in range(1,len(t)):
            self.assertGreater(t.entry_date.iloc[i],t.exit_date.iloc[i-1])

if __name__=="__main__":
    unittest.main()
