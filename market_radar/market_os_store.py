"""Read-only Market OS dashboard and learning views."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime,timezone,timedelta
import os
import re

import psycopg
from psycopg.rows import dict_row

from flow_store import desk_payload
from market_os_rule_engine import VERSION as RULE_VERSION


def db():
    return psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row,connect_timeout=5,
                           options="-c statement_timeout=15000 -c lock_timeout=3000")


def exists(cur,name):
    cur.execute("SELECT to_regclass(%s) AS name",("public."+name,))
    return cur.fetchone()["name"] is not None


def _segment_depth(kind):
    return {
        "STANCE_TRIGGER":2,"TIER_SESSION":2,"STANCE_SETUP":2,"SETUP_TRIGGER":2,
        "STANCE_SETUP_TRIGGER":3,
        "STANCE_TRIGGER_MICRO":3,"SETUP_TRIGGER_MICRO":3,
        "STANCE_SETUP_TRIGGER_MICRO":4,
    }.get(kind,1)


def _quality(n,stocks=0,days=0,depth=1):
    """Evidence quality with stricter diversity gates for higher-order interactions."""
    if depth>=4:
        if n>=350 and stocks>=20 and days>=12:return "충분"
        if n>=160 and stocks>=15 and days>=8:return "형성"
        if n>=60 and stocks>=10 and days>=4:return "초기"
        return "탐색"
    if depth==3:
        if n>=260 and stocks>=18 and days>=10:return "충분"
        if n>=120 and stocks>=12 and days>=6:return "형성"
        if n>=40 and stocks>=8 and days>=3:return "초기"
        return "탐색"
    if depth==2:
        if n>=200 and stocks>=15 and days>=8:return "충분"
        if n>=90 and stocks>=10 and days>=5:return "형성"
        if n>=30 and stocks>=6 and days>=3:return "초기"
        return "탐색"
    if n>=150 and stocks>=10 and days>=5:return "충분"
    if n>=60 and stocks>=8 and days>=3:return "형성"
    if n>=20 and stocks>=5 and days>=2:return "초기"
    return "탐색"


def _quality_rank(q):
    return {"탐색":0,"초기":1,"형성":2,"충분":3}.get(q,0)


def _current_session():
    from zoneinfo import ZoneInfo
    from datetime import time as dtime
    t=datetime.now(ZoneInfo("Asia/Seoul")).time()
    if t<dtime(9,0):return "PRE"
    if t<dtime(9,20):return "OPEN_20"
    if t<dtime(11,30):return "MORNING"
    if t<dtime(13,30):return "MIDDAY"
    if t<dtime(14,50):return "AFTERNOON"
    if t<=dtime(15,30):return "CLOSE"
    return "AFTER"


def _bucket_strength(v):
    try:v=float(v)
    except (TypeError,ValueError):return "UNKNOWN"
    if v>=120:return "120+"
    if v>=100:return "100-119"
    if v>=80:return "80-99"
    return "<80"


def _bucket_buy_share(v):
    try:v=float(v)
    except (TypeError,ValueError):return "UNKNOWN"
    if v>=.65:return "65%+"
    if v>=.55:return "55-64%"
    if v>=.45:return "45-54%"
    return "<45%"


def _bucket_setup(v):
    try:v=int(v)
    except (TypeError,ValueError):return "UNKNOWN"
    if v>=80:return "80-100"
    if v>=65:return "65-79"
    if v>=50:return "50-64"
    return "0-49"


def _micro_state(strength,buy_share):
    try:s=float(strength)
    except (TypeError,ValueError):s=None
    try:b=float(buy_share)
    except (TypeError,ValueError):b=None
    if s is None or b is None:return "NO_DATA"
    if s>=120 and b>=.65:return "STRONG_CONFIRM"
    if s<80 and b<.45:return "WEAK_CONFIRM"
    if s>=100 and b>=.55:return "POSITIVE"
    if s<100 and b<.45:return "NEGATIVE"
    return "MIXED"


def _parent_key(kind,value):
    p=value.split(" | ")
    try:
        if kind=="STANCE_TRIGGER":return ("STANCE",p[0])
        if kind=="TIER_SESSION":return ("TIER",p[0])
        if kind=="STANCE_SETUP":return ("STANCE",p[0])
        if kind=="SETUP_TRIGGER":return ("SETUP",p[0])
        if kind=="STANCE_SETUP_TRIGGER":return ("STANCE_TRIGGER",p[0]+" | "+p[2])
        if kind=="STANCE_TRIGGER_MICRO":return ("STANCE_TRIGGER",p[0]+" | "+p[1])
        if kind=="SETUP_TRIGGER_MICRO":return ("SETUP_TRIGGER",p[0]+" | "+p[1])
        if kind=="STANCE_SETUP_TRIGGER_MICRO":
            return ("STANCE_SETUP_TRIGGER",p[0]+" | "+p[1]+" | "+p[2])
    except IndexError:
        return None
    return None


def _enrich_edges(segments,edge_rows=None):
    idx={(s["segment_type"],s["segment_value"],s["horizon"]):s for s in segments}
    edge_index={(e["segment_type"],e["segment_value"],e["horizon"]):e for e in (edge_rows or [])}
    interactions=[]
    for s in segments:
        depth=_segment_depth(s["segment_type"])
        s["interaction_depth"]=depth
        parent_key=_parent_key(s["segment_type"],s["segment_value"])
        e=edge_index.get((s["segment_type"],s["segment_value"],s["horizon"]))
        if e:
            comparator_quality=_quality(e["comparator_samples"],e["comparator_stocks"],e["comparator_days"],
                                        max(1,depth-1))
            s["baseline"]={
                "comparison":"PARENT_COMPLEMENT",
                "segment_type":e["parent_type"],"segment_value":e["parent_value"],
                "samples":e["comparator_samples"],"distinct_stocks":e["comparator_stocks"],
                "distinct_days":e["comparator_days"],"quality":comparator_quality,
                "avg_return_pct":e["comparator_avg_return_pct"],
                "positive_rate":e["comparator_positive_rate"],
                "avg_mfe_pct":e["comparator_avg_mfe_pct"],"avg_mae_pct":e["comparator_avg_mae_pct"],
            }
            s["edge_avg_return_pct"]=e["delta_avg_return_pct"]
            s["edge_positive_rate_pp"]=e["delta_positive_rate_pp"]
            s["edge_mfe_pct"]=e["delta_mfe_pct"]
            s["edge_mae_pct"]=e["delta_mae_pct"]
            s["edge_ready"]=bool(_quality_rank(s["quality"])>=2 and _quality_rank(comparator_quality)>=2)
        elif parent_key:
            # Compatibility fallback for databases created before the edge table.
            parent=idx.get((parent_key[0],parent_key[1],s["horizon"]))
            if parent:
                s["baseline"]={
                    "comparison":"PARENT_AGGREGATE_FALLBACK",
                    "segment_type":parent["segment_type"],"segment_value":parent["segment_value"],
                    "samples":parent["samples"],"distinct_stocks":parent["distinct_stocks"],
                    "distinct_days":parent["distinct_days"],"quality":parent["quality"],
                    "avg_return_pct":parent["avg_return_pct"],"positive_rate":parent["positive_rate"],
                    "avg_mfe_pct":parent["avg_mfe_pct"],"avg_mae_pct":parent["avg_mae_pct"],
                }
                s["edge_avg_return_pct"]=(s["avg_return_pct"]-parent["avg_return_pct"]
                    if s["avg_return_pct"] is not None and parent["avg_return_pct"] is not None else None)
                s["edge_positive_rate_pp"]=((s["positive_rate"]-parent["positive_rate"])*100
                    if s["positive_rate"] is not None and parent["positive_rate"] is not None else None)
                s["edge_mfe_pct"]=(s["avg_mfe_pct"]-parent["avg_mfe_pct"]
                    if s["avg_mfe_pct"] is not None and parent["avg_mfe_pct"] is not None else None)
                s["edge_mae_pct"]=(s["avg_mae_pct"]-parent["avg_mae_pct"]
                    if s["avg_mae_pct"] is not None and parent["avg_mae_pct"] is not None else None)
                s["edge_ready"]=False
        if depth>=2:
            interactions.append(s)
    interactions.sort(key=lambda s:(
        -_quality_rank(s["quality"]),-int(bool(s.get("edge_ready"))),-s["interaction_depth"],-s["samples"],
        {"30m":0,"close":1,"D+1":2,"5m":3}.get(s["horizon"],9)
    ))
    return interactions




def latest_microstructure(cur,codes):
    out={}
    if not codes:return out
    now=datetime.now(timezone.utc)
    if exists(cur,"market_realtime_minute_bars"):
        cur.execute("""SELECT DISTINCT ON(stock_code)
                        stock_code,minute_time,close_price,volume,trade_value_krw,buy_volume,sell_volume,
                        tick_count,gap_count,last_strength,last_buy_ratio,last_exchange,updated_at
                       FROM market_realtime_minute_bars
                       WHERE stock_code=ANY(%s) AND minute_time>now()-interval '5 minutes'
                       ORDER BY stock_code,minute_time DESC""",(list(codes),))
        for r in cur.fetchall():
            buy=float(r["buy_volume"] or 0);sell=float(r["sell_volume"] or 0);total=buy+sell
            out[r["stock_code"]]={
                "minute_time":r["minute_time"].isoformat() if r["minute_time"] else None,
                "age_sec":max(0,int((now-r["updated_at"]).total_seconds())) if r["updated_at"] else None,
                "close_price":float(r["close_price"]) if r["close_price"] is not None else None,
                "volume":float(r["volume"] or 0),"trade_value_krw":float(r["trade_value_krw"] or 0),
                "buy_volume":buy,"sell_volume":sell,"buy_share":buy/total if total else None,
                "tick_count":int(r["tick_count"] or 0),"gap_count":int(r["gap_count"] or 0),
                "strength":r["last_strength"],"buy_ratio":r["last_buy_ratio"],
                "exchange":r["last_exchange"],"source":"KIWOOM_0B"
            }
    if exists(cur,"market_realtime_5s_bars"):
        cur.execute("""SELECT stock_code,SUM(trade_value_krw) AS tv,SUM(buy_volume) AS buy,
                              SUM(sell_volume) AS sell,SUM(tick_count) AS ticks,SUM(gap_count) AS gaps,
                              MAX(updated_at) AS updated_at
                       FROM market_realtime_5s_bars
                       WHERE stock_code=ANY(%s) AND bucket_time>=now()-interval '15 seconds'
                       GROUP BY stock_code""",(list(codes),))
        for r in cur.fetchall():
            x=out.setdefault(r["stock_code"],{"source":"KIWOOM_0B"})
            buy=float(r["buy"] or 0);sell=float(r["sell"] or 0);den=buy+sell
            x.update({
                "trade_value_15s_krw":float(r["tv"] or 0),
                "buy_share_15s":buy/den if den else None,
                "tick_count_15s":int(r["ticks"] or 0),
                "gap_count_15s":int(r["gaps"] or 0),
                "age_15s_sec":max(0,int((now-r["updated_at"]).total_seconds())) if r["updated_at"] else None
            })
    return out


def learning_payload():
    current=desk_payload()
    learning={
        "rule_version":RULE_VERSION,
        "mode":"SHADOW_LEARNING",
        "notice":"성과를 자동 측정하고 조건별 차이를 학습하지만, 충분한 표본 전에는 규칙 임계값을 자동 변경하지 않습니다.",
        "status":None,"segments":[],"interactions":[],"notes":[],"daily_assessments":[],
    }
    edge_rows=[]
    with db() as c,c.cursor() as cur:
        micro=latest_microstructure(cur,[x.get("code") for x in current.get("market_os_watchlist",[]) if x.get("code")])
        if not exists(cur,"market_os_learning_status"):
            for x in current.get("market_os_watchlist",[]):
                x["microstructure"]=micro.get(x.get("code"))
            current["learning"]=learning
            return current
        cur.execute("SELECT * FROM market_os_learning_status WHERE id=1")
        st=cur.fetchone()
        if st:
            learning["status"]={
                "updated_at":st["updated_at"].isoformat() if st["updated_at"] else None,
                "status":st["status"],
                "last_snapshot_at":st["last_snapshot_at"].isoformat() if st["last_snapshot_at"] else None,
                "last_outcome_at":st["last_outcome_at"].isoformat() if st["last_outcome_at"] else None,
                "assessments_total":st["assessments_total"],
                "outcomes_total":st["outcomes_total"],
                "note":st["note"],
            }
        if exists(cur,"market_os_learning_segments"):
            cur.execute("""SELECT segment_type,segment_value,horizon,samples,distinct_stocks,distinct_days,
                                  sample_basis,avg_return_pct,median_return_pct,positive_rate,
                                  avg_mfe_pct,avg_mae_pct,updated_at
                           FROM market_os_learning_segments
                           ORDER BY CASE horizon WHEN '5m' THEN 1 WHEN '30m' THEN 2 WHEN 'close' THEN 3 ELSE 4 END,
                                    samples DESC,segment_type,segment_value""")
            for r in cur.fetchall():
                learning["segments"].append({
                    "segment_type":r["segment_type"],"segment_value":r["segment_value"],
                    "horizon":r["horizon"],"samples":r["samples"],
                    "distinct_stocks":r["distinct_stocks"],"distinct_days":r["distinct_days"],
                    "sample_basis":r["sample_basis"],
                    "quality":_quality(r["samples"],r["distinct_stocks"],r["distinct_days"],
                                       _segment_depth(r["segment_type"])),
                    "avg_return_pct":r["avg_return_pct"],"median_return_pct":r["median_return_pct"],
                    "positive_rate":r["positive_rate"],"avg_mfe_pct":r["avg_mfe_pct"],
                    "avg_mae_pct":r["avg_mae_pct"],
                    "updated_at":r["updated_at"].isoformat() if r["updated_at"] else None
                })
        if exists(cur,"market_os_interaction_edges"):
            cur.execute("""SELECT segment_type,segment_value,horizon,parent_type,parent_value,sample_basis,
                                  child_samples,child_stocks,child_days,
                                  comparator_samples,comparator_stocks,comparator_days,
                                  child_avg_return_pct,comparator_avg_return_pct,delta_avg_return_pct,
                                  child_positive_rate,comparator_positive_rate,delta_positive_rate_pp,
                                  child_avg_mfe_pct,comparator_avg_mfe_pct,delta_mfe_pct,
                                  child_avg_mae_pct,comparator_avg_mae_pct,delta_mae_pct
                           FROM market_os_interaction_edges""")
            edge_rows=[dict(r) for r in cur.fetchall()]
        if exists(cur,"market_os_assessment_snapshots"):
            cur.execute("""SELECT (snapshot_time AT TIME ZONE 'Asia/Seoul')::date AS d,COUNT(*) AS n,
                                  COUNT(*) FILTER(WHERE watch_tier='FOCUS') AS focus,
                                  COUNT(*) FILTER(WHERE watch_tier='PREP') AS prep
                           FROM market_os_assessment_snapshots
                           WHERE rule_version=%s AND snapshot_time>now()-interval '14 days'
                           GROUP BY d ORDER BY d""",(RULE_VERSION,))
            learning["daily_assessments"]=[
                {"date":r["d"].isoformat(),"count":r["n"],"focus":r["focus"],"prep":r["prep"]}
                for r in cur.fetchall()
            ]

    learning["interactions"]=_enrich_edges(learning["segments"],edge_rows)

    # Conservative, deterministic feedback. This is evidence for review, not an
    # automatic rewrite of thresholds.
    for s in learning["segments"]:
        if s["quality"]=="탐색" or s["horizon"] not in ("30m","close"):
            continue
        if s.get("interaction_depth",1)>=2 and not s.get("edge_ready"):
            continue
        avg=s["avg_return_pct"];pr=s["positive_rate"]
        if avg is not None and pr is not None and avg>0.5 and pr>=0.58:
            learning["notes"].append({
                "kind":"STRENGTH","title":f"{s['segment_type']} · {s['segment_value']}",
                "text":f"{s['horizon']} 표본 {s['samples']}개에서 평균 {avg:.2f}%, 양(+) 비율 {pr*100:.0f}% — 추가 검증할 강한 조건 후보",
                "samples":s["samples"]
            })
        elif avg is not None and pr is not None and avg<-0.3 and pr<=0.42:
            learning["notes"].append({
                "kind":"WEAKNESS","title":f"{s['segment_type']} · {s['segment_value']}",
                "text":f"{s['horizon']} 표본 {s['samples']}개에서 평균 {avg:.2f}%, 양(+) 비율 {pr*100:.0f}% — 축소/제외 규칙 후보로 검토",
                "samples":s["samples"]
            })
    learning["notes"]=sorted(learning["notes"],key=lambda x:-x["samples"])[:12]

    # Attach shadow historical evidence to current candidates without changing
    # their live tier. Matching uses only already-resolved outcomes.
    seg_index={(s["segment_type"],s["segment_value"],s["horizon"]):s for s in learning["segments"]}
    for x in current.get("market_os_watchlist",[]):
        m=micro.get(x.get("code"))
        stance=x.get("market_stance") or "UNKNOWN"
        trigger=x.get("trigger_state") or "UNKNOWN"
        setup=_bucket_setup(x.get("setup_score"))
        keys=[
            ("STANCE_SETUP_TRIGGER",stance+" | "+setup+" | "+trigger),
            ("STANCE_TRIGGER",stance+" | "+trigger),
            ("STANCE_SETUP",stance+" | "+setup),
            ("SETUP_TRIGGER",setup+" | "+trigger),
            ("TIER_SESSION",(x.get("watch_tier") or "UNKNOWN")+" | "+_current_session()),
            ("TRIGGER",trigger),("SETUP",setup),("STANCE",stance),("TIER",x.get("watch_tier") or "UNKNOWN"),
        ]
        if m and int(m.get("tick_count_15s") or 0)>0 and int(m.get("gap_count_15s") or 0)==0:
            micro_state=_micro_state(m.get("strength"),m.get("buy_share_15s"))
            keys=[
                ("STANCE_SETUP_TRIGGER_MICRO",stance+" | "+setup+" | "+trigger+" | "+micro_state),
                ("STANCE_TRIGGER_MICRO",stance+" | "+trigger+" | "+micro_state),
                ("SETUP_TRIGGER_MICRO",setup+" | "+trigger+" | "+micro_state),
            ]+keys+[
                ("MICRO_STATE",micro_state),
                ("MICRO_STRENGTH",_bucket_strength(m.get("strength"))),
                ("MICRO_BUY_SHARE",_bucket_buy_share(m.get("buy_share_15s"))),
            ]
        evidence=[]
        for horizon in ("30m","close","5m"):
            for kind,value in keys:
                s=seg_index.get((kind,value,horizon))
                depth=_segment_depth(kind)
                ready=bool(s and s["quality"]!="탐색")
                if depth>=3:
                    ready=bool(s and _quality_rank(s["quality"])>=2 and s.get("edge_ready"))
                if ready:
                    evidence.append({
                        "segment_type":kind,"segment_value":value,"horizon":horizon,
                        "samples":s["samples"],"distinct_stocks":s["distinct_stocks"],
                        "distinct_days":s["distinct_days"],"quality":s["quality"],
                        "interaction_depth":depth,"avg_return_pct":s["avg_return_pct"],
                        "median_return_pct":s["median_return_pct"],"positive_rate":s["positive_rate"],
                        "avg_mfe_pct":s["avg_mfe_pct"],"avg_mae_pct":s["avg_mae_pct"],
                        "edge_avg_return_pct":s.get("edge_avg_return_pct"),
                        "edge_positive_rate_pp":s.get("edge_positive_rate_pp"),
                        "edge_mae_pct":s.get("edge_mae_pct"),
                        "baseline":s.get("baseline")
                    })
            if evidence:break
        x["learning_context"]=sorted(evidence,key=lambda z:(
            -_quality_rank(z["quality"]),-z.get("interaction_depth",1),-z["samples"]
        ))[:3]
        x["microstructure"]=micro.get(x.get("code"))

    current["learning"]=learning
    return current


def history_payload(code):
    if not re.fullmatch(r"[0-9A-Z]{6}",code):
        raise ValueError("INVALID_CODE")
    out={"code":code,"assessments":[],"outcomes":[]}
    with db() as c,c.cursor() as cur:
        if exists(cur,"market_os_assessment_snapshots"):
            cur.execute("""SELECT snapshot_time,stock_name,watch_tier,radar_score,theme_score,setup_score,
                                  catalyst_grade,trigger_state,market_stance,session_bucket,market_theme,
                                  event_type,current_price_krw,change_pct,
                                  micro_trade_value_15s_krw,micro_buy_share_15s,micro_tick_count_15s,
                                  micro_gap_count_15s,micro_strength,micro_buy_ratio,
                                  axis_reasons,risk_flags
                           FROM market_os_assessment_snapshots
                           WHERE stock_code=%s AND rule_version=%s
                           ORDER BY snapshot_time DESC LIMIT 120""",(code,RULE_VERSION))
            for r in cur.fetchall():
                x=dict(r);x["snapshot_time"]=r["snapshot_time"].isoformat()
                if x.get("current_price_krw") is not None:x["current_price_krw"]=float(x["current_price_krw"])
                if x.get("micro_trade_value_15s_krw") is not None:x["micro_trade_value_15s_krw"]=float(x["micro_trade_value_15s_krw"])
                out["assessments"].append(x)
        if exists(cur,"market_os_assessment_outcomes"):
            cur.execute("""SELECT assessment_time,horizon,reference_price_krw,outcome_price_krw,
                                  return_pct,mfe_pct,mae_pct,outcome_time,outcome_source,quality_flags
                           FROM market_os_assessment_outcomes
                           WHERE stock_code=%s AND rule_version=%s
                           ORDER BY assessment_time DESC,horizon LIMIT 400""",(code,RULE_VERSION))
            for r in cur.fetchall():
                x=dict(r);x["assessment_time"]=r["assessment_time"].isoformat()
                x["outcome_time"]=r["outcome_time"].isoformat() if r["outcome_time"] else None
                for k in ("reference_price_krw","outcome_price_krw"):
                    if x.get(k) is not None:x[k]=float(x[k])
                out["outcomes"].append(x)
    return out
