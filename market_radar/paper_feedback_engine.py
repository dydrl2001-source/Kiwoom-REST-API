"""Automatic feedback for the local Paper Trading Lab.

This module evaluates prospective paper experiments. It never changes live rule
thresholds, never places orders, and never calls an AI provider. Its job is to
surface sample size, weak/strong observation patterns, and calibration candidates.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import os
import statistics
import time

import psycopg
from psycopg.rows import dict_row

DB=os.getenv("DATABASE_URL","")
POLL=max(30,int(os.getenv("PAPER_FEEDBACK_POLL_SECONDS","60")))
LOOKBACK_DAYS=max(7,min(180,int(os.getenv("PAPER_FEEDBACK_LOOKBACK_DAYS","30"))))
MIN_TYPE_SAMPLES=max(10,min(100,int(os.getenv("PAPER_FEEDBACK_MIN_TYPE_SAMPLES","20"))))
MIN_RULE_SAMPLES=max(20,min(200,int(os.getenv("PAPER_FEEDBACK_MIN_RULE_SAMPLES","30"))))
RULE_VERSION="paper-v1-observation"

SCHEMA="""
CREATE TABLE IF NOT EXISTS radar_paper_feedback_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  closed_count INTEGER NOT NULL DEFAULT 0,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  note TEXT
);
CREATE TABLE IF NOT EXISTS radar_paper_feedback_history(
  rule_version TEXT NOT NULL,
  closed_count INTEGER NOT NULL,
  snapshot_time TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL,
  PRIMARY KEY(rule_version,closed_count)
);
"""

def db(read_only=False):
    c=psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=12000 -c lock_timeout=3000')
    if read_only:c.execute("SET TRANSACTION READ ONLY")
    return c

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)",(72419068,))
        cur.execute(SCHEMA)

def finite(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None

def median(xs):
    xs=[finite(x) for x in xs]
    xs=[x for x in xs if x is not None]
    return statistics.median(xs) if xs else None

def mean(xs):
    xs=[finite(x) for x in xs]
    xs=[x for x in xs if x is not None]
    return sum(xs)/len(xs) if xs else None

def positive_pct(xs):
    xs=[finite(x) for x in xs]
    xs=[x for x in xs if x is not None]
    return (sum(1 for x in xs if x>0)/len(xs)*100) if xs else None

def score_band(score):
    s=int(score or 0)
    if s>=85:return "85+"
    if s>=80:return "80-84"
    if s>=75:return "75-79"
    return "70-74"

def exit_bucket(reason):
    r=str(reason or "")
    if "후보 이탈" in r:return "후보 이탈"
    if "관찰도" in r:return "관찰도 하락"
    if "추세" in r or "돌파 실패" in r:return "차트 훼손"
    if "고점 경계" in r:return "고점 경계"
    if "관찰 종료" in r:return "시간 종료"
    return "기타"

def metrics(rows):
    returns=[r.get("return_pct") for r in rows]
    mfes=[r.get("mfe_pct") for r in rows]
    maes=[r.get("mae_pct") for r in rows]
    usable=[r for r in rows if finite(r.get("return_pct")) is not None]
    giveback=[r for r in usable if (finite(r.get("mfe_pct")) or 0)>=1.0 and (finite(r.get("return_pct")) or 0)<=0]
    immediate=[r for r in usable if (finite(r.get("mae_pct")) or 0)<=-1.0 and (finite(r.get("mfe_pct")) or 0)<0.5]
    return {
        "n":len(usable),
        "median_return_pct":median(returns),
        "avg_return_pct":mean(returns),
        "positive_pct":positive_pct(returns),
        "median_mfe_pct":median(mfes),
        "median_mae_pct":median(maes),
        "giveback_pct":(len(giveback)/len(usable)*100) if usable else None,
        "immediate_failure_pct":(len(immediate)/len(usable)*100) if usable else None,
    }

def summarize_groups(rows,keyfn,min_samples):
    groups=defaultdict(list)
    for r in rows:groups[keyfn(r)].append(r)
    out=[]
    for key,rs in groups.items():
        m=metrics(rs)
        if m["n"]<min_samples:
            verdict="SAMPLE_BUILDING";label="표본 축적"
        elif (m["median_return_pct"] or 0)>0 and (m["positive_pct"] or 0)>=50:
            verdict="STABLE";label="유지 관찰"
        else:
            verdict="REVIEW";label="수정 검토"
        out.append({"key":key,**m,"verdict":verdict,"label":label,
                    "small_sample":m["n"]<min_samples})
    out.sort(key=lambda x:(-x["n"],x["key"]))
    return out

def rule_checks(rows):
    checks=[]
    overall=metrics(rows)
    if overall["n"]<MIN_RULE_SAMPLES:
        return [{
            "rule":"전체","status":"SAMPLE_BUILDING","label":"표본 축적",
            "message":f"완료 {overall['n']}건 / 최소 {MIN_RULE_SAMPLES}건. 현재 임계값은 변경하지 않음.",
            "evidence":{"n":overall["n"]}
        }]

    bands=summarize_groups(rows,lambda r:score_band(r.get("entry_score")),10)
    low=next((x for x in bands if x["key"]=="70-74"),None)
    higher=[x for x in bands if x["key"]!="70-74" and x["n"]>=10]
    if low and low["n"]>=10 and higher:
        high_n=sum(x["n"] for x in higher)
        high_returns=[]
        for r in rows:
            if score_band(r.get("entry_score"))!="70-74" and finite(r.get("return_pct")) is not None:
                high_returns.append(r.get("return_pct"))
        high_med=median(high_returns);high_pos=positive_pct(high_returns)
        low_med=low["median_return_pct"];low_pos=low["positive_pct"]
        if low_med is not None and high_med is not None and low_med<=0 and high_med>=low_med+0.5 and (high_pos or 0)>=(low_pos or 0)+10:
            checks.append({
                "rule":"진입 관찰도","status":"REVIEW_CANDIDATE","label":"상향 검토 후보",
                "message":"70~74 구간이 상위 점수구간보다 약하게 관측됨. 70→75 실험 분기를 검토할 근거가 생김.",
                "evidence":{"low_n":low["n"],"low_median":low_med,"low_positive_pct":low_pos,
                            "higher_n":high_n,"higher_median":high_med,"higher_positive_pct":high_pos}
            })
        else:
            checks.append({
                "rule":"진입 관찰도","status":"KEEP","label":"현재값 유지",
                "message":"현재 표본에서는 70~74 구간을 제거할 근거가 충분하지 않음.",
                "evidence":{"low_n":low["n"],"low_median":low_med,"higher_n":high_n,"higher_median":high_med}
            })

    time_rows=[r for r in rows if exit_bucket(r.get("exit_reason"))=="시간 종료" and finite(r.get("return_pct")) is not None]
    tm=metrics(time_rows)
    if tm["n"]>=10:
        if (tm["median_return_pct"] or 0)<=0 and (tm["median_mfe_pct"] or 0)>=1:
            checks.append({
                "rule":"최대 관찰시간","status":"REVIEW_CANDIDATE","label":"청산 구조 검토",
                "message":"시간 종료군은 중간 상승폭이 있었지만 종료 시점 중앙값이 약함. 되돌림 관리 규칙을 별도 실험할 후보.",
                "evidence":tm
            })
        else:
            checks.append({
                "rule":"최대 관찰시간","status":"KEEP","label":"현재값 유지",
                "message":"30분 시간 종료 규칙을 바꿀 충분한 근거가 아직 없음.",
                "evidence":tm
            })

    if (overall["giveback_pct"] or 0)>=30:
        checks.append({
            "rule":"되돌림 관리","status":"REVIEW_CANDIDATE","label":"되돌림 과다",
            "message":"MFE +1% 이상을 기록한 뒤 0% 이하로 끝난 비율이 높음. 별도 청산 실험군이 필요함.",
            "evidence":{"giveback_pct":overall["giveback_pct"],"n":overall["n"]}
        })
    if (overall["immediate_failure_pct"] or 0)>=25:
        checks.append({
            "rule":"진입 필터","status":"REVIEW_CANDIDATE","label":"초기 실패 과다",
            "message":"진입 후 MAE -1% 이하이면서 MFE +0.5% 미만인 사례 비중이 높음. 진입 필터 강화 실험 후보.",
            "evidence":{"immediate_failure_pct":overall["immediate_failure_pct"],"n":overall["n"]}
        })
    if not checks:
        checks.append({
            "rule":"전체","status":"KEEP","label":"현재값 유지",
            "message":"현재 표본에서 명확한 임계값 변경 근거가 없음.",
            "evidence":overall
        })
    return checks

def analyze(rows):
    closed=[r for r in rows if r.get("status")=="CLOSED" and finite(r.get("return_pct")) is not None]
    overall=metrics(closed)
    types=summarize_groups(closed,lambda r:r.get("primary_type") or "미분류",MIN_TYPE_SAMPLES)
    bands=summarize_groups(closed,lambda r:score_band(r.get("entry_score")),10)
    exits=Counter(exit_bucket(r.get("exit_reason")) for r in closed)
    if overall["n"]<MIN_RULE_SAMPLES:
        state="SAMPLE_BUILDING";label="표본 축적"
    elif any(x["status"]=="REVIEW_CANDIDATE" for x in rule_checks(closed)):
        state="REVIEW";label="수정 후보 있음"
    else:
        state="STABLE";label="현재 규칙 유지"
    return {
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "rule_version":RULE_VERSION,
        "lookback_days":LOOKBACK_DAYS,
        "state":state,"label":label,
        "overall":overall,
        "types":types,
        "score_bands":bands,
        "exit_reasons":[{"reason":k,"count":v} for k,v in exits.most_common()],
        "checks":rule_checks(closed),
        "gates":{"min_type_samples":MIN_TYPE_SAMPLES,"min_rule_samples":MIN_RULE_SAMPLES},
        "note":"자동 피드백은 관찰 규칙 변경 후보만 제시하며 실제 규칙·환경변수·주문을 변경하지 않음"
    }

def load_rows(cur):
    cur.execute("""SELECT status,return_pct,mfe_pct,mae_pct,entry_score,primary_type,
                          market_theme,event_type,exit_reason,opened_at,closed_at
                   FROM radar_paper_trades
                   WHERE rule_version=%s AND opened_at>now()-(%s || ' days')::interval
                   ORDER BY opened_at""",(RULE_VERSION,LOOKBACK_DAYS))
    return [dict(r) for r in cur.fetchall()]

def cycle():
    with db() as c,c.cursor() as cur:
        rows=load_rows(cur)
        payload=analyze(rows)
        n=int(payload["overall"]["n"] or 0)
        cur.execute("""INSERT INTO radar_paper_feedback_status(
                       id,updated_at,status,rule_version,closed_count,payload,note)
                       VALUES(1,now(),%s,%s,%s,%s::jsonb,%s)
                       ON CONFLICT(id) DO UPDATE SET updated_at=now(),status=excluded.status,
                         rule_version=excluded.rule_version,closed_count=excluded.closed_count,
                         payload=excluded.payload,note=excluded.note""",
                    (payload["state"],RULE_VERSION,n,json.dumps(payload,ensure_ascii=False),payload["note"]))
        cur.execute("""INSERT INTO radar_paper_feedback_history(rule_version,closed_count,snapshot_time,payload)
                       VALUES(%s,%s,now(),%s::jsonb)
                       ON CONFLICT(rule_version,closed_count) DO UPDATE
                       SET snapshot_time=excluded.snapshot_time,payload=excluded.payload""",
                    (RULE_VERSION,n,json.dumps(payload,ensure_ascii=False)))

def main():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    schema()
    print(f"Paper feedback started: {RULE_VERSION}; auto-change disabled",flush=True)
    while True:
        started=time.monotonic()
        try:cycle()
        except Exception as exc:print("Paper feedback error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))

if __name__=="__main__":
    main()
