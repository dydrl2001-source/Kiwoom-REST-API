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
                dp=r['delta_positive_rate_pp'];dm=r['delta_mae_pct']
                ca_txt=f"{ca:+.3f}%" if ca is not None else '—'
                ha_txt=f"{ha:+.3f}%" if ha is not None else '—'
                da_txt=f"{da:+.3f}pp" if da is not None else '—'
                dp_txt=f"{dp:+.1f}pp" if dp is not None else '—'
                dm_txt=f"{dm:+.3f}pp" if dm is not None else '—'
                print(f"{r['shadow_rule_id']} {r['horizon']} {r['cohort']} {r['evidence_state']} "
                      f"changes={r['membership_changes']} controlN={r['control_samples']} "
                      f"challengerN={r['challenger_samples']} "
                      f"controlAvg={ca_txt} challengerAvg={ha_txt} "
                      f"dAvg={da_txt} dPos={dp_txt} dMAE={dm_txt}")

        print('\n[SHADOW DECISION GATE v1.6]')
        if not exists('market_os_shadow_decisions'):
            print('shadow decision table missing')
        else:
            cur.execute("""SELECT d.shadow_rule_id,d.decision_state,d.review_eligible,
                                  d.primary_cohort,d.reason_codes,d.manual_decision_state,
                                  d.state_since,d.updated_at,
                                  r.action,r.segment_type,r.segment_value,r.source_horizon
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
            decisions=cur.fetchall()
            if not decisions:
                print('decision rows 없음')
            for r in decisions:
                print(f"{r['decision_state']} eligible={r['review_eligible']} "
                      f"cohort={r['primary_cohort'] or '—'} {r['shadow_rule_id']} "
                      f"{r['action'] or '—'} {r['source_horizon'] or '—'} "
                      f"{r['segment_type'] or '—'}={r['segment_value'] or '—'} "
                      f"manual={r['manual_decision_state']} "
                      f"reasons={','.join(r['reason_codes'] or [])}")
        if exists('market_os_shadow_decision_events'):
            print('\n[SHADOW DECISION TRANSITIONS]')
            cur.execute("""SELECT event_time,shadow_rule_id,from_state,to_state,
                                  review_eligible,reason_codes
                           FROM market_os_shadow_decision_events
                           ORDER BY event_time DESC LIMIT 20""")
            events=cur.fetchall()
            if not events:
                print('decision transition history 없음')
            for r in events:
                print(f"{r['event_time']} {r['shadow_rule_id']} "
                      f"{r['from_state'] or '—'}->{r['to_state']} "
                      f"eligible={r['review_eligible']} "
                      f"reasons={','.join(r['reason_codes'] or [])}")

        print('\n[ADOPTION REVIEW DOSSIER v1.7]')
        if not exists('market_os_adoption_dossiers'):
            print('adoption dossier table missing')
        else:
            cur.execute("""SELECT d.dossier_id,d.shadow_rule_id,d.revision,d.content_hash,
                                  d.source_decision_event_id,d.decision_state,d.review_state,
                                  d.generated_at,d.reviewed_at,
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
                               d.generated_at DESC""")
            dossiers=cur.fetchall()
            if not dossiers:
                print('dossier 없음')
            for r in dossiers[:30]:
                print(f"{r['review_state']} {r['dossier_id']} rev={r['revision']} "
                      f"decision={r['decision_state']} event={r['source_decision_event_id'] or '—'} "
                      f"{r['source_horizon'] or '—'} {r['action'] or '—'} "
                      f"{r['segment_type'] or '—'}={r['segment_value'] or '—'} "
                      f"generated={r['generated_at']} reviewed={r['reviewed_at']} "
                      f"hash={r['content_hash'][:12]}")
        if exists('market_os_adoption_dossier_events'):
            print('\n[ADOPTION DOSSIER EVENTS]')
            cur.execute("""SELECT event_time,dossier_id,event_type,from_review_state,
                                  to_review_state,note
                           FROM market_os_adoption_dossier_events
                           ORDER BY event_time DESC LIMIT 20""")
            rows=cur.fetchall()
            if not rows:
                print('dossier event 없음')
            for r in rows:
                print(f"{r['event_time']} {r['dossier_id']} {r['event_type']} "
                      f"{r['from_review_state'] or '—'}->{r['to_review_state']} "
                      f"{r['note'] or ''}")

        print('\n[VERSIONED RULESET DRY RUN v1.8]')
        if not exists('market_os_versioned_rulesets'):
            print('versioned ruleset table missing')
        else:
            cur.execute("""SELECT vr.ruleset_id,vr.version_label,vr.base_rule_version,
                                  vr.source_dossier_id,vr.status,vr.spec_hash,vr.activated_at,
                                  vr.stopped_at,vr.stale_at,vr.last_evaluated_at,
                                  COUNT(o.*) AS observations,
                                  COUNT(o.*) FILTER(WHERE o.changed) AS changed
                           FROM market_os_versioned_rulesets vr
                           LEFT JOIN market_os_ruleset_dry_run_observations o
                             ON o.ruleset_id=vr.ruleset_id
                           GROUP BY vr.ruleset_id
                           ORDER BY vr.activated_at DESC""")
            rows=cur.fetchall()
            if not rows:
                print('versioned ruleset 없음')
            for r in rows:
                print(f"{r['status']} {r['ruleset_id']} {r['version_label']} "
                      f"base={r['base_rule_version']} dossier={r['source_dossier_id']} "
                      f"obs={r['observations']} changed={r['changed']} "
                      f"activated={r['activated_at']} last_eval={r['last_evaluated_at']} "
                      f"hash={r['spec_hash'][:12]}")
        if exists('market_os_ruleset_dry_run_summary'):
            print('\n[RULESET CONTROL vs CANDIDATE]')
            cur.execute("""SELECT ruleset_id,horizon,cohort,evidence_state,membership_changes,
                                  control_samples,candidate_samples,
                                  control_avg_return_pct,candidate_avg_return_pct,
                                  delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct
                           FROM market_os_ruleset_dry_run_summary
                           ORDER BY ruleset_id,
                                    CASE horizon WHEN '30m' THEN 1 WHEN 'close' THEN 2
                                    WHEN 'D+1' THEN 3 ELSE 4 END,cohort""")
            rows=cur.fetchall()
            if not rows:
                print('ruleset dry-run outcomes 대기')
            for r in rows[:80]:
                print(f"{r['ruleset_id']} {r['horizon']} {r['cohort']} {r['evidence_state']} "
                      f"changes={r['membership_changes']} controlN={r['control_samples']} "
                      f"candidateN={r['candidate_samples']} "
                      f"dAvg={r['delta_avg_return_pct']} dPos={r['delta_positive_rate_pp']} "
                      f"dMAE={r['delta_mae_pct']}")
        if exists('market_os_ruleset_events'):
            print('\n[RULESET EVENTS]')
            cur.execute("""SELECT event_time,ruleset_id,event_type,from_status,to_status
                           FROM market_os_ruleset_events
                           ORDER BY event_time DESC LIMIT 20""")
            for r in cur.fetchall():
                print(f"{r['event_time']} {r['ruleset_id']} {r['event_type']} "
                      f"{r['from_status'] or '—'}->{r['to_status']}")

        print('\n[RULESET SUCCESSION GATE v1.9]')
        if not exists('market_os_ruleset_succession_decisions'):
            print('ruleset succession table missing')
        else:
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
            rows=cur.fetchall()
            if not rows:
                print('succession decision 없음')
            for r in rows:
                ev=r['evidence'] or {}
                conc=ev.get('concentration') or {}
                ret=ev.get('shadow_effect_retention') or {}
                print(f"{r['decision_state']} eligible={r['review_eligible']} "
                      f"{r['ruleset_id']} version={r['version_label'] or '—'} "
                      f"status={r['status'] or '—'} cohort={r['primary_cohort'] or '—'} "
                      f"30m={ev.get('overall_30m','—')} close={ev.get('overall_close','—')} "
                      f"D+1={ev.get('overall_d1','—')} "
                      f"changed={conc.get('changed_episodes','—')} "
                      f"topStock={conc.get('top_stock_share','—')} topDay={conc.get('top_day_share','—')} "
                      f"shadowRet30={ret.get('30m','—')} shadowRetClose={ret.get('close','—')} "
                      f"reasons={','.join(r['reason_codes'] or [])}")
        if exists('market_os_ruleset_succession_events'):
            print('\n[RULESET SUCCESSION TRANSITIONS]')
            cur.execute("""SELECT event_time,ruleset_id,from_state,to_state,
                                  review_eligible,reason_codes
                           FROM market_os_ruleset_succession_events
                           ORDER BY event_time DESC LIMIT 20""")
            rows=cur.fetchall()
            if not rows:
                print('succession transition history 없음')
            for r in rows:
                print(f"{r['event_time']} {r['ruleset_id']} "
                      f"{r['from_state'] or '—'}->{r['to_state']} "
                      f"eligible={r['review_eligible']} "
                      f"reasons={','.join(r['reason_codes'] or [])}")

        print('\n[RELEASE CANDIDATE / CANARY v2.0]')
        if not exists('market_os_release_candidates'):
            print('release candidate tables missing')
        else:
            cur.execute("""SELECT rc.release_candidate_id,rc.release_version_label,
                                  rc.source_ruleset_id,rc.status,rc.canary_allocation_pct,
                                  rc.created_at,rc.canary_started_at,rc.canary_last_scanned_at,
                                  rc.last_evaluated_at,
                                  cd.decision_state,cd.review_eligible,
                                  COUNT(o.*) AS observations,
                                  COUNT(o.*) FILTER(WHERE o.changed) AS changed
                           FROM market_os_release_candidates rc
                           LEFT JOIN market_os_canary_decisions cd
                             ON cd.release_candidate_id=rc.release_candidate_id
                           LEFT JOIN market_os_canary_observations o
                             ON o.release_candidate_id=rc.release_candidate_id
                           GROUP BY rc.release_candidate_id,cd.decision_state,cd.review_eligible
                           ORDER BY rc.created_at DESC""")
            rows=cur.fetchall()
            if not rows:
                print('release candidate 없음')
            for r in rows:
                print(f"{r['status']} {r['release_candidate_id']} "
                      f"version={r['release_version_label']} ruleset={r['source_ruleset_id']} "
                      f"canary={r['canary_allocation_pct']}% "
                      f"decision={r['decision_state'] or '—'} eligible={r['review_eligible'] or False} "
                      f"obs={r['observations']} changed={r['changed']} "
                      f"started={r['canary_started_at']} scanned={r['canary_last_scanned_at']} "
                      f"last_eval={r['last_evaluated_at']}")
        if exists('market_os_canary_summary'):
            print('\n[CANARY CONTROL vs CANDIDATE]')
            cur.execute("""SELECT release_candidate_id,horizon,cohort,evidence_state,
                                  membership_changes,control_samples,candidate_samples,
                                  control_avg_return_pct,candidate_avg_return_pct,
                                  delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct
                           FROM market_os_canary_summary
                           ORDER BY release_candidate_id,
                                    CASE horizon WHEN '30m' THEN 1 WHEN 'close' THEN 2
                                    WHEN 'D+1' THEN 3 ELSE 4 END,cohort""")
            rows=cur.fetchall()
            if not rows:
                print('canary outcomes 대기')
            for r in rows[:80]:
                print(f"{r['release_candidate_id']} {r['horizon']} {r['cohort']} "
                      f"{r['evidence_state']} changes={r['membership_changes']} "
                      f"controlN={r['control_samples']} candidateN={r['candidate_samples']} "
                      f"dAvg={r['delta_avg_return_pct']} "
                      f"dPos={r['delta_positive_rate_pp']} dMAE={r['delta_mae_pct']}")
        if exists('market_os_canary_decisions'):
            print('\n[CANARY SAFETY GATE]')
            cur.execute("""SELECT release_candidate_id,decision_state,review_eligible,
                                  primary_cohort,reason_codes,evidence,updated_at
                           FROM market_os_canary_decisions
                           ORDER BY CASE decision_state
                               WHEN 'CANARY_PROMOTION_CANDIDATE' THEN 1
                               WHEN 'CANARY_HEALTHY' THEN 2
                               WHEN 'CANARY_COLLECTING' THEN 3
                               WHEN 'CANARY_ROLLBACK_REQUIRED' THEN 4 ELSE 5 END,
                               updated_at DESC""")
            for r in cur.fetchall():
                ev=r['evidence'] or {}
                print(f"{r['decision_state']} eligible={r['review_eligible']} "
                      f"{r['release_candidate_id']} cohort={r['primary_cohort'] or '—'} "
                      f"30m={ev.get('overall_30m','—')} close={ev.get('overall_close','—')} "
                      f"D+1={ev.get('overall_d1','—')} recent30={ev.get('recent_30m','—')} "
                      f"recentClose={ev.get('recent_close','—')} "
                      f"reasons={','.join(r['reason_codes'] or [])}")
        if exists('market_os_canary_observations'):
            print('\n[RECENT CANARY PREVIEW]')
            cur.execute("""SELECT o.assessment_time,o.stock_code,a.stock_name,
                                  o.release_candidate_id,o.assignment_bucket,o.allocation_pct,
                                  o.control_tier,o.candidate_tier,o.changed
                           FROM market_os_canary_observations o
                           LEFT JOIN market_os_assessment_snapshots a
                             ON a.snapshot_time=o.assessment_time
                            AND a.stock_code=o.stock_code
                            AND a.rule_version=o.control_rule_version
                           ORDER BY o.assessment_time DESC,o.stock_code LIMIT 20""")
            for r in cur.fetchall():
                print(f"{r['assessment_time']} {r['stock_code']} {r['stock_name'] or ''} "
                      f"{r['release_candidate_id']} {r['control_tier']}->{r['candidate_tier']} "
                      f"changed={r['changed']} bucket={r['assignment_bucket']} "
                      f"allocation={r['allocation_pct']}%")
        if exists('market_os_release_events'):
            print('\n[RELEASE / CANARY EVENTS]')
            cur.execute("""SELECT event_time,release_candidate_id,event_type,
                                  from_status,to_status
                           FROM market_os_release_events
                           ORDER BY event_time DESC LIMIT 20""")
            for r in cur.fetchall():
                print(f"{r['event_time']} {r['release_candidate_id']} {r['event_type']} "
                      f"{r['from_status'] or '—'}->{r['to_status']}")

        print('\n[FULL RELEASE REVIEW GATE v2.1]')
        if not exists('market_os_full_release_gates'):
            print('full release gate tables missing')
        else:
            cur.execute("""SELECT g.release_candidate_id,g.gate_state,g.review_eligible,
                                  g.reason_codes,g.evidence,g.updated_at,
                                  rc.release_version_label,rc.status
                           FROM market_os_full_release_gates g
                           LEFT JOIN market_os_release_candidates rc
                             ON rc.release_candidate_id=g.release_candidate_id
                           ORDER BY CASE g.gate_state
                               WHEN 'FULL_RELEASE_REVIEW_READY' THEN 1 ELSE 2 END,
                               g.updated_at DESC""")
            rows=cur.fetchall()
            if not rows:
                print('full release gate 없음')
            for r in rows:
                ev=r['evidence'] or {};al=ev.get('effect_alignment') or {}
                bias=ev.get('sample_bias') or {};rb=(ev.get('rollback') or {}).get('rollback_target') or {}
                r30=(al.get('30m') or {}).get('avg_effect_ratio')
                rcl=(al.get('close') or {}).get('avg_effect_ratio')
                print(f"{r['gate_state']} eligible={r['review_eligible']} "
                      f"{r['release_candidate_id']} version={r['release_version_label'] or '—'} "
                      f"releaseStatus={r['status'] or '—'} "
                      f"effect30={r30 if r30 is not None else '—'} "
                      f"effectClose={rcl if rcl is not None else '—'} "
                      f"allocation={bias.get('actual_pct','—')}/{bias.get('expected_pct','—')}% "
                      f"stanceTVD={bias.get('stance_tvd','—')} tierTVD={bias.get('tier_tvd','—')} "
                      f"rollback={rb.get('target_id','—')} "
                      f"reasons={','.join(r['reason_codes'] or [])}")
        if exists('market_os_full_release_reviews'):
            print('\n[FULL RELEASE REVIEWS]')
            cur.execute("""SELECT fr.review_id,fr.release_candidate_id,fr.revision,
                                  fr.gate_state,fr.review_state,fr.created_at,fr.reviewed_at,
                                  fr.content_hash,g.gate_state AS current_gate,
                                  g.review_eligible AS current_eligible
                           FROM market_os_full_release_reviews fr
                           LEFT JOIN market_os_full_release_gates g
                             ON g.release_candidate_id=fr.release_candidate_id
                           ORDER BY CASE fr.review_state
                               WHEN 'PENDING' THEN 1 WHEN 'RELEASE_READY' THEN 2
                               WHEN 'REJECTED' THEN 3 WHEN 'STALE_CANARY' THEN 4 ELSE 5 END,
                               fr.created_at DESC""")
            rows=cur.fetchall()
            if not rows:
                print('full release review 없음')
            for r in rows[:30]:
                print(f"{r['review_state']} {r['review_id']} rev={r['revision']} "
                      f"release={r['release_candidate_id']} frozen={r['gate_state']} "
                      f"current={r['current_gate'] or '—'} eligible={r['current_eligible'] or False} "
                      f"created={r['created_at']} reviewed={r['reviewed_at']} "
                      f"hash={r['content_hash'][:12]}")
        if exists('market_os_full_release_review_events'):
            print('\n[FULL RELEASE REVIEW EVENTS]')
            cur.execute("""SELECT event_time,review_id,event_type,
                                  from_review_state,to_review_state,note
                           FROM market_os_full_release_review_events
                           ORDER BY event_time DESC LIMIT 20""")
            for r in cur.fetchall():
                print(f"{r['event_time']} {r['review_id']} {r['event_type']} "
                      f"{r['from_review_state'] or '—'}->{r['to_review_state']} "
                      f"{r['note'] or ''}")

        print('\n[REVERSIBLE CONTROL SWITCH v2.2]')
        if not exists('market_os_control_state'):
            print('control state table missing')
        else:
            cur.execute("""SELECT control_id,mode,active_version_label,base_rule_version,
                                  ruleset_id,source_review_id,switch_transaction_id,
                                  control_hash,activated_at,updated_at
                           FROM market_os_control_state WHERE id=1""")
            r=cur.fetchone()
            if r:
                print(f"CONTROL {r['control_id']} mode={r['mode']} "
                      f"version={r['active_version_label']} base={r['base_rule_version']} "
                      f"ruleset={r['ruleset_id'] or '—'} review={r['source_review_id'] or '—'} "
                      f"switch={r['switch_transaction_id'] or '—'} "
                      f"hash={r['control_hash'][:12]} activated={r['activated_at']} updated={r['updated_at']}")
        if exists('market_os_switch_transactions'):
            print('\n[SWITCH TRANSACTIONS]')
            cur.execute("""SELECT switch_transaction_id,source_review_id,release_candidate_id,
                                  ruleset_id,state,expected_control_hash,candidate_hash,
                                  pre_switch_watch_count,prepared_at,committed_at,health_deadline,
                                  completed_at,rollback_at,rollback_reason,note
                           FROM market_os_switch_transactions
                           ORDER BY prepared_at DESC LIMIT 20""")
            rows=cur.fetchall()
            if not rows:
                print('switch transaction 없음')
            for r in rows:
                print(f"{r['state']} {r['switch_transaction_id']} review={r['source_review_id']} "
                      f"ruleset={r['ruleset_id']} preWatch={r['pre_switch_watch_count']} "
                      f"prepared={r['prepared_at']} committed={r['committed_at']} "
                      f"health={r['health_deadline']} completed={r['completed_at']} "
                      f"rollback={r['rollback_at']} reason={r['rollback_reason'] or '—'}")
        if exists('market_os_switch_events'):
            print('\n[SWITCH EVENTS]')
            cur.execute("""SELECT event_time,switch_transaction_id,event_type,
                                  from_state,to_state,evidence
                           FROM market_os_switch_events
                           ORDER BY event_time DESC LIMIT 20""")
            for r in cur.fetchall():
                print(f"{r['event_time']} {r['switch_transaction_id']} {r['event_type']} "
                      f"{r['from_state'] or '—'}->{r['to_state']} evidence={r['evidence'] or {}}")

        print('\n[EXECUTION FIREWALL v2.3]')
        if not exists('market_os_execution_intents'):
            print('execution firewall tables missing')
        else:
            cur.execute("""SELECT status,COUNT(*) AS n
                           FROM market_os_execution_intents
                           GROUP BY status ORDER BY status""")
            rows=cur.fetchall()
            if not rows:
                print('execution intent 없음')
            for r in rows:
                print(f"{r['status']}: {r['n']}")
            cur.execute("""SELECT intent_id,status,stock_code,stock_name,snapshot_time,expires_at,
                                  active_version_label,switch_transaction_id,reference_price_krw,
                                  watch_tier,base_watch_tier,trigger_state,market_stance,
                                  catalyst_grade,reviewed_at,review_note
                           FROM market_os_execution_intents
                           ORDER BY CASE status WHEN 'REVIEW_PENDING' THEN 1
                                    WHEN 'HUMAN_APPROVED_INTENT' THEN 2 ELSE 3 END,
                                    created_at DESC LIMIT 30""")
            for r in cur.fetchall():
                print(f"{r['status']} {r['intent_id']} {r['stock_code']} {r['stock_name'] or ''} "
                      f"{r['base_watch_tier'] or '—'}->{r['watch_tier']} "
                      f"trigger={r['trigger_state']} stance={r['market_stance']} "
                      f"catalyst={r['catalyst_grade']} ref={r['reference_price_krw']} "
                      f"expires={r['expires_at']} switch={r['switch_transaction_id']} "
                      f"reviewed={r['reviewed_at']} note={r['review_note'] or '—'}")
        if exists('market_os_execution_firewall_runs'):
            print('\n[EXECUTION FIREWALL RUNS]')
            cur.execute("""SELECT run_time,enabled,control_id,switch_transaction_id,switch_state,
                                  assessed,review_eligible,created_intents,blocked,block_reasons,note
                           FROM market_os_execution_firewall_runs
                           ORDER BY run_time DESC LIMIT 12""")
            for r in cur.fetchall():
                print(f"{r['run_time']} enabled={r['enabled']} control={r['control_id'] or '—'} "
                      f"switch={r['switch_transaction_id'] or '—'} state={r['switch_state'] or '—'} "
                      f"assessed={r['assessed']} eligible={r['review_eligible']} "
                      f"created={r['created_intents']} blocked={r['blocked']} "
                      f"reasons={r['block_reasons'] or {}}")
        if exists('market_os_execution_intent_events'):
            print('\n[EXECUTION INTENT EVENTS]')
            cur.execute("""SELECT event_time,intent_id,event_type,from_status,to_status,
                                  reason_codes
                           FROM market_os_execution_intent_events
                           ORDER BY event_time DESC LIMIT 20""")
            for r in cur.fetchall():
                print(f"{r['event_time']} {r['intent_id']} {r['event_type']} "
                      f"{r['from_status'] or '—'}->{r['to_status']} "
                      f"reasons={','.join(r['reason_codes'] or [])}")

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
print('Shadow Decision Gate v1.6: 30m+close, time-split stability, membership changes and stance reproduction are required before ACCEPT_CANDIDATE; no automatic live adoption.')
print('Adoption Review Dossier v1.7: one immutable dossier revision is generated per ACCEPT_CANDIDATE transition; human review can only approve a future dry-run or reject it.')
print('Versioned Ruleset v1.8: APPROVED_DRY_RUN still requires explicit dry-run-start; activation creates a new prospective boundary and source Decision invalidation => STALE_SOURCE.')
print('Ruleset Succession Gate v1.9: 30m+close, time splits, stance replication, impact concentration, frozen Shadow-effect retention and D+1 degradation are required before SUCCESSION_CANDIDATE; no live promotion.')
print('Release Candidate / Canary v2.0: SUCCESSION_CANDIDATE requires human release-create and canary-start; deterministic <=20% stock-day preview never replaces primary CONTROL tier, and comparable harm auto-stops as CANARY_ROLLBACK_REQUIRED.')
print('Full Release Review v2.1: CANARY_PROMOTION_CANDIDATE is rechecked against full Dry Run effect alignment, Canary sample bias and CONTROL rollback identity; RELEASE_READY is human metadata only and no live switch exists.')
print('Reversible CONTROL Switch v2.2: prepare never changes CONTROL; commit requires MARKET_OS_LIVE_SWITCH_ENABLED=1, expected CONTROL hash match and fresh RELEASE_READY evidence; hard health failures restore the previous CONTROL atomically. Orders/positions remain separate.')
print('Execution Firewall v2.3: only a HEALTHY RULESET CONTROL can create short-lived human review intents; engine is default OFF, approvals never create broker orders, quantities, limit prices or positions.')
print('Notice: raw snapshots remain stored; segment N is episode-anchor N, not repeated screen snapshots. No threshold or live score was changed.')
PY
