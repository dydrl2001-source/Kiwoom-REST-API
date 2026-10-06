"""Conservative exact-number recovery; absence or ambiguous history is not rejection."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from market_os_order_plan import advance, OrderError
from market_os_risk import timestamp


def integer(value):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value)):
        return None
    return int(value)


def trade_day(plan):
    return datetime.fromisoformat(plan.prepared_at).astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()


def binding_valid(plan, attempt, row, parent_number=None):
    """Manual exact-number attribution of a lost ACK; never a search/match heuristic."""
    if (str(row.get('stk_cd','')).removeprefix('A') != plan.stock_code
            or integer(row.get('ord_qty')) != plan.quantity):
        return False
    if plan.operation != 'CANCEL' and integer(row.get('ord_uv')) != plan.limit_price:
        return False
    if plan.operation == 'BUY' and row.get('io_tp_nm') not in {'매수','+매수'}:
        return False
    if plan.operation != 'BUY' and (row.get('ori_ord') != parent_number
            or row.get('mdfy_cncl') != ('취소' if plan.operation=='CANCEL' else '정정')):
        return False
    try:
        at = datetime.strptime(trade_day(plan)+' '+str(row['ord_tm']), '%Y-%m-%d %H%M%S').replace(tzinfo=ZoneInfo('Asia/Seoul'))
        submitted = timestamp(attempt['submitted_at'])
        return submitted is not None and -2 <= (at-submitted).total_seconds() <= 20
    except (ValueError,KeyError,TypeError):
        return False


def resolve(attempt, rows):
    number = attempt.get('broker_order_number')
    if not number:
        return None  # Kiwoom has no documented client idempotency key for a lost ACK.
    matches = [r for r in rows if r.get('ord_no') == number]
    if len(matches) != 1:
        return None  # Do not sum duplicate rows or assume per-fill quantities are cumulative.
    r = matches[0]
    if str(r.get('stk_cd', '')).removeprefix('A') != attempt['stock_code']:
        return None
    qty, filled, remaining = (integer(r.get(k)) for k in ('ord_qty','cntr_qty','ord_remnq'))
    if qty != attempt['quantity'] or filled is None or remaining is None or filled + remaining > qty:
        return None
    status = None
    if r.get('acpt_tp') in {'거부', '주문거부'} and filled == remaining == 0:
        status = 'REJECTED'
    elif attempt['operation'] == 'CANCEL':
        if r.get('mdfy_cncl') == '취소' and remaining == 0:
            status = 'CANCELLED'
    elif r.get('mdfy_cncl') == '정정' and remaining == 0 and filled < qty:
        status = 'AMENDED'
    elif r.get('mdfy_cncl') == '취소' and remaining == 0:
        status = 'CANCELLED'
    elif filled == qty and remaining == 0:
        status = 'FILLED'
    elif 0 < filled < qty and 0 < remaining <= qty - filled:
        status = 'PARTIALLY_FILLED'
    elif filled == 0 and 0 < remaining <= qty and r.get('acpt_tp') in {'접수', '확인'}:
        status = 'ACCEPTED'
    if status is None:
        return None
    try:
        return advance(attempt, status, filled, remaining)
    except OrderError:
        return None
