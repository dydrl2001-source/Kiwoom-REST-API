import unittest

from ai_brokerage.allocation import (
    AllocationPolicy,
    correlation_matrix,
    optimize_allocations,
)


def candidate(
    code,
    theme="반도체",
    family="BREAKOUT",
    action="PROMOTE_CANDIDATE_EXECUTION_ADJUSTED",
    capacity_state="EVIDENCE_SUPPORTED",
    capacity=10_000_000,
    price=100_000,
    stop=2.0,
):
    return {
        "stock_code":code,
        "stock_name":code,
        "state":"PAPER_ENTRY",
        "conviction":82,
        "strategy_id":"MR-B01-"+code,
        "strategy_name":"테스트",
        "strategy_family":family,
        "strategy_fit":84,
        "market_theme":theme,
        "price_krw":price,
        "stop_pct":stop,
        "final_action":action,
        "capacity_state":capacity_state,
        "evidence_capacity_krw":capacity,
        "median_net_return_pct":0.45,
        "profit_factor":1.35,
        "positive_pct":58,
        "median_round_trip_is_bps":20,
        "median_return_drag_pct":0.20,
    }


class AllocationTests(unittest.TestCase):
    def test_total_and_theme_risk_caps_hold(self):
        p=AllocationPolicy(
            account_equity_krw=100_000_000,
            max_total_risk_pct=1.0,
            max_single_risk_pct=0.5,
            max_theme_risk_pct=0.6,
            max_family_risk_pct=1.0,
            max_positions=5,
            risk_chunk_pct=0.05,
        )
        rows=[candidate("A"),candidate("B"),candidate("C")]
        out=optimize_allocations(rows,{},[],p)
        total=sum(x["allocated_risk_krw"] for x in out["allocations"])
        self.assertLessEqual(total,600_000+1)
        self.assertLessEqual(total,1_000_000+1)

    def test_pending_strategy_gets_reduced_risk_budget(self):
        p=AllocationPolicy(
            account_equity_krw=100_000_000,
            max_total_risk_pct=2.0,
            max_single_risk_pct=0.5,
            max_theme_risk_pct=2.0,
            max_family_risk_pct=2.0,
            max_positions=5,
            risk_chunk_pct=0.01,
            pending_evidence_scale=0.35,
        )
        c=candidate("A",action="EXECUTION_GATE_PENDING",capacity_state="SAMPLE_BUILDING")
        c["evidence_capacity_krw"]=None
        c["point_in_time_capacity_krw"]=10_000_000
        out=optimize_allocations([c],{},[],p)
        self.assertEqual(len(out["allocations"]),1)
        self.assertLessEqual(out["allocations"][0]["allocated_risk_krw"],175_000+1)
        self.assertAlmostEqual(out["allocations"][0]["evidence_scale"],0.35)

    def test_execution_blocked_strategy_gets_no_allocation(self):
        c=candidate("A",action="EXECUTION_BLOCKED")
        out=optimize_allocations([c],{},[],AllocationPolicy())
        self.assertEqual(out["allocations"],[])
        reasons=sum(((x.get("reasons") or []) for x in out["rejected"]),[])
        self.assertIn("EVIDENCE_BLOCKED",reasons)

    def test_capacity_caps_position_risk(self):
        p=AllocationPolicy(
            account_equity_krw=100_000_000,
            max_total_risk_pct=2.0,
            max_single_risk_pct=1.0,
            max_theme_risk_pct=2.0,
            max_family_risk_pct=2.0,
            risk_chunk_pct=0.01,
        )
        c=candidate("A",capacity=2_000_000,stop=2.0)
        out=optimize_allocations([c],{},[],p)
        self.assertEqual(len(out["allocations"]),1)
        self.assertLessEqual(out["allocations"][0]["allocated_notional_krw"],2_000_000+1)
        self.assertLessEqual(out["allocations"][0]["allocated_risk_krw"],40_000+1)

    def test_high_correlation_reduces_second_name_budget(self):
        p=AllocationPolicy(
            account_equity_krw=100_000_000,
            max_total_risk_pct=1.0,
            max_single_risk_pct=0.5,
            max_theme_risk_pct=1.0,
            max_family_risk_pct=1.0,
            max_positions=2,
            risk_chunk_pct=0.05,
            correlation_penalty_weight=0.8,
        )
        rows=[candidate("A",theme="반도체A"),candidate("B",theme="반도체B")]
        low={"A":{"A":1.0,"B":0.0},"B":{"A":0.0,"B":1.0}}
        high={"A":{"A":1.0,"B":0.95},"B":{"A":0.95,"B":1.0}}
        out_low=optimize_allocations(rows,low,[],p)
        out_high=optimize_allocations(rows,high,[],p)
        low_map={x["stock_code"]:x["allocated_risk_krw"] for x in out_low["allocations"]}
        high_map={x["stock_code"]:x["allocated_risk_krw"] for x in out_high["allocations"]}
        self.assertLessEqual(high_map.get("B",0),low_map.get("B",0))

    def test_unknown_correlation_is_visible(self):
        p=AllocationPolicy(
            account_equity_krw=100_000_000,
            max_total_risk_pct=1.0,
            max_single_risk_pct=0.5,
            max_theme_risk_pct=1.0,
            max_family_risk_pct=1.0,
            max_positions=2,
            risk_chunk_pct=0.05,
        )
        out=optimize_allocations(
            [candidate("A",theme="A"),candidate("B",theme="B")],
            {"A":{"A":1.0,"B":None},"B":{"A":None,"B":1.0}},[],p
        )
        self.assertTrue(any(x.get("unknown_correlation_peers",0)>0 for x in out["allocations"]))

    def test_open_positions_reduce_available_slots(self):
        p=AllocationPolicy(max_positions=1)
        out=optimize_allocations(
            [candidate("A")],{},
            [{"stock_code":"OPEN","market_theme":"금융","strategy_family":"FLOW","risk_krw":100_000}],p
        )
        self.assertEqual(out["allocations"],[])

    def test_correlation_matrix_uses_aligned_returns(self):
        a={i:100+i for i in range(30)}
        b={i:200+2*i for i in range(30)}
        c={i:200-2*i for i in range(30)}
        m=correlation_matrix({"A":a,"B":b,"C":c},min_obs=20)
        self.assertGreater(m["A"]["B"],0.9)
        self.assertLess(m["A"]["C"],-0.9)


if __name__=="__main__":
    unittest.main()
