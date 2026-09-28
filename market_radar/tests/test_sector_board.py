import os,sys,unittest
from unittest.mock import patch
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('DATABASE_URL','')
os.environ.setdefault('DASHBOARD_TOKEN','test')

import radar_api as api
import evidence_identity as identity

class SectorBoardTests(unittest.TestCase):
    def row(self,name,sector,rank,tv,recent,chg,strength=0,summary=''):
        return {
            'name':name,'code':name[:6].ljust(6,'0'),'market_theme':sector,'official_sector':sector,
            'rank':rank,'rank_change':2,'trade_rank':rank,'trade_value_krw':tv,
            'recent_turnover_krw':recent,'recent_turnover_seconds':31.0,
            'change_rate':chg,'flow_state':'관찰','chart_state':'대기',
            'material_digest':{'material_strength':strength,'summary':summary or '미확인',
                               'assessment':'직접 재료 후보' if strength>=3 else ('테마·업종 재료' if strength==2 else '직접 재료 미확인'),
                               'source_kind':'뉴스','identity_quality':'VERIFIED','material_type':'수주·공급계약' if strength>=3 else '기타·미확인'}
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
        self.assertEqual(g['reason']['level'],'PARTIAL')
        self.assertEqual(g['reason']['label'],'복수 개별재료')
        self.assertIn('공통 원인으로 확정하지 않음',g['reason']['summary'])
        self.assertIn('공통 인과는 별개',g['reason']['note'])

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

    def test_material_type_contract(self):
        cat={'best_text':'대규모 공급계약 체결','dart':[],'external_news':[]}
        self.assertEqual(api.classify_material_type(cat),'수주·공급계약')

    def test_material_type_external_report_can_override_local_generic(self):
        cat={'best_text':'회사 관련 뉴스','dart':[],'external_news':[]}
        self.assertEqual(api.classify_material_type(cat,'승인·임상'),'승인·임상')

    def test_rank_movement_up_down_new_reentry(self):
        row={'code':'000001','rank':3}
        api.apply_rank_movement(row,{'000001':{'rank_30s':8,'rank_5m':12,'best_today':2}})
        self.assertEqual(row['rank_history']['movement'],'▲5')
        row={'code':'000002','rank':7}
        api.apply_rank_movement(row,{'000002':{'rank_30s':4,'best_today':4}})
        self.assertEqual(row['rank_history']['movement'],'▼3')
        row={'code':'000003','rank':9}
        api.apply_rank_movement(row,{'000003':{'rank_30s':None,'rank_5m':None,'had_earlier':False}})
        self.assertEqual(row['rank_history']['movement'],'NEW')
        row={'code':'000004','rank':10}
        api.apply_rank_movement(row,{'000004':{'rank_30s':None,'rank_5m':None,'had_earlier':True}})
        self.assertEqual(row['rank_history']['movement'],'RE')

    def test_leader_desk_filters_four_percent_and_groups_themes(self):
        trade={
          '000001':{'name':'A','rank':1,'trade_value':500,'change_rate':8.0,'current_price':1000,'theme':'반도체','sector':'전기전자'},
          '000002':{'name':'B','rank':2,'trade_value':400,'change_rate':5.0,'current_price':2000,'theme':'반도체','sector':'전기전자'},
          '000003':{'name':'C','rank':3,'trade_value':300,'change_rate':3.9,'current_price':3000,'theme':'로봇','sector':'기계'},
          '000004':{'name':'TIGER 테스트','rank':4,'trade_value':200,'change_rate':12.0,'current_price':4000,'theme':'ETF','sector':'ETF'},
        }
        rows=[{'code':'000001','market_theme':'반도체','rank':3,'rank_history':{'movement':'▲2'}},
              {'code':'000002','market_theme':'반도체','rank':6,'rank_history':{'movement':'NEW'}}]
        with patch.object(api,'build_leader_calendar',return_value={'cells':[],'observed_days':0}):
            out=api.build_leader_desk(None,trade,rows,api.datetime.now(api.timezone.utc))
        self.assertEqual(len(out['strong_stocks']),2)
        self.assertEqual(out['leading_sectors'][0]['name'],'반도체')
        self.assertEqual(out['leading_sectors'][0]['count'],2)
        self.assertEqual(out['threshold_pct'],4)

    def test_remedy_game_article_is_entity_conflict(self):
        title="레메디 신작 '컨트롤 레조넌트' 글로벌 출시…뒤틀린 맨해튼서 초자연적 액션"
        self.assertEqual(identity.identity_quality('레메디',title,'NEWS','의료/정밀기기'),'ENTITY_CONFLICT')
        self.assertFalse(identity.usable_as_catalyst('ENTITY_CONFLICT'))

    def test_ticker_list_is_not_direct_catalyst(self):
        text="9/28 특징 상한가 및 급등종목 +30.00% HLB +25.52% 쓰리빌리언"
        self.assertEqual(identity.identity_quality('쓰리빌리언',text,'Telegram','제약'),'LIST_MENTION')
        self.assertFalse(identity.usable_as_catalyst('LIST_MENTION'))

    def test_unverified_hbm_text_cannot_override_official_sector(self):
        cat={'material_strength':3,'best_identity_quality':'NAME_MATCH','theme':'반도체/HBM'}
        self.assertEqual(api.choose_market_theme('한국비엔씨','제약',cat),'제약')

    def test_verified_stock_context_can_supply_theme(self):
        cat={'material_strength':3,'best_identity_quality':'CONTEXT_VERIFIED','theme':'반도체/HBM'}
        self.assertEqual(api.choose_market_theme('테스트기업','전기전자',cat),'반도체/HBM')

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
        self.assertIn('상세 테마·섹터',self.text)
        self.assertIn('theme-strength',self.text)
        self.assertIn('strengthBlock',self.text)
        self.assertIn('테마강도 ',self.text)
        self.assertIn('sectorCards(homeThemes,4,true)',self.text)

    def test_home_material_colors_and_os_exist(self):
        self.assertIn('homeMaterialLegend',self.text)
        self.assertIn('materialTone',self.text)
        self.assertIn('mt-contract',self.text)
        self.assertIn('mt-earnings',self.text)
        self.assertIn('osMini',self.text)
        self.assertIn('sourceMini',self.text)

    def test_home_rank_history_and_density(self):
        self.assertIn('rankMovement',self.text)
        self.assertIn('sectorCards(homeThemes,4,true)',self.text)
        self.assertIn('.sector-grid{grid-template-columns:1fr;gap:7px}',self.text)

    def test_reference_style_leader_desk_is_on_home(self):
        self.assertIn('오늘 주도 흐름',self.text)
        self.assertIn('homeLeaderSectors',self.text)
        self.assertIn('homeStrongTurnover',self.text)
        self.assertIn('homeLeaderCalendar',self.text)
        self.assertIn('renderLeaderSectors',self.text)
        self.assertIn('renderStrongTurnover',self.text)
        self.assertIn('renderLeaderCalendar',self.text)

    def test_home_v3_compact_market_and_candidates(self):
        self.assertIn('오늘 장',self.text)
        self.assertIn('상세 시장 해석',self.text)
        self.assertIn('관찰 후보 Top5',self.text)
        self.assertIn('homeCandidates',self.text)
        self.assertIn('renderHomeCandidates',self.text)

    def test_sector_cards_show_money_and_reason(self):
        self.assertIn('recentMoney(x)',self.text)
        self.assertIn('왜 움직이나',self.text)
        self.assertIn('sector-reason',self.text)

if __name__=='__main__':
    unittest.main()
