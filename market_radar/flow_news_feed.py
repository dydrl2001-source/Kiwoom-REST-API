"""Round-robin public headlines for the observed universe; not an AI report."""
from datetime import datetime,timezone
import time
import news_feed as base
from flow_store import desk_payload,db


def setup():
    base.schema()
    with db() as c,c.cursor() as cur:
        cur.execute('''CREATE TABLE IF NOT EXISTS radar_news_checks(
           stock_code TEXT PRIMARY KEY,checked_at TIMESTAMPTZ NOT NULL,status TEXT NOT NULL)''')


def cycle():
    rows=[r for r in desk_payload()['rows'] if r.get('sector')!='ETF·ETN']
    if not rows:base.set_status('WAITING_FOR_MARKET_DATA','SOR 관측 표본 대기');return
    now=datetime.now(timezone.utc)
    with db(True) as c,c.cursor() as cur:
        cur.execute('SELECT stock_code,checked_at FROM radar_news_checks');seen={r['stock_code']:r['checked_at'] for r in cur.fetchall()}
    pending=[]
    for r in rows:
        age=(now-seen[r['code']]).total_seconds() if r['code'] in seen else 1e9
        period=300 if (r.get('burst_multiple') or 0)>=3 or (r.get('query_rank') or 999)<=10 else 900
        if age>=period:pending.append((age/period,r))
    pending.sort(key=lambda x:x[0],reverse=True)
    ok=bad=0
    for _,r in pending[:6]:
        status='OK'
        try:base.fetch_news(r['code'],r['name'],r.get('sector'));ok+=1
        except Exception as exc:status='ERROR';bad+=1;print('News fetch:',type(exc).__name__,flush=True)
        with db() as c,c.cursor() as cur:
            cur.execute('INSERT INTO radar_news_checks(stock_code,checked_at,status) VALUES(%s,now(),%s) '
                        'ON CONFLICT(stock_code) DO UPDATE SET checked_at=now(),status=excluded.status',(r['code'],status))
        time.sleep(.5)
    base.set_status('ERROR' if bad and not ok else 'PARTIAL' if bad else 'OK',f'headlines checked={ok} failed={bad}; source titles only',success=bool(ok))

if __name__=='__main__':
    setup()
    while True:
        try:cycle()
        except Exception as e:print('News cycle:',type(e).__name__,flush=True)
        time.sleep(30)
