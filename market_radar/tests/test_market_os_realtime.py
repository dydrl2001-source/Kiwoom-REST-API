import sys,unittest
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import kiwoom_realtime_0b as rt
import market_os_live_validation as live


class RealtimePureTests(unittest.TestCase):
    def test_price_sign_is_not_negative_price(self):
        self.assertEqual(rt.price('-82000'),82000)
        self.assertEqual(rt.code_of('005930_AL'),'005930')

    def test_observed_tick_builds_exact_value(self):
        a=rt.Aggregator()
        a.add({'type':'0B','item':'005930','values':{
            '10':'-80000','15':'+125','13':'1000','20':'103001',
            '228':'121.4','1032':'54.2','14':'12345','9081':'KRX'
        }},datetime(2026,9,28,1,30,1,tzinfo=timezone.utc))
        self.assertEqual(len(a.pending),1)
        p=next(iter(a.pending.values()))
        self.assertEqual(p['volume'],125)
        self.assertEqual(p['turnover'],10_000_000)
        self.assertEqual(p['buy_volume'],125)
        self.assertEqual(p['sell_volume'],0)
        self.assertEqual(p['ticks'],1)
        self.assertEqual(p['gaps'],0)

    def test_five_second_buckets_split_without_splitting_minute(self):
        a=rt.Aggregator()
        a.add({'type':'0B','item':'005930','values':{'10':'80000','15':'+10','13':'100','20':'103001'}},
              datetime(2026,9,28,1,30,1,tzinfo=timezone.utc))
        a.add({'type':'0B','item':'005930','values':{'10':'80100','15':'+10','13':'110','20':'103006'}},
              datetime(2026,9,28,1,30,6,tzinfo=timezone.utc))
        self.assertEqual(len(a.pending_minute),1)
        self.assertEqual(len(a.pending_5s),2)
        vals=sorted(a.pending_5s.values(),key=lambda x:x['bucket'])
        self.assertEqual(vals[0]['open'],80000)
        self.assertEqual(vals[1]['open'],80100)

    def test_reconnect_baseline_jump_is_not_live_gap(self):
        a=rt.Aggregator()
        a.last_cum['005930']=100
        a.baseline_codes.add('005930')
        t=datetime(2026,9,28,1,30,1,tzinfo=timezone.utc)
        a.add({'type':'0B','item':'005930','values':{'10':'80000','15':'+10','13':'140'}},t)
        p=next(iter(a.pending.values()))
        self.assertEqual(p['gaps'],0)
        self.assertEqual(a.total_gaps,0)
        a.add({'type':'0B','item':'005930','values':{'10':'80100','15':'+10','13':'180'}},t)
        p=next(iter(a.pending.values()))
        self.assertEqual(p['gaps'],1)
        self.assertEqual(a.total_gaps,1)

    def test_duplicate_cumulative_volume_is_skipped(self):
        a=rt.Aggregator()
        t=datetime(2026,9,28,1,30,1,tzinfo=timezone.utc)
        e={'type':'0B','item':'005930','values':{'10':'80000','15':'+10','13':'100'}}
        a.add(e,t);a.add(e,t)
        p=next(iter(a.pending.values()))
        self.assertEqual(p['ticks'],1)
        self.assertEqual(a.total_ticks,1)

    def test_gap_is_flagged_not_invented(self):
        a=rt.Aggregator();t=datetime(2026,9,28,1,30,1,tzinfo=timezone.utc)
        a.add({'type':'0B','item':'005930','values':{'10':'80000','15':'+10','13':'100'}},t)
        a.add({'type':'0B','item':'005930','values':{'10':'80100','15':'-10','13':'140'}},t)
        p=next(iter(a.pending.values()))
        self.assertEqual(p['gaps'],1)
        # Only received volume is counted; missing 30 shares are not fabricated.
        self.assertEqual(p['volume'],20)
        self.assertEqual(p['sell_volume'],10)

    def test_live_session_kst(self):
        self.assertEqual(live.market_session(datetime(2026,9,28,1,0,tzinfo=timezone.utc)),'SESSION')
        self.assertEqual(live.market_session(datetime(2026,9,27,1,0,tzinfo=timezone.utc)),'OFF_HOURS')


if __name__=='__main__':
    unittest.main()
