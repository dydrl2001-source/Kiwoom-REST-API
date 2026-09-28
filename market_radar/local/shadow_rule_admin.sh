#!/bin/bash
# Manual Shadow Rule administration. This never changes live Market OS scoring or places orders.
set -eu
cd "$(dirname "$0")"

cmd="${1:-list}"
id="${2:-}"
arg="${3:-}"
confirm="${4:-}"

usage() {
  echo "Usage:"
  echo "  bash shadow_rule_admin.sh list"
  echo "  bash shadow_rule_admin.sh dossier <dossier_id>"
  echo "  bash shadow_rule_admin.sh approve <candidate_key> --confirm"
  echo "  bash shadow_rule_admin.sh disable <shadow_rule_id> --confirm"
  echo "  bash shadow_rule_admin.sh review <dossier_id> <approve-dry-run|reject> --confirm"
}

case "$cmd" in
  list)
    ;;
  dossier)
    if [ -z "$id" ]; then usage; exit 1; fi
    ;;
  approve|disable)
    if [ -z "$id" ] || [ "$arg" != "--confirm" ]; then usage; exit 1; fi
    ;;
  review)
    if [ -z "$id" ] || { [ "$arg" != "approve-dry-run" ] && [ "$arg" != "reject" ]; } || [ "$confirm" != "--confirm" ]; then
      usage; exit 1
    fi
    ;;
  *)
    echo "Unknown command: $cmd"
    usage
    exit 1
    ;;
esac

docker compose exec -T radar-api python - "$cmd" "$id" "$arg" <<'PY'
import json,os,sys
import psycopg
from psycopg.rows import dict_row

cmd=sys.argv[1];ident=sys.argv[2] if len(sys.argv)>2 else ""
arg=sys.argv[3] if len(sys.argv)>3 else ""
db=os.environ["DATABASE_URL"]

with psycopg.connect(db,row_factory=dict_row,connect_timeout=5) as c,c.cursor() as cur:
    def exists(name):
        cur.execute("SELECT to_regclass(%s) AS name",("public."+name,))
        return cur.fetchone()["name"] is not None

    required=["market_os_promotion_registry","market_os_promotion_events",
              "market_os_shadow_rules","market_os_shadow_observations",
              "market_os_shadow_decisions","market_os_adoption_dossiers",
              "market_os_adoption_dossier_events"]
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
        print("\n=== ADOPTION DOSSIERS ===")
        cur.execute("""SELECT dossier_id,shadow_rule_id,revision,decision_state,review_state,
                              generated_at,reviewed_at,content_hash
                       FROM market_os_adoption_dossiers
                       ORDER BY CASE review_state WHEN 'PENDING' THEN 1
                                WHEN 'APPROVED_DRY_RUN' THEN 2 WHEN 'REJECTED' THEN 3
                                ELSE 4 END,generated_at DESC""")
        dossiers=cur.fetchall()
        if not dossiers:print("none")
        for d in dossiers:
            print(f"{d['dossier_id']} | rev={d['revision']} | {d['review_state']} | "
                  f"decision={d['decision_state']} | rule={d['shadow_rule_id']} | "
                  f"generated={d['generated_at']} reviewed={d['reviewed_at']} "
                  f"hash={d['content_hash'][:12]}")

        print("\nRead-only list. No live scores, thresholds, rulesets or orders were changed.")
        raise SystemExit(0)

    if cmd=="dossier":
        cur.execute("""SELECT dossier_id,shadow_rule_id,revision,content_hash,decision_state,
                              review_state,generated_at,reviewed_at,reviewed_by,review_note,dossier
                       FROM market_os_adoption_dossiers
                       WHERE dossier_id=%s""",(ident,))
        d=cur.fetchone()
        if not d:
            raise SystemExit("dossier_id not found")
        print("DOSSIER:",d["dossier_id"])
        print("Rule:",d["shadow_rule_id"],"revision:",d["revision"])
        print("Decision:",d["decision_state"],"review:",d["review_state"])
        print("Hash:",d["content_hash"])
        print("Generated:",d["generated_at"],"Reviewed:",d["reviewed_at"],"By:",d["reviewed_by"])
        print(json.dumps(d["dossier"],ensure_ascii=False,indent=2,default=str))
        print("\nRead-only dossier view. No live scores, rulesets or orders were changed.")
        raise SystemExit(0)

    if cmd=="review":
        cur.execute("""SELECT * FROM market_os_adoption_dossiers
                       WHERE dossier_id=%s FOR UPDATE""",(ident,))
        d=cur.fetchone()
        if not d:
            raise SystemExit("dossier_id not found")
        if d["review_state"]!="PENDING":
            raise SystemExit("Only PENDING dossier revisions can be reviewed. Current="+str(d["review_state"]))
        cur.execute("""SELECT decision_state,review_eligible
                       FROM market_os_shadow_decisions
                       WHERE shadow_rule_id=%s FOR UPDATE""",(d["shadow_rule_id"],))
        sd=cur.fetchone()
        if not sd:
            raise SystemExit("shadow decision missing")
        if arg=="approve-dry-run":
            if sd["decision_state"]!="ACCEPT_CANDIDATE" or not sd["review_eligible"]:
                raise SystemExit("Dry-run approval requires current ACCEPT_CANDIDATE + review_eligible=true.")
            target="APPROVED_DRY_RUN"
            manual="APPROVED_DRY_RUN"
            event="HUMAN_APPROVED_DRY_RUN"
            note="Human approved dossier for a future versioned dry-run only; no live ruleset was created."
        else:
            target="REJECTED"
            manual="REJECTED"
            event="HUMAN_REJECTED_DOSSIER"
            note="Human rejected this dossier revision; existing shadow observations remain preserved."
        cur.execute("""UPDATE market_os_adoption_dossiers
                       SET review_state=%s,reviewed_at=now(),reviewed_by='MANUAL_SCRIPT',
                           review_note=%s
                       WHERE dossier_id=%s""",(target,note,ident))
        cur.execute("""UPDATE market_os_shadow_decisions
                       SET manual_decision_state=%s
                       WHERE shadow_rule_id=%s""",(manual,d["shadow_rule_id"]))
        cur.execute("""INSERT INTO market_os_adoption_dossier_events(
                dossier_id,event_type,from_review_state,to_review_state,note,evidence)
            VALUES(%s,%s,'PENDING',%s,%s,%s::jsonb)""",
            (ident,event,target,note,json.dumps({
                "shadow_rule_id":d["shadow_rule_id"],
                "revision":d["revision"],
                "content_hash":d["content_hash"],
                "live_activation":False,
                "versioned_ruleset_created":False,
            },ensure_ascii=False)))
        print(target+":",ident)
        print(note)
        print("Live Market OS scores/tiers/rulesets/orders were NOT changed.")
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
