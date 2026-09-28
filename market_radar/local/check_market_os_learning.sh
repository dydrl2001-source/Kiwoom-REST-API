#!/bin/bash
# Read-only Market OS learning report. No orders, no API calls, no model calls.
set -eu
cd "$(dirname "$0")"

echo '=== Market OS learning report ==='
docker compose exec -T radar-api python - <<'PY'
import os
import psycopg
from psycopg.rows import dict_row
from market_os_rule_engine import VERSION
from market_os_store import _quality,_segment_depth,_enrich_edges,_validation_candidates

db=os.environ['DATABASE_URL']
with psycopg.connect(db,row_factory=dict_row,connect_timeout=5) as c, c.cursor() as cur:
    def exists(name):
        cur.execute("SELECT to_regclass(%s) AS name",("public."+name,))
        return cur.fetchone()["name"] is not None

    print('RULE_VERSION:',VERSION)
    if not exists('market_os_assessment_snapshots'):
        print('STATUS: assessment table missing')
        raise SystemExit(0)

    cur.execute("""SELECT COUNT(*) AS n,
                          COUNT(*) FILTER(WHERE watch_tier='FOCUS') AS focus,
                          COUNT(*) FILTER(WHERE watch_tier='PREP') AS prep,
                          COUNT(*) FILTER(WHERE micro_tick_count_15s>0) AS micro,
                          COUNT(*) FILTER(WHERE micro_tick_count_15s>0 AND COALESCE(micro_gap_count_15s,0)=0) AS micro_clean
                   FROM market_os_assessment_snapshots
                   WHERE rule_version=%s
                     AND (snapshot_time AT TIME ZONE 'Asia/Seoul')::date=(now() AT TIME ZONE 'Asia/Seoul')::date""",(VERSION,))
    a=cur.fetchone()
    print('ASSESSMENTS_TODAY:',a['n'])
    print('FOCUS_TODAY:',a['focus'])
    print('PREP_TODAY:',a['prep'])
    print('MICRO15_COVERED:',a['micro'])
    print('MICRO15_GAP_FREE:',a['micro_clean'])

    if exists('market_os_assessment_outcomes'):
        cur.execute("""SELECT horizon,COUNT(*) AS n,
                              ROUND(AVG(return_pct)::numeric,3) AS avg_return,
                              ROUND(percentile_cont(.5) WITHIN GROUP(ORDER BY return_pct)::numeric,3) AS median_return,
                              ROUND(AVG(CASE WHEN return_pct>0 THEN 1.0 ELSE 0.0 END)::numeric*100,1) AS positive_pct,
                              ROUND(AVG(mfe_pct)::numeric,3) AS avg_mfe,
                              ROUND(AVG(mae_pct)::numeric,3) AS avg_mae
                       FROM market_os_assessment_outcomes
                       WHERE rule_version=%s
                         AND (calculated_at AT TIME ZONE 'Asia/Seoul')::date=(now() AT TIME ZONE 'Asia/Seoul')::date
                       GROUP BY horizon
                       ORDER BY CASE horizon WHEN '5m' THEN 1 WHEN '30m' THEN 2 WHEN 'close' THEN 3 ELSE 4 END""",(VERSION,))
        print('\n[OUTCOMES]')
        for r in cur.fetchall():
            print(f"{r['horizon']}: N={r['n']} avg={r['avg_return']}% median={r['median_return']}% "
                  f"positive={r['positive_pct']}% MFE={r['avg_mfe']}% MAE={r['avg_mae']}%")

        cur.execute("""SELECT outcome_source,COUNT(*) AS n
                       FROM market_os_assessment_outcomes
                       WHERE rule_version=%s
                         AND (calculated_at AT TIME ZONE 'Asia/Seoul')::date=(now() AT TIME ZONE 'Asia/Seoul')::date
                       GROUP BY outcome_source ORDER BY n DESC""",(VERSION,))
        print('\n[OUTCOME SOURCES]')
        for r in cur.fetchall():
            print(r['outcome_source'],r['n'])

    if exists('market_os_learning_segments'):
        cur.execute("""SELECT segment_type,segment_value,horizon,samples,distinct_stocks,distinct_days,sample_basis,
                              ROUND(avg_return_pct::numeric,3) AS avg_return,
                              ROUND(median_return_pct::numeric,3) AS median_return,
                              ROUND((positive_rate*100)::numeric,1) AS positive_pct,
                              ROUND(avg_mfe_pct::numeric,3) AS avg_mfe,
                              ROUND(avg_mae_pct::numeric,3) AS avg_mae
                       FROM market_os_learning_segments
                       WHERE samples>=5
                       ORDER BY CASE horizon WHEN '5m' THEN 1 WHEN '30m' THEN 2 WHEN 'close' THEN 3 ELSE 4 END,
                                samples DESC,segment_type,segment_value""")
        rows=cur.fetchall()
        segments=[]
        for r in rows:
            s=dict(r)
            s["avg_return_pct"]=float(r["avg_return"]) if r["avg_return"] is not None else None
            s["median_return_pct"]=float(r["median_return"]) if r["median_return"] is not None else None
            s["positive_rate"]=float(r["positive_pct"])/100 if r["positive_pct"] is not None else None
            s["avg_mfe_pct"]=float(r["avg_mfe"]) if r["avg_mfe"] is not None else None
            s["avg_mae_pct"]=float(r["avg_mae"]) if r["avg_mae"] is not None else None
            s["quality"]=_quality(s["samples"],s["distinct_stocks"],s["distinct_days"],_segment_depth(s["segment_type"]))
            segments.append(s)
        edge_rows=[]
        if exists('market_os_interaction_edges'):
            cur.execute("""SELECT segment_type,segment_value,horizon,parent_type,parent_value,sample_basis,
                                  child_samples,child_stocks,child_days,
                                  comparator_samples,comparator_stocks,comparator_days,
                                  child_avg_return_pct,comparator_avg_return_pct,delta_avg_return_pct,
                                  child_positive_rate,comparator_positive_rate,delta_positive_rate_pp,
                                  child_avg_mfe_pct,comparator_avg_mfe_pct,delta_mfe_pct,
                                  child_avg_mae_pct,comparator_avg_mae_pct,delta_mae_pct
                           FROM market_os_interaction_edges""")
            edge_rows=[dict(x) for x in cur.fetchall()]
        interactions=_enrich_edges(segments,edge_rows)
        print('\n[SEGMENTS N>=5]')
        if not rows:
            print('표본 5개 이상 구간 없음')
        for r in rows[:80]:
            print(f"{r['horizon']} | {r['segment_type']}={r['segment_value']} | "
                  f"N={r['samples']} stocks={r['distinct_stocks']} days={r['distinct_days']} basis={r['sample_basis']} "
                  f"avg={r['avg_return']}% med={r['median_return']}% pos={r['positive_pct']}% "
                  f"MFE={r['avg_mfe']}% MAE={r['avg_mae']}%")

        print('\n[INTERACTION LAB]')
        shown=0
        for s in interactions:
            if s["samples"]<5:continue
            b=s.get("baseline") or {}
            edge=s.get("edge_avg_return_pct")
            pos=s.get("edge_positive_rate_pp")
            mae=s.get("edge_mae_pct")
            print(f"{s['horizon']} | d{s.get('interaction_depth',2)} {s['segment_type']}={s['segment_value']} | "
                  f"N={s['samples']} stocks={s['distinct_stocks']} days={s['distinct_days']} q={s['quality']} | "
                  f"avg={s['avg_return_pct']:.3f}% "
                  f"dAvg={(f'{edge:+.3f}pp' if edge is not None else '—')} "
                  f"dPos={(f'{pos:+.1f}pp' if pos is not None else '—')} "
                  f"dMAE={(f'{mae:+.3f}pp' if mae is not None else '—')} | "
                  f"compare={b.get('comparison','—')} parent={b.get('segment_type','—')}:{b.get('segment_value','—')} "
                  f"compN={b.get('samples','—')}")
            shown+=1
            if shown>=40:break
        if not shown:
            print('상호작용 표본 5개 이상 없음')

        wf_rows=[]
        if exists('market_os_walk_forward_windows'):
            cur.execute("""SELECT segment_type,segment_value,horizon,window_name,start_day,end_day,
                                  samples,distinct_stocks,distinct_days,avg_return_pct,median_return_pct,
                                  positive_rate,avg_mfe_pct,avg_mae_pct,comparator_samples,
                                  comparator_stocks,comparator_days,comparator_avg_return_pct,
                                  comparator_positive_rate,comparator_avg_mae_pct,delta_avg_return_pct,
                                  delta_positive_rate_pp,delta_mae_pct
                           FROM market_os_walk_forward_windows""")
            wf_rows=[dict(x) for x in cur.fetchall()]
        gates=_validation_candidates(segments,wf_rows)
        print('\n[VALIDATION GATE v1.3 WALK-FORWARD]')
        if not gates:
            print('형성 등급 이상의 30m/close/D+1 검증 후보 없음')
        else:
            for g in gates[:30]:
                edge=g.get('edge_avg_return_pct')
                edge_txt=(f"{edge:+.3f}pp" if edge is not None else '—')
                wf=g.get('walk_forward') or {}
                early=wf.get('early') or {};recent=wf.get('recent') or {}
                ea=early.get('avg_return_pct');ra=recent.get('avg_return_pct')
                print(f"{g['status']} {g['horizon']} {g['segment_type']}={g['segment_value']} "
                      f"N={g['samples']} stocks={g['distinct_stocks']} days={g['distinct_days']} "
                      f"q={g['quality']} wf={wf.get('status','—')} "
                      f"earlyAvg={(f'{ea:+.3f}%' if ea is not None else '—')} "
                      f"recentAvg={(f'{ra:+.3f}%' if ra is not None else '—')} "
                      f"avg={g['avg_return_pct']:.3f}% med={g['median_return_pct']:.3f}% "
                      f"pos={(g['positive_rate'] or 0)*100:.1f}% dAvg={edge_txt} "
                      f"reasons={','.join(g.get('reason_codes') or [])}")

        print('\n[PROMOTION REGISTRY]')
        if not exists('market_os_promotion_registry'):
            print('promotion registry table missing')
        else:
            cur.execute("""SELECT current_stage,COUNT(*) AS n
                           FROM market_os_promotion_registry
                           WHERE rule_version=%s AND active=TRUE
                           GROUP BY current_stage
                           ORDER BY CASE current_stage
                               WHEN 'SHADOW_RULE' THEN 1
                               WHEN 'PROMOTION_CANDIDATE' THEN 2
                               WHEN 'STABLE' THEN 3
                               WHEN 'VALIDATED' THEN 4
                               WHEN 'FORMING' THEN 5 ELSE 6 END""",(VERSION,))
            stage_rows=cur.fetchall()
            if not stage_rows:
                print('active registry entries 없음')
            for r in stage_rows:
                print(f"{r['current_stage']}: {r['n']}")
            cur.execute("""SELECT candidate_key,current_stage,direction,review_action,manual_review_state,
                                  segment_type,segment_value,horizon,samples,distinct_stocks,distinct_days,
                                  quality,walk_forward_status,early_avg_return_pct,recent_avg_return_pct
                           FROM market_os_promotion_registry
                           WHERE rule_version=%s AND active=TRUE
                           ORDER BY CASE current_stage
                               WHEN 'SHADOW_RULE' THEN 1
                               WHEN 'PROMOTION_CANDIDATE' THEN 2
                               WHEN 'STABLE' THEN 3
                               WHEN 'VALIDATED' THEN 4
                               WHEN 'FORMING' THEN 5 ELSE 6 END,
                               samples DESC LIMIT 30""",(VERSION,))
            for r in cur.fetchall():
                ea=r['early_avg_return_pct'];ra=r['recent_avg_return_pct']
                print(f"{r['current_stage']} {r['review_action']} {r['horizon']} "
                      f"{r['segment_type']}={r['segment_value']} N={r['samples']} "
                      f"stocks={r['distinct_stocks']} days={r['distinct_days']} q={r['quality']} "
                      f"wf={r['walk_forward_status'] or '—'} "
                      f"early={(f'{ea:+.3f}%' if ea is not None else '—')} "
                      f"recent={(f'{ra:+.3f}%' if ra is not None else '—')} "
                      f"manual={r['manual_review_state']}")

        print('\n[PROMOTION TRANSITIONS]')
        if exists('market_os_promotion_events'):
            cur.execute("""SELECT e.event_time,e.event_type,e.from_stage,e.to_stage,e.direction,
                                  e.review_action,r.segment_type,r.segment_value,r.horizon
                           FROM market_os_promotion_events e
                           LEFT JOIN market_os_promotion_registry r ON r.candidate_key=e.candidate_key
                           ORDER BY e.event_time DESC LIMIT 15""")
            events=cur.fetchall()
            if not events:
                print('transition history 없음')
            for r in events:
                print(f"{r['event_time']} {r['event_type']} "
                      f"{r['from_stage'] or '—'}->{r['to_stage']} "
                      f"{r['direction'] or '—'} {r['review_action'] or '—'} "
                      f"{r['horizon'] or '—'} {r['segment_type'] or '—'}={r['segment_value'] or '—'}")

        print('\n[SHADOW RULE LAB v1.5]')
        if not exists('market_os_shadow_rules'):
            print('shadow rule tables missing')
        else:
            cur.execute("""SELECT r.shadow_rule_id,r.enabled,r.action,r.segment_type,r.segment_value,
                                  r.source_horizon,r.approved_at,
                                  COUNT(o.*) AS observations,
                                  COUNT(o.*) FILTER(WHERE o.matched) AS matched,
                                  COUNT(o.*) FILTER(WHERE o.changed) AS changed
                           FROM market_os_shadow_rules r
                           LEFT JOIN market_os_shadow_observations o
                             ON o.shadow_rule_id=r.shadow_rule_id
                           GROUP BY r.shadow_rule_id
                           ORDER BY r.enabled DESC,r.approved_at DESC""")
            rules=cur.fetchall()
            if not rules:
                print('approved shadow rules 없음')
            for r in rules:
                print(f"{r['shadow_rule_id']} {'ON' if r['enabled'] else 'OFF'} {r['action']} "
                      f"{r['source_horizon']} {r['segment_type']}={r['segment_value']} "
                      f"approved={r['approved_at']} obs={r['observations']} "
                      f"matched={r['matched']} changed={r['changed']}")
        if exists('market_os_shadow_experiment_summary'):
            print('\n[CONTROL vs CHALLENGER]')
            cur.execute("""SELECT shadow_rule_id,horizon,cohort,evidence_state,membership_changes,
                                  control_samples,challenger_samples,control_avg_return_pct,
                                  challenger_avg_return_pct,delta_avg_return_pct,
                                  delta_positive_rate_pp,delta_mae_pct
                           FROM market_os_shadow_experiment_summary
                           ORDER BY CASE evidence_state
                               WHEN 'COMPARABLE' THEN 1 WHEN 'FORMING' THEN 2
                               WHEN 'COLLECTING' THEN 3 ELSE 4 END,
                               shadow_rule_id,horizon,cohort""")
            rows=cur.fetchall()
            if not rows:
                print('prospective outcomes 대기')
            for r in rows[:60]:
                ca=r['control_avg_return_pct'];ha=r['challenger_avg_return_pct'];da=r['delta_avg_return_pct']
                print(f"{r['shadow_rule_id']} {r['horizon']} {r['cohort']} {r['evidence_state']} "
                      f"changes={r['membership_changes']} controlN={r['control_samples']} "
                      f"challengerN={r['challenger_samples']} "
                      f"controlAvg={(f'{ca:+.3f}%' if ca is not None else '—')} "
                      f"challengerAvg={(f'{ha:+.3f}%' if ha is not None else '—')} "
                      f"dAvg={(f'{da:+.3f}pp' if da is not None else '—')} "
                      f"dPos={(f'{r['delta_positive_rate_pp']:+.1f}pp' if r['delta_positive_rate_pp'] is not None else '—')} "
                      f"dMAE={(f'{r['delta_mae_pct']:+.3f}pp' if r['delta_mae_pct'] is not None else '—')}")

        print('\n[INTERACTION REVIEW READY]')
        ready=[s for s in interactions if s.get("edge_ready") and s["horizon"] in ("30m","close")]
        if not ready:
            print('아직 형성 등급 이상의 30m/close 상호작용 없음')
        else:
            for s in ready[:20]:
                print(f"{s['horizon']} {s['segment_type']}={s['segment_value']} "
                      f"N={s['samples']} stocks={s['distinct_stocks']} days={s['distinct_days']} "
                      f"quality={s['quality']} dAvg={s.get('edge_avg_return_pct'):+.3f}pp "
                      f"dPos={s.get('edge_positive_rate_pp'):+.1f}pp")

        review=[s for s in segments
                if s["horizon"] in ("30m","close")
                and s["quality"] in ("형성","충분")
                and s.get("interaction_depth",_segment_depth(s["segment_type"]))==1]
        review.sort(key=lambda s:(s["avg_return_pct"] is None,-(s["avg_return_pct"] or 0)))
        print('\n[BASE REVIEW READY]')
        if not review:
            print('아직 형성 등급 이상의 30m/close 단일축 조건 없음')
        else:
            for s in review[:12]:
                print(f"{s['horizon']} {s['segment_type']}={s['segment_value']} "
                      f"N={s['samples']} stocks={s['distinct_stocks']} days={s['distinct_days']} "
                      f"q={s['quality']} avg={s['avg_return_pct']:.3f}% "
                      f"positive={(s['positive_rate'] or 0)*100:.1f}%")


print('\nSampling: 5m=non-overlap 5m, 30m=non-overlap 30m, close/D+1=one per stock-day.')
print('Interaction policy: only pre-registered regime/setup/trigger/micro combinations are tested; no arbitrary combination search.')
print('Validation gate v1.3: cumulative gate + day-split EARLY/RECENT walk-forward stability; recent reversal/weakening/comparator gaps => HOLD.')
print('Promotion Registry v1.4: lifecycle is persisted with transition history; automation stops at PROMOTION_CANDIDATE and never creates SHADOW_RULE.')
print('Shadow Rule Lab v1.5: only manually approved rules are observed; pre-approval data is excluded and CONTROL/CHALLENGER share identical outcome paths.')
print('Notice: raw snapshots remain stored; segment N is episode-anchor N, not repeated screen snapshots. No threshold or live score was changed.')
PY
