import os, json, time
from datetime import datetime, timezone, timedelta
import psycopg

DB=os.getenv("DATABASE_URL","")
POLL=int(os.getenv("REGIME_POLL_SECONDS","30"))
STALE=int(os.getenv("REGIME_STALE_SECONDS","120"))

def db(): return psycopg.connect(DB)

def n(v):
    try: return float(v) if v is not None else None
    except: return None

def share(a,b): return (float(a)/float(b)) if a is not None and b else None

def classify(m):
    reasons=[]
    idx=m.get("index_change")
    if idx is None: trend="UNKNOWN"; reasons.append("지수 데이터 부족")
    elif idx>=1: trend="RISING"; reasons.append(f"주요지수 {idx:.2f}%")
    elif idx<=-1: trend="FALLING"; reasons.append(f"주요지수 {idx:.2f}%")
    else: trend="RANGE_OR_MIXED"; reasons.append(f"주요지수 {idx:.2f}%")

    if m.get("largecap_share") is not None and m["largecap_share"]>=.55:
        flow="LARGE_CAP_CONCENTRATED"
    elif all(m.get(k) is not None for k in ("top_sector","top3_sector","turnover")) and (m["top_sector"]>=.35 or m["top3_sector"]>=.62) and m["turnover"]<=.45:
        flow="LEADER_CONCENTRATED"
    elif all(m.get(k) is not None for k in ("top_sector","top3_sector","turnover")) and m["top_sector"]<.25 and m["top3_sector"]<.50 and m["turnover"]>=.55:
        flow="ROTATIONAL_DISTRIBUTED"
    elif m.get("sector_count") is not None and m.get("turnover") is not None and m["sector_count"]>=7 and m["turnover"]>=.45:
        flow="BROAD_DISTRIBUTED"
    else:
        flow="TRANSITION_OR_MIXED"

    if m.get("positive_share") is None or m.get("avg_change") is None:
        sentiment="UNKNOWN"
    elif m["positive_share"]>=.70 and m["avg_change"]>=2:
        sentiment="STRONG"
    elif m["positive_share"]<=.40 or m["avg_change"]<0:
        sentiment="WEAK"
    else:
        sentiment="NORMAL"

    tm={"RISING":"상승","FALLING":"하락","RANGE_OR_MIXED":"횡보·혼합","UNKNOWN":"추세 미확인"}
    fm={"LEADER_CONCENTRATED":"주도주 집중","ROTATIONAL_DISTRIBUTED":"수급분산·시소타기","BROAD_DISTRIBUTED":"광범위 수급분산","LARGE_CAP_CONCENTRATED":"대형주 집중","TRANSITION_OR_MIXED":"전환·혼합"}
    sm={"STRONG":"투자심리 강함","NORMAL":"투자심리 보통","WEAK":"투자심리 위축","UNKNOWN":"심리 미확인"}
    return trend,flow,sentiment,f"{tm[trend]} / {fm[flow]} / {sm[sentiment]}",reasons

def ensure_schema():
    with db() as c, c.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS market_regime_snapshots(
          snapshot_time TIMESTAMPTZ PRIMARY KEY,
          candidate_trend_state TEXT,candidate_flow_state TEXT,candidate_sentiment_state TEXT,
          candidate_label TEXT,stable_label TEXT,confidence DOUBLE PRECISION,data_freshness_sec INTEGER,
          rank_turnover_5m DOUBLE PRECISION,top5_trade_share DOUBLE PRECISION,top10_trade_share DOUBLE PRECISION,
          top_sector_share DOUBLE PRECISION,top3_sector_share DOUBLE PRECISION,largecap_trade_share DOUBLE PRECISION,
          positive_rank_share DOUBLE PRECISION,avg_rank_change_rate DOUBLE PRECISION,sector_count_top20 INTEGER,
          explanation JSONB NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE TABLE IF NOT EXISTS market_regime_status(
          id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),updated_at TIMESTAMPTZ NOT NULL,status TEXT NOT NULL,
          last_market_data_at TIMESTAMPTZ,stable_label TEXT,candidate_label TEXT,candidate_count INTEGER NOT NULL DEFAULT 0,note TEXT
        );
        """)
        c.commit()

def latest(cur,table):
    cur.execute(f"SELECT MAX(snapshot_time) FROM {table}")
    return cur.fetchone()[0]

def compute():
    with db() as c, c.cursor() as cur:
        tables=["market_rank_snapshots","market_trade_value_snapshots","market_sector_snapshots","market_index_snapshots"]
        times=[]
        for t in tables:
            try:
                x=latest(cur,t)
                if x: times.append(x)
            except Exception:
                c.rollback()
        if not times:
            cur.execute("""INSERT INTO market_regime_status(id,updated_at,status,note)
                           VALUES(1,now(),'WAITING_FOR_MARKET_DATA','키움 시장 데이터 대기 중')
                           ON CONFLICT(id) DO UPDATE SET updated_at=now(),status='WAITING_FOR_MARKET_DATA',note=excluded.note""")
            c.commit(); return

        newest=max(times)
        freshness=max(0,int((datetime.now(timezone.utc)-newest).total_seconds()))
        status="STALE" if freshness>STALE else "OK"

        rt=latest(cur,"market_rank_snapshots")
        cur.execute("""SELECT stock_code,change_rate,market_cap_krw,official_sector FROM market_rank_snapshots
                       WHERE snapshot_time=%s ORDER BY rank_no NULLS LAST LIMIT 20""",(rt,))
        ranks=cur.fetchall()
        target=rt-timedelta(minutes=5)
        cur.execute("""SELECT snapshot_time FROM market_rank_snapshots WHERE snapshot_time<=%s GROUP BY snapshot_time
                       ORDER BY snapshot_time DESC LIMIT 1""",(target,))
        rr=cur.fetchone(); pt=rr[0] if rr else None
        prior=[]
        if pt:
            cur.execute("""SELECT stock_code FROM market_rank_snapshots WHERE snapshot_time=%s ORDER BY rank_no NULLS LAST LIMIT 20""",(pt,))
            prior=[x[0] for x in cur.fetchall()]
        nowcodes=[x[0] for x in ranks]
        turnover=None
        if prior:
            A,B=set(nowcodes),set(prior); U=A|B
            turnover=1-(len(A&B)/len(U) if U else 0)

        tt=latest(cur,"market_trade_value_snapshots")
        cur.execute("""SELECT trade_value_krw,market_cap_krw FROM market_trade_value_snapshots
                       WHERE snapshot_time=%s ORDER BY rank_no NULLS LAST LIMIT 20""",(tt,))
        trades=cur.fetchall()
        vals=[n(x[0]) or 0 for x in trades]; total=sum(vals)
        top5=share(sum(vals[:5]),total); top10=share(sum(vals[:10]),total)
        large=sum((n(v) or 0) for v,cap in trades if n(cap) is not None and n(cap)>=10_000_000_000_000)
        large_share=share(large,total)

        st=latest(cur,"market_sector_snapshots")
        cur.execute("""SELECT sector_name,trade_value_krw FROM market_sector_snapshots
                       WHERE snapshot_time=%s ORDER BY trade_value_krw DESC NULLS LAST""",(st,))
        sectors=cur.fetchall()
        sv=[(name,n(v) or 0) for name,v in sectors if name and (n(v) or 0)>0]
        stotal=sum(v for _,v in sv)
        top_sector=share(sv[0][1],stotal) if sv else None
        top3=share(sum(v for _,v in sv[:3]),stotal) if sv else None

        changes=[n(x[1]) for x in ranks if n(x[1]) is not None]
        positive=sum(1 for x in changes if x>0)/len(changes) if changes else None
        avg=sum(changes)/len(changes) if changes else None
        sector_count=len(set(x[3] for x in ranks if x[3])) if ranks else None

        it=latest(cur,"market_index_snapshots")
        cur.execute("""SELECT index_code,index_name,change_rate FROM market_index_snapshots
                       WHERE snapshot_time=%s""",(it,))
        idxrows=cur.fetchall(); idx=None
        for code,name,chg in idxrows:
            if str(code)=="001" or "KOSPI" in str(name).upper(): idx=n(chg); break
        if idx is None and idxrows: idx=n(idxrows[0][2])

        m={"turnover":turnover,"top_sector":top_sector,"top3_sector":top3,"largecap_share":large_share,
           "positive_share":positive,"avg_change":avg,"sector_count":sector_count,"index_change":idx}
        trend,flow,sent,label,reasons=classify(m)

        cur.execute("SELECT stable_label,candidate_label,candidate_count FROM market_regime_status WHERE id=1")
        p=cur.fetchone() or (None,None,0)
        cnt=(p[2]+1) if p[1]==label else 1
        stable=p[0] or label
        if cnt>=3: stable=label
        explanation={"reasons":reasons,"provisional_rules":True,
                     "self_feedback":"10거래일 이상 축적 후 시간대별 rolling percentile로 보정",
                     "top_sectors":[{"sector":x[0],"trade_value_krw":x[1]} for x in sv[:5]]}
        snap=datetime.now(timezone.utc).replace(microsecond=0)
        cur.execute("""INSERT INTO market_regime_snapshots VALUES
          (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT(snapshot_time) DO NOTHING""",
          (snap,trend,flow,sent,label,stable,.7,freshness,turnover,top5,top10,top_sector,top3,large_share,positive,avg,sector_count,json.dumps(explanation,ensure_ascii=False)))
        cur.execute("""INSERT INTO market_regime_status(id,updated_at,status,last_market_data_at,stable_label,candidate_label,candidate_count,note)
          VALUES(1,now(),%s,%s,%s,%s,%s,%s)
          ON CONFLICT(id) DO UPDATE SET updated_at=now(),status=excluded.status,last_market_data_at=excluded.last_market_data_at,
          stable_label=excluded.stable_label,candidate_label=excluded.candidate_label,candidate_count=excluded.candidate_count,note=excluded.note""",
          (status,newest,stable,label,cnt,"시장 데이터 정상" if status=="OK" else f"시장 데이터 {freshness}초 지연"))
        c.commit()

if __name__=="__main__":
    ensure_schema()
    print("Market Regime Engine started",flush=True)
    while True:
        try: compute()
        except Exception as e: print("regime error",str(e)[:500],flush=True)
        time.sleep(POLL)
