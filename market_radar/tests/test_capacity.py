import unittest

from ai_brokerage.capacity import (
    build_capacity_matrix,
    execution_adjusted_lifecycle,
    execution_adjusted_strategy_rows,
    strategy_capacity_rows,
)


def shadow_row(
    strategy_id="MR-T01",
    net=0.4,
    paper=0.6,
    drag=0.2,
    is_bps=20.0,
    notional=2_000_000,
    book_capacity=20_000_000,
    spread=8.0,
    regime="RISING",
):
    return {
        "strategy_id":strategy_id,
        "strategy_name":"테스트전략",
        "strategy_family":"REGIME_TREND",
        "status":"CLOSED",
        "entry_model_mode":"BOOK_V2",
        "regime_label":regime,
        "requested_notional_krw":notional,
        "entry_book_capacity_krw":book_capacity,
        "entry_spread_bps":spread,
        "entry_fill_ratio":1.0,
        "paper_return_pct":paper,
        "net_return_pct":net,
        "return_drag_pct":drag,
        "round_trip_is_bps":is_bps,
    }


class CapacityAnalyticsTests(unittest.TestCase):
    def test_capacity_matrix_uses_execution_context(self):
        rows=[shadow_row() for _ in range(5)]
        out=build_capacity_matrix(rows)
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["strategy_id"],"MR-T01")
        self.assertEqual(out[0]["regime"],"RISING")
        self.assertEqual(out[0]["liquidity"],"L3 20-50M")
        self.assertEqual(out[0]["spread"],"S2 5-15bp")
        self.assertEqual(out[0]["order_size"],"O1 <=2.5M")
        self.assertFalse(out[0]["small_sample"])

    def test_strategy_capacity_requires_book_sample_and_regime_diversity(self):
        rows=[]
        for i in range(20):
            rows.append(shadow_row(regime="RISING" if i<10 else "RANGE_OR_MIXED"))
        out=strategy_capacity_rows(rows,min_total_book_closed=20,min_bucket_closed=5,min_regimes=2)
        self.assertEqual(out[0]["state"],"EVIDENCE_SUPPORTED")
        self.assertEqual(out[0]["highest_supported_bucket"],"O1 <=2.5M")
        self.assertGreater(out[0]["evidence_capacity_krw"],0)
        self.assertFalse(out[0]["auto_apply"])

    def test_large_size_failure_is_not_promoted_as_capacity(self):
        rows=[]
        for i in range(20):
            rows.append(shadow_row(regime="RISING" if i<10 else "RANGE_OR_MIXED",notional=2_000_000))
        for i in range(8):
            rows.append(shadow_row(net=-0.5,paper=0.2,drag=0.7,is_bps=55,
                                   notional=7_000_000,book_capacity=30_000_000,
                                   regime="RISING" if i<4 else "RANGE_OR_MIXED"))
        out=strategy_capacity_rows(rows,min_total_book_closed=20,min_bucket_closed=5,min_regimes=2)
        self.assertEqual(out[0]["highest_supported_bucket"],"O1 <=2.5M")
        self.assertLessEqual(out[0]["evidence_capacity_krw"],2_500_000)

    def test_execution_adjusted_gate_blocks_weak_shadow(self):
        rows=[]
        for i in range(20):
            rows.append(shadow_row(net=-0.2,paper=0.5,drag=0.7,is_bps=45,
                                   regime="RISING" if i<10 else "RANGE_OR_MIXED"))
        exec_rows=execution_adjusted_strategy_rows(rows)
        caps=strategy_capacity_rows(rows,min_total_book_closed=20,min_bucket_closed=5,min_regimes=2)
        paper=[{
            "strategy_id":"MR-T01","name":"테스트전략","lifecycle":"PAPER",
            "action":"PROMOTE_CANDIDATE","label":"ACTIVE 승격 검토"
        }]
        out=execution_adjusted_lifecycle(paper,exec_rows,caps,min_shadow_closed=20)
        self.assertEqual(out[0]["action"],"EXECUTION_BLOCKED")
        self.assertFalse(out[0]["auto_apply"])

    def test_final_promotion_needs_execution_and_capacity(self):
        rows=[]
        for i in range(20):
            rows.append(shadow_row(regime="RISING" if i<10 else "RANGE_OR_MIXED"))
        # add a second order-size bucket so capacity has more than one tested size
        for i in range(8):
            rows.append(shadow_row(notional=4_000_000,book_capacity=30_000_000,
                                   regime="RISING" if i<4 else "RANGE_OR_MIXED"))
        exec_rows=execution_adjusted_strategy_rows(rows)
        caps=strategy_capacity_rows(rows,min_total_book_closed=20,min_bucket_closed=5,min_regimes=2)
        paper=[{
            "strategy_id":"MR-T01","name":"테스트전략","lifecycle":"PAPER",
            "action":"PROMOTE_CANDIDATE","label":"ACTIVE 승격 검토"
        }]
        out=execution_adjusted_lifecycle(paper,exec_rows,caps,min_shadow_closed=20)
        self.assertEqual(out[0]["action"],"PROMOTE_CANDIDATE_EXECUTION_ADJUSTED")
        self.assertTrue(all(out[0]["criteria"].values()))
        self.assertFalse(out[0]["auto_apply"])


if __name__=="__main__":
    unittest.main()
