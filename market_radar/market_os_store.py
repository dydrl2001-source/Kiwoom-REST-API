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


def _quality(n):
    if n>=80:return "충분"
    if n>=40:return "형성"
    if n>=20:return "초기"
    return "탐색"


def learning_payload():
    current=desk_payload()
    learning={
        "rule_version":RULE_VERSION,
        "mode":"SHADOW_LEARNING",
        "notice":"성과를 자동 측정하고 조건별 차이를 학습하지만, 충분한 표본 전에는 규칙 임계값을 자동 변경하지 않습니다.",
        "status":None,"segments":[],"notes":[],"daily_assessments":[],
    }
    with db() as c,c.cursor() as cur:
        if not exists(cur,"market_os_learning_status"):
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
            cur.execute("""SELECT segment_type,segment_value,horizon,samples,avg_return_pct,
                                  median_return_pct,positive_rate,avg_mfe_pct,avg_mae_pct,updated_at
                           FROM market_os_learning_segments
                           ORDER BY CASE horizon WHEN '5m' THEN 1 WHEN '30m' THEN 2 WHEN 'close' THEN 3 ELSE 4 END,
                                    samples DESC,segment_type,segment_value""")
            for r in cur.fetchall():
                learning["segments"].append({
                    "segment_type":r["segment_type"],"segment_value":r["segment_value"],
                    "horizon":r["horizon"],"samples":r["samples"],"quality":_quality(r["samples"]),
                    "avg_return_pct":r["avg_return_pct"],"median_return_pct":r["median_return_pct"],
                    "positive_rate":r["positive_rate"],"avg_mfe_pct":r["avg_mfe_pct"],
                    "avg_mae_pct":r["avg_mae_pct"],
                    "updated_at":r["updated_at"].isoformat() if r["updated_at"] else None
                })
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

    # Conservative, deterministic feedback. This is evidence for review, not an
    # automatic rewrite of thresholds.
    for s in learning["segments"]:
        if s["samples"]<20 or s["horizon"] not in ("30m","close"):
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
                                  event_type,current_price_krw,change_pct,axis_reasons,risk_flags
                           FROM market_os_assessment_snapshots
                           WHERE stock_code=%s AND rule_version=%s
                           ORDER BY snapshot_time DESC LIMIT 120""",(code,RULE_VERSION))
            for r in cur.fetchall():
                x=dict(r);x["snapshot_time"]=r["snapshot_time"].isoformat()
                if x.get("current_price_krw") is not None:x["current_price_krw"]=float(x["current_price_krw"])
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
