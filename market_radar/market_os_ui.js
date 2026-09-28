/* Market OS — multi-axis market cockpit + shadow learning. */
(() => {
 'use strict';
 const root=document.querySelector('.app'); if(!root)return;
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n;};
 const svg=(tag,attrs={})=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,String(v));return n;};
 const style=el('style');style.textContent=`
 :root{--mos-ink:#15233a;--mos-muted:#6b7890;--mos-line:#dbe3ee;--mos-bg:#f4f7fb;--mos-card:#fff;--mos-blue:#3156d3;--mos-teal:#118b7a;--mos-amber:#b87517;--mos-red:#b94a52;--mos-purple:#6d55b8}
 .mos{color:var(--mos-ink);background:var(--mos-bg);padding:16px;border-radius:16px;min-height:78vh}
 .mos *{box-sizing:border-box}.mos-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:12px}.mos-title h2{margin:0;font-size:24px;letter-spacing:-.7px}.mos-kicker{font-size:10px;letter-spacing:1.2px;font-weight:800;color:var(--mos-blue);text-transform:uppercase}.mos-sub{font-size:11px;color:var(--mos-muted);line-height:1.65;margin-top:4px}
 .mos-btn,.mos-chip,.mos input,.mos select{border:1px solid var(--mos-line);background:#fff;color:#29415f;border-radius:8px;padding:7px 10px;font:inherit}.mos-btn,.mos-chip{cursor:pointer}.mos-chip[aria-pressed=true],.mos-btn[aria-pressed=true]{background:#223a7a;color:#fff;border-color:#223a7a}.mos-btn:focus-visible,.mos-chip:focus-visible,.mos input:focus-visible{outline:3px solid #b8c9ff}
 .mos-toolbar{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.mos-tabs{display:inline-flex;padding:3px;border:1px solid var(--mos-line);background:#fff;border-radius:10px;gap:2px}.mos-tabs button{border:0;background:transparent;border-radius:7px;padding:7px 11px;cursor:pointer;color:#5f6e84}.mos-tabs button[aria-pressed=true]{background:#263b71;color:white}
 .mos-strip{display:grid;grid-template-columns:1.4fr repeat(4,minmax(0,1fr));gap:9px;margin:12px 0}.mos-metric{background:var(--mos-card);border:1px solid var(--mos-line);border-radius:12px;padding:12px 13px;min-width:0}.mos-metric.primary{border-left:4px solid var(--mos-blue)}.mos-metric strong{display:block;font-size:18px;line-height:1.4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mos-label{font-size:9px;color:#7b879b;text-transform:uppercase;letter-spacing:.7px;font-weight:700}.mos-micro{font-size:10px;color:var(--mos-muted);line-height:1.55}
 .mos-marketline{display:flex;gap:6px;flex-wrap:wrap;margin:7px 0 2px}.mos-pill{display:inline-flex;align-items:center;gap:4px;border-radius:999px;background:#eef2f8;padding:4px 7px;font-size:9px;color:#52627a}.mos-pill.teal{background:#dff4ee;color:#0f715f}.mos-pill.amber{background:#fff0d7;color:#86530c}.mos-pill.red{background:#fde5e7;color:#9b3640}.mos-pill.purple{background:#eee9fb;color:#5b47a0}
 .mos-main{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(320px,.8fr);gap:12px;align-items:start}.mos-panel{background:var(--mos-card);border:1px solid var(--mos-line);border-radius:13px;overflow:hidden}.mos-panel-head{padding:12px 13px;border-bottom:1px solid #edf1f6;display:flex;justify-content:space-between;gap:8px;align-items:center}.mos-panel-head h3{margin:0;font-size:13px}.mos-filters{display:flex;gap:6px;flex-wrap:wrap;padding:10px 12px;border-bottom:1px solid #edf1f6}.mos-filters input{min-width:180px;flex:1}
 .mos-scroll{overflow:auto;max-height:680px}.mos-table{width:100%;border-collapse:collapse;font-size:10px;min-width:1080px}.mos-table th{position:sticky;top:0;background:#f6f8fc;color:#748196;padding:9px 7px;text-align:right;z-index:1}.mos-table th:first-child,.mos-table td:first-child{text-align:left}.mos-table td{padding:9px 7px;border-top:1px solid #edf1f6;text-align:right;white-space:nowrap}.mos-table tr{cursor:pointer}.mos-table tr:hover{background:#f8faff}.mos-table tr[data-selected=true]{background:#edf3ff}.mos-name{font-weight:800;font-size:11px}.mos-code{font-size:9px;color:#8a95a6;margin-top:2px}
 .mos-tier{font-size:9px;font-weight:800;border-radius:6px;padding:3px 6px;display:inline-block}.mos-tier.focus{background:#dff4ee;color:#0f725f}.mos-tier.prep{background:#fff0d7;color:#8b5a13}.mos-tier.discover{background:#e8edfb;color:#41598e}.mos-tier.blocked{background:#fde5e7;color:#a43b44}
 .mos-axisnum{font-weight:800}.mos-up{color:#c94651}.mos-down{color:#3869b7}.mos-detail{position:sticky;top:58px;padding:14px}.mos-detail h3{font-size:19px;margin:0}.mos-detail h4{font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:#78869b;margin:15px 0 7px}.mos-axis{display:grid;grid-template-columns:55px 1fr 34px;gap:7px;align-items:center;margin:8px 0;font-size:10px}.mos-track{height:7px;border-radius:99px;background:#edf1f6;overflow:hidden}.mos-track span{display:block;height:100%;background:linear-gradient(90deg,#3f64db,#1ca48e);border-radius:99px}.mos-axis strong{text-align:right}
 .mos-reasons{display:flex;gap:5px;flex-wrap:wrap}.mos-risk{background:#fff2f2;border:1px solid #f2d6d8;border-radius:9px;padding:8px 9px;font-size:10px;line-height:1.65;color:#8e4047}.mos-note{background:#eef3fa;border-radius:9px;padding:9px 10px;font-size:10px;line-height:1.65;color:#56677d}.mos-research{white-space:pre-wrap;font-size:10px;line-height:1.75;color:#34465d}
 .mos-heat{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));grid-auto-flow:dense;gap:7px;padding:10px}.mos-tile{border:1px solid var(--mos-line);border-radius:10px;padding:10px;min-height:90px;cursor:pointer;background:#fff;overflow:hidden}.mos-tile.big{grid-column:span 2;grid-row:span 2;min-height:187px}.mos-tile.mid{grid-column:span 2}.mos-tile.focus{box-shadow:inset 0 3px 0 #15917d}.mos-tile.prep{box-shadow:inset 0 3px 0 #d18a26}.mos-tile.blocked{box-shadow:inset 0 3px 0 #c35a62}.mos-tile h4{margin:0;font-size:12px}.mos-tile .mos-tile-change{font-size:18px;font-weight:800;margin:8px 0}.mos-tile-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}.mos-tile-grid div{background:#f3f6fa;border-radius:6px;padding:4px;text-align:center;font-size:9px}.mos-section-title{padding:10px 12px 0;font-size:11px;font-weight:800;color:#3a4e69}
 .mos-learning{padding:12px}.mos-learning-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin-bottom:12px}.mos-learn-card{border:1px solid var(--mos-line);background:#fff;border-radius:11px;padding:11px}.mos-learn-card strong{display:block;font-size:19px}.mos-feedback{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:10px 0}.mos-feedback article{border:1px solid var(--mos-line);border-left:4px solid #7186b8;border-radius:10px;padding:10px;background:white}.mos-feedback article[data-kind=STRENGTH]{border-left-color:#16947e}.mos-feedback article[data-kind=WEAKNESS]{border-left-color:#c46167}.mos-feedback h4{margin:0 0 4px;font-size:11px}.mos-learn-table{width:100%;border-collapse:collapse;font-size:10px}.mos-learn-table th,.mos-learn-table td{padding:8px;border-top:1px solid #edf1f6;text-align:right}.mos-learn-table th:first-child,.mos-learn-table td:first-child{text-align:left}.mos-learn-table th{color:#78869a;background:#f7f9fc}
 .mos-spark{width:100%;height:64px}.mos-empty{padding:20px;color:var(--mos-muted);font-size:11px;line-height:1.7}.mos-dialog{width:min(900px,94vw);max-height:90vh;overflow:auto;border:1px solid #cad5e5;border-radius:14px;padding:16px;background:#fff;color:var(--mos-ink)}.mos-dialog::backdrop{background:#16223c99}.mos-history{width:100%;border-collapse:collapse;font-size:10px}.mos-history th,.mos-history td{padding:7px;border-top:1px solid #edf1f6;text-align:right}.mos-history th:first-child,.mos-history td:first-child{text-align:left}
 @media(max-width:1200px){.mos-strip{grid-template-columns:repeat(3,minmax(0,1fr))}.mos-main{grid-template-columns:1fr}.mos-detail{position:static}.mos-heat{grid-template-columns:repeat(4,minmax(0,1fr))}}
 @media(max-width:700px){.mos{padding:9px}.mos-head{flex-direction:column}.mos-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.mos-heat{grid-template-columns:repeat(2,minmax(0,1fr))}.mos-tile.big,.mos-tile.mid{grid-column:span 1;grid-row:span 1;min-height:100px}.mos-learning-grid{grid-template-columns:repeat(2,1fr)}.mos-feedback{grid-template-columns:1fr}}
 @media(prefers-color-scheme:dark){.mos{--mos-ink:#e9eef8;--mos-muted:#9ca9bc;--mos-line:#344055;--mos-bg:#131a26;--mos-card:#1a2331}.mos-btn,.mos-chip,.mos input,.mos select,.mos-tabs,.mos-metric,.mos-panel,.mos-tile,.mos-learn-card,.mos-feedback article,.mos-dialog{background:#1a2331;color:#e9eef8}.mos-table th,.mos-learn-table th{background:#202b3c}.mos-table tr:hover{background:#222f42}.mos-table tr[data-selected=true]{background:#26354f}.mos-axis div,.mos-tile-grid div{background:#263244}.mos-note{background:#243248;color:#bcc7d7}.mos-risk{background:#3a252a;border-color:#593138;color:#e4a6aa}.mos-track{background:#2a3547}}
 `;document.head.append(style);

 const view=el('section',null,'view mos');view.id='view-market-os';root.append(view);
 function switchView(){if(typeof window.setView==='function')window.setView('market-os');else{document.querySelectorAll('.view').forEach(n=>n.classList.toggle('active',n===view));document.querySelectorAll('[data-view]').forEach(n=>n.classList.toggle('active',n.dataset.view==='market-os'));}load(true);}
 for(const id of ['tabs','bottom']){const nav=document.getElementById(id);if(!nav)continue;const b=el('button',id==='bottom'?'Market OS':'Market OS',id==='tabs'?'tab':'');b.dataset.view='market-os';b.addEventListener('click',switchView);nav.insertBefore(b,nav.children[1]||null);}

 const head=el('div',null,'mos-head'),title=el('div',null,'mos-title');title.append(el('div','MARKET OPERATING SYSTEM','mos-kicker'),el('h2','오늘 시장 · 관심종목 · 학습'),el('div','시장→테마→종목→재료→차트→Trigger를 한 화면에서 봅니다.','mos-sub'));
 const toolbar=el('div',null,'mos-toolbar'),tabs=el('div',null,'mos-tabs');
 const tableBtn=el('button','Screener'),chartBtn=el('button','Charts'),heatBtn=el('button','Heatmap'),learnBtn=el('button','Learning'),refresh=el('button','새로고침','mos-btn');
 [tableBtn,chartBtn,heatBtn,learnBtn].forEach(b=>tabs.append(b));toolbar.append(tabs,refresh);head.append(title,toolbar);
 const strip=el('div',null,'mos-strip'),content=el('div');view.append(head,strip,content);
 const dialog=el('dialog',null,'mos-dialog mos');document.body.append(dialog);

 let DATA=null,mode='table',selected=null,tier='ALL',query='',busy=false,lastLoaded=0,chartRenderVersion=0;
 const fmt=(n,d=1)=>Number(n).toLocaleString('ko-KR',{maximumFractionDigits:d});
 const pct=n=>n==null?'—':(n>0?'+':'')+fmt(n,2)+'%';
 const money=n=>n==null?'—':Math.abs(n)>=1e12?fmt(n/1e12,2)+'조':Math.abs(n)>=1e8?fmt(n/1e8,1)+'억':fmt(n,0)+'원';
 const stamp=t=>t?new Date(t).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'미확인';
 const accessKey=()=>{try{return localStorage.getItem('marketRadarToken')||'';}catch(_){return '';}};
 async function get(url){const ctl=new AbortController(),timer=setTimeout(()=>ctl.abort(),18000);try{const r=await fetch(url,{headers:{'x-dashboard-token':accessKey()},cache:'no-store',signal:ctl.signal});if(!r.ok)throw new Error('HTTP '+r.status);return await r.json();}finally{clearTimeout(timer);}}
 function pill(text,cls=''){return el('span',text,'mos-pill '+cls);}
 function tierClass(t){return t==='FOCUS'?'focus':t==='PREP'?'prep':t==='BLOCKED'?'blocked':'discover';}
 function tierKo(t){return ({FOCUS:'집중검토',PREP:'준비',DISCOVER:'발견',BLOCKED:'구조제외'})[t]||t||'미확인';}
 function axis(label,value){const wrap=el('div',null,'mos-axis'),name=el('span',label),track=el('div',null,'mos-track'),bar=el('span');bar.style.width=Math.max(0,Math.min(100,value||0))+'%';track.append(bar);wrap.append(name,track,el('strong',value==null?'—':String(value)));return wrap;}
 function candidates(){let xs=[...(DATA?.market_os_watchlist||[])];if(tier!=='ALL')xs=xs.filter(x=>x.watch_tier===tier);if(query){const q=query.toLowerCase();xs=xs.filter(x=>(x.name+' '+x.code+' '+(x.market_theme||'')+' '+(x.event_type||'')).toLowerCase().includes(q));}return xs;}
 function rowData(code){return (DATA?.rows||[]).find(r=>r.code===code);}
 function selectedItem(){return (DATA?.market_os_watchlist||[]).find(x=>x.code===selected)||null;}

 function renderStrip(){
   strip.replaceChildren();
   const rg=DATA?.market_regime||{},xs=DATA?.market_os_watchlist||[],learn=DATA?.learning||{},st=learn.status||{};
   const focus=xs.filter(x=>x.watch_tier==='FOCUS').length,prep=xs.filter(x=>x.watch_tier==='PREP').length;
   const themes=(DATA?.theme_rotation?.series||[]).filter(x=>x.name).slice(0,3);
   const cards=[
     ['오늘 장세',rg.stable_label||rg.candidate_label||'레짐 대기',rg.stale?'자료 지연':'실시간 레짐','primary'],
     ['FOCUS / PREP',focus+' / '+prep,'상위 검토 후보',''],
     ['주도 테마',themes[0]?.name||'테마 대기',themes[0]?.change_pp!=null?'비중 '+(themes[0].change_pp>=0?'+':'')+fmt(themes[0].change_pp,1)+'%p':'공통표본 대기',''],
     ['학습 표본',fmt(st.assessments_total||0,0),fmt(st.outcomes_total||0,0)+' outcomes',''],
     ['Live data',DATA?.live_health?.overall||'진단 대기',(DATA?.live_health?.blockers||[]).join(' · ')||((DATA?.live_health?.warnings||[]).join(' · ')||'freshness check'),''],
     ['Rule',DATA?.market_os_version||learn.rule_version||'v1',learn.mode==='SHADOW_LEARNING'?'Shadow learning':'대기','']
   ];
   for(const [lab,val,note,cls] of cards){const c=el('div',null,'mos-metric '+cls);c.append(el('div',lab,'mos-label'),el('strong',val),el('div',note,'mos-micro'));strip.append(c);}
 }

 function filterBar(){
   const f=el('div',null,'mos-filters'),tiers=[['ALL','전체'],['FOCUS','집중검토'],['PREP','준비'],['DISCOVER','발견'],['BLOCKED','구조제외']];
   for(const [v,t] of tiers){const b=el('button',t,'mos-chip');b.setAttribute('aria-pressed',String(tier===v));b.onclick=()=>{tier=v;renderContent();};f.append(b);}
   const q=el('input');q.placeholder='종목 · 코드 · 테마 · 재료 검색';q.value=query;q.oninput=()=>{query=q.value;renderBodyOnly();};f.append(q);
   return f;
 }

 function renderTableView(){
   const main=el('div',null,'mos-main'),left=el('section',null,'mos-panel'),right=el('aside',null,'mos-panel mos-detail');
   const ph=el('div',null,'mos-panel-head');ph.append(el('h3','관심종목 Screener'),el('div','축별 점수는 독립 지표','mos-micro'));left.append(ph,filterBar());
   const scroll=el('div',null,'mos-scroll'),table=el('table',null,'mos-table'),thead=el('thead'),trh=el('tr');
   ['종목','단계','등락','Radar','Theme','Setup','Catalyst','Trigger','학습','0B Micro','최근 구간','리스크'].forEach(x=>trh.append(el('th',x)));thead.append(trh);const tbody=el('tbody');table.append(thead,tbody);scroll.append(table);left.append(scroll);
   const xs=candidates();for(const x of xs){const r=rowData(x.code)||{},tr=el('tr');tr.dataset.selected=String(x.code===selected);tr.onclick=()=>{selected=x.code;renderContent();};
     const n=el('td');n.append(el('div',x.name,'mos-name'),el('div',x.code+' · '+(x.market_theme||'테마 미확인'),'mos-code'));tr.append(n);
     const tdTier=el('td');tdTier.append(el('span',tierKo(x.watch_tier),'mos-tier '+tierClass(x.watch_tier)));tr.append(tdTier);
     const lc=(x.learning_context||[])[0],mic=x.microstructure||null;const microText=mic?((mic.strength==null?'강도—':'강도 '+fmt(mic.strength,0))+' · 15초 '+money(mic.trade_value_15s_krw??mic.trade_value_krw)):'—';tr.append(el('td',pct(x.change_pct),x.change_pct>0?'mos-up':x.change_pct<0?'mos-down':''),el('td',x.radar_score,'mos-axisnum'),el('td',x.theme_score,'mos-axisnum'),el('td',x.setup_score,'mos-axisnum'),el('td',x.catalyst_grade||'—'),el('td',x.trigger_state||'—'),el('td',lc?('N'+lc.samples+' · '+pct(lc.avg_return_pct)):'—',lc&&lc.avg_return_pct>0?'mos-up':lc&&lc.avg_return_pct<0?'mos-down':''),el('td',microText,mic&&mic.gap_count===0?'mos-up':''),el('td',money(x.interval_turnover_krw)),el('td',(x.risk_flags||[]).length?String((x.risk_flags||[]).length):'—'));tbody.append(tr);}
   if(!xs.length){const tr=el('tr'),td=el('td','현재 필터를 충족한 후보가 없습니다.','mos-empty');td.colSpan=12;tr.append(td);tbody.append(tr);}
   main.append(left,right);content.replaceChildren(main);renderDetail(right);
 }

 function renderDetail(box){
   box.replaceChildren();const x=selectedItem();if(!x){box.append(el('h3','종목을 선택하세요'),el('div','FOCUS/PREP/DISCOVER는 매수 지시가 아니라 검토 순서입니다.','mos-note'));return;}
   const r=rowData(x.code)||{};box.append(el('div','STOCK DETAIL','mos-kicker'),el('h3',x.name+' · '+x.code),el('div',(x.market_theme||'테마 미확인')+' · '+(x.event_type||'재료분류 대기'),'mos-sub'));
   const top=el('div',null,'mos-marketline');top.append(el('span',tierKo(x.watch_tier),'mos-tier '+tierClass(x.watch_tier)),pill('Catalyst '+x.catalyst_grade,x.catalyst_grade==='A'?'teal':x.catalyst_grade==='U'?'amber':'purple'),pill(x.trigger_note||x.trigger_state,x.trigger_state==='BLOCKED'?'red':'purple'));box.append(top);
   box.append(el('h4','Independent axes'),axis('Radar',x.radar_score),axis('Theme',x.theme_score),axis('Setup',x.setup_score));
   box.append(el('h4','Why now'));const why=el('div',null,'mos-reasons');for(const v of [...(x.axis_reasons?.radar||[]),...(x.axis_reasons?.theme||[]),...(x.axis_reasons?.setup||[])].slice(0,10))why.append(pill(v));box.append(why);
   box.append(el('h4','Market context'),el('div',(x.market_stance_label||x.market_stance)+' · '+(DATA?.market_regime?.stable_label||DATA?.market_regime?.candidate_label||'레짐 대기'),'mos-note'));
   box.append(el('h4','0B Microstructure'));
   const mic=x.microstructure||null;
   if(mic){
     const mbox=el('div',null,'mos-note');
     const bs=mic.buy_share==null?'—':fmt(mic.buy_share*100,0)+'%';
     const bs15=mic.buy_share_15s==null?'—':fmt(mic.buy_share_15s*100,0)+'%';
     mbox.append(el('div','최근 15초 '+money(mic.trade_value_15s_krw)+' · Tick '+(mic.tick_count_15s??'—')+' · Gap '+(mic.gap_count_15s??'—')+' · 매수체결 '+bs15,'mos-micro'),
                 el('div','현재 1분 '+money(mic.trade_value_krw)+' · Tick '+(mic.tick_count??'—')+' · Gap '+(mic.gap_count??'—'),'mos-micro'),
                 el('div','체결강도 '+(mic.strength==null?'—':fmt(mic.strength,1))+' · 매수비율 '+(mic.buy_ratio==null?'—':fmt(mic.buy_ratio,1))+' · 1분 매수체결 비중 '+bs,'mos-micro'),
                 el('div','0B는 아직 Radar/Setup 점수에 자동 반영하지 않고 shadow-learning으로 검증합니다.','mos-micro'));
     box.append(mbox);
   }else box.append(el('div','Kiwoom 0B 실시간 관측 대기 · 기능을 켜기 전에는 기존 30초/3분 데이터만 사용합니다.','mos-note'));
   const histctx=x.learning_context||[];
   box.append(el('h4','Shadow learning'));
   if(histctx.length){
     const hc=el('div',null,'mos-note');
     for(const s of histctx){
       const edge=s.edge_avg_return_pct==null?'':(' · 부모대비 '+(s.edge_avg_return_pct>=0?'+':'')+fmt(s.edge_avg_return_pct,2)+'%p');
       const line=el('div',(s.segment_type+' · '+s.horizon+' · N'+s.samples+' / '+(s.distinct_stocks??'—')+'종목 / '+(s.distinct_days??'—')+'일 · '+s.quality+' · 평균 '+pct(s.avg_return_pct)+edge),'mos-micro');
       hc.append(line);
     }
     box.append(hc);
   }else box.append(el('div','같은 조건이 여러 종목·여러 거래일에서 충분히 반복되기 전에는 역사 성과를 현재 판단에 붙이지 않습니다.','mos-note'));
   box.append(el('h4','Invalidation / Risk'));box.append(el('div',(x.risk_flags||[]).length?(x.risk_flags||[]).join(' · '):'현재 등록된 위험 플래그 없음','mos-risk'));
   if(r.research){box.append(el('h4','Catalyst evidence'),el('div',(x.catalyst_note||'인용 포함 보고서')+' · '+stamp(r.research.completed_at),'mos-note'));const sec=r.research.sections||{};if(sec['핵심 재료'])box.append(el('div',sec['핵심 재료'].text,'mos-research'));}
   else box.append(el('h4','Catalyst evidence'),el('div',x.catalyst_note||'종합 검증 대기','mos-note'));
   const actions=el('div',null,'mos-toolbar'),hist=el('button','학습 기록','mos-btn');hist.onclick=()=>openHistory(x.code,x.name);const flow=el('button','30초 흐름 보기','mos-btn');flow.onclick=()=>{const b=document.querySelector('[data-view="flow"]');if(b)b.click();else if(typeof window.setView==='function')window.setView('flow');};actions.append(hist,flow);box.append(el('h4','Review'),actions);
 }

 function tileSize(x,rank){if(rank<2)return'big';if(rank<6)return'mid';return'';}
 function drawMiniChart(info,box){
   box.replaceChildren();const rows=(info?.minute||[]).filter(r=>['open','high','low','close'].every(k=>Number.isFinite(Number(r[k]))&&Number(r[k])>0)).slice(-60);
   if(rows.length<2){box.append(el('div','저장된 3분봉 대기','mos-empty'));return;}
   const W=520,H=170,l=46,r=8,t=8,b=18,lo0=Math.min(...rows.map(x=>Number(x.low))),hi0=Math.max(...rows.map(x=>Number(x.high))),pad=(hi0-lo0||hi0*.01)*.06,lo=lo0-pad,hi=hi0+pad,span=hi-lo||1,x=i=>l+(i+.5)*(W-l-r)/rows.length,y=v=>t+(hi-v)/(span)*(H-t-b),bw=Math.max(1,(W-l-r)/rows.length*.55),s=svg('svg',{viewBox:'0 0 '+W+' '+H,role:'img','aria-label':'3분봉 차트'});
   for(let i=0;i<4;i++){const v=lo+span*i/3,yy=y(v);s.append(svg('line',{x1:l,x2:W-r,y1:yy,y2:yy,stroke:'#e4eaf3'}));const tx=svg('text',{x:l-5,y:yy+3,'text-anchor':'end','font-size':9,fill:'#7b8799'});tx.textContent=fmt(v,0);s.append(tx);}
   rows.forEach((q,i)=>{const up=Number(q.close)>=Number(q.open),col=up?'#c44d58':'#4775b9',g=svg('g',{opacity:q.provisional?.55:1});g.append(svg('line',{x1:x(i),x2:x(i),y1:y(q.high),y2:y(q.low),stroke:col,'stroke-width':1}));g.append(svg('rect',{x:x(i)-bw/2,y:Math.min(y(q.open),y(q.close)),width:bw,height:Math.max(1,Math.abs(y(q.open)-y(q.close))),fill:up?'#fff':col,stroke:col,'stroke-width':1}));s.append(g);});
   box.append(s);
 }
 async function renderCharts(){
   const version=++chartRenderVersion,panel=el('section',null,'mos-panel'),ph=el('div',null,'mos-panel-head');ph.append(el('h3','Chart Grid'),el('div','저장된 KRX 3분봉 · 상위 후보 최대 8개','mos-micro'));panel.append(ph,filterBar());const grid=el('div',null,'mos-feedback');panel.append(grid);content.replaceChildren(panel);
   const xs=candidates().slice(0,8);if(!xs.length){grid.append(el('div','차트로 볼 후보가 없습니다.','mos-empty'));return;}
   for(const x of xs){const card=el('article');card.style.borderLeftColor=x.watch_tier==='FOCUS'?'#15917d':x.watch_tier==='PREP'?'#d18a26':'#7186b8';const hd=el('div',null,'mos-head'),lt=el('div');lt.append(el('h4',x.name+' · '+x.code),el('div',(x.market_theme||'테마 미확인')+' · '+tierKo(x.watch_tier),'mos-micro'));hd.append(lt,el('strong',pct(x.change_pct),x.change_pct>0?'mos-up':x.change_pct<0?'mos-down':''));const chart=el('div','차트 불러오는 중…','mos-empty');card.append(hd,chart);card.onclick=()=>{selected=x.code;mode='table';syncTabs();renderContent();};grid.append(card);
     get('/api/flow-chart/'+encodeURIComponent(x.code)).then(info=>{if(version===chartRenderVersion)drawMiniChart(info,chart);}).catch(()=>{if(version===chartRenderVersion)chart.textContent='저장 차트 대기';});
   }
 }
 function renderHeatmap(){
   const panel=el('section',null,'mos-panel'),ph=el('div',null,'mos-panel-head');ph.append(el('h3','관심종목 Heatmap'),el('div','타일 크기 = 최근 구간 거래대금 순위 · 색상 = 검토 단계','mos-micro'));panel.append(ph,filterBar());
   const grid=el('div',null,'mos-heat');const xs=candidates().sort((a,b)=>(b.interval_turnover_krw||0)-(a.interval_turnover_krw||0));
   xs.forEach((x,i)=>{const t=el('article',null,'mos-tile '+tierClass(x.watch_tier)+' '+tileSize(x,i));t.onclick=()=>{selected=x.code;mode='table';syncTabs();renderContent();};t.append(el('div',tierKo(x.watch_tier),'mos-label'),el('h4',x.name),el('div',x.market_theme||'테마 미확인','mos-code'),el('div',pct(x.change_pct),'mos-tile-change '+(x.change_pct>0?'mos-up':x.change_pct<0?'mos-down':'')));const g=el('div',null,'mos-tile-grid');[['R',x.radar_score],['T',x.theme_score],['S',x.setup_score]].forEach(([a,v])=>{const d=el('div');d.append(el('div',a,'mos-label'),el('strong',v));g.append(d);});t.append(g,el('div','Catalyst '+x.catalyst_grade+' · '+money(x.interval_turnover_krw),'mos-micro'));grid.append(t);});
   if(!xs.length)grid.append(el('div','Heatmap에 표시할 후보가 없습니다.','mos-empty'));panel.append(grid);content.replaceChildren(panel);
 }

 function sparkDaily(rows){
   const s=svg('svg',{viewBox:'0 0 360 64',class:'mos-spark'});if(!rows||rows.length<2)return s;const vals=rows.map(x=>Number(x.count||0)),mx=Math.max(1,...vals),w=360/vals.length;rows.forEach((r,i)=>{const h=48*(r.count||0)/mx;s.append(svg('rect',{x:i*w+2,y:56-h,width:Math.max(2,w-5),height:h,rx:2,fill:'#5572d5'}));const tt=svg('title');tt.textContent=r.date+' · '+r.count+' assessments · FOCUS '+r.focus;s.lastChild.append(tt);});return s;
 }

 function renderLearning(){
   const learn=DATA?.learning||{},st=learn.status||{},wrap=el('section',null,'mos-panel'),ph=el('div',null,'mos-panel-head');ph.append(el('h3','Learning Lab'),pill('SHADOW LEARNING','purple'));wrap.append(ph);
   const body=el('div',null,'mos-learning'),k=el('div',null,'mos-learning-grid');
   const days=(learn.daily_assessments||[]).length,segs=learn.segments||[];
   for(const [a,b,c] of [['Assessments',st.assessments_total||0,'실시간 판단 스냅샷'],['Outcomes',st.outcomes_total||0,'5m · 30m · 종가 · D+1'],['Days',days,'최근 14일 관찰'],['Stable segments',segs.filter(x=>x.quality!=='탐색').length,'다일·다종목 표본 통과']]){const card=el('div',null,'mos-learn-card');card.append(el('div',a,'mos-label'),el('strong',fmt(b,0)),el('div',c,'mos-micro'));k.append(card);}body.append(k,el('div',learn.notice||'결과를 모으는 중입니다.','mos-note'),sparkDaily(learn.daily_assessments||[]));
   const lh=DATA?.live_health||{},fq=lh.flow_quality||{},rt=lh.realtime||{},cv=lh.coverage||{},dq=el('div',null,'mos-learning-grid');
   const turnBad=fq.turnover_unresolved_pct,turnOk=turnBad==null?'—':fmt(Math.max(0,100-turnBad),1)+'%';
   const microN=cv.recent_micro15_assessments||0,assessN=cv.recent_assessments||0,microPct=assessN?fmt(microN/assessN*100,0)+'%':'—';
   for(const [a,b,note] of [
     ['Turnover quality',turnOk,'거래대금 단위 검증 통과율'],
     ['0B stream',rt.connected?('ON · '+(rt.subscribed_count||0)):'OFF',rt.status||'상태 대기'],
     ['Recent gaps',rt.recent_gap_count_5m??'—','최근 5분 gap 이벤트'],
     ['Micro coverage',microPct,microN+' / '+assessN+' assessments']
   ]){const card=el('div',null,'mos-learn-card');card.append(el('div',a,'mos-label'),el('strong',b),el('div',note,'mos-micro'));dq.append(card);}
   body.append(el('div','Data Quality','mos-section-title'),dq);
   if((fq.cap_unresolved_pct??0)>20)body.append(el('div','시가총액 단위는 별도 참조 검증 중입니다. 거래대금·0B 학습의 READY 판정과 분리합니다.','mos-note'));
   body.append(el('div','Validation Gate','mos-section-title'));
   const vs=learn.validation_summary||{},vg=learn.validation_candidates||[],vgGrid=el('div',null,'mos-learning-grid');
   for(const [a,b,note] of [
     ['승격 검토',vs.promote_review||0,'양(+) 효과 + 반복 표본 + 비교군 통과'],
     ['축소 검토',vs.suppress_review||0,'음(-) 효과 + 반복 표본 통과'],
     ['보류',vs.hold||0,'효과 정렬 또는 비교군 검증 미충족']
   ]){const card=el('div',null,'mos-learn-card');card.append(el('div',a,'mos-label'),el('strong',fmt(b,0)),el('div',note,'mos-micro'));vgGrid.append(card);}body.append(vgGrid);
   body.append(el('div','30분·종가·D+1만 검토합니다. 평균·중앙값·양(+) 비율이 같은 방향이어야 하며, 상호작용은 부모조건의 complement 비교군까지 형성 이상이어야 합니다. 이 단계는 규칙 변경이 아니라 사람 검토 후보를 좁히는 shadow gate입니다.','mos-note'));
   const vgScroll=el('div',null,'mos-scroll'),vgTable=el('table',null,'mos-learn-table'),vgHead=el('tr');
   ['상태','조건','구간','N','종목','일수','품질','평균','중앙값','양(+)','Δ평균','Δ양(+)','근거'].forEach(v=>vgHead.append(el('th',v)));const vgThead=el('thead');vgThead.append(vgHead);const vgBody=el('tbody');
   for(const s of vg.slice(0,40)){const tr=el('tr'),status=({PROMOTE_REVIEW:'승격 검토',SUPPRESS_REVIEW:'축소 검토',HOLD:'보류'})[s.status]||s.status;const cls=s.status==='PROMOTE_REVIEW'?'mos-up':s.status==='SUPPRESS_REVIEW'?'mos-down':'';tr.append(el('td',status,cls),el('td',s.segment_type+' · '+s.segment_value),el('td',s.horizon),el('td',s.samples),el('td',s.distinct_stocks??'—'),el('td',s.distinct_days??'—'),el('td',(s.quality||'—')+(s.readiness?' · '+s.readiness:'')),el('td',pct(s.avg_return_pct),s.avg_return_pct>0?'mos-up':s.avg_return_pct<0?'mos-down':''),el('td',pct(s.median_return_pct)),el('td',s.positive_rate==null?'—':fmt(s.positive_rate*100,0)+'%'),el('td',s.edge_avg_return_pct==null?'—':((s.edge_avg_return_pct>=0?'+':'')+fmt(s.edge_avg_return_pct,2)+'%p')),el('td',s.edge_positive_rate_pp==null?'—':((s.edge_positive_rate_pp>=0?'+':'')+fmt(s.edge_positive_rate_pp,1)+'%p')),el('td',(s.reason_codes||[]).join(' · '),'mos-micro'));vgBody.append(tr);}
   if(!vg.length){const tr=el('tr'),td=el('td','아직 형성 등급 이상의 30분·종가·D+1 검증 후보가 없습니다.','mos-empty');td.colSpan=13;tr.append(td);vgBody.append(tr);}vgTable.append(vgThead,vgBody);vgScroll.append(vgTable);body.append(vgScroll);
   body.append(el('div','자동 피드백 후보','mos-section-title'));const fb=el('div',null,'mos-feedback');for(const n of learn.notes||[]){const a=el('article');a.dataset.kind=n.kind;a.append(el('h4',(n.kind==='STRENGTH'?'강한 조건 후보 · ':'약한 조건 후보 · ')+n.title),el('div',n.text,'mos-micro'));fb.append(a);}if(!(learn.notes||[]).length)fb.append(el('div','표본 20개 이상이 쌓인 뒤 조건별 강·약 피드백을 냅니다. 아직 규칙을 자동 수정하지 않습니다.','mos-empty'));body.append(fb);
   body.append(el('div','Interaction Lab','mos-section-title'));
   body.append(el('div','시장 레짐 × Setup × Trigger × 0B를 미리 정한 조합만 비교합니다. Δ는 같은 부모조건 안에서 해당 child를 제외한 나머지 표본과의 차이이며, 형성/충분 등급 전에는 탐색 가설로만 봅니다.','mos-note'));
   const inter=(learn.interactions||[]).filter(x=>x.samples>=5).slice(0,100),iscroll=el('div',null,'mos-scroll'),itable=el('table',null,'mos-learn-table'),ith=el('tr');
   ['상호작용','구간','N','종목','일수','품질','평균','Δ평균','Δ양(+)','ΔMAE','부모조건'].forEach(v=>ith.append(el('th',v)));const ithead=el('thead');ithead.append(ith);const itb=el('tbody');
   for(const s of inter){const tr=el('tr'),base=s.baseline||{};const cond=el('td');cond.append(el('div',s.segment_type+' · '+s.segment_value),el('div','depth '+(s.interaction_depth||2)+' · '+(s.sample_basis||''),'mos-micro'));tr.append(cond,el('td',s.horizon),el('td',s.samples),el('td',s.distinct_stocks??'—'),el('td',s.distinct_days??'—'),el('td',s.quality),el('td',pct(s.avg_return_pct),s.avg_return_pct>0?'mos-up':s.avg_return_pct<0?'mos-down':''),el('td',s.edge_avg_return_pct==null?'—':((s.edge_avg_return_pct>=0?'+':'')+fmt(s.edge_avg_return_pct,2)+'%p'),s.edge_avg_return_pct>0?'mos-up':s.edge_avg_return_pct<0?'mos-down':''),el('td',s.edge_positive_rate_pp==null?'—':((s.edge_positive_rate_pp>=0?'+':'')+fmt(s.edge_positive_rate_pp,1)+'%p')),el('td',s.edge_mae_pct==null?'—':((s.edge_mae_pct>=0?'+':'')+fmt(s.edge_mae_pct,2)+'%p'),s.edge_mae_pct>0?'mos-up':s.edge_mae_pct<0?'mos-down':''),el('td',base.segment_type?(base.segment_type+' · '+base.segment_value+' · compN '+(base.samples??'—')):'—'));itb.append(tr);}
   if(!inter.length){const tr=el('tr'),td=el('td','상호작용 표본이 아직 없습니다.','mos-empty');td.colSpan=11;tr.append(td);itb.append(tr);}itable.append(ithead,itb);iscroll.append(itable);body.append(iscroll);
   body.append(el('div','조건별 실제 결과','mos-section-title'));body.append(el('div','반복 스냅샷을 독립 표본으로 세지 않습니다. 5m는 종목별 5분 비중첩, 30m는 30분 비중첩, 종가·D+1은 종목/일자당 1회만 학습합니다.','mos-note'));const scroll=el('div',null,'mos-scroll'),table=el('table',null,'mos-learn-table'),th=el('tr');['조건','구간','N','종목','일수','품질','평균','중앙값','양(+)','MFE','MAE'].forEach(v=>th.append(el('th',v)));const thead=el('thead');thead.append(th);const tb=el('tbody');for(const s of segs.filter(x=>x.samples>=5).slice(0,120)){const tr=el('tr');const cond=el('td');cond.append(el('div',s.segment_type+' · '+s.segment_value),el('div',s.sample_basis||'','mos-micro'));tr.append(cond,el('td',s.horizon),el('td',s.samples),el('td',s.distinct_stocks??'—'),el('td',s.distinct_days??'—'),el('td',s.quality),el('td',pct(s.avg_return_pct),s.avg_return_pct>0?'mos-up':s.avg_return_pct<0?'mos-down':''),el('td',pct(s.median_return_pct)),el('td',s.positive_rate==null?'—':fmt(s.positive_rate*100,0)+'%'),el('td',pct(s.avg_mfe_pct)),el('td',pct(s.avg_mae_pct)));tb.append(tr);}table.append(thead,tb);scroll.append(table);body.append(scroll);wrap.append(body);content.replaceChildren(wrap);
 }

 function renderContent(){renderStrip();if(mode==='table')renderTableView();else if(mode==='charts')renderCharts();else if(mode==='heat')renderHeatmap();else renderLearning();}
 function renderBodyOnly(){if(mode==='table')renderTableView();else if(mode==='charts')renderCharts();else if(mode==='heat')renderHeatmap();}
 function syncTabs(){tableBtn.setAttribute('aria-pressed',String(mode==='table'));chartBtn.setAttribute('aria-pressed',String(mode==='charts'));heatBtn.setAttribute('aria-pressed',String(mode==='heat'));learnBtn.setAttribute('aria-pressed',String(mode==='learn'));}
 tableBtn.onclick=()=>{mode='table';syncTabs();renderContent();};chartBtn.onclick=()=>{mode='charts';syncTabs();renderContent();};heatBtn.onclick=()=>{mode='heat';syncTabs();renderContent();};learnBtn.onclick=()=>{mode='learn';syncTabs();renderContent();};refresh.onclick=()=>load(true);syncTabs();

 async function openHistory(code,name){
   dialog.replaceChildren();const top=el('div',null,'mos-head'),ttl=el('div');ttl.append(el('div','LEARNING HISTORY','mos-kicker'),el('h3',name+' · '+code));const close=el('button','닫기','mos-btn');close.onclick=()=>dialog.close();top.append(ttl,close);dialog.append(top,el('div','과거 스냅샷의 이후 결과를 보는 복기 자료입니다. 현재 매수·매도 판단을 대신하지 않습니다.','mos-note'));if(!dialog.open)dialog.showModal();
   const holder=el('div','기록 불러오는 중…','mos-empty');dialog.append(holder);
   try{const d=await get('/api/market-os/history/'+encodeURIComponent(code));holder.replaceChildren();const latest=(d.assessments||[])[0];if(latest){const s=el('div',null,'mos-marketline');s.append(pill(tierKo(latest.watch_tier),tierClass(latest.watch_tier)),pill('Radar '+latest.radar_score),pill('Theme '+latest.theme_score),pill('Setup '+latest.setup_score),pill('Catalyst '+latest.catalyst_grade));holder.append(s);}
     const table=el('table',null,'mos-history'),th=el('tr');['판단시각','구간','기준가','결과','수익률','MFE','MAE','소스'].forEach(x=>th.append(el('th',x)));const h=el('thead');h.append(th);const tb=el('tbody');for(const o of d.outcomes||[]){const tr=el('tr');tr.append(el('td',stamp(o.assessment_time)),el('td',o.horizon),el('td',money(o.reference_price_krw)),el('td',money(o.outcome_price_krw)),el('td',pct(o.return_pct),o.return_pct>0?'mos-up':o.return_pct<0?'mos-down':''),el('td',pct(o.mfe_pct)),el('td',pct(o.mae_pct)),el('td',o.outcome_source||'—'));tb.append(tr);}table.append(h,tb);holder.append(table);if(!(d.outcomes||[]).length)holder.append(el('div','아직 확정된 outcome이 없습니다.','mos-empty'));
   }catch(e){holder.textContent='학습 기록 응답 대기 · '+e.message;}
 }

 async function load(force=false){if(busy||(!force&&(!view.classList.contains('active')||document.hidden||Date.now()-lastLoaded<28000)))return;if(!accessKey()){content.replaceChildren(el('div','대시보드 접속키가 필요합니다.','mos-empty'));return;}busy=true;try{const [d,h]=await Promise.all([get('/api/market-os'),get('/api/market-os/live-health').catch(()=>null)]);d.live_health=h;DATA=d;lastLoaded=Date.now();if(!selected&&(d.market_os_watchlist||[]).length)selected=d.market_os_watchlist[0].code;renderContent();}catch(e){content.replaceChildren(el('div','Market OS 자료 응답 대기 · '+e.message,'mos-empty'));}finally{busy=false;}}
 setInterval(()=>load(false),30000);load(true);
})();
