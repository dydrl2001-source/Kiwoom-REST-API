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
  echo "  bash shadow_rule_admin.sh full-release <review_id>"
  echo "  bash shadow_rule_admin.sh switch <switch_transaction_id>"
  echo "  bash shadow_rule_admin.sh intent <intent_id>"
  echo "  bash shadow_rule_admin.sh approve <candidate_key> --confirm"
  echo "  bash shadow_rule_admin.sh disable <shadow_rule_id> --confirm"
  echo "  bash shadow_rule_admin.sh review <dossier_id> <approve-dry-run|reject> --confirm"
  echo "  bash shadow_rule_admin.sh dry-run-start <dossier_id> --confirm"
  echo "  bash shadow_rule_admin.sh dry-run-stop <ruleset_id> --confirm"
  echo "  bash shadow_rule_admin.sh release-create <ruleset_id> --confirm"
  echo "  bash shadow_rule_admin.sh canary-start <release_candidate_id> --confirm"
  echo "  bash shadow_rule_admin.sh canary-stop <release_candidate_id> --confirm"
  echo "  bash shadow_rule_admin.sh full-release-review <review_id> <approve|reject> --confirm"
  echo "  bash shadow_rule_admin.sh switch-prepare <review_id> --confirm"
  echo "  bash shadow_rule_admin.sh switch-commit <switch_transaction_id> --confirm"
  echo "  bash shadow_rule_admin.sh switch-rollback <switch_transaction_id> --confirm"
  echo "  bash shadow_rule_admin.sh switch-cancel <switch_transaction_id> --confirm"
  echo "  bash shadow_rule_admin.sh intent-review <intent_id> <approve|reject> --confirm"
}

case "$cmd" in
  list)
    ;;
  dossier|ruleset|release|full-release|switch|intent)
    if [ -z "$id" ]; then usage; exit 1; fi
    ;;
  approve|disable|dry-run-start|dry-run-stop|release-create|canary-start|canary-stop|switch-prepare|switch-commit|switch-rollback|switch-cancel)
    if [ -z "$id" ] || [ "$arg" != "--confirm" ]; then usage; exit 1; fi
    ;;
  review)
    if [ -z "$id" ] || { [ "$arg" != "approve-dry-run" ] && [ "$arg" != "reject" ]; } || [ "$confirm" != "--confirm" ]; then
      usage; exit 1
    fi
    ;;
  full-release-review)
    if [ -z "$id" ] || { [ "$arg" != "approve" ] && [ "$arg" != "reject" ]; } || [ "$confirm" != "--confirm" ]; then
      usage; exit 1
    fi
    ;;
  intent-review)
    if [ -z "$id" ] || { [ "$arg" != "approve" ] && [ "$arg" != "reject" ]; } || [ "$confirm" != "--confirm" ]; then
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
import json,os,sys,hashlib
from datetime import datetime,timezone
import psycopg
from psycopg.rows import dict_row
from market_os_ruleset import build_spec as build_versioned_ruleset
from market_os_release import build_release_candidate
from market_os_rule_engine import VERSION as MARKET_OS_BASE_VERSION
from market_os_control import (
    base_control as runtime_base_control,
    candidate_control as runtime_candidate_control,
    control_hash as runtime_control_hash,
)
from market_os_execution import approval_still_valid as execution_approval_valid

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
              "market_os_canary_decision_events","market_os_full_release_gates",
              "market_os_full_release_gate_events","market_os_full_release_reviews",
              "market_os_full_release_review_events","market_os_control_state",
              "market_os_switch_transactions","market_os_switch_events",
              "market_os_execution_intents","market_os_execution_intent_events",
              "market_os_execution_firewall_runs"]
    missing=[x for x in required if not exists(x)]
    if missing:
        raise SystemExit("Shadow Lab schema missing: "+", ".join(missing)+". Deploy/restart market-os-learning first.")

    def current_control(for_update=False):
        suffix=" FOR UPDATE" if for_update else ""
        cur.execute("""SELECT control_id,mode,active_version_label,base_rule_version,
                              ruleset_id,ruleset_hash,ruleset_spec,source_review_id,
                              switch_transaction_id,control_hash,activated_at
                       FROM market_os_control_state WHERE id=1"""+suffix)
        row=cur.fetchone()
        if row:
            x=dict(row)
            if x.get("activated_at"):
                x["activated_at"]=x["activated_at"].isoformat()
            return x
        return runtime_base_control(MARKET_OS_BASE_VERSION)

    def write_control(x,activated_at_sql=False):
        cur.execute("""INSERT INTO market_os_control_state(
                id,control_id,mode,active_version_label,base_rule_version,
                ruleset_id,ruleset_hash,ruleset_spec,source_review_id,
                switch_transaction_id,control_hash,activated_at,updated_at)
            VALUES(1,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,
                   CASE WHEN %s THEN now() ELSE %s::timestamptz END,now())
            ON CONFLICT(id) DO UPDATE SET
                control_id=excluded.control_id,mode=excluded.mode,
                active_version_label=excluded.active_version_label,
                base_rule_version=excluded.base_rule_version,
                ruleset_id=excluded.ruleset_id,ruleset_hash=excluded.ruleset_hash,
                ruleset_spec=excluded.ruleset_spec,source_review_id=excluded.source_review_id,
                switch_transaction_id=excluded.switch_transaction_id,
                control_hash=excluded.control_hash,activated_at=excluded.activated_at,
                updated_at=now()""",
            (x.get("control_id"),x.get("mode"),x.get("active_version_label"),
             x.get("base_rule_version"),x.get("ruleset_id"),x.get("ruleset_hash"),
             json.dumps(x.get("ruleset_spec"),ensure_ascii=False) if x.get("ruleset_spec") is not None else None,
             x.get("source_review_id"),x.get("switch_transaction_id"),
             x.get("control_hash") or runtime_control_hash(x),
             activated_at_sql,x.get("activated_at")))

    def switch_sources(review_id,for_update=False):
        suffix=" FOR UPDATE" if for_update else ""
        cur.execute("""SELECT fr.review_id,fr.release_candidate_id,fr.content_hash,
                              fr.review_state,g.gate_state,g.review_eligible AS gate_eligible,
                              rc.status AS release_status,rc.source_ruleset_id,
                              cd.decision_state AS canary_state,
                              cd.review_eligible AS canary_eligible,
                              vr.ruleset_id,vr.version_label,vr.base_rule_version,
                              vr.spec_hash,vr.spec,vr.status AS ruleset_status,
                              sd.decision_state AS succession_state,
                              sd.review_eligible AS succession_eligible
                       FROM market_os_full_release_reviews fr
                       JOIN market_os_full_release_gates g
                         ON g.release_candidate_id=fr.release_candidate_id
                       JOIN market_os_release_candidates rc
                         ON rc.release_candidate_id=fr.release_candidate_id
                       JOIN market_os_canary_decisions cd
                         ON cd.release_candidate_id=fr.release_candidate_id
                       JOIN market_os_versioned_rulesets vr
                         ON vr.ruleset_id=rc.source_ruleset_id
                       JOIN market_os_ruleset_succession_decisions sd
                         ON sd.ruleset_id=vr.ruleset_id
                       WHERE fr.review_id=%s"""+suffix,(review_id,))
        return cur.fetchone()

    def require_switch_sources(row):
        if not row:
            raise SystemExit("full release review source missing")
        checks=[
            (row["review_state"]=="RELEASE_READY","review not RELEASE_READY"),
            (row["gate_state"]=="FULL_RELEASE_REVIEW_READY" and row["gate_eligible"],"full release gate not ready"),
            (row["release_status"]=="CANARY_ACTIVE","release not CANARY_ACTIVE"),
            (row["canary_state"]=="CANARY_PROMOTION_CANDIDATE" and row["canary_eligible"],"canary not promotion eligible"),
            (row["ruleset_status"]=="DRY_RUN_ACTIVE","ruleset not DRY_RUN_ACTIVE"),
            (row["succession_state"]=="SUCCESSION_CANDIDATE" and row["succession_eligible"],"succession not eligible"),
        ]
        bad=[msg for ok,msg in checks if not ok]
        if bad:
            raise SystemExit("Switch source invalid: "+", ".join(bad))

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

        print("\n=== FULL RELEASE REVIEWS ===")
        cur.execute("""SELECT fr.review_id,fr.release_candidate_id,fr.revision,
                              fr.gate_state,fr.review_state,fr.created_at,fr.reviewed_at,
                              fr.content_hash,g.review_eligible,g.gate_state AS current_gate_state
                       FROM market_os_full_release_reviews fr
                       LEFT JOIN market_os_full_release_gates g
                         ON g.release_candidate_id=fr.release_candidate_id
                       ORDER BY CASE fr.review_state WHEN 'PENDING' THEN 1
                                WHEN 'RELEASE_READY' THEN 2 WHEN 'REJECTED' THEN 3
                                ELSE 4 END,fr.created_at DESC""")
        reviews=cur.fetchall()
        if not reviews:print("none")
        for r in reviews:
            print(f"{r['review_id']} | rev={r['revision']} | {r['review_state']} | "
                  f"release={r['release_candidate_id']} frozenGate={r['gate_state']} "
                  f"currentGate={r['current_gate_state'] or '—'} "
                  f"eligible={r['review_eligible'] or False} "
                  f"created={r['created_at']} reviewed={r['reviewed_at']} "
                  f"hash={r['content_hash'][:12]}")

        print("\n=== CONTROL / SWITCH TRANSACTIONS ===")
        ctrl=current_control()
        print(f"CONTROL {ctrl['control_id']} mode={ctrl['mode']} "
              f"version={ctrl['active_version_label']} hash={ctrl['control_hash'][:12]} "
              f"switch={ctrl.get('switch_transaction_id') or '—'}")
        cur.execute("""SELECT switch_transaction_id,source_review_id,release_candidate_id,
                              ruleset_id,state,expected_control_hash,candidate_hash,
                              pre_switch_watch_count,prepared_at,committed_at,
                              health_deadline,completed_at,rollback_at,rollback_reason
                       FROM market_os_switch_transactions
                       ORDER BY prepared_at DESC LIMIT 20""")
        switches=cur.fetchall()
        if not switches:print("none")
        for s in switches:
            print(f"{s['switch_transaction_id']} | {s['state']} | review={s['source_review_id']} "
                  f"ruleset={s['ruleset_id']} prepared={s['prepared_at']} "
                  f"committed={s['committed_at']} health={s['health_deadline']} "
                  f"rollback={s['rollback_at']} reason={s['rollback_reason'] or '—'}")

        print("\n=== EXECUTION FIREWALL INTENTS ===")
        cur.execute("""SELECT intent_id,status,stock_code,stock_name,snapshot_time,expires_at,
                              active_version_label,switch_transaction_id,reference_price_krw,
                              watch_tier,trigger_state,market_stance,catalyst_grade,
                              created_at,reviewed_at
                       FROM market_os_execution_intents
                       ORDER BY CASE status WHEN 'REVIEW_PENDING' THEN 1
                                WHEN 'HUMAN_APPROVED_INTENT' THEN 2 ELSE 3 END,
                                created_at DESC LIMIT 40""")
        intents=cur.fetchall()
        if not intents:print("none")
        for x in intents:
            print(f"{x['intent_id']} | {x['status']} | {x['stock_code']} {x['stock_name'] or ''} | "
                  f"tier={x['watch_tier']} trigger={x['trigger_state']} stance={x['market_stance']} "
                  f"catalyst={x['catalyst_grade']} ref={x['reference_price_krw']} "
                  f"expires={x['expires_at']} version={x['active_version_label']} "
                  f"switch={x['switch_transaction_id']}")

        print("\nRead-only list. No live scores, thresholds, rulesets or orders were changed.")
        raise SystemExit(0)

    if cmd=="intent":
        cur.execute("""SELECT * FROM market_os_execution_intents
                       WHERE intent_id=%s""",(ident,))
        x=cur.fetchone()
        if not x:
            raise SystemExit("intent_id not found")
        print("EXECUTION INTENT:",x["intent_id"],"Status:",x["status"])
        print("Stock:",x["stock_code"],x["stock_name"] or "")
        print("Snapshot:",x["snapshot_time"],"Expires:",x["expires_at"])
        print("CONTROL:",x["active_version_label"],x["control_hash"],
              "Switch:",x["switch_transaction_id"])
        print("Reference price:",x["reference_price_krw"])
        print(json.dumps(x["evidence"],ensure_ascii=False,indent=2,default=str))
        print("\nRead-only intent. Quantity/limit price/broker order are not generated.")
        raise SystemExit(0)

    if cmd=="switch":
        cur.execute("""SELECT * FROM market_os_switch_transactions
                       WHERE switch_transaction_id=%s""",(ident,))
        s=cur.fetchone()
        if not s:
            raise SystemExit("switch_transaction_id not found")
        print("SWITCH:",s["switch_transaction_id"],"State:",s["state"])
        print("Review:",s["source_review_id"],"Release:",s["release_candidate_id"],
              "Ruleset:",s["ruleset_id"])
        print("Expected CONTROL:",s["expected_control_hash"])
        print("Candidate hash:",s["candidate_hash"])
        print("Prepared:",s["prepared_at"],"Committed:",s["committed_at"],
              "Health deadline:",s["health_deadline"],"Completed:",s["completed_at"])
        print("Rollback:",s["rollback_at"],"Reason:",s["rollback_reason"])
        print("\nPrevious CONTROL:")
        print(json.dumps(s["previous_control"],ensure_ascii=False,indent=2,default=str))
        print("\nCandidate CONTROL:")
        print(json.dumps(s["candidate_control"],ensure_ascii=False,indent=2,default=str))
        print("\nCurrent CONTROL:")
        print(json.dumps(current_control(),ensure_ascii=False,indent=2,default=str))
        print("\nRead-only switch view. No CONTROL change was performed.")
        raise SystemExit(0)

    if cmd=="full-release":
        cur.execute("""SELECT fr.*,g.gate_state AS current_gate_state,
                              g.review_eligible AS current_review_eligible
                       FROM market_os_full_release_reviews fr
                       LEFT JOIN market_os_full_release_gates g
                         ON g.release_candidate_id=fr.release_candidate_id
                       WHERE fr.review_id=%s""",(ident,))
        fr=cur.fetchone()
        if not fr:
            raise SystemExit("review_id not found")
        print("FULL RELEASE REVIEW:",fr["review_id"])
        print("Release:",fr["release_candidate_id"],"Revision:",fr["revision"])
        print("Frozen gate:",fr["gate_state"],"Review:",fr["review_state"])
        print("Current gate:",fr["current_gate_state"],"Eligible:",fr["current_review_eligible"])
        print("Hash:",fr["content_hash"])
        print("Created:",fr["created_at"],"Reviewed:",fr["reviewed_at"],"By:",fr["reviewed_by"])
        print(json.dumps(fr["package"],ensure_ascii=False,indent=2,default=str))
        print("\nRead-only full release review. No live switch or order change was performed.")
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

    if cmd=="full-release-review":
        cur.execute("""SELECT * FROM market_os_full_release_reviews
                       WHERE review_id=%s FOR UPDATE""",(ident,))
        fr=cur.fetchone()
        if not fr:
            raise SystemExit("review_id not found")
        if fr["review_state"]!="PENDING":
            raise SystemExit("Only PENDING full release reviews can be decided. Current="+str(fr["review_state"]))

        cur.execute("""SELECT g.gate_state,g.review_eligible,
                              rc.status AS release_status,rc.source_ruleset_id,
                              cd.decision_state AS canary_state,
                              cd.review_eligible AS canary_eligible,
                              vr.status AS ruleset_status,
                              sd.decision_state AS succession_state,
                              sd.review_eligible AS succession_eligible
                       FROM market_os_full_release_gates g
                       JOIN market_os_release_candidates rc
                         ON rc.release_candidate_id=g.release_candidate_id
                       JOIN market_os_canary_decisions cd
                         ON cd.release_candidate_id=g.release_candidate_id
                       JOIN market_os_versioned_rulesets vr
                         ON vr.ruleset_id=rc.source_ruleset_id
                       JOIN market_os_ruleset_succession_decisions sd
                         ON sd.ruleset_id=rc.source_ruleset_id
                       WHERE g.release_candidate_id=%s FOR UPDATE""",
                    (fr["release_candidate_id"],))
        current=cur.fetchone()
        if not current:
            raise SystemExit("current full release source state missing")

        if arg=="approve":
            if current["gate_state"]!="FULL_RELEASE_REVIEW_READY" or not current["review_eligible"]:
                raise SystemExit("Release approval requires current FULL_RELEASE_REVIEW_READY.")
            if current["release_status"]!="CANARY_ACTIVE":
                raise SystemExit("Release approval requires CANARY_ACTIVE.")
            if current["canary_state"]!="CANARY_PROMOTION_CANDIDATE" or not current["canary_eligible"]:
                raise SystemExit("Release approval requires current CANARY_PROMOTION_CANDIDATE.")
            if current["ruleset_status"]!="DRY_RUN_ACTIVE":
                raise SystemExit("Release approval requires DRY_RUN_ACTIVE source ruleset.")
            if current["succession_state"]!="SUCCESSION_CANDIDATE" or not current["succession_eligible"]:
                raise SystemExit("Release approval requires current SUCCESSION_CANDIDATE.")
            target="RELEASE_READY"
            event="HUMAN_RELEASE_READY_APPROVED"
            note="Human approved Full Release Review as RELEASE_READY metadata only; no live switch exists in v2.1."
            manual="RELEASE_READY"
        else:
            target="REJECTED"
            event="HUMAN_FULL_RELEASE_REJECTED"
            note="Human rejected this Full Release Review; Canary evidence remains preserved."
            manual="FULL_RELEASE_REJECTED"

        cur.execute("""UPDATE market_os_full_release_reviews
                       SET review_state=%s,reviewed_at=now(),reviewed_by='MANUAL_SCRIPT',
                           review_note=%s
                       WHERE review_id=%s""",(target,note,ident))
        cur.execute("""UPDATE market_os_canary_decisions
                       SET manual_review_state=%s
                       WHERE release_candidate_id=%s""",(manual,fr["release_candidate_id"]))
        cur.execute("""INSERT INTO market_os_full_release_review_events(
                review_id,event_type,from_review_state,to_review_state,note,evidence)
            VALUES(%s,%s,'PENDING',%s,%s,%s::jsonb)""",
            (ident,event,target,note,json.dumps({
                "release_candidate_id":fr["release_candidate_id"],
                "content_hash":fr["content_hash"],
                "live_switch_created":False,
                "orders_changed":False,
                "primary_view_switched":False,
            },ensure_ascii=False)))
        print(target+":",ident)
        print(note)
        print("Live Market OS CONTROL, orders and positions were NOT changed.")
        raise SystemExit(0)

    if cmd=="switch-prepare":
        cur.execute("SELECT pg_advisory_xact_lock(72419073)")
        src=switch_sources(ident,for_update=True)
        require_switch_sources(src)
        ctrl=current_control(for_update=True)
        if ctrl["mode"]!="BASE":
            raise SystemExit("v2.2 switch preparation requires current BASE CONTROL.")
        if runtime_control_hash(ctrl)!=ctrl["control_hash"]:
            raise SystemExit("Current CONTROL hash is invalid.")
        cur.execute("""SELECT switch_transaction_id,state
                       FROM market_os_switch_transactions
                       WHERE state IN ('PREPARED_SWITCH','COMMITTED')
                       ORDER BY prepared_at DESC LIMIT 1""")
        active=cur.fetchone()
        if active:
            raise SystemExit("Another switch is active: "+active["switch_transaction_id"]+" "+active["state"])
        cur.execute("""SELECT COUNT(*) AS n FROM market_os_switch_transactions
                       WHERE source_review_id=%s""",(ident,))
        attempt=int(cur.fetchone()["n"] or 0)+1
        seed="|".join((ident,ctrl["control_hash"],src["spec_hash"],src["content_hash"],str(attempt)))
        switch_id="sw-"+hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
        candidate=runtime_candidate_control(
            MARKET_OS_BASE_VERSION,
            {"ruleset_id":src["ruleset_id"],"spec_hash":src["spec_hash"],
             "version_label":src["version_label"],"spec":src["spec"]},
            ident,switch_id
        )
        cur.execute("""SELECT COUNT(*) AS n
                       FROM market_os_assessment_snapshots
                       WHERE rule_version=%s
                         AND snapshot_time=(
                             SELECT MAX(snapshot_time) FROM market_os_assessment_snapshots
                             WHERE rule_version=%s
                         )""",(ctrl["active_version_label"],ctrl["active_version_label"]))
        pre_count=int(cur.fetchone()["n"] or 0)
        cur.execute("""INSERT INTO market_os_switch_transactions(
                switch_transaction_id,source_review_id,release_candidate_id,ruleset_id,
                state,expected_control_hash,previous_control,candidate_control,
                candidate_hash,pre_switch_watch_count,note)
            VALUES(%s,%s,%s,%s,'PREPARED_SWITCH',%s,%s::jsonb,%s::jsonb,%s,%s,
                   'Prepared only; CONTROL unchanged')""",
            (switch_id,ident,src["release_candidate_id"],src["ruleset_id"],
             ctrl["control_hash"],json.dumps(ctrl,ensure_ascii=False,default=str),
             json.dumps(candidate,ensure_ascii=False,default=str),
             candidate["control_hash"],pre_count))
        cur.execute("""INSERT INTO market_os_switch_events(
                switch_transaction_id,event_type,from_state,to_state,evidence)
            VALUES(%s,'HUMAN_SWITCH_PREPARED',NULL,'PREPARED_SWITCH',%s::jsonb)""",
            (switch_id,json.dumps({
                "review_id":ident,"expected_control_hash":ctrl["control_hash"],
                "candidate_hash":candidate["control_hash"],
                "pre_switch_watch_count":pre_count,
                "orders_changed":False
            },ensure_ascii=False)))
        print("PREPARED_SWITCH:",switch_id)
        print("Current CONTROL remains:",ctrl["active_version_label"])
        print("Candidate:",candidate["active_version_label"])
        print("Commit requires MARKET_OS_LIVE_SWITCH_ENABLED=1 and explicit switch-commit.")
        print("Orders/positions were NOT changed.")
        raise SystemExit(0)

    if cmd=="switch-commit":
        enabled=os.getenv("MARKET_OS_LIVE_SWITCH_ENABLED","0").strip().lower() in ("1","true","yes","on")
        if not enabled:
            raise SystemExit("MARKET_OS_LIVE_SWITCH_ENABLED is OFF. Commit blocked.")
        health=max(300,min(3600,int(os.getenv("MARKET_OS_SWITCH_HEALTH_SECONDS","900"))))
        ttl=max(300,min(3600,int(os.getenv("MARKET_OS_SWITCH_PREPARE_TTL_SECONDS","1800"))))
        cur.execute("SELECT pg_advisory_xact_lock(72419073)")
        cur.execute("""SELECT * FROM market_os_switch_transactions
                       WHERE switch_transaction_id=%s FOR UPDATE""",(ident,))
        tx=cur.fetchone()
        if not tx:
            raise SystemExit("switch_transaction_id not found")
        if tx["state"]!="PREPARED_SWITCH":
            raise SystemExit("Commit requires PREPARED_SWITCH. Current="+str(tx["state"]))
        age=(datetime.now(timezone.utc)-tx["prepared_at"]).total_seconds()
        if age>ttl:
            raise SystemExit("Prepared switch expired; cancel and prepare a fresh transaction.")
        src=switch_sources(tx["source_review_id"],for_update=True)
        require_switch_sources(src)
        ctrl=current_control(for_update=True)
        if ctrl["control_hash"]!=tx["expected_control_hash"]:
            raise SystemExit("CONTROL changed since prepare; commit aborted.")
        if runtime_control_hash(ctrl)!=ctrl["control_hash"]:
            raise SystemExit("Current CONTROL identity invalid; commit aborted.")
        candidate=dict(tx["candidate_control"] or {})
        if runtime_control_hash(candidate)!=tx["candidate_hash"]:
            raise SystemExit("Candidate CONTROL hash invalid; commit aborted.")
        if candidate.get("ruleset_hash")!=src["spec_hash"] or candidate.get("ruleset_id")!=src["ruleset_id"]:
            raise SystemExit("Candidate ruleset no longer matches release source.")
        write_control(candidate,activated_at_sql=True)
        cur.execute("""UPDATE market_os_switch_transactions
                       SET state='COMMITTED',committed_at=now(),
                           health_deadline=now()+(%s || ' seconds')::interval,
                           note='Atomic CONTROL selector commit; orders unchanged'
                       WHERE switch_transaction_id=%s AND state='PREPARED_SWITCH'""",
                    (health,ident))
        cur.execute("""INSERT INTO market_os_switch_events(
                switch_transaction_id,event_type,from_state,to_state,evidence)
            VALUES(%s,'HUMAN_SWITCH_COMMITTED','PREPARED_SWITCH','COMMITTED',%s::jsonb)""",
            (ident,json.dumps({
                "candidate_control_id":candidate.get("control_id"),
                "candidate_hash":candidate.get("control_hash"),
                "health_window_seconds":health,
                "orders_changed":False,"positions_changed":False
            },ensure_ascii=False)))
        print("COMMITTED:",ident)
        print("New CONTROL:",candidate["active_version_label"])
        print("Health window:",str(health)+"s")
        print("Orders/positions remain unchanged. Automatic rollback watches hard failures.")
        raise SystemExit(0)

    if cmd=="switch-rollback":
        cur.execute("SELECT pg_advisory_xact_lock(72419073)")
        cur.execute("""SELECT * FROM market_os_switch_transactions
                       WHERE switch_transaction_id=%s FOR UPDATE""",(ident,))
        tx=cur.fetchone()
        if not tx:
            raise SystemExit("switch_transaction_id not found")
        if tx["state"] not in ("COMMITTED","HEALTHY"):
            raise SystemExit("Rollback requires COMMITTED or HEALTHY. Current="+str(tx["state"]))
        ctrl=current_control(for_update=True)
        if ctrl.get("switch_transaction_id")!=ident or ctrl.get("control_hash")!=tx["candidate_hash"]:
            raise SystemExit("Current CONTROL no longer matches this switch; refusing unsafe rollback.")
        previous=dict(tx["previous_control"] or {})
        write_control(previous,activated_at_sql=False)
        cur.execute("""UPDATE market_os_switch_transactions
                       SET state='ROLLED_BACK',rollback_at=now(),completed_at=now(),
                           rollback_reason='MANUAL_ROLLBACK',
                           note='Manual rollback restored previous CONTROL'
                       WHERE switch_transaction_id=%s""",(ident,))
        cur.execute("""INSERT INTO market_os_switch_events(
                switch_transaction_id,event_type,from_state,to_state,evidence)
            VALUES(%s,'HUMAN_SWITCH_ROLLBACK',%s,'ROLLED_BACK',%s::jsonb)""",
            (ident,tx["state"],json.dumps({
                "restored_control_id":previous.get("control_id"),
                "restored_control_hash":previous.get("control_hash"),
                "orders_changed":False
            },ensure_ascii=False)))
        print("ROLLED_BACK:",ident)
        print("Restored CONTROL:",previous.get("active_version_label"))
        print("Orders/positions were NOT changed.")
        raise SystemExit(0)

    if cmd=="switch-cancel":
        cur.execute("SELECT pg_advisory_xact_lock(72419073)")
        cur.execute("""SELECT * FROM market_os_switch_transactions
                       WHERE switch_transaction_id=%s FOR UPDATE""",(ident,))
        tx=cur.fetchone()
        if not tx:
            raise SystemExit("switch_transaction_id not found")
        if tx["state"]!="PREPARED_SWITCH":
            raise SystemExit("Cancel requires PREPARED_SWITCH. Current="+str(tx["state"]))
        cur.execute("""UPDATE market_os_switch_transactions
                       SET state='CANCELLED',completed_at=now(),
                           note='Prepared switch cancelled; CONTROL was never changed'
                       WHERE switch_transaction_id=%s""",(ident,))
        cur.execute("""INSERT INTO market_os_switch_events(
                switch_transaction_id,event_type,from_state,to_state,evidence)
            VALUES(%s,'HUMAN_SWITCH_CANCELLED','PREPARED_SWITCH','CANCELLED','{}'::jsonb)""",
            (ident,))
        print("CANCELLED:",ident)
        print("CONTROL was never changed.")
        raise SystemExit(0)

    if cmd=="intent-review":
        cur.execute("""SELECT * FROM market_os_execution_intents
                       WHERE intent_id=%s FOR UPDATE""",(ident,))
        x=cur.fetchone()
        if not x:
            raise SystemExit("intent_id not found")
        if x["status"]!="REVIEW_PENDING":
            raise SystemExit("Only REVIEW_PENDING intents can be reviewed. Current="+str(x["status"]))

        if arg=="approve":
            ctrl=current_control(for_update=True)
            cur.execute("""SELECT state FROM market_os_switch_transactions
                           WHERE switch_transaction_id=%s""",(x["switch_transaction_id"],))
            sr=cur.fetchone()
            switch_state=sr["state"] if sr else None
            check=execution_approval_valid(dict(x),ctrl,switch_state,datetime.now(timezone.utc))
            if not check["valid"]:
                target="EXPIRED" if "INTENT_EXPIRED" in check["reason_codes"] else "STALE_CONTROL"
                cur.execute("""UPDATE market_os_execution_intents
                               SET status=%s,reviewed_at=now(),reviewed_by='MANUAL_SCRIPT',
                                   review_note=%s
                               WHERE intent_id=%s""",
                            (target,",".join(check["reason_codes"]),ident))
                cur.execute("""INSERT INTO market_os_execution_intent_events(
                        intent_id,event_type,from_status,to_status,reason_codes,evidence)
                    VALUES(%s,'REVIEW_INVALIDATED','REVIEW_PENDING',%s,%s::jsonb,%s::jsonb)""",
                    (ident,target,json.dumps(check["reason_codes"],ensure_ascii=False),
                     json.dumps({"broker_order_created":False},ensure_ascii=False)))
                raise SystemExit(target+": "+",".join(check["reason_codes"]))
            # Recheck current source facts; daily AI advice and the frozen intent
            # cannot substitute for a fresh entry risk check.
            from market_os_risk import evaluate as entry_risk, observation_facts
            from flow_store import desk_payload
            current=desk_payload(include_tracking=False)
            from market_os_readonly import enrich_payload
            current=enrich_payload(current)
            cc=next((v for v in current.get("market_os_watchlist",[]) if v.get("code")==x["stock_code"]),{})
            rr=next((v for v in current.get("rows",[]) if v.get("code")==x["stock_code"]),{})
            gate=entry_risk(cc,observation_facts(rr),datetime.now(timezone.utc),mode="manual_confirm")
            if not gate["review_eligible"]:
                raise SystemExit("RISK_GATE_BLOCKED: "+",".join(gate["reason_codes"]))
            target="HUMAN_APPROVED_INTENT"
            event="HUMAN_INTENT_APPROVED"
            note="Human approved review intent metadata only; no broker order, quantity or position mutation."
        else:
            target="HUMAN_REJECTED"
            event="HUMAN_INTENT_REJECTED"
            note="Human rejected execution review intent."

        cur.execute("""UPDATE market_os_execution_intents
                       SET status=%s,reviewed_at=now(),reviewed_by='MANUAL_SCRIPT',
                           review_note=%s
                       WHERE intent_id=%s""",(target,note,ident))
        cur.execute("""INSERT INTO market_os_execution_intent_events(
                intent_id,event_type,from_status,to_status,reason_codes,evidence)
            VALUES(%s,%s,'REVIEW_PENDING',%s,'[]'::jsonb,%s::jsonb)""",
            (ident,event,target,json.dumps({
                "broker_order_created":False,
                "quantity":None,
                "limit_price":None,
                "position_change":False,
            },ensure_ascii=False)))
        print(target+":",ident)
        print(note)
        print("No broker API was called.")
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
