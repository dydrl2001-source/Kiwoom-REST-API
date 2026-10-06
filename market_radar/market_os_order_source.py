"""Trusted DB/credential boundary for operator execution. No UI-supplied live facts.

The built-in source intentionally blocks on unverified daily-loss/session/capacity.
A deployment may provide a server-owned facts module implementing collect() and
history(). It must use authenticated broker/exchange feeds, never AI/packet JSON.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import importlib
import os
import re

from market_os_order_plan import OrderError
from market_os_risk import observation_facts


def credential_account_ref(env, *, client=None):
    key = env.get('APP_KEY')
    if env.get('KIWOOM_MODE') != 'real' or not key or not env.get('APP_SECRET'):
        raise OrderError('REAL_ACCOUNT_CREDENTIALS_REQUIRED')
    secret=env.get('MARKET_OS_ACCOUNT_BINDING_SECRET','')
    if len(secret)<32:
        raise OrderError('STABLE_PRIVATE_ACCOUNT_BINDING_SECRET_REQUIRED')
    if client is None:
        from market_os_readonly import Client
        client=Client(env=env)
    client.read('kt00017',{})  # Authenticate using a permitted read only.
    # Additional account identity read belongs only to this private execution source.
    # The public read-only adapter's allowlist/identifier stripping stays unchanged.
    d,_=client._post('/api/dostk/acnt',{},
                    {'authorization':'Bearer '+client.token,'api-id':'ka00001'})
    account=d.get('acctNo')
    if not isinstance(account,str) or not re.fullmatch(r'[0-9]{8,20}',account):
        raise OrderError('BROKER_SINGLE_ACCOUNT_IDENTITY_UNVERIFIED')
    # The same actual account shares one lock even across app keys; HMAC prevents
    # reversing a low-entropy account number from the persisted alias.
    return 'acct-' + hmac.new(secret.encode(),('kiwoom-real|'+account).encode(),hashlib.sha256).hexdigest()


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
            if mode=='live':
                fingerprint=hashlib.sha256(('binding-v1|'+self.env['MARKET_OS_ACCOUNT_BINDING_SECRET']).encode()).hexdigest()
                connection.execute('''INSERT INTO market_os_order_binding_config(id,secret_fingerprint)
                    VALUES(1,%s) ON CONFLICT(id) DO NOTHING''',(fingerprint,))
                config=connection.execute('SELECT secret_fingerprint FROM market_os_order_binding_config WHERE id=1 FOR SHARE').fetchone()
                if config['secret_fingerprint'] != fingerprint:
                    raise OrderError('ACCOUNT_BINDING_SECRET_CHANGED_MIGRATION_REQUIRED')
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
    client = Client(env=env)
    ref = credential_account_ref(env,client=client)
    return KiwoomBroker(client.token,ref,env=env)
