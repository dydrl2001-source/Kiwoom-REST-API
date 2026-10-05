(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, text) => {const n=document.createElement(tag); if(text!=null)n.textContent=String(text);return n;};
  const link = (label, url) => {
    const a=el('a',label);
    try {const u=new URL(url);if(['http:','https:'].includes(u.protocol)&&!u.username&&!u.password){a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';}} catch (_) {}
    return a;
  };
  const riskLabels={
    STALE_OR_MISSING_PRICE_AS_OF:'가격 자료가 없거나 오래됨',STALE_OR_MISSING_ACCOUNT_AS_OF:'최신 계좌 확인 필요',
    STALE_OR_MISSING_SESSION_AS_OF:'시장 운영 상태 확인 필요',STALE_OR_MISSING_DUPLICATE_AS_OF:'중복주문 확인 필요',
    STALE_OR_MISSING_THEME_AS_OF:'테마 유지 확인 필요',STALE_OR_MISSING_TURNOVER_AS_OF:'거래대금 시각 확인 필요',
    ORDER_WINDOW_CLOSED_OR_UNKNOWN:'주문 가능시간·거래일 미확인',ENTRY_PRICE_UNKNOWN:'진입 기준가 미확인',
    STOP_INVALID:'손절 기준 미확인',STOP_TOO_WIDE:'손절폭 초과',DAILY_LOSS_UNKNOWN:'일일 손실 정보 미확인',
    DAILY_LOSS_LIMIT:'일일 손실한도 도달',THEME_EXIT_OR_UNKNOWN:'테마 이탈 또는 미확인',
    DATA_CONFIDENCE_LOW_OR_UNKNOWN:'데이터 신뢰도 미확인',DUPLICATE_ORDER_OR_UNKNOWN:'중복주문 여부 미확인',
    CHASE_LIMIT:'추격 허용가 초과',TURNOVER_COLLAPSE_OR_UNKNOWN:'거래대금 급감 또는 미확인',
    SOURCE_QUALITY_UNVERIFIED:'원천 자료 품질 확인 필요',RULE_TRIGGER_NOT_READY:'규칙상 진입 구조 미충족',
    MARKET_STANCE_BLOCKED:'시장 상태가 검토 조건에 맞지 않음',RULE_RISK_OR_CATALYST_BLOCK:'위험·재료 검증 조건 미충족',
    LIVE_AUTO_FORBIDDEN:'자동 주문 금지'};
  const kst=value=>{const d=new Date(value);return Number.isNaN(d.getTime())?'미확인':d.toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})+' KST';};
  async function api(path,method='GET') {
    const r=await fetch(path,{method,headers:{'X-Dashboard-Token':$('token').value},cache:'no-store'});
    if(!r.ok)throw new Error(r.status===401||r.status===403?'토큰을 확인해 주세요.':'자료가 아직 준비되지 않았습니다.');
    return r.json();
  }
  function show(packet,status,advice) {
    const box=$('decision');box.replaceChildren(el('h2','판단 패킷 · '+status));
    if(!packet){box.append(el('p','14:30–14:40 KST의 신선한 후보 자료를 기다립니다.'));return;}
    box.append(el('p','시장 상태 '+packet.market_stance+' · 기준일 '+packet.budget_day_kst));
    box.append(el('p','생성 '+kst(packet.generated_at)+' · 시장 자료 '+kst(packet.market_data_as_of)));
    if(advice) {const a=el('article');a.append(el('h3','AI 참고 의견 · 실행 권한 없음'),el('p',advice.summary));
      for(const note of advice.candidate_notes||[])a.append(el('p',note.code+' · '+note.note));
      for(const s of advice.uncertainties||[])a.append(el('p','미확인: '+s));box.append(a);}
    for(const c of packet.candidates||[]) {
      const a=el('article');a.append(el('h3',c.name+' · '+c.code+' · '+c.watch_tier));
      a.append(el('p',`Radar ${c.radar} / Theme ${c.theme} / Setup ${c.setup} / Catalyst ${c.catalyst} / Trigger ${c.trigger}`));
      a.append(el('p','가격 기준 '+kst(c.price_as_of)+' · 외국인/기관 수급 미연결'));
      const risk=el('p','실행 검토: '+(c.execution_risk_gate.status==='BLOCKED'?'차단':'사람 확인 필요')+' · '+c.execution_risk_gate.reason_codes.map(r=>riskLabels[r]||r).join(' / '));risk.className='risk';a.append(risk);
      a.append(link('네이버 증권에서 확인',c.naver_search_context.finance_url),el('span',' · '),link('네이버 검색 열기',c.naver_search_context.search_url));
      const b=el('button','이 종목 검색어 선택');b.addEventListener('click',()=>{$('query').value=c.naver_search_context.query;$('query').focus();});a.append(el('span',' '),b);box.append(a);
    }
    const detail=el('details');detail.append(el('summary','압축 JSON 확인'),el('pre',JSON.stringify(packet,null,2)));box.append(detail);
  }
  $('load').addEventListener('click',async()=>{try{const d=await api('/api/market-os/daily-decision');show(d.daily.packet,d.daily.status,d.daily.advice);$('audit').textContent=JSON.stringify(d.api_attempts,null,2);$('status').textContent='저장 시각을 확인하세요. 과거 패킷은 현재 실행 판단에 사용할 수 없습니다.';}catch(e){$('status').textContent=e.message;}});
  $('preview').addEventListener('click',async()=>{try{const p=await api('/api/market-os/decision-preview');show(p,'현재 규칙 미리보기');$('status').textContent='미리보기 완료 · 저장/AI 호출 없음';}catch(e){$('status').textContent=e.message;}});
  let expires;
  $('query').addEventListener('input',()=>{$('search-results').replaceChildren();});
  $('search').addEventListener('click',async()=>{
    const box=$('search-results');clearTimeout(expires);box.replaceChildren(el('p','검색 중…'));$('search').disabled=true;
    try{
      const q=new URLSearchParams({query:$('query').value,kind:$('kind').value});
      const d=await api('/api/market-os/naver-search?'+q,'POST');box.replaceChildren(el('h3','네이버 검색결과'));
      if(d.status!=='OK'){
        const notices={DISABLED:'네이버 공식 API 검색이 아직 꺼져 있습니다. 등록과 설정 후 사용할 수 있습니다.',NAVER_NOT_CONFIGURED:'네이버 API 인증 정보가 아직 설정되지 않았습니다.',DAILY_BUDGET_USED:'오늘의 검색 한도를 사용했습니다.',API_COOLDOWN:'잠시 후 다시 검색해 주세요.',NAVER_PERMISSION_DENIED:'네이버 API 등록 권한을 확인해 주세요.',NAVER_QUOTA_EXCEEDED:'네이버 API 사용 한도에 도달했습니다.'};
        box.append(el('p',notices[d.status]||'검색을 완료하지 못했습니다. 상태: '+d.status));return;
      }
      box.append(el('p','조회 시각 '+d.fetched_at));const list=el('ol');
      // Render provider strings as text (no executable HTML), preserving result order.
      for(const item of d.results.items){const li=el('li');li.append(link(item.title,item.link),el('p',item.description));if(item.originallink)li.append(link('원문 출처',item.originallink));if(item.pubDate||item.postdate)li.append(el('p',item.pubDate||item.postdate));list.append(li);}box.append(list);
      // No localStorage/IndexedDB; remove transient results on next query or after 15m.
      expires=setTimeout(()=>box.replaceChildren(el('p','검색 표시가 만료되었습니다.')),15*60*1000);
    }catch(e){box.replaceChildren(el('p',e.message));}finally{$('search').disabled=false;}
  });
})();
