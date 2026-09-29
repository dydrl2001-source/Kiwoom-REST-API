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




def _validation_gate(segment):
    """Deterministic shadow gate for deciding what deserves human rule review.

    This never changes live tiers or thresholds. It only classifies already
    resolved learning evidence into HOLD / PROMOTE_REVIEW / SUPPRESS_REVIEW.
    """
    horizon=segment.get("horizon")
    if horizon not in ("30m","close","D+1"):
        return None

    depth=segment.get("interaction_depth",_segment_depth(segment.get("segment_type")))
    quality=segment.get("quality") or _quality(
        segment.get("samples",0),segment.get("distinct_stocks",0),
        segment.get("distinct_days",0),depth
    )
    qrank=_quality_rank(quality)
    if qrank<2:
        return None

    avg=segment.get("avg_return_pct")
    median=segment.get("median_return_pct")
    positive=segment.get("positive_rate")
    if avg is None or median is None or positive is None:
        return {
            "status":"HOLD","direction":"MIXED","quality":quality,
            "reason_codes":["MISSING_CORE_METRIC"],
        }

    strength=avg>=0.50 and median>0 and positive>=0.58
    weakness=avg<=-0.30 and median<0 and positive<=0.42
    if not strength and not weakness:
        return {
            "status":"HOLD","direction":"MIXED","quality":quality,
            "reason_codes":["CORE_EFFECT_NOT_ALIGNED"],
        }

    direction="STRENGTH" if strength else "WEAKNESS"
    reasons=["CORE_EFFECT_ALIGNED","MULTI_DAY_DIVERSITY"]
    if depth>=2:
        baseline=segment.get("baseline") or {}
        if not segment.get("edge_ready"):
            return {
                "status":"HOLD","direction":direction,"quality":quality,
                "reason_codes":reasons+["COMPARATOR_NOT_READY"],
            }
        edge_avg=segment.get("edge_avg_return_pct")
        edge_pos=segment.get("edge_positive_rate_pp")
        edge_mae=segment.get("edge_mae_pct")
        comparator_quality=baseline.get("quality")
        if _quality_rank(comparator_quality)<2:
            return {
                "status":"HOLD","direction":direction,"quality":quality,
                "reason_codes":reasons+["COMPARATOR_NOT_DIVERSE"],
            }
        if direction=="STRENGTH":
            edge_ok=(edge_avg is not None and edge_avg>=0.20
                     and edge_pos is not None and edge_pos>=3.0
                     and (edge_mae is None or edge_mae>=0))
        else:
            edge_ok=(edge_avg is not None and edge_avg<=-0.20
                     and edge_pos is not None and edge_pos<=-3.0
                     and (edge_mae is None or edge_mae<=0))
        if not edge_ok:
            return {
                "status":"HOLD","direction":direction,"quality":quality,
                "reason_codes":reasons+["EDGE_EFFECT_NOT_ALIGNED"],
            }
        reasons+=["PARENT_COMPLEMENT_READY","EDGE_EFFECT_ALIGNED"]

    status="PROMOTE_REVIEW" if direction=="STRENGTH" else "SUPPRESS_REVIEW"
    readiness="READY" if qrank>=3 else "FORMING"
    return {
        "status":status,"direction":direction,"quality":quality,
        "readiness":readiness,"reason_codes":reasons,
    }


def _walk_forward_gate(segment,windows,direction):
    """Require time-split persistence before a review candidate can advance."""
    by_name={x.get("window_name"):x for x in (windows or [])}
    early=by_name.get("EARLY");recent=by_name.get("RECENT")
    if not early or not recent:
        return {
            "status":"INSUFFICIENT","ready":False,
            "reason_codes":["WALK_FORWARD_WINDOWS_MISSING"],
            "early":early,"recent":recent,
        }

    depth=segment.get("interaction_depth",_segment_depth(segment.get("segment_type")))
    min_samples={1:10,2:14,3:18,4:22}.get(depth,22)
    min_stocks={1:3,2:4,3:5,4:6}.get(depth,6)

    def diverse(w):
        return (int(w.get("samples") or 0)>=min_samples
                and int(w.get("distinct_stocks") or 0)>=min_stocks
                and int(w.get("distinct_days") or 0)>=2)

    if not diverse(early) or not diverse(recent):
        return {
            "status":"INSUFFICIENT","ready":False,
            "reason_codes":["WALK_FORWARD_DIVERSITY_LOW"],
            "early":early,"recent":recent,
        }

    def aligned(w):
        avg=w.get("avg_return_pct");med=w.get("median_return_pct");pos=w.get("positive_rate")
        if avg is None or med is None or pos is None:
            return False
        if direction=="STRENGTH":
            return avg>0 and med>=0 and pos>=0.50
        if direction=="WEAKNESS":
            return avg<0 and med<=0 and pos<=0.50
        return False

    early_ok=aligned(early);recent_ok=aligned(recent)
    if not recent_ok:
        avg=recent.get("avg_return_pct")
        reversed_sign=(direction=="STRENGTH" and avg is not None and avg<0) or (
            direction=="WEAKNESS" and avg is not None and avg>0
        )
        return {
            "status":"REVERSAL" if reversed_sign else "UNSTABLE","ready":False,
            "reason_codes":["RECENT_DIRECTION_REVERSED" if reversed_sign else "RECENT_DIRECTION_WEAK"],
            "early":early,"recent":recent,
        }
    if not early_ok:
        return {
            "status":"UNSTABLE","ready":False,
            "reason_codes":["EARLY_DIRECTION_WEAK"],
            "early":early,"recent":recent,
        }

    full_threshold=.50 if direction=="STRENGTH" else .30
    recent_avg=abs(float(recent.get("avg_return_pct") or 0))
    if recent_avg < full_threshold*.35:
        return {
            "status":"WEAKENING","ready":False,
            "reason_codes":["RECENT_EFFECT_TOO_SMALL"],
            "early":early,"recent":recent,
        }

    if depth>=2:
        comp_min=max(8,min_samples//2)
        comp_stocks=max(3,min_stocks-1)
        for name,w in (("EARLY",early),("RECENT",recent)):
            if (int(w.get("comparator_samples") or 0)<comp_min
                    or int(w.get("comparator_stocks") or 0)<comp_stocks
                    or int(w.get("comparator_days") or 0)<2):
                return {
                    "status":"INSUFFICIENT","ready":False,
                    "reason_codes":[f"{name}_COMPARATOR_DIVERSITY_LOW"],
                    "early":early,"recent":recent,
                }
            d_avg=w.get("delta_avg_return_pct")
            d_pos=w.get("delta_positive_rate_pp")
            d_mae=w.get("delta_mae_pct")
            if direction=="STRENGTH":
                edge_ok=(d_avg is not None and d_avg>0
                         and d_pos is not None and d_pos>0
                         and (d_mae is None or d_mae>=0))
            else:
                edge_ok=(d_avg is not None and d_avg<0
                         and d_pos is not None and d_pos<0
                         and (d_mae is None or d_mae<=0))
            if not edge_ok:
                return {
                    "status":"REVERSAL" if name=="RECENT" else "UNSTABLE",
                    "ready":False,
                    "reason_codes":[f"{name}_EDGE_DIRECTION_MISMATCH"],
                    "early":early,"recent":recent,
                }

    early_avg=abs(float(early.get("avg_return_pct") or 0))
    retention=(recent_avg/early_avg) if early_avg>1e-9 else None
    return {
        "status":"STABLE","ready":True,
        "retention_ratio":retention,
        "reason_codes":["EARLY_RECENT_DIRECTION_ALIGNED","WALK_FORWARD_DIVERSITY_OK"],
        "early":early,"recent":recent,
    }


def _validation_candidates(segments,walk_forward_rows=None):
    """Return review-worthy shadow evidence without altering the live engine."""
    wf_index=defaultdict(list)
    for w in walk_forward_rows or []:
        wf_index[(w.get("segment_type"),w.get("segment_value"),w.get("horizon"))].append(w)

    rows=[]
    for s in segments:
        gate=_validation_gate(s)
        if not gate:
            continue
        key=(s.get("segment_type"),s.get("segment_value"),s.get("horizon"))
        wf=None
        if gate.get("direction") in ("STRENGTH","WEAKNESS"):
            wf=_walk_forward_gate(s,wf_index.get(key),gate["direction"])
            if gate.get("status") in ("PROMOTE_REVIEW","SUPPRESS_REVIEW"):
                if wf.get("ready"):
                    gate["reason_codes"]=gate.get("reason_codes",[])+["WALK_FORWARD_STABLE"]
                else:
                    gate["status"]="HOLD"
                    gate["readiness"]="WAIT_WALK_FORWARD"
                    gate["reason_codes"]=gate.get("reason_codes",[])+wf.get("reason_codes",[])
        row={
            "segment_type":s.get("segment_type"),
            "segment_value":s.get("segment_value"),
            "horizon":s.get("horizon"),
            "samples":s.get("samples",0),
            "distinct_stocks":s.get("distinct_stocks",0),
            "distinct_days":s.get("distinct_days",0),
            "interaction_depth":s.get("interaction_depth",_segment_depth(s.get("segment_type"))),
            "avg_return_pct":s.get("avg_return_pct"),
            "median_return_pct":s.get("median_return_pct"),
            "positive_rate":s.get("positive_rate"),
            "avg_mfe_pct":s.get("avg_mfe_pct"),
            "avg_mae_pct":s.get("avg_mae_pct"),
            "edge_avg_return_pct":s.get("edge_avg_return_pct"),
            "edge_positive_rate_pp":s.get("edge_positive_rate_pp"),
            "edge_mae_pct":s.get("edge_mae_pct"),
            "baseline":s.get("baseline"),
            "walk_forward":wf,
            **gate,
        }
        rows.append(row)
    priority={"PROMOTE_REVIEW":0,"SUPPRESS_REVIEW":1,"HOLD":2}
    stability={"STABLE":0,"WEAKENING":1,"UNSTABLE":2,"REVERSAL":3,"INSUFFICIENT":4}
    rows.sort(key=lambda x:(
        priority.get(x["status"],9),
        stability.get((x.get("walk_forward") or {}).get("status"),9),
        -_quality_rank(x.get("quality")),
        -x.get("interaction_depth",1),
        -x.get("samples",0),
        {"close":0,"D+1":1,"30m":2}.get(x.get("horizon"),9)
    ))
    return rows


def _promotion_stage(segment,validation=None):
    """Map current evidence to the registry lifecycle.

    Automatic evidence may advance only through PROMOTION_CANDIDATE.
    SHADOW_RULE is intentionally excluded and requires a separate manual action.
    """
    horizon=segment.get("horizon")
    if horizon not in ("30m","close","D+1"):
        return None

    depth=segment.get("interaction_depth",_segment_depth(segment.get("segment_type")))
    quality=segment.get("quality") or _quality(
        segment.get("samples",0),segment.get("distinct_stocks",0),
        segment.get("distinct_days",0),depth
    )
    qrank=_quality_rank(quality)
    base={
        "stage":"HYPOTHESIS","direction":"MIXED","review_action":"NONE",
        "quality":quality,"reason_codes":[],
    }
    if qrank==0:
        base["reason_codes"]=["EVIDENCE_EXPLORATORY"]
        return base
    if qrank==1:
        base.update(stage="FORMING",reason_codes=["EVIDENCE_INITIAL"])
        return base

    cumulative=_validation_gate(segment)
    if not cumulative or cumulative.get("status")=="HOLD":
        base.update(
            stage="FORMING",
            direction=(cumulative or {}).get("direction","MIXED"),
            reason_codes=(cumulative or {}).get("reason_codes",["CUMULATIVE_GATE_NOT_PASSED"])
        )
        return base

    direction=cumulative.get("direction","MIXED")
    review_action="PROMOTE" if direction=="STRENGTH" else "SUPPRESS" if direction=="WEAKNESS" else "NONE"
    base.update(
        stage="VALIDATED",direction=direction,review_action=review_action,
        reason_codes=list(cumulative.get("reason_codes") or [])+["CUMULATIVE_GATE_PASSED"]
    )
    wf=(validation or {}).get("walk_forward") or {}
    if wf.get("status")!="STABLE" or not wf.get("ready"):
        base["reason_codes"]+=list(wf.get("reason_codes") or ["WALK_FORWARD_NOT_STABLE"])
        return base

    base.update(stage="STABLE")
    base["reason_codes"]+=["WALK_FORWARD_STABLE"]
    if qrank>=3 and (validation or {}).get("status") in ("PROMOTE_REVIEW","SUPPRESS_REVIEW"):
        base.update(stage="PROMOTION_CANDIDATE")
        base["reason_codes"]+=["SUFFICIENT_EVIDENCE_FOR_HUMAN_REVIEW"]
    return base


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
        "status":None,"segments":[],"interactions":[],"validation_candidates":[],
        "validation_summary":{"promote_review":0,"suppress_review":0,"hold":0,
                              "stable":0,"weakening":0,"reversal":0,"insufficient":0},
        "promotion_registry":[],
        "promotion_summary":{"hypothesis":0,"forming":0,"validated":0,"stable":0,
                             "promotion_candidate":0,"shadow_rule":0},
        "promotion_events":[],
        "shadow_lab":{
            "mode":"PROSPECTIVE_AB",
            "enabled":os.getenv("MARKET_OS_SHADOW_LAB_ENABLED","1").strip().lower() in {"1","true","yes","on"},
            "rules":[],"summaries":[],"decisions":[],"decision_events":[],
            "decision_summary":{"collecting":0,"comparable":0,"consistent":0,
                                "accept_candidate":0,"reject":0,"more_data":0},
            "stats":{"rules":0,"enabled_rules":0,"observations":0,"matched":0,"changed":0},
            "notice":"수동 승인 시각 이후 새 assessment만 CONTROL/CHALLENGER로 동시 기록합니다. ACCEPT_CANDIDATE도 사람의 교체 검토 자격일 뿐 live tier/점수/주문을 변경하지 않습니다."
        },
        "adoption_review":{
            "dossiers":[],"events":[],
            "summary":{"pending":0,"approved_dry_run":0,"rejected":0,
                       "superseded":0,"stale_decision":0},
            "notice":"ACCEPT_CANDIDATE의 증거·반례·영향범위·rollback 조건을 immutable revision으로 심사합니다. APPROVED_DRY_RUN도 live rule 생성이 아닙니다."
        },
        "ruleset_dry_run":{
            "enabled":os.getenv("MARKET_OS_RULESET_DRY_RUN_ENABLED","1").strip().lower() in {"1","true","yes","on"},
            "rulesets":[],"summaries":[],"events":[],
            "succession_decisions":[],"succession_events":[],
            "succession_summary":{"collecting":0,"comparable":0,"stable":0,
                                  "succession_candidate":0,"more_data":0,"reject":0},
            "summary":{"active":0,"stopped":0,"stale_source":0,"observations":0,"changed":0},
            "notice":"APPROVED_DRY_RUN dossier를 사람이 다시 시작한 뒤 CONTROL market-os-v1과 immutable candidate ruleset을 prospective로 병렬 계산합니다. SUCCESSION_CANDIDATE도 release 검토 자격일 뿐 live Market OS는 변경하지 않습니다."
        },
        "release_canary":{
            "enabled":os.getenv("MARKET_OS_CANARY_ENABLED","1").strip().lower() in {"1","true","yes","on"},
            "releases":[],"summaries":[],"decisions":[],"events":[],"decision_events":[],
            "recent_observations":[],
            "summary":{"release_candidate":0,"active":0,"stopped":0,"source_stale":0,
                       "rollback_required":0,"promotion_candidate":0,
                       "observations":0,"changed":0},
            "notice":"Release Candidate는 deterministic stock-day Canary preview에서만 candidate tier를 계산합니다. 기본 Market OS watch_tier와 주문/포지션은 CONTROL 그대로입니다."
        },
        "full_release_review":{
            "gates":[],"gate_events":[],"reviews":[],"review_events":[],
            "summary":{"more_data":0,"review_ready":0,"pending":0,
                       "release_ready":0,"rejected":0,"stale_canary":0,"superseded":0},
            "notice":"Canary promotion 후보를 전체 Dry Run, Canary 대표성, CONTROL rollback identity와 다시 대조한 immutable Full Release Review입니다. RELEASE_READY도 배포가 아닙니다."
        },
        "notes":[],"daily_assessments":[],
    }
    edge_rows=[]
    walk_forward_rows=[]
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
        if exists(cur,"market_os_walk_forward_windows"):
            cur.execute("""SELECT segment_type,segment_value,horizon,window_name,start_day,end_day,
                                  samples,distinct_stocks,distinct_days,avg_return_pct,median_return_pct,
                                  positive_rate,avg_mfe_pct,avg_mae_pct,comparator_samples,
                                  comparator_stocks,comparator_days,comparator_avg_return_pct,
                                  comparator_positive_rate,comparator_avg_mae_pct,delta_avg_return_pct,
                                  delta_positive_rate_pp,delta_mae_pct
                           FROM market_os_walk_forward_windows""")
            for r in cur.fetchall():
                x=dict(r)
                x["start_day"]=r["start_day"].isoformat() if r["start_day"] else None
                x["end_day"]=r["end_day"].isoformat() if r["end_day"] else None
                walk_forward_rows.append(x)
        if exists(cur,"market_os_promotion_registry"):
            cur.execute("""SELECT candidate_key,segment_type,segment_value,horizon,interaction_depth,
                                  current_stage,direction,review_action,manual_review_state,active,
                                  first_seen_at,last_seen_at,stage_since,last_transition_at,
                                  samples,distinct_stocks,distinct_days,quality,walk_forward_status,
                                  avg_return_pct,median_return_pct,positive_rate,
                                  edge_avg_return_pct,edge_positive_rate_pp,edge_mae_pct,
                                  early_avg_return_pct,recent_avg_return_pct,reason_codes,
                                  shadow_rule_id,manual_note
                           FROM market_os_promotion_registry
                           WHERE rule_version=%s AND active=TRUE
                           ORDER BY CASE current_stage
                               WHEN 'SHADOW_RULE' THEN 1
                               WHEN 'PROMOTION_CANDIDATE' THEN 2
                               WHEN 'STABLE' THEN 3
                               WHEN 'VALIDATED' THEN 4
                               WHEN 'FORMING' THEN 5
                               ELSE 6 END,
                               samples DESC,segment_type,segment_value""",(RULE_VERSION,))
            for r in cur.fetchall():
                x=dict(r)
                for k in ("first_seen_at","last_seen_at","stage_since","last_transition_at"):
                    x[k]=r[k].isoformat() if r[k] else None
                learning["promotion_registry"].append(x)
            for stage,key in (
                ("HYPOTHESIS","hypothesis"),("FORMING","forming"),
                ("VALIDATED","validated"),("STABLE","stable"),
                ("PROMOTION_CANDIDATE","promotion_candidate"),("SHADOW_RULE","shadow_rule")
            ):
                learning["promotion_summary"][key]=sum(
                    x["current_stage"]==stage for x in learning["promotion_registry"]
                )
        if exists(cur,"market_os_promotion_events"):
            cur.execute("""SELECT e.event_id,e.candidate_key,e.event_time,e.event_type,
                                  e.from_stage,e.to_stage,e.direction,e.review_action,e.reason_codes,
                                  r.segment_type,r.segment_value,r.horizon
                           FROM market_os_promotion_events e
                           LEFT JOIN market_os_promotion_registry r
                             ON r.candidate_key=e.candidate_key
                           ORDER BY e.event_time DESC LIMIT 30""")
            for r in cur.fetchall():
                x=dict(r)
                x["event_time"]=r["event_time"].isoformat() if r["event_time"] else None
                learning["promotion_events"].append(x)
        if exists(cur,"market_os_shadow_rules"):
            cur.execute("""SELECT r.shadow_rule_id,r.candidate_key,r.segment_type,r.segment_value,
                                  r.source_horizon,r.action,r.enabled,r.approved_at,r.approved_by,
                                  r.created_at,r.disabled_at,r.last_evaluated_at,r.note,r.spec,
                                  COUNT(o.*) AS observations,
                                  COUNT(o.*) FILTER(WHERE o.matched) AS matched,
                                  COUNT(o.*) FILTER(WHERE o.changed) AS changed,
                                  MIN(o.assessment_time) AS first_observation_at,
                                  MAX(o.assessment_time) AS last_observation_at
                           FROM market_os_shadow_rules r
                           LEFT JOIN market_os_shadow_observations o
                             ON o.shadow_rule_id=r.shadow_rule_id
                           GROUP BY r.shadow_rule_id
                           ORDER BY r.enabled DESC,r.approved_at DESC""")
            for r in cur.fetchall():
                x=dict(r)
                for k in ("approved_at","created_at","disabled_at","last_evaluated_at",
                          "first_observation_at","last_observation_at"):
                    x[k]=r[k].isoformat() if r[k] else None
                x["observations"]=int(r["observations"] or 0)
                x["matched"]=int(r["matched"] or 0)
                x["changed"]=int(r["changed"] or 0)
                learning["shadow_lab"]["rules"].append(x)
            learning["shadow_lab"]["stats"]["rules"]=len(learning["shadow_lab"]["rules"])
            learning["shadow_lab"]["stats"]["enabled_rules"]=sum(
                bool(x["enabled"]) for x in learning["shadow_lab"]["rules"]
            )
            learning["shadow_lab"]["stats"]["observations"]=sum(
                x["observations"] for x in learning["shadow_lab"]["rules"]
            )
            learning["shadow_lab"]["stats"]["matched"]=sum(
                x["matched"] for x in learning["shadow_lab"]["rules"]
            )
            learning["shadow_lab"]["stats"]["changed"]=sum(
                x["changed"] for x in learning["shadow_lab"]["rules"]
            )
        if exists(cur,"market_os_shadow_experiment_summary"):
            cur.execute("""SELECT shadow_rule_id,horizon,cohort,evidence_state,membership_changes,
                                  control_samples,control_stocks,control_days,
                                  control_avg_return_pct,control_median_return_pct,
                                  control_positive_rate,control_avg_mfe_pct,control_avg_mae_pct,
                                  challenger_samples,challenger_stocks,challenger_days,
                                  challenger_avg_return_pct,challenger_median_return_pct,
                                  challenger_positive_rate,challenger_avg_mfe_pct,challenger_avg_mae_pct,
                                  delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct,updated_at
                           FROM market_os_shadow_experiment_summary
                           ORDER BY CASE evidence_state
                               WHEN 'COMPARABLE' THEN 1 WHEN 'FORMING' THEN 2
                               WHEN 'COLLECTING' THEN 3 ELSE 4 END,
                               CASE horizon WHEN '30m' THEN 1 WHEN 'close' THEN 2
                                    WHEN 'D+1' THEN 3 ELSE 4 END,
                               cohort,shadow_rule_id""")
            for r in cur.fetchall():
                x=dict(r)
                x["updated_at"]=r["updated_at"].isoformat() if r["updated_at"] else None
                learning["shadow_lab"]["summaries"].append(x)
        if exists(cur,"market_os_shadow_decisions"):
            cur.execute("""SELECT d.shadow_rule_id,d.decision_state,d.review_eligible,
                                  d.primary_cohort,d.reason_codes,d.evidence,
                                  d.manual_decision_state,d.state_since,d.updated_at,
                                  r.segment_type,r.segment_value,r.source_horizon,r.action,r.enabled
                           FROM market_os_shadow_decisions d
                           LEFT JOIN market_os_shadow_rules r
                             ON r.shadow_rule_id=d.shadow_rule_id
                           ORDER BY CASE d.decision_state
                               WHEN 'ACCEPT_CANDIDATE' THEN 1
                               WHEN 'CONSISTENT' THEN 2
                               WHEN 'COMPARABLE' THEN 3
                               WHEN 'MORE_DATA' THEN 4
                               WHEN 'COLLECTING' THEN 5
                               WHEN 'REJECT' THEN 6 ELSE 7 END,
                               d.updated_at DESC""")
            for r in cur.fetchall():
                x=dict(r)
                for k in ("state_since","updated_at"):
                    x[k]=r[k].isoformat() if r[k] else None
                learning["shadow_lab"]["decisions"].append(x)
            for state,key in (
                ("COLLECTING","collecting"),("COMPARABLE","comparable"),
                ("CONSISTENT","consistent"),("ACCEPT_CANDIDATE","accept_candidate"),
                ("REJECT","reject"),("MORE_DATA","more_data")
            ):
                learning["shadow_lab"]["decision_summary"][key]=sum(
                    x["decision_state"]==state for x in learning["shadow_lab"]["decisions"]
                )
        if exists(cur,"market_os_shadow_decision_events"):
            cur.execute("""SELECT e.event_id,e.shadow_rule_id,e.event_time,e.from_state,e.to_state,
                                  e.review_eligible,e.reason_codes,
                                  r.segment_type,r.segment_value,r.source_horizon,r.action
                           FROM market_os_shadow_decision_events e
                           LEFT JOIN market_os_shadow_rules r
                             ON r.shadow_rule_id=e.shadow_rule_id
                           ORDER BY e.event_time DESC LIMIT 30""")
            for r in cur.fetchall():
                x=dict(r)
                x["event_time"]=r["event_time"].isoformat() if r["event_time"] else None
                learning["shadow_lab"]["decision_events"].append(x)
        if exists(cur,"market_os_adoption_dossiers"):
            cur.execute("""SELECT d.dossier_id,d.shadow_rule_id,d.revision,d.content_hash,
                                  d.decision_state,d.decision_updated_at,d.review_state,
                                  d.generated_at,d.reviewed_at,d.reviewed_by,d.review_note,d.dossier,
                                  r.segment_type,r.segment_value,r.source_horizon,r.action
                           FROM market_os_adoption_dossiers d
                           LEFT JOIN market_os_shadow_rules r
                             ON r.shadow_rule_id=d.shadow_rule_id
                           ORDER BY CASE d.review_state
                               WHEN 'PENDING' THEN 1
                               WHEN 'APPROVED_DRY_RUN' THEN 2
                               WHEN 'REJECTED' THEN 3
                               WHEN 'STALE_DECISION' THEN 4
                               WHEN 'SUPERSEDED' THEN 5 ELSE 6 END,
                               d.generated_at DESC,d.revision DESC""")
            for r in cur.fetchall():
                x=dict(r)
                for k in ("decision_updated_at","generated_at","reviewed_at"):
                    x[k]=r[k].isoformat() if r[k] else None
                learning["adoption_review"]["dossiers"].append(x)
            for state,key in (
                ("PENDING","pending"),("APPROVED_DRY_RUN","approved_dry_run"),
                ("REJECTED","rejected"),("SUPERSEDED","superseded"),
                ("STALE_DECISION","stale_decision")
            ):
                learning["adoption_review"]["summary"][key]=sum(
                    x["review_state"]==state
                    for x in learning["adoption_review"]["dossiers"]
                )
        if exists(cur,"market_os_adoption_dossier_events"):
            cur.execute("""SELECT e.event_id,e.dossier_id,e.event_time,e.event_type,
                                  e.from_review_state,e.to_review_state,e.note,e.evidence,
                                  d.shadow_rule_id,d.revision
                           FROM market_os_adoption_dossier_events e
                           LEFT JOIN market_os_adoption_dossiers d
                             ON d.dossier_id=e.dossier_id
                           ORDER BY e.event_time DESC LIMIT 30""")
            for r in cur.fetchall():
                x=dict(r)
                x["event_time"]=r["event_time"].isoformat() if r["event_time"] else None
                learning["adoption_review"]["events"].append(x)
        if exists(cur,"market_os_versioned_rulesets"):
            cur.execute("""SELECT vr.ruleset_id,vr.version_label,vr.base_rule_version,
                                  vr.source_dossier_id,vr.source_shadow_rule_id,vr.status,
                                  vr.spec_hash,vr.spec,vr.created_at,vr.activated_at,
                                  vr.stopped_at,vr.stale_at,vr.last_evaluated_at,vr.note,
                                  COUNT(o.*) AS observations,
                                  COUNT(o.*) FILTER(WHERE o.changed) AS changed
                           FROM market_os_versioned_rulesets vr
                           LEFT JOIN market_os_ruleset_dry_run_observations o
                             ON o.ruleset_id=vr.ruleset_id
                           GROUP BY vr.ruleset_id
                           ORDER BY CASE vr.status WHEN 'DRY_RUN_ACTIVE' THEN 1
                                    WHEN 'STALE_SOURCE' THEN 2 ELSE 3 END,
                                    vr.activated_at DESC""")
            for r in cur.fetchall():
                x=dict(r)
                for k in ("created_at","activated_at","stopped_at","stale_at","last_evaluated_at"):
                    x[k]=r[k].isoformat() if r[k] else None
                x["observations"]=int(r["observations"] or 0)
                x["changed"]=int(r["changed"] or 0)
                learning["ruleset_dry_run"]["rulesets"].append(x)
            learning["ruleset_dry_run"]["summary"]["active"]=sum(
                x["status"]=="DRY_RUN_ACTIVE" for x in learning["ruleset_dry_run"]["rulesets"]
            )
            learning["ruleset_dry_run"]["summary"]["stopped"]=sum(
                x["status"]=="DRY_RUN_STOPPED" for x in learning["ruleset_dry_run"]["rulesets"]
            )
            learning["ruleset_dry_run"]["summary"]["stale_source"]=sum(
                x["status"]=="STALE_SOURCE" for x in learning["ruleset_dry_run"]["rulesets"]
            )
            learning["ruleset_dry_run"]["summary"]["observations"]=sum(
                x["observations"] for x in learning["ruleset_dry_run"]["rulesets"]
            )
            learning["ruleset_dry_run"]["summary"]["changed"]=sum(
                x["changed"] for x in learning["ruleset_dry_run"]["rulesets"]
            )
        if exists(cur,"market_os_ruleset_dry_run_summary"):
            cur.execute("""SELECT ruleset_id,horizon,cohort,evidence_state,membership_changes,
                                  control_samples,control_stocks,control_days,
                                  control_avg_return_pct,control_median_return_pct,
                                  control_positive_rate,control_avg_mfe_pct,control_avg_mae_pct,
                                  candidate_samples,candidate_stocks,candidate_days,
                                  candidate_avg_return_pct,candidate_median_return_pct,
                                  candidate_positive_rate,candidate_avg_mfe_pct,candidate_avg_mae_pct,
                                  delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct,updated_at
                           FROM market_os_ruleset_dry_run_summary
                           ORDER BY CASE evidence_state WHEN 'COMPARABLE' THEN 1
                                    WHEN 'FORMING' THEN 2 WHEN 'COLLECTING' THEN 3 ELSE 4 END,
                                    CASE horizon WHEN '30m' THEN 1 WHEN 'close' THEN 2
                                    WHEN 'D+1' THEN 3 ELSE 4 END,cohort,ruleset_id""")
            for r in cur.fetchall():
                x=dict(r)
                x["updated_at"]=r["updated_at"].isoformat() if r["updated_at"] else None
                learning["ruleset_dry_run"]["summaries"].append(x)
        if exists(cur,"market_os_ruleset_events"):
            cur.execute("""SELECT event_id,ruleset_id,event_time,event_type,
                                  from_status,to_status,evidence
                           FROM market_os_ruleset_events
                           ORDER BY event_time DESC LIMIT 30""")
            for r in cur.fetchall():
                x=dict(r)
                x["event_time"]=r["event_time"].isoformat() if r["event_time"] else None
                learning["ruleset_dry_run"]["events"].append(x)
        if exists(cur,"market_os_ruleset_succession_decisions"):
            cur.execute("""SELECT d.ruleset_id,d.decision_state,d.review_eligible,
                                  d.primary_cohort,d.reason_codes,d.evidence,
                                  d.manual_review_state,d.state_since,d.updated_at,
                                  r.version_label,r.status,r.source_dossier_id
                           FROM market_os_ruleset_succession_decisions d
                           LEFT JOIN market_os_versioned_rulesets r
                             ON r.ruleset_id=d.ruleset_id
                           ORDER BY CASE d.decision_state
                               WHEN 'SUCCESSION_CANDIDATE' THEN 1
                               WHEN 'RULESET_STABLE' THEN 2
                               WHEN 'RULESET_COMPARABLE' THEN 3
                               WHEN 'RULESET_MORE_DATA' THEN 4
                               WHEN 'RULESET_COLLECTING' THEN 5
                               WHEN 'RULESET_REJECT' THEN 6 ELSE 7 END,
                               d.updated_at DESC""")
            for r in cur.fetchall():
                x=dict(r)
                for k in ("state_since","updated_at"):
                    x[k]=r[k].isoformat() if r[k] else None
                learning["ruleset_dry_run"]["succession_decisions"].append(x)
            for state,key in (
                ("RULESET_COLLECTING","collecting"),
                ("RULESET_COMPARABLE","comparable"),
                ("RULESET_STABLE","stable"),
                ("SUCCESSION_CANDIDATE","succession_candidate"),
                ("RULESET_MORE_DATA","more_data"),
                ("RULESET_REJECT","reject")
            ):
                learning["ruleset_dry_run"]["succession_summary"][key]=sum(
                    x["decision_state"]==state
                    for x in learning["ruleset_dry_run"]["succession_decisions"]
                )
        if exists(cur,"market_os_ruleset_succession_events"):
            cur.execute("""SELECT e.event_id,e.ruleset_id,e.event_time,e.from_state,e.to_state,
                                  e.review_eligible,e.reason_codes,
                                  r.version_label,r.status,r.source_dossier_id
                           FROM market_os_ruleset_succession_events e
                           LEFT JOIN market_os_versioned_rulesets r
                             ON r.ruleset_id=e.ruleset_id
                           ORDER BY e.event_time DESC LIMIT 30""")
            for r in cur.fetchall():
                x=dict(r)
                x["event_time"]=r["event_time"].isoformat() if r["event_time"] else None
                learning["ruleset_dry_run"]["succession_events"].append(x)
        if exists(cur,"market_os_release_candidates"):
            cur.execute("""SELECT rc.release_candidate_id,rc.release_version_label,
                                  rc.source_ruleset_id,rc.source_succession_event_id,
                                  rc.package_hash,rc.package,rc.status,rc.canary_allocation_pct,
                                  rc.created_at,rc.canary_started_at,rc.stopped_at,rc.stale_at,
                                  rc.rollback_at,rc.last_evaluated_at,rc.note,
                                  COUNT(o.*) AS observations,
                                  COUNT(o.*) FILTER(WHERE o.changed) AS changed
                           FROM market_os_release_candidates rc
                           LEFT JOIN market_os_canary_observations o
                             ON o.release_candidate_id=rc.release_candidate_id
                           GROUP BY rc.release_candidate_id
                           ORDER BY CASE rc.status WHEN 'CANARY_ACTIVE' THEN 1
                                    WHEN 'RELEASE_CANDIDATE' THEN 2
                                    WHEN 'CANARY_ROLLBACK_REQUIRED' THEN 3
                                    WHEN 'CANARY_SOURCE_STALE' THEN 4 ELSE 5 END,
                                    rc.created_at DESC""")
            for r in cur.fetchall():
                x=dict(r)
                for k in ("created_at","canary_started_at","stopped_at","stale_at",
                          "rollback_at","last_evaluated_at"):
                    x[k]=r[k].isoformat() if r[k] else None
                x["observations"]=int(r["observations"] or 0)
                x["changed"]=int(r["changed"] or 0)
                learning["release_canary"]["releases"].append(x)
            rel=learning["release_canary"]["releases"]
            sm=learning["release_canary"]["summary"]
            sm["release_candidate"]=sum(x["status"]=="RELEASE_CANDIDATE" for x in rel)
            sm["active"]=sum(x["status"]=="CANARY_ACTIVE" for x in rel)
            sm["stopped"]=sum(x["status"]=="CANARY_STOPPED" for x in rel)
            sm["source_stale"]=sum(x["status"]=="CANARY_SOURCE_STALE" for x in rel)
            sm["rollback_required"]=sum(x["status"]=="CANARY_ROLLBACK_REQUIRED" for x in rel)
            sm["observations"]=sum(x["observations"] for x in rel)
            sm["changed"]=sum(x["changed"] for x in rel)
        if exists(cur,"market_os_canary_summary"):
            cur.execute("""SELECT release_candidate_id,horizon,cohort,evidence_state,
                                  membership_changes,control_samples,control_stocks,control_days,
                                  control_avg_return_pct,control_median_return_pct,
                                  control_positive_rate,control_avg_mfe_pct,control_avg_mae_pct,
                                  candidate_samples,candidate_stocks,candidate_days,
                                  candidate_avg_return_pct,candidate_median_return_pct,
                                  candidate_positive_rate,candidate_avg_mfe_pct,candidate_avg_mae_pct,
                                  delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct,updated_at
                           FROM market_os_canary_summary
                           ORDER BY CASE horizon WHEN '30m' THEN 1 WHEN 'close' THEN 2
                                    WHEN 'D+1' THEN 3 ELSE 4 END,cohort,release_candidate_id""")
            for r in cur.fetchall():
                x=dict(r)
                x["updated_at"]=r["updated_at"].isoformat() if r["updated_at"] else None
                learning["release_canary"]["summaries"].append(x)
        if exists(cur,"market_os_canary_decisions"):
            cur.execute("""SELECT d.release_candidate_id,d.decision_state,d.review_eligible,
                                  d.primary_cohort,d.reason_codes,d.evidence,
                                  d.manual_review_state,d.state_since,d.updated_at,
                                  rc.release_version_label,rc.status,rc.source_ruleset_id,
                                  rc.canary_allocation_pct
                           FROM market_os_canary_decisions d
                           LEFT JOIN market_os_release_candidates rc
                             ON rc.release_candidate_id=d.release_candidate_id
                           ORDER BY CASE d.decision_state
                               WHEN 'CANARY_PROMOTION_CANDIDATE' THEN 1
                               WHEN 'CANARY_HEALTHY' THEN 2
                               WHEN 'CANARY_COLLECTING' THEN 3
                               WHEN 'CANARY_ROLLBACK_REQUIRED' THEN 4 ELSE 5 END,
                               d.updated_at DESC""")
            for r in cur.fetchall():
                x=dict(r)
                for k in ("state_since","updated_at"):
                    x[k]=r[k].isoformat() if r[k] else None
                learning["release_canary"]["decisions"].append(x)
            learning["release_canary"]["summary"]["promotion_candidate"]=sum(
                x["decision_state"]=="CANARY_PROMOTION_CANDIDATE"
                for x in learning["release_canary"]["decisions"]
            )
        if exists(cur,"market_os_release_events"):
            cur.execute("""SELECT event_id,release_candidate_id,event_time,event_type,
                                  from_status,to_status,evidence
                           FROM market_os_release_events
                           ORDER BY event_time DESC LIMIT 30""")
            for r in cur.fetchall():
                x=dict(r);x["event_time"]=r["event_time"].isoformat() if r["event_time"] else None
                learning["release_canary"]["events"].append(x)
        if exists(cur,"market_os_canary_decision_events"):
            cur.execute("""SELECT event_id,release_candidate_id,event_time,from_state,to_state,
                                  review_eligible,reason_codes,evidence
                           FROM market_os_canary_decision_events
                           ORDER BY event_time DESC LIMIT 30""")
            for r in cur.fetchall():
                x=dict(r);x["event_time"]=r["event_time"].isoformat() if r["event_time"] else None
                learning["release_canary"]["decision_events"].append(x)
        if exists(cur,"market_os_canary_observations"):
            cur.execute("""SELECT o.assessment_time,o.stock_code,a.stock_name,o.release_candidate_id,
                                  o.trade_day,o.assignment_bucket,o.allocation_pct,
                                  o.control_tier,o.candidate_tier,o.changed,o.matched_overlays
                           FROM market_os_canary_observations o
                           LEFT JOIN market_os_assessment_snapshots a
                             ON a.snapshot_time=o.assessment_time
                            AND a.stock_code=o.stock_code
                            AND a.rule_version=o.control_rule_version
                           ORDER BY o.assessment_time DESC,o.stock_code
                           LIMIT 40""")
            for r in cur.fetchall():
                x=dict(r)
                x["assessment_time"]=r["assessment_time"].isoformat() if r["assessment_time"] else None
                x["trade_day"]=r["trade_day"].isoformat() if hasattr(r["trade_day"],"isoformat") else str(r["trade_day"])
                learning["release_canary"]["recent_observations"].append(x)
        if exists(cur,"market_os_full_release_gates"):
            cur.execute("""SELECT g.release_candidate_id,g.gate_state,g.review_eligible,
                                  g.reason_codes,g.evidence,g.state_since,g.updated_at,
                                  rc.release_version_label,rc.status,rc.source_ruleset_id
                           FROM market_os_full_release_gates g
                           LEFT JOIN market_os_release_candidates rc
                             ON rc.release_candidate_id=g.release_candidate_id
                           ORDER BY CASE g.gate_state WHEN 'FULL_RELEASE_REVIEW_READY' THEN 1 ELSE 2 END,
                                    g.updated_at DESC""")
            for r in cur.fetchall():
                x=dict(r)
                for k in ("state_since","updated_at"):
                    x[k]=r[k].isoformat() if r[k] else None
                learning["full_release_review"]["gates"].append(x)
            learning["full_release_review"]["summary"]["more_data"]=sum(
                x["gate_state"]=="FULL_RELEASE_MORE_DATA"
                for x in learning["full_release_review"]["gates"]
            )
            learning["full_release_review"]["summary"]["review_ready"]=sum(
                x["gate_state"]=="FULL_RELEASE_REVIEW_READY"
                for x in learning["full_release_review"]["gates"]
            )
        if exists(cur,"market_os_full_release_gate_events"):
            cur.execute("""SELECT event_id,release_candidate_id,event_time,from_state,to_state,
                                  review_eligible,reason_codes,evidence
                           FROM market_os_full_release_gate_events
                           ORDER BY event_time DESC LIMIT 30""")
            for r in cur.fetchall():
                x=dict(r)
                x["event_time"]=r["event_time"].isoformat() if r["event_time"] else None
                learning["full_release_review"]["gate_events"].append(x)
        if exists(cur,"market_os_full_release_reviews"):
            cur.execute("""SELECT fr.review_id,fr.release_candidate_id,fr.revision,
                                  fr.source_gate_event_id,fr.content_hash,fr.gate_state,
                                  fr.review_state,fr.created_at,fr.reviewed_at,
                                  fr.reviewed_by,fr.review_note,fr.package,
                                  rc.release_version_label
                           FROM market_os_full_release_reviews fr
                           LEFT JOIN market_os_release_candidates rc
                             ON rc.release_candidate_id=fr.release_candidate_id
                           ORDER BY CASE fr.review_state
                               WHEN 'PENDING' THEN 1 WHEN 'RELEASE_READY' THEN 2
                               WHEN 'REJECTED' THEN 3 WHEN 'STALE_CANARY' THEN 4
                               WHEN 'SUPERSEDED' THEN 5 ELSE 6 END,
                               fr.created_at DESC,fr.revision DESC""")
            for r in cur.fetchall():
                x=dict(r)
                for k in ("created_at","reviewed_at"):
                    x[k]=r[k].isoformat() if r[k] else None
                learning["full_release_review"]["reviews"].append(x)
            for state,key in (
                ("PENDING","pending"),("RELEASE_READY","release_ready"),
                ("REJECTED","rejected"),("STALE_CANARY","stale_canary"),
                ("SUPERSEDED","superseded")
            ):
                learning["full_release_review"]["summary"][key]=sum(
                    x["review_state"]==state
                    for x in learning["full_release_review"]["reviews"]
                )
        if exists(cur,"market_os_full_release_review_events"):
            cur.execute("""SELECT e.event_id,e.review_id,e.event_time,e.event_type,
                                  e.from_review_state,e.to_review_state,e.note,e.evidence,
                                  fr.release_candidate_id,fr.revision
                           FROM market_os_full_release_review_events e
                           LEFT JOIN market_os_full_release_reviews fr
                             ON fr.review_id=e.review_id
                           ORDER BY e.event_time DESC LIMIT 30""")
            for r in cur.fetchall():
                x=dict(r)
                x["event_time"]=r["event_time"].isoformat() if r["event_time"] else None
                learning["full_release_review"]["review_events"].append(x)
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
    learning["validation_candidates"]=_validation_candidates(learning["segments"],walk_forward_rows)
    learning["validation_summary"]={
        "promote_review":sum(x["status"]=="PROMOTE_REVIEW" for x in learning["validation_candidates"]),
        "suppress_review":sum(x["status"]=="SUPPRESS_REVIEW" for x in learning["validation_candidates"]),
        "hold":sum(x["status"]=="HOLD" for x in learning["validation_candidates"]),
        "stable":sum((x.get("walk_forward") or {}).get("status")=="STABLE" for x in learning["validation_candidates"]),
        "weakening":sum((x.get("walk_forward") or {}).get("status")=="WEAKENING" for x in learning["validation_candidates"]),
        "reversal":sum((x.get("walk_forward") or {}).get("status")=="REVERSAL" for x in learning["validation_candidates"]),
        "insufficient":sum((x.get("walk_forward") or {}).get("status")=="INSUFFICIENT" for x in learning["validation_candidates"]),
    }

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
