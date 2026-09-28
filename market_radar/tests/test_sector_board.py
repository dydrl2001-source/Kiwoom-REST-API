import os,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('DATABASE_URL','')
os.environ.setdefault('DASHBOARD_TOKEN','test')

import radar_api as api

class SectorBoardTests(unittest.TestCase):
    def row(self,name,sector,rank,tv,recent,chg,strength=0,summary=''):
        return {
            'name':name,'code':name[:6].ljust(6,'0'),'market_theme':sector,'official_sector':sector,
            'rank':rank,'rank_change':2,'trade_rank':rank,'trade_value_krw':tv,
            'recent_turnover_krw':recent,'recent_turnover_seconds':31.0,
            'change_rate':chg,'flow_state':'관찰','chart_state':'대기',
            'material_digest':{'material_strength':strength,'summary':summary or '미확인',
                               'assessment':'직접 재료 후보' if strength>=3 else ('테마·업종 재료' if strength==2 else '직접 재료 미확인'),
                               'source_kind':'뉴스'}
        }

    def test_stock_money_and_recent_money_are_kept(self):
        g=api.build_sector_groups([self.row('AAA','반도체',1,500_000_000_000,20_000_000_000,5.0)])[0]
        self.assertEqual(g['trade_value_krw'],500_000_000_000)
        self.assertEqual(g['recent_turnover_krw'],20_000_000_000)
        self.assertEqual(g['stocks'][0]['trade_value_krw'],500_000_000_000)
        self.assertEqual(g['stocks'][0]['recent_turnover_krw'],20_000_000_000)

    def test_multiple_direct_materials_are_supported_not_certain_causality(self):
        rows=[
          self.row('AAA','로봇',1,100,10,8.0,3,'공급계약 체결'),
          self.row('BBB','로봇',2,90,8,6.0,3,'신제품 양산'),
        ]
        g=api.build_sector_groups(rows)[0]
        self.assertEqual(g['reason']['level'],'SUPPORTED')
        self.assertIn('복수 종목',g['reason']['summary'])
        self.assertIn('인과관계 확정이 아님',g['reason']['note'])

    def test_no_material_stays_unconfirmed(self):
        rows=[self.row('AAA','전력',1,100,10,4.0,0,'미확인')]
        g=api.build_sector_groups(rows)[0]
        self.assertEqual(g['reason']['level'],'UNCONFIRMED')
        self.assertIn('공통 촉발 재료',g['reason']['summary'])

    def test_theme_strength_is_bounded_and_explained(self):
        rows=[
          self.row('AAA','반도체',1,500,50,8.0,3,'공급계약'),
          self.row('BBB','반도체',2,400,40,6.0,3,'양산'),
          self.row('CCC','로봇',8,100,5,1.0,0,'미확인'),
        ]
        groups=api.build_sector_groups(rows)
        semi=next(g for g in groups if g['name']=='반도체')
        self.assertGreaterEqual(semi['theme_strength'],0)
        self.assertLessEqual(semi['theme_strength'],100)
        self.assertIn('money',semi['theme_strength_components'])
        self.assertIn('수익확률이 아님',semi['theme_strength_note'])

    def test_top12_count_contributes_to_theme_strength(self):
        rows=[self.row('AAA','A',1,100,10,2.0),self.row('BBB','B',20,100,10,2.0)]
        groups=api.build_sector_groups(rows)
        a=next(g for g in groups if g['name']=='A')
        b=next(g for g in groups if g['name']=='B')
        self.assertEqual(a['surge_count'],1)
        self.assertEqual(b['surge_count'],0)
        self.assertGreater(a['theme_strength_components']['surge'],b['theme_strength_components']['surge'])

    def test_money_first_order_inside_sector(self):
        rows=[
          self.row('AAA','반도체',1,100,2,3.0),
          self.row('BBB','반도체',9,80,20,2.0),
        ]
        g=api.build_sector_groups(rows)[0]
        self.assertEqual(g['stocks'][0]['name'],'BBB')

class SectorUISourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=(ROOT/'radar_ui_v2.py').read_text(encoding='utf-8')

    def test_surge_sector_color_summary_exists(self):
        self.assertIn('homeSectorMix',self.text)
        self.assertIn('renderSectorMix',self.text)
        self.assertIn('sector-chip',self.text)

    def test_home_has_theme_strength(self):
        self.assertIn('실시간 테마·섹터 보드',self.text)
        self.assertIn('theme-strength',self.text)
        self.assertIn('strengthBlock',self.text)
        self.assertIn('테마강도 ',self.text)
        self.assertIn('sectorCards(homeThemes,8,true)',self.text)

    def test_sector_cards_show_money_and_reason(self):
        self.assertIn('recentMoney(x)',self.text)
        self.assertIn('왜 움직이나',self.text)
        self.assertIn('sector-reason',self.text)

if __name__=='__main__':
    unittest.main()
