import unittest
from datetime import datetime, timezone
from pathlib import Path

from orderbook_collector import normalize_book


class OrderBookNormalizationTests(unittest.TestCase):
    def test_official_ka10004_fields_map_to_ten_levels(self):
        raw={
            "bid_req_base_tm":"101530",
            "sel_fpr_bid":"+101000","sel_fpr_req":"50",
            "buy_fpr_bid":"+100500","buy_fpr_req":"60",
            "tot_sel_req":"550","tot_buy_req":"660",
        }
        for i in range(2,11):
            raw[f"sel_{i}th_pre_bid"]=str(101000+(i-1)*500)
            raw[f"sel_{i}th_pre_req"]=str(50+i)
            raw[f"buy_{i}th_pre_bid"]=str(100500-(i-1)*500)
            raw[f"buy_{i}th_pre_req"]=str(60+i)
        out=normalize_book(raw,"005930","005930_AL",datetime.now(timezone.utc))
        self.assertEqual(out["venue"],"SOR")
        self.assertEqual(len(out["asks"]),10)
        self.assertEqual(len(out["bids"]),10)
        self.assertEqual(out["asks"][0]["price_krw"],101000)
        self.assertEqual(out["asks"][0]["qty"],50)
        self.assertEqual(out["bids"][0]["price_krw"],100500)
        self.assertEqual(out["bids"][0]["qty"],60)
        self.assertEqual(out["total_ask_qty"],550)
        self.assertEqual(out["total_bid_qty"],660)
        self.assertGreater(out["spread_bps"],0)
        self.assertEqual(out["book_time_raw"],"101530")

    def test_crossed_book_is_flagged(self):
        raw={
            "sel_fpr_bid":"100000","sel_fpr_req":"10",
            "buy_fpr_bid":"100500","buy_fpr_req":"10",
        }
        out=normalize_book(raw,"005930","005930_AL",datetime.now(timezone.utc))
        self.assertIn("CROSSED_BOOK",out["quality_flags"])

    def test_collector_is_read_only_ka10004(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/"orderbook_collector.py").read_text(encoding="utf-8")
        self.assertIn('"ka10004"',text)
        self.assertIn('"/api/dostk/mrkcond"',text)
        for banned in ("send_order","place_order","/api/dostk/ordr"):
            self.assertNotIn(banned,text)


if __name__=="__main__":
    unittest.main()
