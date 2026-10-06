# Manual Kiwoom execution v2.4

Execution is a separate operator command. `intent-review approve` still only saves
`HUMAN_APPROVED_INTENT`. It never prepares a plan or calls a broker. AI chart mode,
NAVER human-only research, the read-only adapter and existing Risk policy are unchanged.

## Boundaries

1. Existing human intent review records approval.
2. `prepare --confirm` fixes quantity, KRX limit price, stop, account binding and mode.
3. `inspect` displays the exact plan hash and minimal order status.
4. `execute --confirm-plan <exact hash> --command-id <unique ID>` revalidates and submits.

`MARKET_OS_LIVE_ORDERS_ENABLED=0` by default. Setting it to `1` is insufficient to
send an order. Both the executor and Kiwoom adapter require the explicit plan hash.
No new web route, worker, timer or automatic order hook was added. Market orders,
credit orders and automatic quantity calculations are not provided by this layer.

`dry-run`: journal-only, no broker number or fill. `paper`: simulated order number;
only explicit `paper-event` commands change simulated fills. `live`: fixed production
Kiwoom host, KRX limit order, one POST with no auth retry, redirect or HTTP retry.
Paper/dry-run never construct the live order adapter. These modes have separate
plan hashes, reservations and account locks; paper results cannot be reconciled
against a real account or promoted into live orders.

## Commands

Run from `market_radar/local` (or `python market_os_order_admin.py` inside the image):

```sh
bash order_admin.sh init-journal
bash order_admin.sh account-ref
bash order_admin.sh prepare <approved-intent-id> --account-ref <opaque-ref> \
  --mode paper --quantity 1 --limit-price <KRW> --stop-price <KRW> --confirm
bash order_admin.sh inspect <plan-id>
bash order_admin.sh execute <plan-id> --command-id <unique-operator-command-id> \
  --confirm-plan <plan-id>
bash order_admin.sh reconcile <plan-id>
bash order_admin.sh paper-event <paper-plan-id> --status PARTIALLY_FILLED \
  --filled-quantity 1 --event-key <unique-event-id> --confirm-plan <paper-plan-id>
```

Live plans use `account-ref` derived from broker-confirmed `ka00001` actual account
identity, protected by `MARKET_OS_ACCOUNT_BINDING_SECRET` (private random secret,
at least 32 characters). The same account shares an execution lock across app keys.
Every executor using the same journal must use the same persistent secret. An
immutable journal fingerprint blocks a changed secret until a reviewed migration
resolves existing order lineage; it cannot quietly create another account lock.
Unexpected/multiple account identity responses block.
No token/app key/account number or raw broker response enters an event or CLI result.
Broker order numbers remain in the private PostgreSQL journal; inspection only
returns `broker_number_recorded`. Do not export this journal to an LLM/report packet.

## Trusted facts integration

The current repository does not prove cash-flow-adjusted daily loss, trading session
or orderable capacity. Its built-in source therefore **blocks** execution. It does
not infer these facts from available cash, AI opinions or a saved decision packet.

Configure `MARKET_OS_ORDER_FACTS_MODULE` with a **server-owned Python module**, deployed
alongside the application. No CLI flag/HTTP body can provide live facts. The module
must implement:

```python
collect(*, stock_code, account_ref, mode, limit_context, env) -> dict
history(*, plan, env) -> dict
```

`collect` receives requested quantity/limit/stop/operation and a private parent
broker number for cancel/amend. It returns `{account_ref, mode, facts}` from
authenticated broker/exchange sources. This is a trusted code boundary: never use
an AI answer, operator-supplied JSON or saved packet as its implementation.

Required facts:

| Field | Requirement |
| --- | --- |
| `price_krw`, `price_as_of` | Correct stock quote; exchange timestamp within 5 s, never future |
| `account_as_of`, `executable` | Verified permission/account state, at most 30 s; `True` |
| `orderable_quantity` | Nonnegative integer for the exact symbol/limit/operation, including outstanding reservations |
| `tick_size_krw` | Verified current price-band/instrument tick; integer price must align |
| `session_as_of`, `is_trading_day`, `session_open` | Verified exchange session/holiday facts |
| `duplicate_as_of`, `duplicate_order` | Complete account-wide broker order query, `False` for entry |
| `daily_loss_pct` | Verified opening equity + current equity + cash-flow adjustment |
| `theme_as_of`, `theme_intact` | Current trusted theme condition |
| `turnover_as_of`, `turnover_rate_ratio` | Current turnover observation |
| `data_confidence`, `quality_flags` | Valid source quality; no unknown/missing flags |
| `parent_order_number`, `parent_remaining_quantity`, `parent_as_of` | For child requests: exact parent + broker-verified remaining quantity, at most 5 s |

For amend, the trusted complete duplicate check may exclude only the exact known
parent, not another order in that stock. Current quote and proposed limit both
pass the unchanged entry Risk policy. Active CONTROL is read from PostgreSQL,
canonical hash recomputed, switch checked HEALTHY, runtime APPLIED verified, intent
evidence hash and approval identity checked, and entry TTL retained after approval.
CONTROL/intent/switch rows remain locked during final validation and the bounded
broker call; switch/rollback cannot silently race the send boundary.

Cancel/amend use a separately prepared/confirmed child plan with `--operation`
and `--parent-plan-id`. Amend needs a currently valid approved intent (a fresh
approved intent can authorize a later amendment). Cancel is risk reducing and
gets its own 120-second plan TTL after preparation, so expiration of the original
entry does not prevent cancellation. It checks fresh account/session/quote/parent
remaining facts and current CONTROL; entry daily-loss/theme/duplicate/cash capacity
cannot prohibit risk reduction. A later CONTROL change still blocks the prepared
cancel plan. The original intent approval/evidence lineage must remain intact.

Accepted child requests do not change the parent's status. Reconcile both parent
and child against broker facts. A replacement amendment order is tracked using
the child's number through partial/full fills; parent `AMENDED` is recorded only
when broker history confirms its replacement. Partial cancellations preserve
remaining quantity separately from original and cumulative filled quantities.

## Recovery and idempotency

PostgreSQL tables: `market_os_order_plans`, `market_os_order_attempts`,
`market_os_order_events`. Plans/events reject UPDATE/DELETE at the database level.
Unique intent/account/mode/operation/parent scope prevents changing price/quantity
under another plan. A durable attempt is committed **before** network I/O. There
is one attempt per plan and one use per command ID, including rejected attempts.

Account locks serialize fresh capacity checking and submission. Unresolved
`SUBMITTING`/`UNKNOWN` blocks further account submissions; active orders block
another entry in the same stock. After a process crash, `reconcile` converts an
abandoned reservation into UNKNOWN; it never replays the POST.

`history` returns `{account_ref, mode: "live", trade_day_kst: "YYYY-MM-DD",
observed_at, complete: True, rows: [...]}` after complete authenticated pagination
for the plan's actual trade day. Rows are **normalized order-level cumulative
facts** using the repository's `kt00007` field names: `ord_no`, `stk_cd`, `ord_qty`,
`ord_uv`, `cntr_qty`, `ord_remnq`, `acpt_tp`, `mdfy_cncl`, `io_tp_nm`, `ord_tm`, `ori_ord`.
Documented mappings must normalize accepted/rejected/confirmed and cancel/amend
codes to `접수`/`거부`/`확인`, `취소`/`정정`, `매수`. Unmapped codes or per-fill rows
must remain unknown. Do not assume a per-fill `cntr_qty` is a cumulative total.
Ambiguous duplicate rows, missing order numbers or incomplete pagination cannot
establish rejection, cancellation or fill. Cumulative fills/remaining quantities
cannot regress; duplicate event keys are ignored; terminal orders cannot reopen.

Lost ACK with no known number stays UNKNOWN even if a similar order appears.
An operator may explicitly identify a broker number and confirm the exact plan:

```sh
bash order_admin.sh reconcile <plan-id> --broker-order-number <private-number> \
  --confirm-plan <plan-id>
```

Binding requires the complete authenticated history to prove exact stock,
quantity, limit, side/operation/parent and the narrow submitted-time window.
There is no automatic fuzzy match or no-order inference. If these facts cannot
be proved, the order remains blocked for recovery. Broker numbers are not printed.
Kiwoom's documented request has no client idempotency key; local durability prevents
resends but cannot promise broker-level exactly-once delivery after a lost ACK.

Official Kiwoom API IDs/endpoint:
https://openapi.kiwoom.com/m/guide/apiguide?dummyVal=0
`kt10000` BUY, `kt10002` AMEND, `kt10003` CANCEL at `/api/dostk/ordr`.

## Validation

```sh
python -m unittest discover -s tests -p 'test_market_os*.py'
```

CI supplies `MARKET_OS_TEST_DATABASE_URL` and runs the real PostgreSQL lifecycle,
immutability, concurrency, unknown/restart, duplicate-event, partial-fill and
child-lineage tests. Without that variable, DB tests explicitly skip. All broker
tests use isolated transports; no real order is created by tests or publishing.
