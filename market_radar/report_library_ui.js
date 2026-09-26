/* Saved reports only: GETs to local API; no paid request, queue, or retry. */
(() => {
  'use strict';
  const host = document.getElementById('view-material');
  if (!host) return;
  const el = (tag,text,cls) => { const n=document.createElement(tag); if(text!=null)n.textContent=String(text); if(cls)n.className=cls; return n; };
  const css=el('style');
  css.textContent=`
  .srl-panel{margin-bottom:20px;background:#fff;border:1px solid #cbd5ed;border-top:4px solid #6157c4;border-radius:14px;padding:16px;color:#1b2940}
  .srl-head,.srl-tools{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}.srl-head h2{margin:0;font-size:18px}.srl-sub{font-size:12px;color:#53647b;line-height:1.7}
  .srl-tools{margin:12px 0;justify-content:flex-start}.srl-tools input,.srl-tools select,.srl-button{font:inherit;border:1px solid #c3cfe6;border-radius:8px;padding:7px 10px;background:#f8faff;color:#233f70;max-width:100%}.srl-button{cursor:pointer}.srl-tools input{width:220px;background:white}.srl-button:focus-visible,.srl-tools input:focus-visible{outline:3px solid #9eb1ee}
  .srl-badge{display:inline-block;border-radius:7px;font-size:11px;line-height:1.5;padding:4px 7px;background:#eef1f6;color:#53647b}.srl-ok{background:#e3f4ec;color:#185f46}.srl-wait{background:#e8f0ff;color:#24559a}.srl-error{background:#ffeded;color:#9b3333}.srl-old{background:#fff2d8;color:#815709}
  .srl-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.srl-card{border:1px solid #d8e1ef;border-left:4px solid #6157c4;border-radius:10px;padding:12px;min-width:0}.srl-card h3{margin:0 0 8px;font-size:15px}.srl-card .srl-button{margin-top:8px}.srl-card p{margin:5px 0}.srl-link{margin-top:6px}.srl-link .srl-button{padding:4px 7px;font-size:11px}
  .srl-dialog{width:min(900px,94vw);max-height:88vh;border:1px solid #cbd6e8;border-radius:14px;padding:20px;color:#1b2940;background:#fff;overflow:auto}.srl-dialog::backdrop{background:rgba(18,29,52,.55)}.srl-dialog h2{font-size:20px;margin:0}.srl-report{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.95;margin-top:15px}.srl-report a,.srl-sources a{color:#254fa1;text-decoration:underline}.srl-sources{font-size:12px;overflow-wrap:anywhere;padding-left:18px}.srl-notice{margin-top:12px;padding:9px;background:#f3f4fc;border-radius:8px;color:#4d536f;font-size:12px;line-height:1.7}
  @media(max-width:950px){.srl-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:650px){.srl-grid{grid-template-columns:1fr}.srl-panel,.srl-dialog{padding:12px}}
  `;
  document.head.append(css);
  const panel=el('section',null,'srl-panel'); panel.id='saved-report-library';
  const head=el('div',null,'srl-head'), title=el('div');
  title.append(el('h2','종목별 AI 보고서'),el('div','저장된 외부 웹 조사 결과 · 열람만 하며 새 조사를 실행하지 않습니다.','srl-sub'));
  const refresh=el('button','저장 결과 새로고침','srl-button'); head.append(title,refresh);
  const status=el('div','저장 결과 확인 중…','srl-sub');
  const tools=el('div',null,'srl-tools'), search=el('input'); search.type='search'; search.placeholder='종목명 또는 코드'; search.setAttribute('aria-label','저장 보고서 검색');
  const filter=el('select'); filter.setAttribute('aria-label','보고서 상태 필터');
  [['all','전체 상태'],['report','보고서 있음'],['error','최근 조사 실패'],['waiting','대기·진행 중']].forEach(([v,t])=>{const o=el('option',t);o.value=v;filter.append(o);});
  tools.append(search,filter);const grid=el('div',null,'srl-grid');
  panel.append(head,status,tools,grid);host.prepend(panel);
  const dialog=el('dialog',null,'srl-dialog');dialog.setAttribute('aria-label','저장된 AI 보고서');document.body.append(dialog);
  const stateNames={QUEUED:'조사 대기',RUNNING:'조사 진행 중',CITED_REPORT:'인용 포함 보고서',EVIDENCE_INCOMPLETE:'출처 미충족',ERROR:'조사 실패',UNCERTAIN:'완료 여부 미확인',EXPIRED:'대기 만료',CANCELLED:'취소됨'};
  const errorNames={AUTH_FAILED:'API 인증 실패',ACCESS_DENIED:'접근 권한 거절',RATE_OR_CREDIT_LIMIT:'공급자 한도·크레딧 확인',MODEL_OR_ENDPOINT_UNAVAILABLE:'모델·경로 확인 필요',INCOMPLETE_RESPONSE:'응답 미완료'};
  let entries=[], byCode=new Map(), busy=false, signature='', lastLoaded=0, focusBack=null;
  const stamp=v=>{const d=new Date(v);return v&&!Number.isNaN(d.getTime())?d.toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'미확인';};
  const badge=(text,tone='')=>el('span',text,'srl-badge '+tone);
  function safeLink(url,text){
    try{const u=new URL(url);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)throw 0;const a=el('a',text);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch(_){return el('span',text);}
  }
  function reportText(report){
    const box=el('div',null,'srl-report'), chars=Array.from(report.text||'');let p=0,i=0;
    for(const a of [...(report.citations||[])].sort((x,y)=>x.start-y.start)){
      if(!Number.isInteger(a.start)||!Number.isInteger(a.end)||a.start<p||a.end>chars.length||a.end<=a.start)continue;
      box.append(document.createTextNode(chars.slice(p,a.start).join('')),safeLink(a.url,'[출처 '+(++i)+']'));p=a.end;
    }
    box.append(document.createTextNode(chars.slice(p).join('')));return box;
  }
  function openReport(code,button){
    const x=byCode.get(code);focusBack=button;dialog.replaceChildren();
    const header=el('div',null,'srl-head'), close=el('button','닫기','srl-button');close.addEventListener('click',()=>dialog.close());
    header.append(el('h2',(x?.name||code)+' · '+code),close);dialog.append(header);
    if(!x){dialog.append(el('p','최근 7일·최대 50종목의 저장 목록에서 이 종목의 보고서를 찾지 못했습니다. 이 버튼은 조사 요청을 보내지 않습니다.','srl-sub'));}
    else{
      dialog.append(el('p','최근 시도: '+(stateNames[x.latest_state]||x.latest_state)+' · '+stamp(x.latest_attempt_at),'srl-sub'));
      if(x.latest_error)dialog.append(badge(errorNames[x.latest_error]||x.latest_error,'srl-error'));
      if(x.report){
        dialog.append(el('div','저장 보고서 #'+x.report_id+' · 작성 '+stamp(x.report_completed_at)+' · '+(x.model||'모델 미확인'),'srl-sub'));
        dialog.append(el('div','보고서에 사용된 수집 시각 '+stamp(x.market_collected_at)+' / 가격봉 시각 '+stamp(x.price_bar_at),'srl-sub'));
        if(x.older_than_6h)dialog.append(badge('작성 후 6시간 경과 · 과거 보고서','srl-old'));
        dialog.append(reportText(x.report));
        const sources=el('ul',null,'srl-sources');for(const s of x.report.sources||[]){const li=el('li');li.append(safeLink(s.url,s.title||s.url));sources.append(li);}dialog.append(sources);
        dialog.append(el('div','인용은 출처 링크의 존재를 뜻합니다. 사실 확인·주가 원인 검증 완료나 매수·매도 신호가 아닙니다. 최신 가격과 사건은 별도로 확인하세요.','srl-notice'));
      }else dialog.append(el('p','이 조회 범위에 표시할 인용 포함 보고서가 없습니다. 실패·대기 기록을 분석 완료로 표시하지 않습니다.','srl-sub'));
    }
    if(!dialog.open)dialog.showModal();close.focus();
  }
  dialog.addEventListener('close',()=>{if(focusBack?.isConnected)focusBack.focus();});
  function repaint(){
    const term=search.value.trim().toLowerCase();grid.replaceChildren();
    const items=entries.filter(x=>(!term||(x.name+' '+x.code).toLowerCase().includes(term))&&(filter.value==='all'||filter.value==='report'&&x.report||filter.value==='error'&&['ERROR','UNCERTAIN'].includes(x.latest_state)||filter.value==='waiting'&&['QUEUED','RUNNING'].includes(x.latest_state)));
    if(!items.length){grid.append(el('p','조건에 맞는 저장 보고서·시도 기록이 없습니다.','srl-sub'));return;}
    for(const x of items){
      const card=el('article',null,'srl-card');card.append(el('h3',x.name+' · '+x.code));
      const tone=['ERROR','UNCERTAIN'].includes(x.latest_state)?'srl-error':['QUEUED','RUNNING'].includes(x.latest_state)?'srl-wait':x.latest_state==='CITED_REPORT'&&x.report?'srl-ok':'';
      card.append(badge('최근 시도: '+(stateNames[x.latest_state]||x.latest_state),tone));
      if(x.report){card.append(el('p','인용 '+x.report.citations.length+'개 · 작성 '+stamp(x.report_completed_at),'srl-sub'));if(x.older_than_6h)card.append(badge('작성 6시간 경과','srl-old'));}
      else card.append(el('p','인용 포함 보고서 없음','srl-sub'));
      const b=el('button',x.report?'AI 보고서 열기':'조사 상태 보기','srl-button');b.addEventListener('click',()=>openReport(x.code,b));card.append(b);grid.append(card);
    }
  }
  function attachTableLinks(){
    for(const id of ['queryRows','tradeRows'])for(const row of document.querySelectorAll('#'+id+' tr')){
      const code=[...row.querySelectorAll('.sub')].map(n=>n.textContent.trim()).find(s=>/^[0-9A-Z]{6}$/.test(s));
      const cell=row.cells[8];if(!code||!cell)continue;
      const x=byCode.get(code), tag=x?.report?'AI 보고서 · 인용 '+x.report.citations.length+'개':x?'AI 상태: '+(stateNames[x.latest_state]||x.latest_state):'외부 AI 보고서 미확인';
      let box=cell.querySelector('.srl-link');if(box&&box.dataset.label===tag)continue;
      if(!box){box=el('div',null,'srl-link');cell.append(box);}box.dataset.label=tag;box.replaceChildren();
      const b=el('button',tag,'srl-button');b.addEventListener('click',()=>openReport(code,b));box.append(b);
    }
  }
  let attachPending=false;const observer=new MutationObserver(()=>{if(attachPending)return;attachPending=true;requestAnimationFrame(()=>{attachPending=false;attachTableLinks();});});
  for(const id of ['queryRows','tradeRows']){const node=document.getElementById(id);if(node)observer.observe(node,{childList:true,subtree:true});}
  async function load(force=false){
    const relevant=['view-material','view-query','view-trade'].some(id=>document.getElementById(id)?.classList.contains('active'));
    if(busy||(!force&&(!relevant||document.hidden||Date.now()-lastLoaded<30000)))return;
    let key='';try{key=localStorage.getItem('marketRadarToken')||'';}catch(_){}
    if(!key){status.textContent='대시보드 접속키 필요 · 새 조사는 실행하지 않았습니다.';return;}
    busy=true;const ctl=new AbortController(),timer=setTimeout(()=>ctl.abort(),15000);
    try{
      const r=await fetch('/api/report-library',{headers:{'x-dashboard-token':key},cache:'no-store',signal:ctl.signal});
      if(!r.ok)throw new Error('저장 보고서 읽기 HTTP '+r.status);const d=await r.json();
      lastLoaded=Date.now();status.textContent='최근 '+d.lookback_days+'일 · 최대 '+d.max_stocks+'종목 · 저장 상태 '+(d.entries||[]).length+'종목 · 열람 전용';
      if(d.storage==='NOT_INITIALIZED')status.textContent='외부 조사 저장소가 아직 준비되지 않았습니다. 자동 조사나 초기화는 하지 않았습니다.';
      const sig=JSON.stringify(d.entries||[]);if(sig!==signature){signature=sig;entries=d.entries||[];byCode=new Map(entries.map(x=>[x.code,x]));repaint();attachTableLinks();}
    }catch(e){status.textContent=e.name==='AbortError'?'저장 결과 응답 지연 · 기존 화면 유지':e.message;}
    finally{busy=false;clearTimeout(timer);}
  }
  search.addEventListener('input',repaint);filter.addEventListener('change',repaint);refresh.addEventListener('click',()=>load(true));
  document.querySelectorAll('[data-view="material"],[data-view="query"],[data-view="trade"]').forEach(b=>b.addEventListener('click',()=>load(false)));
  load(true);setInterval(()=>load(false),30000);
})();
