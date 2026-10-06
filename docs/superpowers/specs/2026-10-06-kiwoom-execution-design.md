# Explicit Kiwoom execution v2.4

Base: PR #3 head c7e36d9803d7dd5bea9531dbf59a25d9d8c55880.

Intent approval remains metadata only. A separate operator command creates a frozen,
hash-addressed OrderPlan with explicit quantity, limit price, stop, execution mode
and opaque account binding. An additional execute command confirms that exact hash.
Dry-run and paper use no Kiwoom writes; live requires its own default-off switch.
No scheduler, HTTP route, AI chart or NAVER action invokes execution.

PostgreSQL stores immutable plans, command attempts and append-only events. Unique
intent/mode/account plans and command keys prevent retries under new request IDs.
An account advisory lock serializes capacity checks and submission; CONTROL and
intent rows remain locked during final validation and the bounded broker call.
A committed SUBMITTING reservation precedes network I/O. Crash/timeout means
UNKNOWN, never an automatic resend. Unknown orders block new account submissions.
Recovery queries complete broker history; an unidentified result remains UNKNOWN.

Fresh trusted source code supplies quotes, Risk facts, account permission and
orderable capacity. JSON/AI/UI input cannot supply live facts. The repository's
current daily-loss/session facts are incomplete; default source fails closed.
CONTROL identity/hash, HEALTHY switch, runtime apply, intent evidence/hash and TTL
are checked again at send time. Risk is evaluated against the requested limit and
stop. Quantity is explicit and bounded by verified orderable capacity.

Cancel/amend are separately confirmed immutable child plans, linked to a known
broker parent number. No parent state is changed merely because a child request
was accepted. Cumulative fill updates are monotonic and bounded; duplicate event
keys are ignored, terminal state regressions blocked. Broker numbers stay in the
private journal; inspect returns opaque plan IDs/status/quantities only. No
credentials, raw broker response or account number enters audit/UI/LLM payloads.

Validation: pure policy/adaptor tests, real PostgreSQL integration tests in CI,
existing Market OS and compatibility suites. No real broker requests in tests.
