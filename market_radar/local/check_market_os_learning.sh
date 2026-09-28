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
        cur.execute("""SELECT segment_type,segment_value,horizon,samples,
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
        print('\n[SEGMENTS N>=5]')
        if not rows:
            print('표본 5개 이상 구간 없음')
        for r in rows:
            print(f"{r['horizon']} | {r['segment_type']}={r['segment_value']} | N={r['samples']} "
                  f"avg={r['avg_return']}% med={r['median_return']}% pos={r['positive_pct']}% "
                  f"MFE={r['avg_mfe']}% MAE={r['avg_mae']}%")

        cur.execute("""SELECT segment_type,segment_value,horizon,samples,avg_return_pct,positive_rate,avg_mfe_pct,avg_mae_pct
                       FROM market_os_learning_segments
                       WHERE samples>=20 AND horizon IN('30m','close')
                       ORDER BY avg_return_pct DESC NULLS LAST LIMIT 8""")
        strong=cur.fetchall()
        cur.execute("""SELECT segment_type,segment_value,horizon,samples,avg_return_pct,positive_rate,avg_mfe_pct,avg_mae_pct
                       FROM market_os_learning_segments
                       WHERE samples>=20 AND horizon IN('30m','close')
                       ORDER BY avg_return_pct ASC NULLS LAST LIMIT 8""")
        weak=cur.fetchall()
        print('\n[REVIEW CANDIDATES N>=20]')
        if not strong and not weak:
            print('아직 30m/close 표본 20개 이상 조건 없음')
        else:
            for label,rows in [('STRONG',strong),('WEAK',weak)]:
                for r in rows:
                    print(f"{label} {r['horizon']} {r['segment_type']}={r['segment_value']} "
                          f"N={r['samples']} avg={r['avg_return_pct']:.3f}% "
                          f"positive={(r['positive_rate'] or 0)*100:.1f}%")

print('\nNotice: early samples are descriptive only. No threshold or live score was changed.')
PY
