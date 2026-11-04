"""Offline source-table, inventory and summary semantics tests."""
import unittest
from unittest.mock import Mock
import expanded_universe as u


class UniverseTests(unittest.TestCase):
    def test_parse_and_deduplicate(self):
        html="<table><tr><th>No.</th><th>Symbol</th></tr><tr><td>1</td><td><a>AAPL</a></td></tr><tr><td>2</td><td>BRK.B</td></tr><tr><td>3</td><td>AAPL</td></tr></table>"
        self.assertEqual(u.parse_symbols(html,minimum=2),["AAPL","BRK.B"])
        with self.assertRaises(ValueError):u.parse_symbols(html)

    def test_missing_source_table_fails(self):
        with self.assertRaises(ValueError):u.parse_symbols("<table><tr><th>Price</th></tr></table>")

    def test_indices_are_not_claimed_optionless(self):
        for symbol in ("SPX","XSP"):
            self.assertEqual(u.inventory(Mock(),symbol,"2026-08-03","2026-10-30"),"unsupported_index_adapter")

    def test_share_class_not_silently_renamed(self):
        self.assertEqual(u.inventory(Mock(),"BRK.B","2026-08-03","2026-10-30"),"unsupported_share_class_symbol_adapter")

    def test_verified_standard_contract(self):
        client=Mock()
        client.get.return_value={"option_contracts":[dict(size="100",symbol="SPY261016C00100000")]}
        self.assertEqual(u.inventory(client,"SPY","2026-08-03","2026-10-30"),"options_inventory_verified")

    def test_no_inventory_differs_from_permission_error(self):
        client=Mock()
        client.get.return_value={"option_contracts":[]}
        self.assertEqual(u.inventory(client,"SPY","2026-08-03","2026-10-30"),"no_supported_calls_found_in_inventory_window")
        client.get.side_effect=ValueError("access denied fixture")
        with self.assertRaises(ValueError):u.inventory(client,"SPY","2026-08-03","2026-10-30")

    def test_capital_totals_not_one_shared_account(self):
        metrics=dict(starting_equity=2000.,final_equity=2100.,trades=3,wins=2,losses=1)
        runs=[dict(status="completed_with_trades",metrics=metrics)]*2
        result=u.totals(runs,2)
        self.assertEqual((result["starting_equity"],result["final_equity"],result["total_trades"],result["winning_trades"],result["lost_trades"]),(4000.,4200.,6,4,2))

    def test_incomplete_equity_is_not_zero(self):
        r=u.totals([dict(status="failed")],2)
        self.assertFalse(r["complete"])
        self.assertIsNone(r["starting_equity"])
        self.assertIsNone(r["final_equity"])


if __name__=="__main__":unittest.main()
