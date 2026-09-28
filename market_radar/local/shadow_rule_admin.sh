#!/bin/bash
# Manual Shadow Rule administration. This never changes live Market OS scoring or places orders.
set -eu
cd "$(dirname "$0")"

cmd="${1:-list}"
id="${2:-}"
confirm="${3:-}"

case "$cmd" in
  list)
    ;;
  approve|disable)
    if [ -z "$id" ] || [ "$confirm" != "--confirm" ]; then
      echo "Usage:"
      echo "  bash shadow_rule_admin.sh list"
      echo "  bash shadow_rule_admin.sh approve <candidate_key> --confirm"
      echo "  bash shadow_rule_admin.sh disable <shadow_rule_id> --confirm"
      exit 1
    fi
    ;;
  *)
    echo "Unknown command: $cmd"
    exit 1
    ;;
esac

docker compose exec -T radar-api python - "$cmd" "$id" <<'PY'
import json,os,sys
import psycopg
from psycopg.rows import dict_row

cmd=sys.argv[1];ident=sys.argv[2] if len(sys.argv)>2 else ""
db=os.environ["DATABASE_URL"]

with psycopg.connect(db,row_factory=dict_row,connect_timeout=5) as c,c.cursor() as cur:
    def exists(name):
        cur.execute("SELECT to_regclass(%s) AS name",("public."+name,))
        return cur.fetchone()["name"] is not None

    required=["market_os_promotion_registry","market_os_promotion_events",
              "market_os_shadow_rules","market_os_shadow_observations",
              "market_os_shadow_decisions"]
    missing=[x for x in required if not exists(x)]
    if missing:
        raise SystemExit("Shadow Lab schema missing: "+", ".join(missing)+". Deploy/restart market-os-learning first.")

    if cmd=="list":
        print("=== PROMOTION CANDIDATES ===")
        cur.execute("""SELECT candidate_key,current_stage,direction,review_action,segment_type,
                              segment_value,horizon,samples,distinct_stocks,distinct_days,
                              quality,walk_forward_status,manual_review_state
                       FROM market_os_promotion_registry
                       WHERE active=TRUE AND current_stage='PROMOTION_CANDIDATE'
                       ORDER BY samples DESC,segment_type,segment_value""")
        rows=cur.fetchall()
        if not rows:print("none")
        for r in rows:
            print(f"{r['candidate_key']} | {r['review_action']} | {r['horizon']} | "
                  f"{r['segment_type']}={r['segment_value']} | N={r['samples']} "
                  f"stocks={r['distinct_stocks']} days={r['distinct_days']} "
                  f"q={r['quality']} wf={r['walk_forward_status']} manual={r['manual_review_state']}")
        print("\n=== SHADOW RULES ===")
        cur.execute("""SELECT r.shadow_rule_id,r.candidate_key,r.action,r.enabled,r.approved_at,
                              r.approved_by,r.segment_type,r.segment_value,r.source_horizon,
                              r.last_evaluated_at,d.decision_state,d.review_eligible,
                              d.manual_decision_state
                       FROM market_os_shadow_rules r
                       LEFT JOIN market_os_shadow_decisions d
                         ON d.shadow_rule_id=r.shadow_rule_id
                       ORDER BY r.approved_at DESC""")
        rules=cur.fetchall()
        if not rules:print("none")
        for r in rules:
            print(f"{r['shadow_rule_id']} | {'ON' if r['enabled'] else 'OFF'} | {r['action']} | "
                  f"{r['source_horizon']} | {r['segment_type']}={r['segment_value']} | "
                  f"decision={r['decision_state'] or '—'} eligible={r['review_eligible'] or False} "
                  f"manual={r['manual_decision_state'] or 'PENDING'} | "
                  f"approved={r['approved_at']} last_eval={r['last_evaluated_at']}")
        print("\nRead-only list. No live scores, thresholds or orders were changed.")
        raise SystemExit(0)

    if cmd=="approve":
        cur.execute("""SELECT * FROM market_os_promotion_registry
                       WHERE candidate_key=%s FOR UPDATE""",(ident,))
        r=cur.fetchone()
        if not r:
            raise SystemExit("candidate_key not found")
        if r["current_stage"]!="PROMOTION_CANDIDATE":
            raise SystemExit("Only PROMOTION_CANDIDATE can be manually approved for Shadow Rule Lab.")
        if r["manual_review_state"] not in ("PENDING","REVIEW"):
            raise SystemExit("Candidate manual_review_state is not approvable: "+str(r["manual_review_state"]))
        if r["review_action"]=="PROMOTE":
            action="PROMOTE_ONE_TIER"
        elif r["review_action"]=="SUPPRESS":
            action="SUPPRESS_ONE_TIER"
        else:
            raise SystemExit("Candidate has no PROMOTE/SUPPRESS review_action.")

        shadow_rule_id="sr-"+r["candidate_key"]
        cur.execute("SELECT 1 FROM market_os_shadow_rules WHERE candidate_key=%s",(r["candidate_key"],))
        if cur.fetchone():
            raise SystemExit("A Shadow Rule already exists for this candidate. Re-approval is blocked to preserve the original prospective boundary.")
        spec={
            "engine":"tier-shift-v1",
            "prospective_only":True,
            "action":action,
            "blocked_override":False,
            "source":{
                "candidate_key":r["candidate_key"],
                "rule_version":r["rule_version"],
                "stage":"PROMOTION_CANDIDATE",
                "quality":r["quality"],
                "walk_forward_status":r["walk_forward_status"],
                "samples":r["samples"],
                "distinct_stocks":r["distinct_stocks"],
                "distinct_days":r["distinct_days"],
            }
        }
        cur.execute("""INSERT INTO market_os_shadow_rules(
                shadow_rule_id,candidate_key,rule_version,segment_type,segment_value,
                source_horizon,action,enabled,approved_at,approved_by,spec)
            VALUES(%s,%s,%s,%s,%s,%s,%s,TRUE,now(),'MANUAL_SCRIPT',%s::jsonb)""",
            (shadow_rule_id,r["candidate_key"],r["rule_version"],r["segment_type"],
             r["segment_value"],r["horizon"],action,json.dumps(spec,ensure_ascii=False)))
        cur.execute("""UPDATE market_os_promotion_registry
                       SET current_stage='SHADOW_RULE',manual_review_state='APPROVED',
                           shadow_rule_id=%s,stage_since=now(),last_transition_at=now()
                       WHERE candidate_key=%s""",(shadow_rule_id,r["candidate_key"]))
        event_evidence={"shadow_rule_id":shadow_rule_id,"action":action,"prospective_only":True}
        cur.execute("""INSERT INTO market_os_promotion_events(
                candidate_key,event_type,from_stage,to_stage,direction,review_action,
                reason_codes,evidence)
            VALUES(%s,'MANUAL_SHADOW_RULE_APPROVED','PROMOTION_CANDIDATE','SHADOW_RULE',
                   %s,%s,%s::jsonb,%s::jsonb)""",
            (r["candidate_key"],r["direction"],r["review_action"],
             json.dumps(["MANUAL_APPROVAL","PROSPECTIVE_ONLY"],ensure_ascii=False),
             json.dumps(event_evidence,ensure_ascii=False)))
        print("APPROVED:",shadow_rule_id)
        print("Action:",action)
        print("Prospective boundary: approved_at=now(); pre-approval assessments will not enter A/B.")
        print("Live Market OS scores/tiers/orders were NOT changed.")
        raise SystemExit(0)

    if cmd=="disable":
        cur.execute("""SELECT * FROM market_os_shadow_rules
                       WHERE shadow_rule_id=%s FOR UPDATE""",(ident,))
        r=cur.fetchone()
        if not r:
            raise SystemExit("shadow_rule_id not found")
        cur.execute("""UPDATE market_os_shadow_rules
                       SET enabled=FALSE,disabled_at=now()
                       WHERE shadow_rule_id=%s""",(ident,))
        cur.execute("""UPDATE market_os_promotion_registry
                       SET manual_review_state='DISABLED'
                       WHERE candidate_key=%s""",(r["candidate_key"],))
        cur.execute("""INSERT INTO market_os_promotion_events(
                candidate_key,event_type,from_stage,to_stage,direction,review_action,
                reason_codes,evidence)
            SELECT candidate_key,'MANUAL_SHADOW_RULE_DISABLED','SHADOW_RULE','SHADOW_RULE',
                   direction,review_action,%s::jsonb,%s::jsonb
            FROM market_os_promotion_registry WHERE candidate_key=%s""",
            (json.dumps(["MANUAL_DISABLE"],ensure_ascii=False),
             json.dumps({"shadow_rule_id":ident},ensure_ascii=False),r["candidate_key"]))
        print("DISABLED:",ident)
        print("Existing observations/results are preserved. No new shadow observations will be added.")
        print("Live Market OS scores/tiers/orders were NOT changed.")
PY
