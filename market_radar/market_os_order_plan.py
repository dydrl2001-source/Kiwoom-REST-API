"""Immutable operator order plans. No broker calls or automatic sizing."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re

from market_os_control import control_hash
from market_os_execution import approval_still_valid, canonical_json
from market_os_risk import evaluate as risk_evaluate, fresh, number, timestamp


class OrderError(Exception):
    """Only fixed reason codes may cross the execution/UI boundary."""


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def positive_integer(value):
    return type(value) is int and value > 0


@dataclass(frozen=True)
class OrderPlan:
    intent_id: str
    evidence_hash: str
    approval_at: str
    stock_code: str
    account_ref: str
    mode: str
    operation: str
    quantity: int
    limit_price: int
    stop_price: int
    prepared_at: str
    expires_at: str
    control_hash: str
    switch_transaction_id: str
    parent_plan_id: str | None = None
    schema_version: str = 'kiwoom-order-plan-v1'

    @property
    def plan_id(self):
        return 'op-' + digest(asdict(self))


def build(context, *, quantity, limit_price, stop_price, mode, now=None,
          operation='BUY', parent_plan_id=None):
    now = now or datetime.now(timezone.utc)
    intent = context.get('intent') or {}
    approval = timestamp(intent.get('reviewed_at'))
    expiry = timestamp(intent.get('expires_at'))
    if not approval or not expiry:
        raise OrderError('INTENT_APPROVAL_OR_TTL_MISSING')
    ctrl = context.get('control') or {}
    cancel = operation == 'CANCEL'
    p = OrderPlan(intent_id=intent.get('intent_id'), evidence_hash=intent.get('evidence_hash'),
                  approval_at=approval.isoformat(), stock_code=intent.get('stock_code'),
                  account_ref=context.get('account_ref'), mode=mode, operation=operation,
                  quantity=quantity, limit_price=limit_price, stop_price=stop_price,
                  prepared_at=now.isoformat(),
                  expires_at=(now+timedelta(seconds=120) if cancel else expiry).isoformat(),
                  control_hash=(ctrl if cancel else intent).get('control_hash'),
                  switch_transaction_id=(ctrl if cancel else intent).get('switch_transaction_id'),
                  parent_plan_id=parent_plan_id)
    # Plan creation checks every guard except the separate live switch/execute confirmation.
    validate(p, context, now=now, preparing=True)
    return p


def validate(p, context, *, now=None, confirm=None, env=None, preparing=False):
    now = now or datetime.now(timezone.utc)
    if timestamp(now) is None:
        raise OrderError('CLOCK_TIMEZONE_REQUIRED')
    i = dict(context.get('intent') or {})
    c = dict(context.get('control') or {})
    facts = dict(context.get('facts') or {})
    reasons = []
    if p.schema_version != 'kiwoom-order-plan-v1' or p.mode not in {'dry-run', 'paper', 'live'}:
        reasons.append('PLAN_MODE_OR_VERSION_INVALID')
    if p.operation not in {'BUY', 'CANCEL', 'AMEND'} or (p.operation == 'BUY') != (p.parent_plan_id is None):
        reasons.append('PLAN_LINEAGE_INVALID')
    if not re.fullmatch(r'[0-9]{6}', str(p.stock_code)):
        reasons.append('STOCK_CODE_INVALID')
    if not isinstance(p.account_ref, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{3,100}', p.account_ref):
        reasons.append('OPAQUE_ACCOUNT_REF_REQUIRED')
    if i.get('status') != 'HUMAN_APPROVED_INTENT' or not i.get('reviewed_by'):
        reasons.append('INTENT_NOT_APPROVED')
    evidence = i.get('evidence') or {}
    if (digest(evidence) != p.evidence_hash or i.get('evidence_hash') != p.evidence_hash
            or evidence.get('stock_code') != p.stock_code or i.get('stock_code') != p.stock_code
            or i.get('intent_id') != p.intent_id):
        reasons.append('INTENT_EVIDENCE_MISMATCH')
    ec = evidence.get('control') or {}
    if ec.get('control_hash') != i.get('control_hash') or ec.get('switch_transaction_id') != i.get('switch_transaction_id'):
        reasons.append('EVIDENCE_CONTROL_MISMATCH')
    approval, expiry = timestamp(i.get('reviewed_at')), timestamp(i.get('expires_at'))
    if p.operation != 'CANCEL' and timestamp(evidence.get('expires_at')) != expiry:
        reasons.append('INTENT_EVIDENCE_TTL_MISMATCH')
    if (not approval or approval.isoformat() != p.approval_at or approval > now
            or not expiry or (p.operation != 'CANCEL' and expiry.isoformat() != p.expires_at)):
        reasons.append('APPROVAL_IDENTITY_OR_TTL_CHANGED')
    i['expires_at'] = expiry
    if p.operation != 'CANCEL':
        reasons += approval_still_valid(i, c, context.get('switch_state'), now)['reason_codes']
    else:
        # A separately confirmed cancellation cannot add exposure. Its own short TTL
        # allows risk reduction after entry approval expires; stale prepared CONTROL still blocks.
        prepared, cancel_expiry = timestamp(p.prepared_at), timestamp(p.expires_at)
        if (not prepared or not cancel_expiry or not prepared <= now < cancel_expiry
                or (cancel_expiry-prepared).total_seconds() != 120):
            reasons.append('CANCEL_PLAN_EXPIRED_OR_INVALID')
        if context.get('switch_state') != 'HEALTHY':
            reasons.append('CONTROL_NOT_HEALTHY')
    if c.get('control_hash') != p.control_hash or control_hash(c) != p.control_hash:
        reasons.append('CONTROL_HASH_INVALID_OR_CHANGED')
    if c.get('switch_transaction_id') != p.switch_transaction_id:
        reasons.append('CONTROL_TRANSACTION_CHANGED')
    if c.get('mode') != 'RULESET' or c.get('apply_status') != 'APPLIED':
        reasons.append('CONTROL_RUNTIME_NOT_APPLIED')
    if not fresh(context.get('observed_at'), now, 90):
        reasons.append('STALE_CONTEXT')
    if context.get('account_ref') != p.account_ref:
        reasons.append('ACCOUNT_BINDING_CHANGED')
    if p.mode == 'live' and context.get('broker_mode') != 'real':
        reasons.append('LIVE_ACCOUNT_MODE_REQUIRED')
    if not positive_integer(p.quantity):
        reasons.append('QUANTITY_INVALID')
    if not positive_integer(p.limit_price) or not positive_integer(p.stop_price):
        reasons.append('LIMIT_OR_STOP_INVALID')
    tick = facts.get('tick_size_krw')
    if not positive_integer(tick) or not positive_integer(p.limit_price) or p.limit_price % tick:
        reasons.append('PRICE_TICK_INVALID')
    if not fresh(facts.get('price_as_of'), now, 5):
        reasons.append('STALE_OR_FUTURE_QUOTE')
    if not fresh(facts.get('account_as_of'), now, 30) or facts.get('executable') is not True:
        reasons.append('ACCOUNT_NOT_EXECUTABLE_OR_STALE')
    capacity = facts.get('orderable_quantity')
    if p.operation != 'CANCEL' and (not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 0
            or not positive_integer(p.quantity) or p.quantity > capacity):
        reasons.append('ORDERABLE_CAPACITY_EXCEEDED_OR_UNKNOWN')
    candidate = dict(context.get('candidate') or {})
    if p.operation != 'CANCEL' and candidate.get('code') != p.stock_code:
        reasons.append('CURRENT_CANDIDATE_IDENTITY_MISMATCH')
    # Fresh current price AND the requested limit must respect entry Risk policy.
    px = number(facts.get('price_krw'))
    requested = number(p.limit_price)
    facts.update(reference_price_krw=evidence.get('reference_price_krw'),
                 stop_price_krw=p.stop_price,
                 price_krw=max(px, requested) if px is not None and requested is not None else None)
    gate = risk_evaluate(candidate, facts, now, mode='manual_confirm')
    gate['reason_codes'] += risk_evaluate(candidate,{**facts,'price_krw':px},now,mode='manual_confirm')['reason_codes']
    if p.operation == 'CANCEL':
        gate = {'policy_version':'execution-cancel-risk-v1','reason_codes':[]}
        if (facts.get('session_open') is not True or facts.get('is_trading_day') is not True
                or not fresh(facts.get('session_as_of'),now,30)):
            gate['reason_codes'].append('CANCEL_SESSION_CLOSED_OR_UNKNOWN')
    reasons += gate['reason_codes']
    if not preparing:
        if confirm != p.plan_id:
            reasons.append('EXPLICIT_PLAN_EXECUTION_CONFIRMATION_REQUIRED')
        if p.mode == 'live' and (env or {}).get('MARKET_OS_LIVE_ORDERS_ENABLED') != '1':
            reasons.append('LIVE_ORDERS_DISABLED')
    if reasons:
        raise OrderError(','.join(dict.fromkeys(reasons)))
    return {'policy_version': gate['policy_version'], 'reason_codes': [], 'plan_id': p.plan_id}


TERMINAL = {'FILLED', 'CANCELLED', 'REJECTED', 'AMENDED', 'DRY_RUN'}
BROKER_STATES = {'ACCEPTED', 'REJECTED', 'PARTIALLY_FILLED', 'FILLED', 'CANCELLED', 'AMENDED', 'UNKNOWN'}


def advance(current, status, filled_quantity, remaining_quantity=None):
    """Apply trusted cumulative broker facts, never delta fill arithmetic."""
    old, prev, qty = current['status'], current['filled_quantity'], current['quantity']
    if status not in BROKER_STATES or type(filled_quantity) is not int or not prev <= filled_quantity <= qty:
        raise OrderError('BROKER_EVENT_INVALID_OR_FILL_REGRESSION')
    if old in TERMINAL and (status != old or filled_quantity != prev):
        raise OrderError('TERMINAL_ORDER_REGRESSION')
    if status == 'FILLED' and filled_quantity != qty:
        raise OrderError('FULL_FILL_QUANTITY_MISMATCH')
    if status == 'PARTIALLY_FILLED' and not 0 < filled_quantity < qty:
        raise OrderError('PARTIAL_FILL_QUANTITY_INVALID')
    if status == 'REJECTED' and filled_quantity:
        raise OrderError('REJECTED_ORDER_HAS_FILL')
    if old == 'PARTIALLY_FILLED' and status in {'ACCEPTED', 'REJECTED'}:
        raise OrderError('PARTIAL_ORDER_REGRESSION')
    remaining = (0 if status in TERMINAL else qty-filled_quantity) if remaining_quantity is None else remaining_quantity
    if type(remaining) is not int or not 0 <= remaining <= qty-filled_quantity:
        raise OrderError('BROKER_REMAINING_QUANTITY_INVALID')
    previous_remaining = current.get('remaining_quantity',qty-prev)
    if remaining > previous_remaining or (old in TERMINAL and remaining != previous_remaining):
        raise OrderError('BROKER_REMAINING_QUANTITY_REGRESSION')
    if status in TERMINAL and remaining:
        raise OrderError('TERMINAL_ORDER_HAS_REMAINING_QUANTITY')
    return {**current, 'status': status, 'filled_quantity': filled_quantity,'remaining_quantity':remaining}
