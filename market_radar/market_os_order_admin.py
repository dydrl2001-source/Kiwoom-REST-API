"""Manual-only CLI. It has no web route, worker, cron or approval-trigger hook."""
import argparse
import json
import os
import sys

from market_os_order_plan import OrderError


def parser():
    p = argparse.ArgumentParser(description='Explicit Kiwoom order plans (live default OFF)')
    commands = p.add_subparsers(dest='command',required=True)
    commands.add_parser('init-journal')
    commands.add_parser('account-ref')
    prepare = commands.add_parser('prepare')
    prepare.add_argument('intent_id')
    prepare.add_argument('--account-ref',required=True)
    prepare.add_argument('--mode',choices=['dry-run','paper','live'],required=True)
    prepare.add_argument('--quantity',type=int,required=True)
    prepare.add_argument('--limit-price',type=int,required=True)
    prepare.add_argument('--stop-price',type=int,required=True)
    prepare.add_argument('--operation',choices=['BUY','CANCEL','AMEND'],default='BUY')
    prepare.add_argument('--parent-plan-id')
    prepare.add_argument('--confirm',action='store_true',required=True)
    for command in ('inspect','execute','reconcile','paper-event'):
        sub = commands.add_parser(command)
        sub.add_argument('plan_id')
        if command == 'execute':
            sub.add_argument('--command-id',required=True)
            sub.add_argument('--confirm-plan',required=True)
        if command == 'reconcile':
            sub.add_argument('--broker-order-number')
            sub.add_argument('--confirm-plan')
        if command == 'paper-event':
            sub.add_argument('--status',choices=['PARTIALLY_FILLED','FILLED','CANCELLED','AMENDED','REJECTED'],required=True)
            sub.add_argument('--filled-quantity',type=int,required=True)
            sub.add_argument('--event-key',required=True)
            sub.add_argument('--confirm-plan',required=True)
    return p


def main(argv=None, env=None):
    env = os.environ if env is None else env
    args = parser().parse_args(argv)
    try:
        from market_os_order_source import DatabaseSource, live_broker, credential_account_ref
        if args.command == 'account-ref':
            print(json.dumps({'account_ref':credential_account_ref(env)}))
            return 0
        from market_os_order_store import Store
        store = Store(env.get('DATABASE_URL',''))
        if args.command == 'init-journal':
            store.ensure_schema()
            print('{"journal_initialized":true,"orders_sent":0}')
            return 0
        if args.command == 'inspect':
            print(json.dumps(store.public(store.load(args.plan_id))))
            return 0
        plan = store.load(args.plan_id) if args.command != 'prepare' else None
        mode = plan.mode if plan else args.mode
        # Fail before authentication for an unconfirmed/disabled live execute command.
        if args.command == 'execute' and (args.confirm_plan != plan.plan_id
                or (mode=='live' and env.get('MARKET_OS_LIVE_ORDERS_ENABLED') != '1')):
            raise OrderError('LIVE_OFF_OR_EXPLICIT_CONFIRMATION_MISSING')
        from market_os_broker import PaperBroker, DryRunBroker
        from market_os_orders import Executor
        # Preparing/recovering plans never constructs a mutating broker transport.
        broker = live_broker(env) if mode=='live' and args.command=='execute' else (
            PaperBroker() if mode=='paper' else DryRunBroker())
        if mode=='live' and args.command!='execute':
            class NoWriteBroker:
                mode = 'live'
                def submit(self,*args): raise OrderError('PREPARE_RECOVERY_HAS_NO_BROKER')
            broker = NoWriteBroker()
        executor = Executor(store,DatabaseSource(env),broker,env=env)
        if args.command == 'prepare':
            plan = executor.prepare(args.intent_id,args.account_ref,args.mode,quantity=args.quantity,
                    limit_price=args.limit_price,stop_price=args.stop_price,operation=args.operation,
                    parent_plan_id=args.parent_plan_id)
            out = store.public(plan)
        elif args.command == 'execute':
            out = executor.execute(args.plan_id,args.command_id,confirm=args.confirm_plan)
        elif args.command == 'reconcile':
            out = executor.reconcile(args.plan_id,broker_order_number=args.broker_order_number,
                                     confirm=args.confirm_plan)
        else:
            out = executor.paper_event(args.plan_id,status=args.status,filled_quantity=args.filled_quantity,
                                       event_key=args.event_key,confirm=args.confirm_plan)
        print(json.dumps(out))
        return 0
    except OrderError as exc:
        print(json.dumps({'error':str(exc)}),file=sys.stderr)
        return 2
    except Exception:
        # Never propagate connection URLs, credentials, private broker bodies or SQL params.
        print('{"error":"EXECUTION_INFRASTRUCTURE_ERROR_RECONCILE_BEFORE_RETRY"}',file=sys.stderr)
        return 2


if __name__ == '__main__': sys.exit(main())
