# Kiwoom execution implementation plan

**Goal:** Execute only separately confirmed approved intent plans with durable recovery.
**Architecture:** Frozen plans and policy; one-shot Kiwoom adapter; PostgreSQL journal;
explicit service/CLI. Existing approval and chart/NAVER paths remain unchanged.
**Tech stack:** Python 3.12, psycopg, PostgreSQL, requests, unittest.
**Spec:** ../specs/2026-10-06-kiwoom-execution-design.md

## Constraints and review focus

- live default OFF; paper/dry-run cannot reach network writes.
- Committed reservations survive crashes; UNKNOWN never auto-retries.
- CONTROL changes, expired approval and stale/future facts block before send.
- A different command ID cannot replay the same plan or intent.
- Parent amend/cancel acceptance cannot fabricate a fill/cancellation.
- Event replay cannot reduce cumulative fills or reopen terminal orders.
- PostgreSQL tests exercise simultaneous submissions and restart recovery.

## Tasks

1. Write failing `test_market_os_orders.py` policy/adapter tests. Implement
   `market_os_order_plan.py` frozen OrderPlan/build/validate and
   `market_os_broker.py` one-shot adapters. Run unittest and commit.
2. Write PostgreSQL tests for journal/service lifecycle. Implement
   `market_os_order_store.py` and `market_os_orders.py`: prepare, execute,
   reconcile, child plans, protected audit projection. Run CI DB tests.
3. Add explicit `market_os_order_admin.py` command and trusted context source;
   no web routes or scheduling. Verify CLI confirmation and mode isolation.
4. Add operational docs/default-off config/CI compile, run existing regression
   suites, review diff, recheck remote head and publish to PR branch.
