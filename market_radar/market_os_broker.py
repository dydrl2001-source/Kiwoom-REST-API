"""One-shot Kiwoom writes, deliberately independent of the retrying CLI client."""
from dataclasses import dataclass
import re
import os

from market_os_order_plan import OrderError


@dataclass(frozen=True)
class BrokerResult:
    status: str
    order_number: str | None = None
    reason: str = ''


class DryRunBroker:
    mode = 'dry-run'

    def submit(self, plan, parent_number, *, execution_confirm=None):
        if plan.mode != self.mode or execution_confirm != plan.plan_id:
            raise OrderError('DRY_RUN_MODE_OR_CONFIRMATION_MISMATCH')
        return BrokerResult('DRY_RUN', reason='NO_BROKER_CALL')


class PaperBroker:
    mode = 'paper'

    def submit(self, plan, parent_number, *, execution_confirm=None):
        if plan.mode != self.mode or execution_confirm != plan.plan_id:
            raise OrderError('PAPER_MODE_OR_CONFIRMATION_MISMATCH')
        return BrokerResult('ACCEPTED', 'paper-' + plan.plan_id[3:])


class KiwoomBroker:
    mode = 'live'

    def __init__(self, token, account_ref, *, transport=None, env=None):
        # Token/account binding comes from trusted operator credential code, never a plan/AI.
        if not isinstance(token, str) or not token or not account_ref:
            raise OrderError('BROKER_CREDENTIAL_BINDING_MISSING')
        self._token, self.account_ref = token, account_ref
        self._env = os.environ if env is None else env
        if transport is None:
            import requests
            transport = requests.Session()
            transport.trust_env = False
            # No auth retry, automatic POST retry, redirects or proxy-supplied host.
            from requests.adapters import HTTPAdapter
            transport.mount('https://', HTTPAdapter(max_retries=0))
        self._http = transport

    def submit(self, plan, parent_number, *, execution_confirm=None):
        if self._env.get('MARKET_OS_LIVE_ORDERS_ENABLED') != '1' or execution_confirm != plan.plan_id:
            raise OrderError('LIVE_OFF_OR_EXPLICIT_CONFIRMATION_MISSING')
        if plan.mode != 'live' or plan.account_ref != self.account_ref:
            raise OrderError('BROKER_MODE_OR_ACCOUNT_BINDING_MISMATCH')
        body = {'dmst_stex_tp':'KRX', 'stk_cd':plan.stock_code}
        if plan.operation == 'BUY':
            api = 'kt10000'
            body.update(ord_qty=str(plan.quantity), ord_uv=str(plan.limit_price), trde_tp='0', cond_uv='')
        elif plan.operation in {'AMEND', 'CANCEL'}:
            if not re.fullmatch(r'[0-9]{1,20}', str(parent_number)):
                raise OrderError('BROKER_PARENT_NUMBER_REQUIRED')
            body['orig_ord_no'] = parent_number
            if plan.operation == 'AMEND':
                api = 'kt10002'
                body.update(mdfy_qty=str(plan.quantity), mdfy_uv=str(plan.limit_price), mdfy_cond_uv='')
            else:
                api = 'kt10003'
                body['cncl_qty'] = str(plan.quantity)
        else:
            raise OrderError('BROKER_OPERATION_INVALID')
        try:
            r = self._http.post('https://api.kiwoom.com/api/dostk/ordr', json=body,
                                headers={'authorization':'Bearer '+self._token, 'api-id':api,
                                         'content-type':'application/json;charset=UTF-8'},
                                timeout=(3, 8), allow_redirects=False)
            if r.status_code != 200:
                return BrokerResult('UNKNOWN', reason='BROKER_HTTP_UNCERTAIN')
            d = r.json()
            if not isinstance(d, dict) or type(d.get('return_code')) not in {int, str}:
                return BrokerResult('UNKNOWN', reason='BROKER_RESPONSE_UNCERTAIN')
            code = str(d['return_code'])
            if not re.fullmatch(r'-?[0-9]+', code):
                return BrokerResult('UNKNOWN', reason='BROKER_RESPONSE_UNCERTAIN')
            if int(code) != 0:
                return BrokerResult('REJECTED', reason='BROKER_REJECTED')
            order = d.get('ord_no')
            if not re.fullmatch(r'[0-9]{1,20}', str(order)):
                return BrokerResult('UNKNOWN', reason='BROKER_ORDER_NUMBER_MISSING')
            return BrokerResult('ACCEPTED', str(order))
        except Exception:
            # A timeout, decoding failure or local interruption may follow acceptance.
            # Do not include raw response/exception text in audit or retry the POST.
            return BrokerResult('UNKNOWN', reason='BROKER_TRANSPORT_UNCERTAIN')
