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
  echo "  bash shadow_rule_admin.sh ruleset <ruleset_id>"
  echo "  bash shadow_rule_admin.sh release <release_candidate_id>"
  echo "  bash shadow_rule_admin.sh approve <candidate_key> --confirm"
  echo "  bash shadow_rule_admin.sh disable <shadow_rule_id> --confirm"
  echo "  bash shadow_rule_admin.sh review <dossier_id> <approve-dry-run|reject> --confirm"
  echo "  bash shadow_rule_admin.sh dry-run-start <dossier_id> --confirm"
  echo "  bash shadow_rule_admin.sh dry-run-stop <ruleset_id> --confirm"
  echo "  bash shadow_rule_admin.sh release-create <ruleset_id> --confirm"
  echo "  bash shadow_rule_admin.sh canary-start <release_candidate_id> --confirm"
  echo "  bash shadow_rule_admin.sh canary-stop <release_candidate_id> --confirm"
}

case "$cmd" in
  list)
    ;;
  dossier|ruleset|release)
    if [ -z "$id" ]; then usage; exit 1; fi
    ;;
  approve|disable|dry-run-start|dry-run-stop|release-create|canary-start|canary-stop)
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
from market_os_ruleset import build_spec as build_versioned_ruleset
from market_os_release import build_release_candidate

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
              "market_os_adoption_dossier_events","market_os_versioned_rulesets",
              "market_os_ruleset_dry_run_observations","market_os_ruleset_dry_run_summary",
              "market_os_ruleset_events","market_os_ruleset_succession_decisions",
              "market_os_ruleset_succession_events","market_os_release_candidates",
              "market_os_release_events","market_os_canary_observations",
              "market_os_canary_summary","market_os_canary_decisions",
              "market_os_canary_decision_events"]
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

        print("\n=== VERSIONED RULESET DRY RUNS ===")
        cur.execute("""SELECT vr.ruleset_id,vr.version_label,vr.base_rule_version,
                              vr.source_dossier_id,vr.source_shadow_rule_id,vr.status,
                              vr.activated_at,vr.stopped_at,vr.stale_at,vr.last_evaluated_at,
                              sd.decision_state AS succession_state,
                              sd.review_eligible AS succession_eligible,
                              COUNT(o.*) AS observations,
                              COUNT(o.*) FILTER(WHERE o.changed) AS changed
                       FROM market_os_versioned_rulesets vr
                       LEFT JOIN market_os_ruleset_dry_run_observations o
                         ON o.ruleset_id=vr.ruleset_id
                       LEFT JOIN market_os_ruleset_succession_decisions sd
                         ON sd.ruleset_id=vr.ruleset_id
                       GROUP BY vr.ruleset_id,sd.decision_state,sd.review_eligible
                       ORDER BY vr.activated_at DESC""")
        rulesets=cur.fetchall()
        if not rulesets:print("none")
        for r in rulesets:
            print(f"{r['ruleset_id']} | {r['status']} | {r['version_label']} | "
                  f"base={r['base_rule_version']} dossier={r['source_dossier_id']} "
                  f"succession={r['succession_state'] or '—'} eligible={r['succession_eligible'] or False} "
                  f"obs={r['observations']} changed={r['changed']} "
                  f"activated={r['activated_at']} last_eval={r['last_evaluated_at']}")

        print("\n=== RELEASE CANDIDATES / CANARY ===")
        cur.execute("""SELECT rc.release_candidate_id,rc.release_version_label,
                              rc.source_ruleset_id,rc.status,rc.canary_allocation_pct,
                              rc.created_at,rc.canary_started_at,rc.stopped_at,rc.stale_at,
                              rc.rollback_at,rc.last_evaluated_at,
                              cd.decision_state AS canary_state,
                              cd.review_eligible AS canary_eligible,
                              COUNT(o.*) AS observations,
                              COUNT(o.*) FILTER(WHERE o.changed) AS changed
                       FROM market_os_release_candidates rc
                       LEFT JOIN market_os_canary_decisions cd
                         ON cd.release_candidate_id=rc.release_candidate_id
                       LEFT JOIN market_os_canary_observations o
                         ON o.release_candidate_id=rc.release_candidate_id
                       GROUP BY rc.release_candidate_id,cd.decision_state,cd.review_eligible
                       ORDER BY rc.created_at DESC""")
        releases=cur.fetchall()
        if not releases:print("none")
        for r in releases:
            print(f"{r['release_candidate_id']} | {r['status']} | {r['release_version_label']} | "
                  f"ruleset={r['source_ruleset_id']} canary={r['canary_allocation_pct']}% "
                  f"decision={r['canary_state'] or '—'} eligible={r['canary_eligible'] or False} "
                  f"obs={r['observations']} changed={r['changed']} "
                  f"started={r['canary_started_at']} last_eval={r['last_evaluated_at']}")

        print("\nRead-only list. No live scores, thresholds, rulesets or orders were changed.")
        raise SystemExit(0)

    if cmd=="release":
        cur.execute("""SELECT * FROM market_os_release_candidates
                       WHERE release_candidate_id=%s""",(ident,))
        rc=cur.fetchone()
        if not rc:
            raise SystemExit("release_candidate_id not found")
        print("RELEASE CANDIDATE:",rc["release_candidate_id"])
        print("Version:",rc["release_version_label"],"Status:",rc["status"])
        print("Ruleset:",rc["source_ruleset_id"],"Canary:",str(rc["canary_allocation_pct"])+"%")
        print("Package hash:",rc["package_hash"])
        print("Created:",rc["created_at"],"Canary started:",rc["canary_started_at"])
        print(json.dumps(rc["package"],ensure_ascii=False,indent=2,default=str))
        print("\n=== CANARY DECISION ===")
        cur.execute("""SELECT decision_state,review_eligible,primary_cohort,
                              reason_codes,evidence,manual_review_state,state_since,updated_at
                       FROM market_os_canary_decisions
                       WHERE release_candidate_id=%s""",(ident,))
        cd=cur.fetchone()
        if not cd:
            print("canary evidence 대기")
        else:
            print("State:",cd["decision_state"],"Eligible:",cd["review_eligible"],
                  "Cohort:",cd["primary_cohort"],"Manual:",cd["manual_review_state"])
            print("Reasons:",",".join(cd["reason_codes"] or []))
            print(json.dumps(cd["evidence"],ensure_ascii=False,indent=2,default=str))
        print("\n=== CANARY SUMMARY ===")
        cur.execute("""SELECT * FROM market_os_canary_summary
                       WHERE release_candidate_id=%s
                       ORDER BY CASE horizon WHEN '30m' THEN 1 WHEN 'close' THEN 2
                                WHEN 'D+1' THEN 3 ELSE 4 END,cohort""",(ident,))
        rows=cur.fetchall()
        if not rows:print("prospective canary outcomes 대기")
        for x in rows:
            print(f"{x['horizon']} {x['cohort']} {x['evidence_state']} "
                  f"changes={x['membership_changes']} controlN={x['control_samples']} "
                  f"candidateN={x['candidate_samples']} "
                  f"dAvg={x['delta_avg_return_pct']} dPos={x['delta_positive_rate_pp']} "
                  f"dMAE={x['delta_mae_pct']}")
        print("\nRead-only release view. No live scores, tiers or orders were changed.")
        raise SystemExit(0)

    if cmd=="ruleset":
        cur.execute("""SELECT * FROM market_os_versioned_rulesets
                       WHERE ruleset_id=%s""",(ident,))
        rs=cur.fetchone()
        if not rs:
            raise SystemExit("ruleset_id not found")
        print("RULESET:",rs["ruleset_id"])
        print("Version:",rs["version_label"],"Status:",rs["status"])
        print("Base:",rs["base_rule_version"],"Dossier:",rs["source_dossier_id"])
        print("Activated:",rs["activated_at"],"Stopped:",rs["stopped_at"],"Stale:",rs["stale_at"])
        print("Spec hash:",rs["spec_hash"])
        print(json.dumps(rs["spec"],ensure_ascii=False,indent=2,default=str))
        print("\n=== DRY RUN SUMMARY ===")
        cur.execute("""SELECT * FROM market_os_ruleset_dry_run_summary
                       WHERE ruleset_id=%s
                       ORDER BY CASE horizon WHEN '30m' THEN 1 WHEN 'close' THEN 2
                                WHEN 'D+1' THEN 3 ELSE 4 END,cohort""",(ident,))
        rows=cur.fetchall()
        if not rows:print("prospective outcomes 대기")
        for x in rows:
            print(f"{x['horizon']} {x['cohort']} {x['evidence_state']} "
                  f"changes={x['membership_changes']} controlN={x['control_samples']} "
                  f"candidateN={x['candidate_samples']} "
                  f"dAvg={x['delta_avg_return_pct']} dPos={x['delta_positive_rate_pp']} "
                  f"dMAE={x['delta_mae_pct']}")
        print("\n=== SUCCESSION GATE ===")
        cur.execute("""SELECT decision_state,review_eligible,primary_cohort,
                              reason_codes,evidence,manual_review_state,state_since,updated_at
                       FROM market_os_ruleset_succession_decisions
                       WHERE ruleset_id=%s""",(ident,))
        sd=cur.fetchone()
        if not sd:
            print("succession evidence 대기")
        else:
            print("State:",sd["decision_state"],"Eligible:",sd["review_eligible"],
                  "Cohort:",sd["primary_cohort"],"Manual:",sd["manual_review_state"])
            print("Reasons:",",".join(sd["reason_codes"] or []))
            print(json.dumps(sd["evidence"],ensure_ascii=False,indent=2,default=str))
        print("\nRead-only ruleset view. No live scores, tiers or orders were changed.")
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

    if cmd=="dry-run-start":
        cur.execute("""SELECT * FROM market_os_adoption_dossiers
                       WHERE dossier_id=%s FOR UPDATE""",(ident,))
        d=cur.fetchone()
        if not d:
            raise SystemExit("dossier_id not found")
        if d["review_state"]!="APPROVED_DRY_RUN":
            raise SystemExit("Dry run requires APPROVED_DRY_RUN dossier. Current="+str(d["review_state"]))
        cur.execute("""SELECT d.decision_state,d.review_eligible,d.manual_decision_state,
                              r.enabled AS shadow_rule_enabled
                       FROM market_os_shadow_decisions d
                       JOIN market_os_shadow_rules r ON r.shadow_rule_id=d.shadow_rule_id
                       WHERE d.shadow_rule_id=%s FOR UPDATE""",(d["shadow_rule_id"],))
        sd=cur.fetchone()
        if not sd:
            raise SystemExit("shadow decision missing")
        if sd["decision_state"]!="ACCEPT_CANDIDATE" or not sd["review_eligible"] or not sd["shadow_rule_enabled"]:
            raise SystemExit("Dry run start requires current ACCEPT_CANDIDATE, review_eligible=true, enabled source Shadow Rule.")
        cur.execute("""SELECT 1 FROM market_os_versioned_rulesets
                       WHERE source_dossier_id=%s""",(ident,))
        if cur.fetchone():
            raise SystemExit("A versioned ruleset already exists for this dossier. Re-start is blocked to preserve the prospective boundary.")
        built=build_versioned_ruleset(ident,d["content_hash"],d["dossier"] or {})
        spec=built["spec"]
        cur.execute("""INSERT INTO market_os_versioned_rulesets(
                ruleset_id,version_label,base_rule_version,source_dossier_id,
                source_shadow_rule_id,status,spec_hash,spec,activated_at,note)
            VALUES(%s,%s,%s,%s,%s,'DRY_RUN_ACTIVE',%s,%s::jsonb,now(),
                   'Human-started prospective dry run; live Market OS unchanged')""",
            (built["ruleset_id"],built["version_label"],spec["base_rule_version"],
             ident,d["shadow_rule_id"],built["content_hash"],
             json.dumps(spec,ensure_ascii=False)))
        cur.execute("""INSERT INTO market_os_ruleset_events(
                ruleset_id,event_type,from_status,to_status,evidence)
            VALUES(%s,'HUMAN_DRY_RUN_STARTED',NULL,'DRY_RUN_ACTIVE',%s::jsonb)""",
            (built["ruleset_id"],json.dumps({
                "dossier_id":ident,
                "dossier_hash":d["content_hash"],
                "prospective_only":True,
                "live_activation":False,
            },ensure_ascii=False)))
        cur.execute("""UPDATE market_os_shadow_decisions
                       SET manual_decision_state='DRY_RUN_ACTIVE'
                       WHERE shadow_rule_id=%s""",(d["shadow_rule_id"],))
        print("DRY_RUN_ACTIVE:",built["ruleset_id"])
        print("Version:",built["version_label"])
        print("Prospective boundary: activated_at=now(); earlier assessments are excluded.")
        print("Live Market OS scores/tiers/rulesets/orders were NOT changed.")
        raise SystemExit(0)

    if cmd=="dry-run-stop":
        cur.execute("""SELECT * FROM market_os_versioned_rulesets
                       WHERE ruleset_id=%s FOR UPDATE""",(ident,))
        rs=cur.fetchone()
        if not rs:
            raise SystemExit("ruleset_id not found")
        if rs["status"]!="DRY_RUN_ACTIVE":
            raise SystemExit("Only DRY_RUN_ACTIVE rulesets can be stopped. Current="+str(rs["status"]))
        cur.execute("""UPDATE market_os_versioned_rulesets
                       SET status='DRY_RUN_STOPPED',stopped_at=now(),
                           note='Manually stopped; prior dry-run evidence preserved'
                       WHERE ruleset_id=%s""",(ident,))
        cur.execute("""INSERT INTO market_os_ruleset_events(
                ruleset_id,event_type,from_status,to_status,evidence)
            VALUES(%s,'HUMAN_DRY_RUN_STOPPED','DRY_RUN_ACTIVE','DRY_RUN_STOPPED',
                   %s::jsonb)""",
            (ident,json.dumps({"live_activation":False},ensure_ascii=False)))
        cur.execute("""UPDATE market_os_shadow_decisions
                       SET manual_decision_state='DRY_RUN_STOPPED'
                       WHERE shadow_rule_id=%s""",(rs["source_shadow_rule_id"],))
        print("DRY_RUN_STOPPED:",ident)
        print("All observations and summaries remain preserved.")
        print("Live Market OS scores/tiers/orders were NOT changed.")
        raise SystemExit(0)

    if cmd=="release-create":
        cur.execute("""SELECT vr.*,sd.decision_state,sd.review_eligible,
                              sd.reason_codes,sd.evidence
                       FROM market_os_versioned_rulesets vr
                       JOIN market_os_ruleset_succession_decisions sd
                         ON sd.ruleset_id=vr.ruleset_id
                       WHERE vr.ruleset_id=%s FOR UPDATE""",(ident,))
        rs=cur.fetchone()
        if not rs:
            raise SystemExit("ruleset_id not found")
        if rs["status"]!="DRY_RUN_ACTIVE":
            raise SystemExit("Release Candidate requires DRY_RUN_ACTIVE ruleset.")
        if rs["decision_state"]!="SUCCESSION_CANDIDATE" or not rs["review_eligible"]:
            raise SystemExit("Release Candidate requires current SUCCESSION_CANDIDATE + review_eligible=true.")
        cur.execute("""SELECT event_id,event_time
                       FROM market_os_ruleset_succession_events
                       WHERE ruleset_id=%s AND to_state='SUCCESSION_CANDIDATE'
                       ORDER BY event_time DESC,event_id DESC LIMIT 1""",(ident,))
        ev=cur.fetchone()
        if not ev:
            raise SystemExit("SUCCESSION_CANDIDATE transition event missing")
        cur.execute("""SELECT 1 FROM market_os_release_candidates
                       WHERE source_ruleset_id=%s AND source_succession_event_id=%s""",
                    (ident,ev["event_id"]))
        if cur.fetchone():
            raise SystemExit("A Release Candidate already exists for this succession transition.")
        built=build_release_candidate(
            dict(rs),ev["event_id"],
            {"decision_state":rs["decision_state"],"review_eligible":rs["review_eligible"]},
            20
        )
        pkg=built["package"]
        cur.execute("""INSERT INTO market_os_release_candidates(
                release_candidate_id,release_version_label,source_ruleset_id,
                source_succession_event_id,package_hash,package,status,
                canary_allocation_pct,note)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb,'RELEASE_CANDIDATE',%s,
                   'Human-created immutable release candidate; canary not started')""",
            (built["release_candidate_id"],built["release_version_label"],ident,
             ev["event_id"],built["package_hash"],json.dumps(pkg,ensure_ascii=False),
             pkg["canary"]["allocation_pct"]))
        cur.execute("""INSERT INTO market_os_release_events(
                release_candidate_id,event_type,from_status,to_status,evidence)
            VALUES(%s,'HUMAN_RELEASE_CANDIDATE_CREATED',NULL,'RELEASE_CANDIDATE',%s::jsonb)""",
            (built["release_candidate_id"],json.dumps({
                "ruleset_id":ident,
                "succession_event_id":ev["event_id"],
                "package_hash":built["package_hash"],
                "live_activation":False,
            },ensure_ascii=False)))
        cur.execute("""UPDATE market_os_ruleset_succession_decisions
                       SET manual_review_state='RELEASE_CANDIDATE_CREATED'
                       WHERE ruleset_id=%s""",(ident,))
        print("RELEASE_CANDIDATE:",built["release_candidate_id"])
        print("Version:",built["release_version_label"])
        print("Canary allocation:",str(pkg["canary"]["allocation_pct"])+"%")
        print("Canary has NOT started. Run canary-start explicitly.")
        print("Live Market OS scores/tiers/orders were NOT changed.")
        raise SystemExit(0)

    if cmd=="canary-start":
        cur.execute("""SELECT rc.*,vr.status AS ruleset_status,
                              sd.decision_state,sd.review_eligible
                       FROM market_os_release_candidates rc
                       JOIN market_os_versioned_rulesets vr
                         ON vr.ruleset_id=rc.source_ruleset_id
                       JOIN market_os_ruleset_succession_decisions sd
                         ON sd.ruleset_id=rc.source_ruleset_id
                       WHERE rc.release_candidate_id=%s FOR UPDATE""",(ident,))
        rc=cur.fetchone()
        if not rc:
            raise SystemExit("release_candidate_id not found")
        if rc["status"]!="RELEASE_CANDIDATE":
            raise SystemExit("Canary start requires RELEASE_CANDIDATE. Current="+str(rc["status"]))
        if rc["ruleset_status"]!="DRY_RUN_ACTIVE" or rc["decision_state"]!="SUCCESSION_CANDIDATE" or not rc["review_eligible"]:
            raise SystemExit("Canary start requires active ruleset + current SUCCESSION_CANDIDATE.")
        cur.execute("""UPDATE market_os_release_candidates
                       SET status='CANARY_ACTIVE',canary_started_at=now(),
                           note='Human-started deterministic preview canary; live CONTROL unchanged'
                       WHERE release_candidate_id=%s""",(ident,))
        cur.execute("""INSERT INTO market_os_release_events(
                release_candidate_id,event_type,from_status,to_status,evidence)
            VALUES(%s,'HUMAN_CANARY_STARTED','RELEASE_CANDIDATE','CANARY_ACTIVE',
                   %s::jsonb)""",
            (ident,json.dumps({
                "allocation_pct":rc["canary_allocation_pct"],
                "assignment_unit":"STOCK_KST_DAY",
                "primary_view_replacement":False,
                "live_activation":False,
            },ensure_ascii=False)))
        cur.execute("""UPDATE market_os_ruleset_succession_decisions
                       SET manual_review_state='CANARY_ACTIVE'
                       WHERE ruleset_id=%s""",(rc["source_ruleset_id"],))
        print("CANARY_ACTIVE:",ident)
        print("Allocation:",str(rc["canary_allocation_pct"])+"% deterministic stock-day sample")
        print("Primary Market OS watch_tier remains CONTROL.")
        print("Live orders/positions were NOT changed.")
        raise SystemExit(0)

    if cmd=="canary-stop":
        cur.execute("""SELECT * FROM market_os_release_candidates
                       WHERE release_candidate_id=%s FOR UPDATE""",(ident,))
        rc=cur.fetchone()
        if not rc:
            raise SystemExit("release_candidate_id not found")
        if rc["status"]!="CANARY_ACTIVE":
            raise SystemExit("Only CANARY_ACTIVE can be manually stopped. Current="+str(rc["status"]))
        cur.execute("""UPDATE market_os_release_candidates
                       SET status='CANARY_STOPPED',stopped_at=now(),
                           note='Human-stopped preview canary; evidence preserved'
                       WHERE release_candidate_id=%s""",(ident,))
        cur.execute("""INSERT INTO market_os_release_events(
                release_candidate_id,event_type,from_status,to_status,evidence)
            VALUES(%s,'HUMAN_CANARY_STOPPED','CANARY_ACTIVE','CANARY_STOPPED',
                   %s::jsonb)""",
            (ident,json.dumps({"live_activation":False},ensure_ascii=False)))
        cur.execute("""UPDATE market_os_ruleset_succession_decisions
                       SET manual_review_state='CANARY_STOPPED'
                       WHERE ruleset_id=%s""",(rc["source_ruleset_id"],))
        print("CANARY_STOPPED:",ident)
        print("Existing Canary evidence remains preserved.")
        print("Live Market OS scores/tiers/orders were NOT changed.")
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
