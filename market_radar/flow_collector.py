"""Reuse existing Kiwoom collector with consistent SOR details and observed money windows.
No new brokerage permission, no orders, no credential edits.
"""
from datetime import datetime,timezone
import time
import kiwoom_feed as base
from flow_core import quote, num
from flow_store import schema, save_batch

_original_fetch=base.fetch_all
_original_norm_tv=base.norm_tv
_original_norm_cap=base.norm_cap
current_rank=[]
current_trade=[]
raw_quotes={}


def code_of(r):
    return str(r.get('stk_cd') or '').removesuffix('_AL').removesuffix('_NX')


def fetch(api_id,path,body,key,max_pages=10):
    global current_rank,current_trade
    rows=_original_fetch(api_id,path,body,key,max_pages)
    if api_id=='ka00198':current_rank=rows[:100]
    elif api_id=='ka10032':current_trade=rows[:100]
    return rows


def detail_map(_requested):
    global raw_quotes
    raw_quotes={};out={}
    codes=list(dict.fromkeys(code_of(r) for r in current_rank+current_trade if code_of(r)))
    for i in range(0,len(codes),20):
        rows=_original_fetch('ka10095','/api/dostk/stkinfo',
              {'stk_cd':'|'.join(c+'_AL' for c in codes[i:i+20])},'atn_stk_infr',2)
        received=datetime.now(timezone.utc)
        for r in rows:
            code=code_of(r)
            raw_quotes[code]={'response':r,'received_at':received.isoformat()}
            price=num(r.get('cur_prc'));change=num(r.get('flu_rt'))
            checked=quote(r,received,code) or {}
            out[code]={'name':r.get('stk_nm'),'price':float(abs(price)) if price is not None else None,
                       'change':float(change) if change is not None else None,
                       'trade_value':checked.get('turnover_krw'),
                       'market_cap':checked.get('cap_krw')}
        time.sleep(.25)
    return out


def main():
    base.fetch_all=fetch
    base.detail_map=detail_map
    # Stock snapshots now prefer the validated ka10095 SOR detail value in kiwoom_feed.
    # Keep the legacy normalizers only as fallbacks for endpoints that do not return
    # the detail fields needed for cross-validation (for example official-sector rows).
    base.norm_tv=_original_norm_tv
    base.norm_cap=_original_norm_cap
    base.schema();schema()
    print('Flow collector: SOR details; validated money scales; 30s target',flush=True)
    while True:
        started=time.monotonic()
        try:
            if not base.APPKEY or not base.SECRET:
                base.set_status('WAITING_FOR_CREDENTIALS','기존 Kiwoom 인증 설정 대기')
            else:
                base.one_cycle()
                ranks={code_of(r):int(base.n(r.get('bigd_rank')) or 0) or None for r in current_rank}
                trades={code_of(r):int(base.n(r.get('now_rank')) or 0) or None for r in current_trade}
                save_batch(datetime.now(timezone.utc),raw_quotes,ranks,trades,base.stock_meta)
        except Exception as exc:
            # Do not print response bodies, tokens, DSNs or arbitrary provider errors.
            try: base.set_status('ERROR','SOR/조회/거래대금 관측 오류',type(exc).__name__)
            except Exception: pass
            print('Flow collector error:',type(exc).__name__,flush=True)
        elapsed=time.monotonic()-started
        time.sleep(max(1,30-elapsed))

if __name__=='__main__':main()
