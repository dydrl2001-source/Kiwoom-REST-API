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
from market_os_store import _quality,_segment_depth,_enrich_edges

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
                                samples DESC,segment_type,segment_value
                       LIMIT 80""")
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
        interactions=_enrich_edges(segments)
        print('\n[SEGMENTS N>=5]')
        if not rows:
            print('표본 5개 이상 구간 없음')
        for r in rows:
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
                  f"parent={b.get('segment_type','—')}:{b.get('segment_value','—')}")
            shown+=1
            if shown>=40:break
        if not shown:
            print('상호작용 표본 5개 이상 없음')

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

        cur.execute("""SELECT segment_type,segment_value,horizon,samples,distinct_stocks,distinct_days,
                              avg_return_pct,positive_rate,avg_mfe_pct,avg_mae_pct
                       FROM market_os_learning_segments
                       WHERE samples>=20 AND distinct_stocks>=5 AND distinct_days>=2
                         AND horizon IN('30m','close')
                       ORDER BY avg_return_pct DESC NULLS LAST LIMIT 8""")
        strong=cur.fetchall()
        cur.execute("""SELECT segment_type,segment_value,horizon,samples,distinct_stocks,distinct_days,
                              avg_return_pct,positive_rate,avg_mfe_pct,avg_mae_pct
                       FROM market_os_learning_segments
                       WHERE samples>=20 AND distinct_stocks>=5 AND distinct_days>=2
                         AND horizon IN('30m','close')
                       ORDER BY avg_return_pct ASC NULLS LAST LIMIT 8""")
        weak=cur.fetchall()
        print('\n[REVIEW CANDIDATES N>=20]')
        if not strong and not weak:
            print('아직 30m/close 표본 20개 이상 조건 없음')
        else:
            for label,rows in [('STRONG',strong),('WEAK',weak)]:
                for r in rows:
                    print(f"{label} {r['horizon']} {r['segment_type']}={r['segment_value']} "
                          f"N={r['samples']} stocks={r['distinct_stocks']} days={r['distinct_days']} "
                          f"avg={r['avg_return_pct']:.3f}% positive={(r['positive_rate'] or 0)*100:.1f}%")

print('\nSampling: 5m=non-overlap 5m, 30m=non-overlap 30m, close/D+1=one per stock-day.')
print('Interaction policy: only pre-registered regime/setup/trigger/micro combinations are tested; no arbitrary combination search.')
print('Notice: raw snapshots remain stored; segment N is episode-anchor N, not repeated screen snapshots. No threshold or live score was changed.')
PY
