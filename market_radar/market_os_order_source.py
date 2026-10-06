"""Trusted DB/credential boundary for operator execution. No UI-supplied live facts.

The built-in source intentionally blocks on unverified daily-loss/session/capacity.
A deployment may provide a server-owned facts module implementing collect() and
history(). It must use authenticated broker/exchange feeds, never AI/packet JSON.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import os

from market_os_order_plan import OrderError
from market_os_risk import observation_facts


def credential_account_ref(env):
    key = env.get('APP_KEY')
    if env.get('KIWOOM_MODE') != 'real' or not key or not env.get('APP_SECRET'):
        raise OrderError('REAL_ACCOUNT_CREDENTIALS_REQUIRED')
    # Opaque credential-profile binding; no raw account number or app key is exported.
    return 'acct-' + hashlib.sha256(('kiwoom-real|'+key).encode()).hexdigest()[:32]


class DatabaseSource:
    def __init__(self, env=None):
        self.env = os.environ if env is None else env
        name = self.env.get('MARKET_OS_ORDER_FACTS_MODULE','')
        self.facts_module = importlib.import_module(name) if name else None

    @contextmanager
    def guard(self, connection, intent_id, account_ref, mode, parent, *, request):
        if mode == 'live' and account_ref != credential_account_ref(self.env):
            raise OrderError('ACCOUNT_CREDENTIAL_BINDING_MISMATCH')
        # Lock canonical selector, switch state and approval against mutation until send completes.
        # Existing CONTROL switch/rollback SQL needs UPDATE locks on these same rows.
        with connection.transaction():
            c = connection.execute('SELECT * FROM market_os_control_state WHERE id=1 FOR SHARE').fetchone()
            if not c:
                raise OrderError('CONTROL_STATE_MISSING')
            sw = connection.execute('''SELECT * FROM market_os_switch_transactions
                WHERE switch_transaction_id=%s FOR SHARE''',(c['switch_transaction_id'],)).fetchone()
            i = connection.execute('''SELECT * FROM market_os_execution_intents
                WHERE intent_id=%s FOR SHARE''',(intent_id,)).fetchone()
            if not i:
                raise OrderError('INTENT_NOT_FOUND')
            if not sw or sw['candidate_hash'] != c['control_hash']:
                raise OrderError('CONTROL_SWITCH_HASH_MISMATCH')
            from flow_store import desk_payload
            from market_os_readonly import enrich_payload
            payload = enrich_payload(desk_payload(include_tracking=False))
            meta = payload.get('market_os_control') or {}
            ctrl = dict(c)
            ctrl['apply_status'] = (meta.get('apply_status') if meta.get('control_hash') == c['control_hash']
                                    and meta.get('switch_transaction_id') == c['switch_transaction_id'] else 'MISMATCH')
            candidate = next((x for x in payload.get('market_os_watchlist',[]) if x.get('code')==i['stock_code']),{})
            row = next((x for x in payload.get('rows',[]) if x.get('code')==i['stock_code']),{})
            facts = observation_facts(row)
            if self.facts_module:
                # This is a Python deployment integration, never a JSON/HTTP fact override.
                trusted = self.facts_module.collect(stock_code=i['stock_code'], account_ref=account_ref,
                         mode=mode, limit_context={**request,
                           'parent_order_number':parent['attempt']['broker_order_number'] if parent else None},
                         env=self.env)
                if (trusted.get('account_ref') != account_ref or trusted.get('mode') != mode
                        or not isinstance(trusted.get('facts'),dict)):
                    raise OrderError('TRUSTED_FACT_SOURCE_BINDING_MISMATCH')
                facts.update(trusted['facts'])
            yield {'intent':dict(i),'control':ctrl,'switch_state':sw['state'],
                   'candidate':candidate,'facts':facts,'account_ref':account_ref,
                   'broker_mode':'real' if mode=='live' else mode,
                   'observed_at':payload.get('sample_time')}

    def history(self, plan):
        if plan.mode != 'live' or plan.account_ref != credential_account_ref(self.env):
            raise OrderError('RECOVERY_ACCOUNT_BINDING_MISMATCH')
        if self.facts_module:
            return self.facts_module.history(plan=plan,env=self.env)
        raise OrderError('TRUSTED_COMPLETE_HISTORY_SOURCE_REQUIRED')


def live_broker(env):
    # Auth is read-only and has no order side effects. No credentials are printed/persisted.
    from market_os_readonly import Client
    from market_os_broker import KiwoomBroker
    ref = credential_account_ref(env)
    client = Client(env=env)
    client.read('kt00017',{})
    return KiwoomBroker(client.token,ref,env=env)
