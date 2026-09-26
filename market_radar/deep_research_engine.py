import os,time,json,re
from datetime import datetime,timezone,timedelta
import psycopg

DB=os.getenv("DATABASE_URL","")
POLL=int(os.getenv("DEEP_RESEARCH_POLL_SECONDS","20"))
MIN_PRIORITY=int(os.getenv("DEEP_RESEARCH_MIN_PRIORITY","60"))
LOOKBACK_HOURS=int(os.getenv("DEEP_RESEARCH_LOOKBACK_HOURS","24"))

def db(): return psycopg.connect(DB)

def f(v):
    try:return float(v)
    except:return None

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS deep_research_reports(
          job_id BIGINT PRIMARY KEY REFERENCES research_jobs(id) ON DELETE CASCADE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          stock_code TEXT NOT NULL,
          stock_name TEXT,
          priority INTEGER,
          confidence INTEGER,
          headline TEXT,
          why_now TEXT,
          catalyst_summary TEXT,
          market_response TEXT,
          sector_confirmation TEXT,
          mimosa_summary TEXT,
          risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
          evidence_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
          agent_outputs JSONB NOT NULL DEFAULT '{}'::jsonb,
          report_version TEXT NOT NULL DEFAULT 'local-multiagent-v1'
        );
        CREATE INDEX IF NOT EXISTS idx_deep_reports_time ON deep_research_reports(created_at DESC);

        CREATE TABLE IF NOT EXISTS deep_research_status(
          id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
          updated_at TIMESTAMPTZ NOT NULL,status TEXT NOT NULL,
          last_success_at TIMESTAMPTZ,note TEXT,last_error TEXT
        );
        """);c.commit()

def status(st,note=None,error=None,success=False):
    with db() as c,c.cursor() as cur:
        cur.execute("""INSERT INTO deep_research_status(id,updated_at,status,last_success_at,note,last_error)
        VALUES(1,now(),%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,
        last_success_at=COALESCE(excluded.last_success_at,deep_research_status.last_success_at),
        note=excluded.note,last_error=excluded.last_error""",
        (st,datetime.now(timezone.utc) if success else None,note,error));c.commit()

def one(cur,sql,args=()):
    cur.execute(sql,args);return cur.fetchone()

def many(cur,sql,args=()):
    cur.execute(sql,args);return cur.fetchall()

def rank_agent(cur,code):
    rows=many(cur,"""SELECT snapshot_time,rank_no,rank_change,change_rate
                     FROM market_rank_snapshots
                     WHERE stock_code=%s AND snapshot_time>now()-interval '2 hours'
                     ORDER BY snapshot_time ASC""",(code,))
    if not rows:return {"available":False}
    latest=rows[-1]
    first=rows[0]
    ranks=[x[1] for x in rows if x[1] is not None]
    return {
      "available":True,"latest_rank":latest[1],"latest_rank_change":latest[2],"change_rate":f(latest[3]),
      "best_rank":min(ranks) if ranks else None,"first_rank":first[1],
      "rank_delta":(first[1]-latest[1]) if first[1] is not None and latest[1] is not None else None,
      "samples":len(rows)
    }

def money_agent(cur,code):
    rows=many(cur,"""SELECT snapshot_time,rank_no,trade_value_krw,change_rate,market_cap_krw
                     FROM market_trade_value_snapshots
                     WHERE stock_code=%s AND snapshot_time>now()-interval '2 hours'
                     ORDER BY snapshot_time ASC""",(code,))
    if not rows:return {"available":False}
    latest=rows[-1]
    vals=[f(x[2]) for x in rows if f(x[2]) is not None]
    cap=f(latest[4]);value=f(latest[2])
    return {
      "available":True,"trade_rank":latest[1],"trade_value":value,"change_rate":f(latest[3]),
      "trade_to_cap_pct":(value/cap*100) if value is not None and cap else None,
      "value_growth_pct":((vals[-1]/vals[0]-1)*100) if len(vals)>=2 and vals[0] else None,
      "samples":len(rows)
    }

def disclosure_agent(cur,code):
    rows=[]
    cur.execute("SELECT to_regclass('public.dart_disclosures')")
    if cur.fetchone()[0]:
        rows=many(cur,"""SELECT report_nm,category,rcept_dt,disclosure_url,flr_nm
                         FROM dart_disclosures
                         WHERE stock_code=%s AND rcept_dt>=current_date-interval '5 days'
                         ORDER BY rcept_dt DESC,rcept_no DESC LIMIT 10""",(code,))
    items=[{"title":x[0],"category":x[1],"date":x[2].isoformat() if x[2] else None,"url":x[3],"filer":x[4]} for x in rows]
    return {"count":len(items),"items":items}

def news_agent(cur,code):
    rows=[]
    cur.execute("SELECT to_regclass('public.stock_news_cache')")
    if cur.fetchone()[0]:
        rows=many(cur,"""SELECT title,source,published_at,link
                         FROM stock_news_cache
                         WHERE stock_code=%s AND COALESCE(published_at,fetched_at)>now()-interval '48 hours'
                         ORDER BY COALESCE(published_at,fetched_at) DESC LIMIT 10""",(code,))
    items=[{"title":x[0],"source":x[1],"time":x[2].isoformat() if x[2] else None,"url":x[3]} for x in rows]
    return {"count":len(items),"items":items}

def telegram_agent(cur,name):
    if not name:return {"count":0,"channels":0,"items":[]}
    rows=[]
    cur.execute("SELECT to_regclass('public.telegram_messages')")
    if cur.fetchone()[0]:
        rows=many(cur,"""SELECT message_date,channel_name,text,message_url
                         FROM telegram_messages
                         WHERE collected_at>now()-interval '24 hours' AND text ILIKE %s
                         ORDER BY collected_at DESC LIMIT 20""",(f"%{name}%",))
    items=[]
    for x in rows:
        text=re.sub(r"\s+"," ",x[2] or "").strip()
        items.append({"time":x[0].isoformat() if x[0] else None,"channel":x[1],"text":text[:800],"url":x[3]})
    return {"count":len(items),"channels":len(set(x["channel"] for x in items if x["channel"])),"items":items}

def mimosa_agent(cur,code):
    chart=None
    cur.execute("SELECT to_regclass('public.chart_states')")
    if cur.fetchone()[0]:
        x=one(cur,"""SELECT state,state_ko,score,minute_trend,daily_context,reasons,snapshot_time
                     FROM chart_states WHERE stock_code=%s ORDER BY snapshot_time DESC LIMIT 1""",(code,))
        if x:chart={"state":x[0],"state_ko":x[1],"score":f(x[2]),"minute_trend":x[3],"daily_context":x[4],
                    "reasons":x[5] or [],"time":x[6].isoformat() if x[6] else None}
    strategies={}
    cur.execute("SELECT to_regclass('public.mimosa_strategy_signals')")
    if cur.fetchone()[0]:
        rows=many(cur,"""SELECT DISTINCT ON (strategy) strategy,state,state_ko,score,metrics,reasons,source_note,snapshot_time
                         FROM mimosa_strategy_signals WHERE stock_code=%s
                         ORDER BY strategy,snapshot_time DESC""",(code,))
        for x in rows:
            strategies[x[0]]={"state":x[1],"state_ko":x[2],"score":f(x[3]),"metrics":x[4] or {},
                              "reasons":x[5] or [],"source_note":x[6],"time":x[7].isoformat() if x[7] else None}
    return {"chart":chart,"strategies":strategies}

def sector_agent(cur,code):
    x=one(cur,"""SELECT stock_name,COALESCE(market_theme,official_sector),snapshot_time
                 FROM market_rank_snapshots WHERE stock_code=%s
                 ORDER BY snapshot_time DESC LIMIT 1""",(code,))
    if not x:return {"theme":None,"peers":[]}
    name,theme,tm=x
    peers=[]
    if theme:
        rows=many(cur,"""SELECT stock_code,stock_name,rank_no,change_rate
                         FROM market_rank_snapshots
                         WHERE snapshot_time=%s AND COALESCE(market_theme,official_sector)=%s AND stock_code<>%s
                         ORDER BY rank_no NULLS LAST LIMIT 8""",(tm,theme,code))
        peers=[{"code":r[0],"name":r[1],"rank":r[2],"change_rate":f(r[3])} for r in rows]
    return {"name":name,"theme":theme,"peers":peers}

def market_agent(cur):
    regime={}
    cur.execute("SELECT to_regclass('public.market_regime_status')")
    if cur.fetchone()[0]:
        x=one(cur,"""SELECT status,stable_label,candidate_label,note,last_market_data_at
                     FROM market_regime_status WHERE id=1""")
        if x:regime={"status":x[0],"label":x[1] or x[2],"note":x[3],
                     "last_market_data_at":x[4].isoformat() if x[4] else None}
    idx={}
    cur.execute("SELECT to_regclass('public.market_index_snapshots')")
    if cur.fetchone()[0]:
        x=one(cur,"SELECT MAX(snapshot_time) FROM market_index_snapshots")
        if x and x[0]:
            rows=many(cur,"""SELECT index_code,index_name,change_rate,current_value
                             FROM market_index_snapshots WHERE snapshot_time=%s""",(x[0],))
            idx={r[1] or r[0]:{"change_rate":f(r[2]),"value":f(r[3])} for r in rows}
    return {"regime":regime,"indices":idx}

def synthesize(name,priority,a):
    rank=a["rank"];money=a["money"];disc=a["disclosure"];news=a["news"];tg=a["telegram"];sector=a["sector"];mim=a["mimosa"];market=a["market"]
    parts=[]
    if rank.get("latest_rank") is not None:parts.append(f"조회 #{rank['latest_rank']}")
    if money.get("trade_rank") is not None:parts.append(f"거래대금 #{money['trade_rank']}")
    if rank.get("change_rate") is not None:parts.append(f"{rank['change_rate']:+.1f}%")
    headline=f"{name} · "+" · ".join(parts) if parts else name

    why=[]
    if rank.get("rank_delta") is not None and rank["rank_delta"]>=3:why.append(f"조회순위가 단기 {rank['rank_delta']}계단 개선")
    if money.get("trade_rank") is not None and money["trade_rank"]<=20:why.append("거래대금 Top20")
    if money.get("value_growth_pct") is not None and money["value_growth_pct"]>=20:why.append(f"거래대금 약 {money['value_growth_pct']:.0f}% 증가")
    if disc["count"]:why.append(f"최근 DART 공시 {disc['count']}건")
    if tg["channels"]>=2:why.append(f"Telegram {tg['channels']}개 채널 확산")
    why_now=", ".join(why) if why else "조회·수급·재료 조건이 Research Agent 임계값을 충족"

    if disc["count"]:
        top=disc["items"][0]
        catalyst=f"DART 공시 우선 확인: {top['title']} ({top['category']})"
    elif news["count"]:
        catalyst=f"최신 뉴스 후보: {news['items'][0]['title']}"
    elif tg["count"]:
        catalyst=f"Telegram 주요 언급: {tg['items'][0]['text'][:180]}"
    else:
        catalyst="현재 수집 범위에서 직접 촉발 재료 미확인"

    response=[]
    if rank.get("latest_rank") is not None:response.append(f"조회 #{rank['latest_rank']}")
    if money.get("trade_rank") is not None:response.append(f"대금 #{money['trade_rank']}")
    if money.get("trade_to_cap_pct") is not None:response.append(f"시총대비 대금 {money['trade_to_cap_pct']:.1f}%")
    market_response=" · ".join(response) if response else "수급 데이터 제한"

    peer_count=len(sector.get("peers") or [])
    if sector.get("theme"):
        sector_confirmation=f"{sector['theme']} · 동종 조회상위 {peer_count}종목"
    else:
        sector_confirmation="섹터 확인 필요"

    chart=mim.get("chart")
    if chart:
        mimosa_summary=f"{chart.get('state_ko')} · {chart.get('minute_trend')} · {chart.get('daily_context')}"
    else:
        mimosa_summary="미모사 차트 상태 미확인"

    risks=[]
    if not disc["count"] and not news["count"] and tg["count"]==0:risks.append("직접 재료 미확인")
    if rank.get("change_rate") is not None and abs(rank["change_rate"])>=20:risks.append("등락폭 과대")
    if money.get("trade_rank") is not None and money["trade_rank"]<=20 and not disc["count"] and not news["count"]:risks.append("돈 선행 가능성")
    if chart and chart.get("state") in ("TREND_DAMAGE","BREAKOUT_FAIL"):risks.append(chart.get("state_ko"))

    confidence=45
    confidence+=15 if money.get("trade_rank") is not None and money["trade_rank"]<=20 else 0
    confidence+=15 if disc["count"] else (8 if news["count"] else 0)
    confidence+=10 if tg["channels"]>=2 else 0
    confidence+=10 if peer_count>=2 else 0
    confidence+=5 if chart else 0
    confidence=min(95,confidence)

    evidence_summary={"dart":disc["count"],"news":news["count"],"telegram":tg["count"],"telegram_channels":tg["channels"],
                      "sector_peers":peer_count,"priority":priority}
    return confidence,headline,why_now,catalyst,market_response,sector_confirmation,mimosa_summary,risks,evidence_summary

def pending(cur):
    return many(cur,"""SELECT j.id,j.stock_code,j.stock_name,j.priority
                       FROM research_jobs j
                       JOIN research_results r ON r.job_id=j.id
                       LEFT JOIN deep_research_reports d ON d.job_id=j.id
                       WHERE d.job_id IS NULL
                         AND j.priority>=%s
                         AND (r.deep_research_needed=true OR j.priority>=80)
                         AND j.created_at>now()-(%s||' hours')::interval
                       ORDER BY j.priority DESC,j.created_at ASC
                       LIMIT 12""",(MIN_PRIORITY,str(LOOKBACK_HOURS)))

def cycle():
    done=0
    with db() as c,c.cursor() as cur:
        jobs=pending(cur)
        for jid,code,name,priority in jobs:
            agents={
              "rank":rank_agent(cur,code),
              "money":money_agent(cur,code),
              "disclosure":disclosure_agent(cur,code),
              "news":news_agent(cur,code),
              "telegram":telegram_agent(cur,name),
              "sector":sector_agent(cur,code),
              "mimosa":mimosa_agent(cur,code),
              "market":market_agent(cur),
            }
            vals=synthesize(name or code,priority,agents)
            confidence,headline,why_now,catalyst,market_response,sector_confirmation,mimosa_summary,risks,evidence_summary=vals
            cur.execute("""INSERT INTO deep_research_reports(job_id,stock_code,stock_name,priority,confidence,headline,
            why_now,catalyst_summary,market_response,sector_confirmation,mimosa_summary,risk_flags,evidence_summary,agent_outputs)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb)
            ON CONFLICT(job_id) DO NOTHING""",
            (jid,code,name,priority,confidence,headline,why_now,catalyst,market_response,sector_confirmation,mimosa_summary,
             json.dumps(risks,ensure_ascii=False),json.dumps(evidence_summary,ensure_ascii=False),
             json.dumps(agents,ensure_ascii=False,default=str)))
            cur.execute("UPDATE research_jobs SET status='DEEP_LOCAL_DONE' WHERE id=%s",(jid,))
            done+=1
        c.commit()
    status("OK",f"deep_reports={done}",success=True)

def main():
    schema();print(f"Deep research engine started: min_priority={MIN_PRIORITY}",flush=True)
    while True:
        try:cycle()
        except Exception as e:
            status("ERROR","멀티에이전트 종합 오류",str(e)[:700]);print("deep research error",str(e)[:700],flush=True)
        time.sleep(POLL)

if __name__=="__main__":main()
