"""Read-only live readiness checks for Market OS.

This module inspects freshness, coverage and unit quality. It does not call
Kiwoom/OpenAI, mutate credentials, place orders, or change rule thresholds.
"""
from __future__ import annotations
from datetime import datetime,timezone,time as dtime,timedelta
import json
from zoneinfo import ZoneInfo
import os

import psycopg
from psycopg.rows import dict_row

KST=ZoneInfo("Asia/Seoul")
DB=os.getenv("DATABASE_URL","")

TABLES={
    "rank":"market_rank_snapshots",
    "trade":"market_trade_value_snapshots",
    "flow":"radar_flow_quotes",
    "regime":"market_regime_snapshots",
    "chart":"chart_states",
    "theme":"stock_theme_memberships",
    "assessment":"market_os_assessment_snapshots",
    "outcome":"market_os_assessment_outcomes",
    "realtime":"market_realtime_minute_bars",
    "realtime_5s":"market_realtime_5s_bars",
}

TIME_COLUMNS={
    "market_rank_snapshots":"snapshot_time",
    "market_trade_value_snapshots":"snapshot_time",
    "radar_flow_quotes":"batch_time",
    "market_regime_snapshots":"snapshot_time",
    "chart_states":"snapshot_time",
    "stock_theme_memberships":"refreshed_at",
    "market_os_assessment_snapshots":"snapshot_time",
    "market_os_assessment_outcomes":"calculated_at",
    "market_realtime_minute_bars":"minute_time",
    "market_realtime_5s_bars":"bucket_time",
}


def db():
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
                           options="-c statement_timeout=12000 -c lock_timeout=2500")


def exists(cur,name):
    cur.execute("SELECT to_regclass(%s) AS name",("public."+name,))
    return cur.fetchone()["name"] is not None


def market_session(now=None):
    now=(now or datetime.now(timezone.utc)).astimezone(KST)
    if now.weekday()>=5:
        return "OFF_HOURS"
    t=now.time()
    if dtime(8,0)<=t<=dtime(20,0):
        return "SESSION"
    return "OFF_HOURS"


def _age_seconds(ts,now):
    if not ts:return None
    return max(0,int((now-ts).total_seconds()))


def _freshness_level(key,age,session):
    if age is None:return "MISSING"
    if session=="OFF_HOURS":return "HISTORICAL"
    limits={
        "rank":120,"trade":120,"flow":120,"regime":180,
        "chart":300,"theme":86400,"assessment":180,"outcome":86400,"realtime":120,"realtime_5s":30,
    }
    limit=limits.get(key,300)
    if age<=limit:return "OK"
    if age<=limit*3:return "STALE"
    return "BLOCKED"


def _today_count(cur,table,col):
    cur.execute(f"""SELECT COUNT(*) AS n FROM {table}
                    WHERE ({col} AT TIME ZONE 'Asia/Seoul')::date =
                          (now() AT TIME ZONE 'Asia/Seoul')::date""")
    return int(cur.fetchone()["n"] or 0)


def _latest_table(cur,key,table,now,session):
    if not exists(cur,table):
        return {"key":key,"table":table,"exists":False,"latest":None,"age_sec":None,
                "today_rows":0,"level":"MISSING"}
    col=TIME_COLUMNS[table]
    cur.execute(f"SELECT MAX({col}) AS t,COUNT(*) AS n FROM {table}")
    r=cur.fetchone();latest=r["t"]
    return {
        "key":key,"table":table,"exists":True,
        "latest":latest.isoformat() if latest else None,
        "age_sec":_age_seconds(latest,now),
        "today_rows":_today_count(cur,table,col),
        "total_rows":int(r["n"] or 0),
        "level":_freshness_level(key,_age_seconds(latest,now),session),
    }


def _kiwoom_status(cur,now):
    if not exists(cur,"kiwoom_feed_status"):
        return {"exists":False,"status":"MISSING","last_success_at":None,"age_sec":None}
    cur.execute("SELECT status,mode,last_success_at,note,last_error,updated_at FROM kiwoom_feed_status WHERE id=1")
    r=cur.fetchone()
    if not r:return {"exists":True,"status":"EMPTY","last_success_at":None,"age_sec":None}
    return {
        "exists":True,"status":r["status"],"mode":r["mode"],
        "last_success_at":r["last_success_at"].isoformat() if r["last_success_at"] else None,
        "age_sec":_age_seconds(r["last_success_at"],now),
        "updated_at":r["updated_at"].isoformat() if r["updated_at"] else None,
        "note":r["note"],
        "last_error_type":(r["last_error"] or "").split(":",1)[0][:80] or None,
    }


def _realtime_status(cur,now):
    enabled=os.getenv("KIWOOM_REALTIME_ENABLED","0").strip()=="1"
    if not exists(cur,"kiwoom_realtime_status"):
        return {"enabled":enabled,"exists":False,"status":"MISSING","connected":False,
                "last_message_at":None,"age_sec":None}
    cur.execute("""SELECT status,mode,connected,last_message_at,subscribed_count,tick_count,gap_count,note,updated_at
                   FROM kiwoom_realtime_status WHERE id=1""")
    r=cur.fetchone()
    if not r:
        return {"enabled":enabled,"exists":True,"status":"EMPTY","connected":False,
                "last_message_at":None,"age_sec":None}
    recent_gaps=0;recent_gap_stocks=0
    if exists(cur,"market_realtime_5s_bars"):
        cur.execute("""SELECT COALESCE(SUM(gap_count),0) AS gaps,
                              COUNT(DISTINCT stock_code) FILTER(WHERE gap_count>0) AS stocks
                       FROM market_realtime_5s_bars
                       WHERE bucket_time>now()-interval '5 minutes'""")
        g=cur.fetchone();recent_gaps=int(g["gaps"] or 0);recent_gap_stocks=int(g["stocks"] or 0)
    return {
        "enabled":enabled,"exists":True,"status":r["status"],"mode":r["mode"],
        "connected":bool(r["connected"]),
        "last_message_at":r["last_message_at"].isoformat() if r["last_message_at"] else None,
        "age_sec":_age_seconds(r["last_message_at"],now),
        "subscribed_count":int(r["subscribed_count"] or 0),
        "tick_count":int(r["tick_count"] or 0),"gap_count":int(r["gap_count"] or 0),
        "recent_gap_count_5m":recent_gaps,"recent_gap_stocks_5m":recent_gap_stocks,
        "note":r["note"],"updated_at":r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def _flow_quality(cur):
    """Separate turnover quality from market-cap quality.

    Market OS money-flow math depends on validated turnover. Market-cap unit
    issues are reported separately and must not downgrade live money-flow
    readiness by themselves.
    """
    empty={"latest_batch":None,"stocks":0,
           "turnover_unresolved":0,"turnover_unresolved_pct":None,
           "cap_unresolved":0,"cap_unresolved_pct":None}
    if not exists(cur,"radar_flow_quotes"):
        return empty
    cur.execute("SELECT MAX(batch_time) AS t FROM radar_flow_quotes")
    t=cur.fetchone()["t"]
    if not t:return empty
    cur.execute("SELECT payload FROM radar_flow_quotes WHERE batch_time=%s",(t,))
    rows=cur.fetchall()
    turnover_bad=0;cap_bad=0
    turnover_states={};cap_states={}
    for r in rows:
        flags=[str(x) for x in ((r["payload"] or {}).get("quality_flags") or [])]
        tflags=[x for x in flags if x.startswith("TURNOVER_")]
        cflags=[x for x in flags if x.startswith("CAP_")]
        if tflags:turnover_bad+=1
        if cflags:cap_bad+=1
        for x in tflags:turnover_states[x]=turnover_states.get(x,0)+1
        for x in cflags:cap_states[x]=cap_states.get(x,0)+1
    n=len(rows)
    return {
        "latest_batch":t.isoformat(),"stocks":n,
        "turnover_unresolved":turnover_bad,
        "turnover_unresolved_pct":turnover_bad/n*100 if n else None,
        "turnover_states":turnover_states,
        "cap_unresolved":cap_bad,
        "cap_unresolved_pct":cap_bad/n*100 if n else None,
        "cap_states":cap_states,
        # Backward-compatible aliases now mean turnover-money quality only.
        "unit_unresolved":turnover_bad,
        "unit_unresolved_pct":turnover_bad/n*100 if n else None,
    }


def _coverage(cur):
    out={}
    if exists(cur,"market_rank_snapshots"):
        cur.execute("SELECT MAX(snapshot_time) AS t FROM market_rank_snapshots");t=cur.fetchone()["t"]
        if t:
            cur.execute("SELECT COUNT(*) AS n FROM market_rank_snapshots WHERE snapshot_time=%s",(t,))
            out["rank_latest_stocks"]=int(cur.fetchone()["n"] or 0)
    if exists(cur,"market_trade_value_snapshots"):
        cur.execute("SELECT MAX(snapshot_time) AS t FROM market_trade_value_snapshots");t=cur.fetchone()["t"]
        if t:
            cur.execute("SELECT COUNT(*) AS n FROM market_trade_value_snapshots WHERE snapshot_time=%s",(t,))
            out["trade_latest_stocks"]=int(cur.fetchone()["n"] or 0)
    if exists(cur,"market_os_assessment_snapshots"):
        cur.execute("""SELECT COUNT(*) AS n,COUNT(*) FILTER(WHERE watch_tier='FOCUS') AS focus,
                              COUNT(*) FILTER(WHERE watch_tier='PREP') AS prep,
                              COUNT(*) FILTER(WHERE micro_tick_count_15s>0) AS micro15
                       FROM market_os_assessment_snapshots
                       WHERE snapshot_time>now()-interval '15 minutes'""")
        r=cur.fetchone();out.update({"recent_assessments":int(r["n"] or 0),
                                    "recent_focus":int(r["focus"] or 0),"recent_prep":int(r["prep"] or 0),
                                    "recent_micro15_assessments":int(r["micro15"] or 0)})
    if exists(cur,"market_os_assessment_outcomes"):
        cur.execute("""SELECT horizon,COUNT(*) AS n
                       FROM market_os_assessment_outcomes
                       WHERE calculated_at>now()-interval '1 day'
                       GROUP BY horizon""")
        out["outcomes_today"]={r["horizon"]:int(r["n"] or 0) for r in cur.fetchall()}
    return out


def payload():
    now=datetime.now(timezone.utc);session=market_session(now)
    with db() as c,c.cursor() as cur:
        tables=[_latest_table(cur,k,t,now,session) for k,t in TABLES.items()]
        ks=_kiwoom_status(cur,now)
        quality=_flow_quality(cur)
        realtime=_realtime_status(cur,now)
        coverage=_coverage(cur)
    blockers=[];warnings=[]
    by={x["key"]:x for x in tables}
    for key in ("rank","trade","flow","regime"):
        level=by[key]["level"]
        if session=="SESSION" and level in ("MISSING","BLOCKED"):
            blockers.append(f"{key}:{level}")
        elif session=="SESSION" and level=="STALE":
            warnings.append(f"{key}:STALE")
    if session=="SESSION" and ks.get("status") in ("WAITING_FOR_CREDENTIALS","ERROR","MISSING","EMPTY"):
        blockers.append("kiwoom:"+str(ks.get("status")))
    if realtime.get("enabled") and session=="SESSION":
        if realtime.get("status")!="OK" or not realtime.get("connected"):
            warnings.append("realtime:"+str(realtime.get("status")))
        elif realtime.get("age_sec") is None or realtime.get("age_sec")>120:
            warnings.append("realtime:STALE")
    unresolved=quality.get("turnover_unresolved_pct")
    if unresolved is not None and unresolved>20:
        warnings.append(f"turnover_unit_unresolved:{unresolved:.1f}%")
    if session=="OFF_HOURS":
        overall="OFF_HOURS"
    elif blockers:
        overall="BLOCKED"
    elif warnings:
        overall="PARTIAL"
    else:
        overall="READY"
    return {
        "generated_at":now.isoformat(),"market_session":session,"overall":overall,
        "blockers":blockers,"warnings":warnings,"kiwoom":ks,"tables":tables,
        "flow_quality":quality,"realtime":realtime,"coverage":coverage,
        "notice":"읽기 전용 진단. API 호출·키 변경·주문·AI 호출 없음."
    }


if __name__=="__main__":
    print(json.dumps(payload(),ensure_ascii=False,default=str,indent=2),flush=True)
