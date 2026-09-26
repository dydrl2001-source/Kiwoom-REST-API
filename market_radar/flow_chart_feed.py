"""Prioritize viewed stock charts while keeping existing Kiwoom OHLCV retrieval."""
from datetime import datetime,timezone
import chart_feed as base
from flow_store import db,exists


def setup():
    with db() as c,c.cursor() as cur:
        cur.execute('''CREATE TABLE IF NOT EXISTS radar_chart_requests(
            stock_code TEXT PRIMARY KEY,requested_at TIMESTAMPTZ NOT NULL DEFAULT now())''')


def universe():
    codes=[]
    with db(True) as c,c.cursor() as cur:
        if exists(cur,'radar_chart_requests'):
            cur.execute("SELECT stock_code FROM radar_chart_requests WHERE requested_at>now()-interval '20 minutes' "
                        'ORDER BY requested_at DESC LIMIT 6')
            codes.extend(x['stock_code'] for x in cur.fetchall())
        for table in ('market_rank_snapshots','market_trade_value_snapshots'):
            if exists(cur,table):
                cur.execute(f'SELECT stock_code FROM {table} WHERE snapshot_time=(SELECT MAX(snapshot_time) FROM {table}) '
                            'ORDER BY rank_no NULLS LAST LIMIT 12')
                for r in cur.fetchall():
                    if r['stock_code'] not in codes:codes.append(r['stock_code'])
    return codes[:20]

if __name__=='__main__':
    setup();base.universe=universe;base.main()
