(() => {
  const el = id => document.getElementById(id);
  const money = v => typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('ko-KR') + '원' : '미확인';
  const time = v => v ? new Date(v).toLocaleString('ko-KR', {timeZone:'Asia/Seoul'}) + ' KST' : '미확인';
  const line = (target, value) => { const p = document.createElement('p'); p.textContent = value; target.append(p); };
  async function load(refresh) {
    el('readonly-results').replaceChildren();
    el('readonly-status').textContent = '조회 중…';
    el('readonly-refresh').disabled = true;
    try {
      const url = refresh ? '/api/market-os/readonly-refresh?codes=' + encodeURIComponent(el('readonly-codes').value) : '/api/market-os/readonly-context';
      const r = await fetch(url, {method:refresh?'POST':'GET', headers:{'X-Dashboard-Token':el('token').value}, cache:'no-store'});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || '조회 실패');
      if (!d.fetched_at) { el('readonly-status').textContent = '아직 저장된 연결 결과가 없습니다.'; return; }
      const age = (Date.now() - Date.parse(d.fetched_at))/1000;
      el('readonly-status').textContent = `${d.kiwoom_mode === 'real' ? '실전 계좌 조회' : '모의 또는 모드 미확인'} · 조회 시각: ${time(d.fetched_at)} · ${age>=0 && age<=90 ? '90초 이내 관측' : '오래된 관측 · 위험 판단에 사용 불가'} · 주문 전송 0건`;
      const target = el('readonly-results'), a = d.account || {};
      line(target, `추정 자산 ${money(a.estimated_assets_krw)} · 보유 ${a.position_count ?? '미확인'}종목 · KRX 평가 기준`);
      line(target, `누적 평가손익 ${money(a.unrealized_pl_krw)} · ${a.realized_pl_day || '기준일 미확인'} 실현손익 ${money(a.realized_pl_krw)}`);
      line(target, `D+2 추정예수금 ${money(a.cash_d2_krw)} · 미체결 ${a.unfilled_complete ? a.unfilled_count+'건' : '미확인'}`);
      line(target, '당일 손실률: 미확인 · 검증된 기초자산·입출금 기준 필요 · 실행 위험 게이트 차단 유지');
      for (const [code, context] of Object.entries(d.investor || {})) {
        line(target, `${code} · 수급 기준일 ${context.foreign?.as_of || '미확인'} · 외국인 ${money(context.foreign?.net_buy_krw)} · 기관 ${money(context.institution?.net_buy_krw)} · 장중 매매 신호로 사용하지 않음`);
      }
      if (Object.keys(d.errors || {}).length) line(target, '일부 조회 실패: ' + Object.entries(d.errors).map(([k,v]) => `${k}: ${v}`).join(', '));
    } catch (e) { el('readonly-status').textContent = '연결 결과: ' + e.message; }
    finally { el('readonly-refresh').disabled = false; }
  }
  el('readonly-load').addEventListener('click', () => load(false));
  el('readonly-refresh').addEventListener('click', () => load(true));
})();
