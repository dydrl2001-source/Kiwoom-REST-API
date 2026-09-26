import os,time,json,re
from datetime import datetime,timezone,timedelta
import psycopg

DB=os.getenv("DATABASE_URL","")
POLL=int(os.getenv("RESEARCH_POLL_SECONDS","30"))
MIN_SCORE=int(os.getenv("RESEARCH_MIN_SCORE","40"))
COOLDOWN_MIN=int(os.getenv("RESEARCH_COOLDOWN_MINUTES","15"))

def db(): return psycopg.connect(DB)

def f(v):
    try:return float(v)
    except:return None

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS research_jobs(
          id BIGSERIAL PRIMARY KEY,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          snapshot_time TIMESTAMPTZ,
          stock_code TEXT NOT NULL,
          stock_name TEXT,
          priority INTEGER NOT NULL,
          trigger_types JSONB NOT NULL DEFAULT '[]'::jsonb,
          status TEXT NOT NULL,
          context JSONB NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE INDEX IF NOT EXISTS idx_research_jobs_time ON research_jobs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_research_jobs_stock_time ON research_jobs(stock_code,created_at DESC);

        CREATE TABLE IF NOT EXISTS research_results(
          job_id BIGINT PRIMARY KEY REFERENCES research_jobs(id) ON DELETE CASCADE,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          mode TEXT NOT NULL,
          headline TEXT,
          summary TEXT,
          evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
          deep_research_needed BOOLEAN NOT NULL DEFAULT false
        );

        CREATE TABLE IF NOT EXISTS research_engine_status(
          id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
          updated_at TIMESTAMPTZ NOT NULL,status TEXT NOT NULL,
          last_success_at TIMESTAMPTZ,note TEXT,last_error TEXT
        );
        """);c.commit()

def status(st,note=None,error=None,success=False):
    with db() as c,c.cursor() as cur:
        cur.execute("""INSERT INTO research_engine_status(id,updated_at,status,last_success_at,note,last_error)
        VALUES(1,now(),%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,
        last_success_at=COALESCE(excluded.last_success_at,research_engine_status.last_success_at),
        note=excluded.note,last_error=excluded.last_error""",
        (st,datetime.now(timezone.utc) if success else None,note,error));c.commit()

def latest_maps(cur):
    ranks={};trades={}
    cur.execute("SELECT to_regclass('public.market_rank_snapshots')")
    if cur.fetchone()[0]:
        cur.execute("SELECT MAX(snapshot_time) FROM market_rank_snapshots");rt=cur.fetchone()[0]
        if rt:
            cur.execute("""SELECT stock_code,stock_name,rank_no,rank_change,change_rate,official_sector
                           FROM market_rank_snapshots WHERE snapshot_time=%s
                           ORDER BY rank_no NULLS LAST LIMIT 40""",(rt,))
            for x in cur.fetchall():
                ranks[x[0]]={"name":x[1],"rank":x[2],"rank_change":x[3],"change":f(x[4]),"sector":x[5],"time":rt}
    cur.execute("SELECT to_regclass('public.market_trade_value_snapshots')")
    if cur.fetchone()[0]:
        cur.execute("SELECT MAX(snapshot_time) FROM market_trade_value_snapshots");tt=cur.fetchone()[0]
        if tt:
            cur.execute("""SELECT stock_code,stock_name,rank_no,trade_value_krw,change_rate,market_cap_krw,official_sector
                           FROM market_trade_value_snapshots WHERE snapshot_time=%s
                           ORDER BY rank_no NULLS LAST LIMIT 60""",(tt,))
            for x in cur.fetchall():
                trades[x[0]]={"name":x[1],"rank":x[2],"value":f(x[3]),"change":f(x[4]),"cap":f(x[5]),"sector":x[6],"time":tt}
    return ranks,trades

def evidence_for(cur,code,name):
    out=[]
    cur.execute("SELECT to_regclass('public.stock_news_cache')")
    if cur.fetchone()[0]:
        cur.execute("""SELECT title,source,published_at,link FROM stock_news_cache
                       WHERE stock_code=%s AND COALESCE(published_at,fetched_at)>now()-interval '48 hours'
                       ORDER BY COALESCE(published_at,fetched_at) DESC LIMIT 5""",(code,))
        for x in cur.fetchall():
            out.append({"type":"news","title":x[0],"source":x[1],"time":x[2].isoformat() if x[2] else None,"link":x[3]})
    cur.execute("SELECT to_regclass('public.telegram_messages')")
    if cur.fetchone()[0] and name:
        cur.execute("""SELECT message_date,channel_name,text,message_url
                       FROM telegram_messages
                       WHERE collected_at>now()-interval '24 hours' AND text ILIKE %s
                       ORDER BY collected_at DESC LIMIT 5""",(f"%{name}%",))
        for x in cur.fetchall():
            txt=re.sub(r"\s+"," ",x[2] or "").strip()
            out.append({"type":"telegram","title":txt[:500],"source":x[1],"time":x[0].isoformat() if x[0] else None,"link":x[3]})
    cur.execute("SELECT to_regclass('public.dart_disclosures')")
    if cur.fetchone()[0]:
        cur.execute("""SELECT report_nm,category,rcept_dt,disclosure_url,flr_nm
                       FROM dart_disclosures
                       WHERE stock_code=%s AND rcept_dt>=current_date-interval '3 days'
                       ORDER BY rcept_dt DESC,rcept_no DESC LIMIT 8""",(code,))
        for x in cur.fetchall():
            out.append({"type":"dart","title":x[0],"source":"DART · "+str(x[1] or "DISCLOSURE"),
                        "time":x[2].isoformat() if x[2] else None,"link":x[3],"filer":x[4]})
    return out

def score_one(rank,trade,evidence):
    score=0;tr=[]
    r=rank.get("rank");rc=rank.get("rank_change");chg=rank.get("change")
    tv_rank=trade.get("rank");tv=trade.get("value")
    if r is not None and r<=5:score+=25;tr.append("조회 Top5")
    elif r is not None and r<=10:score+=18;tr.append("조회 Top10")
    if rc is not None and rc>=5:score+=18;tr.append("조회순위 급상승")
    elif rc is not None and rc>=3:score+=10;tr.append("조회순위 상승")
    if tv_rank is not None and tv_rank<=10:score+=28;tr.append("거래대금 Top10")
    elif tv_rank is not None and tv_rank<=20:score+=20;tr.append("거래대금 Top20")
    if chg is not None and abs(chg)>=20:score+=20;tr.append("등락폭 20%+")
    elif chg is not None and abs(chg)>=10:score+=12;tr.append("등락폭 10%+")
    dart_count=sum(1 for x in evidence if x.get("type")=="dart")
    if dart_count: score+=25;tr.append("DART 공시")
    if len(evidence)>=3:score+=12;tr.append("다채널/다기사")
    elif len(evidence)>=1:score+=6;tr.append("재료 후보")
    if tv_rank is not None and tv_rank<=20 and not evidence:
        score+=22;tr.append("돈 선행·재료 미확인")
    return min(100,score),tr

def recent_job_exists(cur,code):
    cur.execute("""SELECT 1 FROM research_jobs WHERE stock_code=%s AND created_at>now()-(%s||' minutes')::interval LIMIT 1""",
                (code,str(COOLDOWN_MIN)))
    return cur.fetchone() is not None

def synthesize(name,rank,trade,evidence,triggers,score):
    r=rank.get("rank");tv_rank=trade.get("rank")
    chg=rank.get("change") if rank.get("change") is not None else trade.get("change")
    headline=f"{name} · 조회 #{r if r is not None else '-'} · 대금 #{tv_rank if tv_rank is not None else '-'}"
    if chg is not None:headline+=f" · {chg:+.1f}%"
    dart_ev=[x for x in evidence if x.get("type")=="dart"]
    if dart_ev and tv_rank is not None and tv_rank<=20:
        summary="최근 DART 공시와 거래대금 상위권이 함께 포착됐습니다. 공시 성격, 발표 시점, 동종주 반응을 우선 검증할 가치가 있습니다."
    elif tv_rank is not None and tv_rank<=20 and not evidence:
        summary="거래대금이 먼저 강해졌지만 현재 수집 범위에서는 직접 연결되는 뉴스·Telegram·공시 재료를 찾지 못했습니다. 심층조사 우선순위를 높입니다."
    elif evidence and tv_rank is not None and tv_rank<=20:
        summary="재료 후보와 거래대금 상위권이 함께 확인됩니다. 기사·Telegram의 신규성, 동일 섹터 동반 움직임, 재탕 여부를 추가 검증할 가치가 있습니다."
    elif evidence:
        summary="재료 후보는 확인되지만 거래대금 최상위권 동행은 제한적입니다. 조회 관심이 실제 수급으로 확장되는지 관찰 대상입니다."
    else:
        summary="조회 관심이 포착됐지만 현재 수집 범위에서는 직접 재료가 뚜렷하지 않습니다."
    deep=bool(score>=70 or (tv_rank is not None and tv_rank<=20 and not evidence))
    return headline,summary,deep

def cycle():
    made=0
    with db() as c,c.cursor() as cur:
        ranks,trades=latest_maps(cur)
        codes=[]
        for code in list(ranks)+list(trades):
            if code not in codes:codes.append(code)
        if not codes:
            status("WAITING_FOR_MARKET_DATA","시장 데이터 대기");return
        for code in codes:
            rank=ranks.get(code,{})
            trade=trades.get(code,{})
            name=rank.get("name") or trade.get("name") or code
            ev=evidence_for(cur,code,name)
            score,triggers=score_one(rank,trade,ev)
            if score<MIN_SCORE or recent_job_exists(cur,code):
                continue
            snap=max([x for x in (rank.get("time"),trade.get("time")) if x],default=None)
            ctx={"rank":rank,"trade":trade,"evidence_count":len(ev)}
            cur.execute("""INSERT INTO research_jobs(snapshot_time,stock_code,stock_name,priority,trigger_types,status,context)
                           VALUES(%s,%s,%s,%s,%s::jsonb,'LOCAL_SYNTHESIZED',%s::jsonb) RETURNING id""",
                        (snap,code,name,score,json.dumps(triggers,ensure_ascii=False),json.dumps(ctx,ensure_ascii=False,default=str)))
            job=cur.fetchone()[0]
            headline,summary,deep=synthesize(name,rank,trade,ev,triggers,score)
            cur.execute("""INSERT INTO research_results(job_id,mode,headline,summary,evidence,deep_research_needed)
                           VALUES(%s,'LOCAL_RULES',%s,%s,%s::jsonb,%s)""",
                        (job,headline,summary,json.dumps(ev,ensure_ascii=False),deep))
            made+=1
        c.commit()
    status("OK",f"new_jobs={made}",success=True)

def main():
    schema();print(f"Research engine started: min_score={MIN_SCORE}, cooldown={COOLDOWN_MIN}m",flush=True)
    while True:
        try:cycle()
        except Exception as e:
            status("ERROR","리서치 큐 생성 오류",str(e)[:500]);print("research engine error",str(e)[:500],flush=True)
        time.sleep(POLL)

if __name__=="__main__":main()
