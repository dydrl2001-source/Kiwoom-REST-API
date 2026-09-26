DASHBOARD_HTML_V2 = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Market Radar V2</title>
<style>
:root{
 --bg:#f4f7fb;--panel:#ffffff;--line:#dce3ee;--txt:#152033;--muted:#6f7c90;
 --red:#e25555;--blue:#4577d4;--green:#1e9c72;--amber:#d88c20;--nav:#162339;--chip:#edf2f8;
}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:13px/1.45 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif}
button{font:inherit}a{color:#4267ba;text-decoration:none}.app{max-width:1500px;margin:auto;min-height:100vh;padding:14px 14px 84px}
.head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}
.brand{font-size:24px;font-weight:900;letter-spacing:-.04em}.brand small{font-size:10px;color:var(--muted);margin-left:5px}
.time{font-size:11px;color:var(--muted)}
.statusbar{display:grid;grid-template-columns:1.4fr repeat(4,1fr);gap:8px;margin-bottom:10px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:10px 11px;min-height:67px}
.stat .k{font-size:10px;color:var(--muted)}.stat .v{font-size:16px;font-weight:850;margin-top:3px}.stat .s{font-size:10px;color:var(--muted);margin-top:2px}
.tabs{position:sticky;top:0;z-index:20;background:rgba(244,247,251,.95);backdrop-filter:blur(8px);display:flex;gap:6px;padding:6px 0 9px;overflow:auto}
.tab{border:1px solid var(--line);background:#fff;color:var(--muted);padding:8px 13px;border-radius:999px;white-space:nowrap;font-weight:700;cursor:pointer}
.tab.active{background:var(--nav);color:#fff;border-color:var(--nav)}
.view{display:none}.view.active{display:block}.section-title{display:flex;align-items:end;justify-content:space-between;margin:14px 2px 7px}.section-title h2{font-size:15px;margin:0}.section-title span{font-size:10px;color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}.pad{padding:12px}
.analysis{display:grid;grid-template-columns:1.3fr .7fr;gap:8px}.analysis-main{font-size:14px}.analysis-line{padding:7px 0;border-bottom:1px solid #eef2f7}.analysis-line:last-child{border:0}
.legend{display:flex;flex-wrap:wrap;gap:5px}.pill{display:inline-flex;align-items:center;gap:4px;padding:3px 7px;border-radius:999px;background:var(--chip);font-size:10px;color:#4d5d73}
.good{color:var(--green)}.bad{color:var(--blue)}.hot{color:var(--red)}.warn{color:var(--amber)}.muted{color:var(--muted)}
.sector-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.sector-card{background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.sector-head{display:flex;justify-content:space-between;align-items:center;padding:9px 10px;border-bottom:1px solid #edf1f6}.sector-head strong{font-size:14px}.sector-meta{font-size:10px;color:var(--muted)}
.stock-list{display:grid;grid-template-columns:1fr 1fr}.stock-mini{padding:8px 9px;border-right:1px solid #f0f3f7;border-bottom:1px solid #f0f3f7;min-height:62px}.stock-mini:nth-child(2n){border-right:0}
.stock-mini .name{font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.stock-mini .num{display:flex;justify-content:space-between;margin-top:4px;font-size:11px}.rank-badge{font-size:9px;color:#fff;background:#7b8799;border-radius:4px;padding:1px 4px}
.tblwrap{overflow:auto;max-height:660px}.tbl{width:100%;border-collapse:collapse;min-width:980px}.tbl th,.tbl td{padding:8px 8px;border-bottom:1px solid #edf1f6;text-align:right;vertical-align:middle;white-space:nowrap}.tbl th{position:sticky;top:0;background:#f8fafc;color:var(--muted);font-size:10px;z-index:2}.tbl .left{text-align:left}.tbl .wrap{white-space:normal;min-width:220px;text-align:left}
.stockname{font-weight:850}.sub{font-size:10px;color:var(--muted)}
.material-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.research-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.research-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:11px}.priority{font-size:18px;font-weight:900}.deep{color:#9b5b00;background:#fff2dc}.material-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:11px}
.material-top{display:flex;justify-content:space-between;gap:6px}.material-card h3{font-size:14px;margin:0}.material-summary{font-weight:750;margin:8px 0 5px;line-height:1.5}.material-why{font-size:11px;color:#516078;background:#f6f8fb;padding:7px;border-radius:7px}
details{margin-top:7px}summary{cursor:pointer;color:#526785;font-size:11px}.evidence{border-top:1px solid #edf1f6;margin-top:7px;padding-top:7px;font-size:11px}.evidence p{margin:4px 0}.links{display:flex;gap:7px;flex-wrap:wrap}
.mimosa-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.index-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.chart-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px}.chart-title{display:flex;justify-content:space-between;align-items:end;margin-bottom:6px}.chart-title b{font-size:14px}.svgchart{width:100%;height:210px;display:block}.strategy-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.strategy-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px}.strategy-card h3{font-size:13px;margin:0}.strategy-score{font-weight:900;font-size:16px}.strategy-note{font-size:10px;color:var(--muted);margin-top:6px}.m-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px}.m-head{display:flex;justify-content:space-between}.m-state{font-size:13px;font-weight:900;margin-top:6px}.score{font-weight:900}.reason{font-size:10px;color:var(--muted);margin-top:5px}.fb{display:flex;gap:5px;margin-top:8px}.fb button{border:1px solid var(--line);background:#fff;border-radius:7px;padding:4px 7px;font-size:10px;color:#5d6b7f;cursor:pointer}.fb button:hover{background:#f3f6fa}.fb .sent{background:#eaf6f1;color:#187a59}
.bottom{display:none}
@media(max-width:1100px){.sector-grid{grid-template-columns:repeat(2,1fr)}.material-grid,.research-grid{grid-template-columns:repeat(2,1fr)}.mimosa-grid{grid-template-columns:repeat(2,1fr)}.strategy-grid{grid-template-columns:repeat(2,1fr)}.index-grid{grid-template-columns:1fr}.statusbar{grid-template-columns:1fr 1fr 1fr}.analysis{grid-template-columns:1fr}}
@media(max-width:700px){
 .app{padding:10px 8px 82px}.head{margin-bottom:6px}.brand{font-size:20px}.statusbar{grid-template-columns:1fr 1fr;gap:6px}.stat{min-height:61px;padding:8px}
 .statusbar .stat:first-child{grid-column:1/-1}.tabs{display:none}.sector-grid{grid-template-columns:1fr 1fr;gap:6px}.stock-list{grid-template-columns:1fr}.stock-mini{border-right:0}
 .material-grid,.research-grid,.mimosa-grid,.strategy-grid{grid-template-columns:1fr}.section-title{margin-top:10px}.bottom{display:flex;position:fixed;bottom:0;left:0;right:0;z-index:40;background:#fff;border-top:1px solid var(--line);padding:5px 4px calc(5px + env(safe-area-inset-bottom));justify-content:space-around}
 .bottom button{border:0;background:transparent;color:#78869b;font-size:9px;display:flex;flex-direction:column;align-items:center;gap:2px;padding:4px 5px}.bottom button.active{color:#1c2b45;font-weight:900}.bottom b{font-size:16px;line-height:1}
}
</style></head>
<body><div class="app">
<div class="head"><div><span class="brand">MARKET RADAR <small>V2</small></span></div><div class="time" id="stamp">연결 중</div></div>

<div class="statusbar">
 <div class="stat"><div class="k">오늘 장</div><div class="v" id="regime">대기</div><div class="s" id="regimeSub">시장 데이터 확인 중</div></div>
 <div class="stat"><div class="k">Kiwoom</div><div class="v" id="kiwoom">-</div><div class="s" id="kiwoomSub"></div></div>
 <div class="stat"><div class="k">재료 / 뉴스</div><div class="v" id="newsStatus">-</div><div class="s" id="newsSub"></div></div>
 <div class="stat"><div class="k">조회 Top20 교체율</div><div class="v" id="turnover">-</div><div class="s">관심 순환 속도</div></div>
 <div class="stat"><div class="k">미모사 엔진</div><div class="v" id="mimosaStatus">-</div><div class="s" id="mimosaSub"></div></div>
</div>

<div class="tabs" id="tabs">
 <button class="tab active" data-view="home">홈</button>
 <button class="tab" data-view="index">지수</button>
 <button class="tab" data-view="query">조회순위</button>
 <button class="tab" data-view="sector">섹터</button>
 <button class="tab" data-view="trade">거래대금</button>
 <button class="tab" data-view="material">재료·뉴스</button>
 <button class="tab" data-view="research">리서치</button>
 <button class="tab" data-view="mimosa">미모사</button>
</div>

<section class="view active" id="view-home">
 <div class="section-title"><h2>시장 해석</h2><span>조회관심 · 거래대금 · 재료를 종합</span></div>
 <div class="analysis">
  <div class="panel pad analysis-main" id="analysis"></div>
  <div class="panel pad"><div class="legend" id="quickSignals"></div><div class="sub" style="margin-top:8px">※ 매수·매도 신호가 아니라 현재 상태를 설명하는 레이더입니다.</div></div>
 </div>
 <div class="section-title"><h2>실시간 섹터 보드</h2><span>조회순위 집중 기준</span></div>
 <div class="sector-grid" id="homeSectors"></div>
 <div class="section-title"><h2>급부상 종목</h2><span>조회 + 거래대금 + 재료</span></div>
 <div class="panel"><div class="tblwrap"><table class="tbl"><thead><tr><th>조회</th><th class="left">종목</th><th>등락</th><th>대금순위</th><th>거래대금</th><th class="left">섹터</th><th class="left">흐름</th><th class="left">재료 요약</th><th class="left">미모사</th></tr></thead><tbody id="homeStocks"></tbody></table></div></div>
</section>

<section class="view" id="view-index">
 <div class="section-title"><h2>KOSPI · KOSDAQ 지수차트</h2><span>Kiwoom ka20005 분봉 / ka20006 일봉</span></div>
 <div class="index-grid">
  <div class="chart-card"><div class="chart-title"><div><b>KOSPI · 5분</b><div class="sub">장중 흐름</div></div><div id="kospiIntraLast"></div></div><div id="kospiIntra"></div></div>
  <div class="chart-card"><div class="chart-title"><div><b>KOSDAQ · 5분</b><div class="sub">장중 흐름</div></div><div id="kosdaqIntraLast"></div></div><div id="kosdaqIntra"></div></div>
  <div class="chart-card"><div class="chart-title"><div><b>KOSPI · 일봉</b><div class="sub">최근 120거래일</div></div><div id="kospiDailyLast"></div></div><div id="kospiDaily"></div></div>
  <div class="chart-card"><div class="chart-title"><div><b>KOSDAQ · 일봉</b><div class="sub">최근 120거래일</div></div><div id="kosdaqDailyLast"></div></div><div id="kosdaqDaily"></div></div>
 </div>
 <div class="panel pad" style="margin-top:8px"><b>지수 해석</b><div class="sub" style="margin-top:5px">지수 방향과 조회집중·거래대금 집중을 함께 봅니다. 지수 상승만으로 주도주 장세로 판단하지 않고, 대형주 집중인지 수급 확산인지 분리합니다.</div></div>
</section>

<section class="view" id="view-query">
 <div class="section-title"><h2>실시간 종목조회 순위</h2><span>사람들이 지금 무엇을 보고 있는가</span></div>
 <div class="panel"><div class="tblwrap"><table class="tbl"><thead><tr><th>순위</th><th>변화</th><th class="left">종목</th><th>등락</th><th>거래대금</th><th>시총대비*</th><th class="left">섹터</th><th class="left">흐름</th><th class="left">재료</th><th class="left">미모사</th></tr></thead><tbody id="queryRows"></tbody></table></div></div>
</section>

<section class="view" id="view-sector">
 <div class="section-title"><h2>섹터별 실시간 순위</h2><span>조회상위 종목의 섹터 집중도</span></div>
 <div class="sector-grid" id="sectorBoard"></div>
 <div class="section-title"><h2>공식 업종 데이터</h2><span>키움 업종 등락·거래대금</span></div>
 <div class="panel"><div class="tblwrap"><table class="tbl"><thead><tr><th class="left">업종</th><th>등락</th><th>거래대금</th><th>상승</th><th>하락</th></tr></thead><tbody id="officialSectors"></tbody></table></div></div>
</section>

<section class="view" id="view-trade">
 <div class="section-title"><h2>거래대금 순위 · 주식</h2><span>ETF/ETN 제외, 실제 종목 수급 중심</span></div>
 <div class="panel"><div class="tblwrap"><table class="tbl"><thead><tr><th>대금순위</th><th class="left">종목</th><th>등락</th><th>거래대금</th><th>조회순위</th><th>시총대비*</th><th class="left">섹터</th><th class="left">흐름</th><th class="left">재료 요약</th><th class="left">미모사</th></tr></thead><tbody id="tradeRows"></tbody></table></div></div>
 <div class="section-title"><h2>ETF / ETN 거래대금</h2><span>시장 방향성 참고용으로 분리</span></div>
 <div class="panel"><div class="tblwrap"><table class="tbl"><thead><tr><th>대금순위</th><th class="left">ETF/ETN</th><th>등락</th><th>거래대금</th><th class="left">비고</th></tr></thead><tbody id="etfTradeRows"></tbody></table></div></div>
</section>

<section class="view" id="view-material">
 <div class="section-title"><h2>재료·뉴스 종합</h2><span>원문 나열보다 요약·판정 먼저</span></div>
 <div class="material-grid" id="materials"></div>
</section>

<section class="view" id="view-research">
 <div class="section-title"><h2>Research Agent 큐</h2><span>조회 급등 · 거래대금 신규진입 · 돈 선행 재료미확인 자동 감지</span></div>
 <div class="panel pad" style="margin-bottom:8px"><b id="researchStatus">Research Engine 대기</b><div class="sub" style="margin-top:5px">현재 단계는 Mac mini의 로컬 데이터로 우선순위를 만들고 근거를 묶는 LOCAL_RULES 모드입니다. 외부 심층 AI 조사는 별도 브리지를 붙일 종목만 표시합니다.</div></div>
 <div class="research-grid" id="researchCards"></div>
</section>

<section class="view" id="view-mimosa">
 <div class="section-title"><h2>미모사 · 기본 차트 상태</h2><span>M수렴 · 전고 · 추세 · 돌파</span></div>
 <div class="panel pad" style="margin-bottom:8px"><b>기본 기준</b><div class="legend" style="margin-top:7px"><span class="pill">M 수렴</span><span class="pill">M 수렴 후 돌파</span><span class="pill">전고점 접근</span><span class="pill">돌파 후 지지</span><span class="pill">분봉 추세 유지</span><span class="pill">추세 훼손</span></div></div>
 <div class="mimosa-grid" id="mimosaCards"></div>

 <div class="section-title"><h2>종가베팅 레이더</h2><span>NXT 당일 주도주 · 거래대금+신고가 · KRX 연속상승</span></div>
 <div class="panel pad" style="margin-bottom:8px"><div class="sub">5강 강사 피드백을 중심으로 분봉 추세 유지, 거래대금, 신고가/연속상승을 분리해 표시합니다. 시스템의 수치 임계값은 검증용 운영값입니다.</div></div>
 <div class="strategy-grid" id="closeBetCards"></div>

 <div class="section-title"><h2>과대낙폭 레이더</h2><span>최근 주도주 · 중기 고점 대비 하락 · 관심 유지</span></div>
 <div class="panel pad" style="margin-bottom:8px"><div class="sub">최근 주도주가 고점 대비 크게 밀린 뒤에도 조회·거래대금 관심이 남아 있는지를 감시합니다. 25~45% 낙폭 등 수치는 운영 v1이며 즉시 진입 신호가 아닙니다.</div></div>
 <div class="strategy-grid" id="oversoldCards"></div>

 <div class="section-title"><h2>낙주 레이더</h2><span>당일 강세주가 장중 급락하는 구조</span></div>
 <div class="panel pad" style="margin-bottom:8px"><div class="sub">과대낙폭과 분리합니다. 당일 거래대금·조회 관심이 유지된 강세주가 고점 대비 급락했는지, 최근 분봉에서 매도 속도가 둔화되는지를 감시합니다.</div></div>
 <div class="strategy-grid" id="fallingCards"></div>
</section>
</div>

<div class="bottom" id="bottom">
 <button class="active" data-view="home"><b>⌂</b>홈</button><button data-view="index"><b>⌁</b>지수</button><button data-view="query"><b>⌕</b>조회</button><button data-view="sector"><b>▦</b>섹터</button><button data-view="trade"><b>₩</b>대금</button><button data-view="material"><b>◆</b>재료</button><button data-view="research"><b>R</b>리서치</button><button data-view="mimosa"><b>M</b>미모사</button>
</div>

<script>
let token=location.hash.slice(1)||localStorage.getItem("marketRadarToken")||"";
if(location.hash){localStorage.setItem("marketRadarToken",token);history.replaceState(null,"",location.pathname);}
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));
const fmt=(v,d=1)=>v==null?"-":Number(v).toLocaleString("ko-KR",{maximumFractionDigits:d});
const rate=v=>v==null?"-":fmt(v)+"%";
const klass=v=>Number(v)>0?"hot":Number(v)<0?"bad":"";
const money=v=>v==null?"-":fmt(Number(v)/1e8)+"억";
const pct=v=>v==null?"-":(Number(v)*100).toFixed(1)+"%";
let DATA=null;

function setView(name){
 document.querySelectorAll(".view").forEach(x=>x.classList.toggle("active",x.id==="view-"+name));
 document.querySelectorAll("[data-view]").forEach(x=>x.classList.toggle("active",x.dataset.view===name));
}
document.querySelectorAll("[data-view]").forEach(b=>b.onclick=()=>setView(b.dataset.view));

async function sendFeedback(category,stock,predicted,verdict,btn){
 try{
  const r=await fetch("/api/feedback",{method:"POST",headers:{"content-type":"application/json","x-dashboard-token":token},
    body:JSON.stringify({category:category,stock_code:stock,predicted_state:predicted,verdict:verdict})});
  if(!r.ok)throw new Error("HTTP "+r.status);
  if(btn){btn.classList.add("sent");btn.textContent="저장됨";}
 }catch(e){if(btn)btn.textContent="실패";console.error(e);}
}


function digest(x){return x?.material_digest||x?.digest||{}}
function sectorCards(list,limit=8){
 return (list||[]).slice(0,limit).map(g=>{
   const stocks=(g.stocks||[]).slice(0,6).map(x=>'<div class="stock-mini"><div class="name">'+esc(x.name||x.code)+'</div><div class="num"><span class="rank-badge">#'+esc(x.rank??"-")+'</span><span class="'+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</span></div></div>').join("");
   return '<div class="sector-card"><div class="sector-head"><div><strong>'+esc(g.name)+'</strong><div class="sector-meta">조회상위 '+esc(g.count)+'종목 · 평균 #'+esc(g.avg_rank==null?"-":Number(g.avg_rank).toFixed(1))+'</div></div><div class="'+klass(g.avg_change_rate)+'"><b>'+esc(rate(g.avg_change_rate))+'</b></div></div><div class="stock-list">'+stocks+'</div></div>';
 }).join("")||'<div class="panel pad muted">섹터 데이터 대기 중</div>';
}
function stockRow(x,mode){
 const d=digest(x), q=x.rank??x.query_rank, t=x.trade_rank;
 const c=x.mimosa||{};
 const first=mode==="trade"?'<td>'+esc(t??"-")+'</td>':'<td>'+esc(q??"-")+'</td>';
 const change=(mode==="query")?'<td class="'+(Number(x.rank_change)>0?"hot":Number(x.rank_change)<0?"bad":"")+'">'+esc(x.rank_change==null?"-":(x.rank_change>0?"↑":"↓")+Math.abs(x.rank_change))+'</td>':"";
 return '<tr>'+first+change+
 '<td class="left"><span class="stockname">'+esc(x.name||x.code)+'</span><div class="sub">'+esc(x.code)+'</div></td>'+
 '<td class="'+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</td>'+
 (mode==="query"?'<td>'+esc(money(x.trade_value_krw))+'</td>':'<td>'+esc(money(x.trade_value_krw))+'</td><td>'+esc(q??"-")+'</td>')+
 '<td>'+esc(x.trade_to_cap_pct==null?"-":Number(x.trade_to_cap_pct).toFixed(1)+"%")+'</td>'+
 '<td class="left">'+esc(x.official_sector||x.market_theme||x.sector||"미분류")+'</td>'+
 '<td class="left"><span class="pill">'+esc(x.flow_state||"관찰")+'</span></td>'+
 '<td class="wrap"><b>'+esc(d.summary||"재료 미확인")+'</b><div class="sub">'+esc(d.assessment||"")+'</div></td>'+
 '<td class="left"><b>'+esc(c.state_ko||x.chart_state||"대기")+'</b><div class="sub">'+esc(c.minute_trend||"")+'</div></td></tr>';
}
function renderHomeStocks(rows){
 return (rows||[]).slice(0,12).map(x=>{
   const d=digest(x),m=x.mimosa||{};
   return '<tr><td>#'+esc(x.rank??"-")+'</td><td class="left"><b>'+esc(x.name||x.code)+'</b></td><td class="'+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</td><td>'+esc(x.trade_rank??"-")+'</td><td>'+esc(money(x.trade_value_krw))+'</td><td class="left">'+esc(x.official_sector||x.market_theme||"미분류")+'</td><td class="left"><span class="pill">'+esc(x.flow_state||"관찰")+'</span></td><td class="wrap">'+esc(d.summary||"직접 재료 미확인")+'</td><td class="left">'+esc(m.state_ko||x.chart_state||"대기")+'</td></tr>';
 }).join("")||'<tr><td colspan="9" class="muted">장중 실시간 데이터 대기 중</td></tr>';
}
function evidence(c){
 let out="";
 (c?.dart||[]).slice(0,5).forEach(d=>{out+='<div class="evidence"><b>DART · '+esc(d.category||"공시")+'</b><p>'+esc(d.report_nm||"")+'</p><div class="links">'+(d.link?'<a href="'+esc(d.link)+'" target="_blank">공시 열기</a>':"")+'</div></div>'});
 (c?.external_news||[]).slice(0,5).forEach(n=>{out+='<div class="evidence"><b>'+esc(n.source||"뉴스")+'</b><p>'+esc(n.title||"")+'</p><div class="links"><a href="'+esc(n.link)+'" target="_blank">기사 열기</a></div></div>'});
 (c?.items||[]).slice(0,4).forEach(i=>{out+='<div class="evidence"><b>'+esc(i.channel||"Telegram")+'</b><p>'+esc(i.text||"")+'</p><div class="links">'+(i.telegram_url?'<a href="'+esc(i.telegram_url)+'" target="_blank">원문</a>':"")+'</div></div>'});
 return out;
}
function materialCards(list){
 return (list||[]).slice(0,30).map(x=>{
   const d=x.digest||{},c=x.catalyst||{};
   return '<article class="material-card"><div class="material-top"><h3>'+esc(x.name||x.code)+'</h3><span class="'+klass(x.change_rate)+'"><b>'+esc(rate(x.change_rate))+'</b></span></div><div class="sub">조회 #'+esc(x.query_rank??"-")+' · 대금 #'+esc(x.trade_rank??"-")+' · '+esc(x.sector||"미분류")+'</div><div class="material-summary">'+esc(d.summary||"직접 재료 미확인")+'</div><div class="legend"><span class="pill">'+esc(d.assessment||"미확인")+'</span><span class="pill">'+esc(d.newness||"")+'</span><span class="pill">'+esc(x.flow_state||"관찰")+'</span></div><div class="material-why"><b>'+esc(d.market_response||"")+'</b><div style="margin-top:4px">'+esc(d.synthesis||d.interpretation||"추가 확인 필요")+'</div><div class="sub" style="margin-top:4px">'+esc(d.quality_note||"")+'</div></div><details><summary>근거 원문·기사 보기</summary>'+evidence(c)+'</details><div class="fb"><button onclick="sendFeedback(\'material\',\''+esc(x.code)+'\',\''+esc(d.assessment||"")+'\',\'correct\',this)">재료 맞음</button><button onclick="sendFeedback(\'material\',\''+esc(x.code)+'\',\''+esc(d.assessment||"")+'\',\'wrong\',this)">재료 아님</button></div></article>';
 }).join("")||'<div class="panel pad muted">재료 데이터 대기 중</div>';
}
function mimosaCards(list){
 return (list||[]).slice(0,30).map(x=>{
   const reasons=(x.reasons||[]).map(r=>'<span class="pill">'+esc(r)+'</span>').join("");
   return '<div class="m-card"><div class="m-head"><div><b>'+esc(x.name||x.code)+'</b><div class="sub">조회 #'+esc(x.query_rank??"-")+' · 대금 #'+esc(x.trade_rank??"-")+'</div></div><div class="score">'+esc(Math.round(Number(x.score||0)))+'</div></div><div class="m-state">'+esc(x.state_ko||"차트 데이터 대기")+'</div><div class="sub">'+esc(x.minute_trend||"분봉 미확인")+' · '+esc(x.daily_context||"일봉 미확인")+'</div><div class="reason">'+reasons+'</div><div class="fb"><button onclick="sendFeedback(\'mimosa\',\''+esc(x.code)+'\',\''+esc(x.state||x.state_ko||"")+'\',\'correct\',this)">판독 맞음</button><button onclick="sendFeedback(\'mimosa\',\''+esc(x.code)+'\',\''+esc(x.state||x.state_ko||"")+'\',\'wrong\',this)">판독 아님</button></div></div>';
 }).join("")||'<div class="panel pad muted">미모사 차트 데이터 대기 중</div>';
}

function renderEtfRows(rows){
 return (rows||[]).slice(0,30).map(x=>
   '<tr><td>'+esc(x.trade_rank??"-")+'</td><td class="left"><b>'+esc(x.name||x.code)+'</b><div class="sub">'+esc(x.code||"")+'</div></td><td class="'+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</td><td>'+esc(money(x.trade_value_krw))+'</td><td class="left"><span class="pill">ETF/ETN 분리</span></td></tr>'
 ).join("")||'<tr><td colspan="5" class="muted">ETF/ETN 데이터 없음</td></tr>';
}


function sparkChart(rows,key,labelMode){
 const pts=(rows||[]).filter(x=>x[key]!=null);
 if(pts.length<2)return '<div class="muted" style="padding:70px 10px;text-align:center">차트 데이터 대기</div>';
 const vals=pts.map(x=>Number(x[key])); const min=Math.min(...vals),max=Math.max(...vals),span=(max-min)||1;
 const W=600,H=210,P=18;
 const xy=vals.map((v,i)=>[(P+(W-2*P)*i/(vals.length-1)),(P+(H-2*P)*(1-(v-min)/span))]);
 const path=xy.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ');
 const first=vals[0],last=vals[vals.length-1],chg=first?((last/first-1)*100):0;
 return '<svg class="svgchart" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+
   '<line x1="'+P+'" y1="'+P+'" x2="'+P+'" y2="'+(H-P)+'" stroke="#dce3ee"/>'+
   '<line x1="'+P+'" y1="'+(H-P)+'" x2="'+(W-P)+'" y2="'+(H-P)+'" stroke="#dce3ee"/>'+
   '<path d="'+path+'" fill="none" stroke="#345c9c" stroke-width="2.2" vector-effect="non-scaling-stroke"/>'+
   '<text x="'+(P+3)+'" y="'+(P+11)+'" font-size="10" fill="#6f7c90">'+max.toFixed(2)+'</text>'+
   '<text x="'+(P+3)+'" y="'+(H-P-5)+'" font-size="10" fill="#6f7c90">'+min.toFixed(2)+'</text>'+
   '<text x="'+(W-P-90)+'" y="'+(P+11)+'" font-size="11" fill="'+(chg>=0?'#e25555':'#4577d4')+'">'+(chg>=0?'+':'')+chg.toFixed(2)+'%</text>'+
   '</svg>';
}
function lastValue(rows,key){
 const p=(rows||[]).filter(x=>x[key]!=null); if(!p.length)return "-";
 const v=Number(p[p.length-1][key]); const first=Number(p[0][key]); const chg=first?((v/first-1)*100):0;
 return '<b>'+fmt(v,2)+'</b> <span class="'+klass(chg)+'">'+(chg>=0?'+':'')+chg.toFixed(2)+'%</span>';
}
function strategyCards(list,kind){
 const rows=(list||[]).filter(x=>!(x.state||"").endsWith("_NO")).slice(0,18);
 if(!rows.length)return '<div class="panel pad muted">현재 조건에 가까운 종목이 없습니다.</div>';
 return rows.map(x=>{
   const rs=(x.reasons||[]).map(r=>'<span class="pill">'+esc(r)+'</span>').join("");
   const m=x.metrics||{};
   let metric="";
   if(kind==="close")metric='대금 #'+esc(m.trade_rank??"-")+' · '+esc(m.nxt_enabled?"NXT 가능":"KRX형")+(m.close_location!=null?' · 종가위치 '+(Number(m.close_location)*100).toFixed(0)+'%':'');
   if(kind==="oversold")metric='고점대비 '+esc(m.drawdown_pct==null?"-":Number(m.drawdown_pct).toFixed(1)+"%")+' · 조회 #'+esc(m.query_rank??"-")+' · 대금 #'+esc(m.trade_rank??"-");
   if(kind==="falling")metric='당일고점대비 '+esc(m.day_drawdown_pct==null?"-":Number(m.day_drawdown_pct).toFixed(1)+"%")+' · 선행상승 '+esc(m.prior_run_pct==null?"-":Number(m.prior_run_pct).toFixed(1)+"%");
   return '<article class="strategy-card"><div class="material-top"><h3>'+esc(x.name||x.code)+'</h3><span class="strategy-score">'+Math.round(Number(x.score||0))+'</span></div><div class="sub">조회 #'+esc(x.query_rank??"-")+' · 대금 #'+esc(x.trade_rank??"-")+' · '+esc(x.sector||"미분류")+'</div><div class="m-state">'+esc(x.state_ko||x.state)+'</div><div class="sub" style="margin-top:3px">'+metric+'</div><div class="reason">'+rs+'</div><div class="strategy-note">'+esc(x.source_note||"")+'</div><div class="fb"><button onclick="sendFeedback(\'mimosa\',\''+esc(x.code)+'\',\''+esc(x.state||"")+'\',\'correct\',this)">판독 맞음</button><button onclick="sendFeedback(\'mimosa\',\''+esc(x.code)+'\',\''+esc(x.state||"")+'\',\'wrong\',this)">판독 아님</button></div></article>';
 }).join("");
}


function researchCards(rows){
 if(!(rows||[]).length)return '<div class="panel pad muted">현재 Research Agent 트리거가 없습니다.</div>';
 return (rows||[]).map(x=>{
   const triggers=(x.triggers||[]).map(t=>'<span class="pill">'+esc(t)+'</span>').join("");
   const evidence=(x.evidence||[]).slice(0,5).map(e=>'<div class="evidence"><b>'+esc(e.source||e.type||"근거")+'</b><p>'+esc(e.title||"")+'</p>'+(e.link?'<a href="'+esc(e.link)+'" target="_blank">원문</a>':"")+'</div>').join("");
   return '<article class="research-card"><div class="material-top"><div><h3>'+esc(x.name||x.code)+'</h3><div class="sub">'+esc(x.created_at?new Date(x.created_at).toLocaleString("ko-KR"):"")+'</div></div><div class="priority">'+esc(x.priority)+'</div></div><div class="legend" style="margin-top:7px">'+triggers+(x.deep_research_needed?'<span class="pill deep">심층조사 필요</span>':'')+'</div><div class="material-summary">'+esc(x.headline||"")+'</div><div class="material-why">'+esc(x.summary||"")+'</div><details><summary>수집 근거 보기 · '+esc((x.evidence||[]).length)+'건</summary>'+evidence+'</details></article>';
 }).join("");
}

function render(d){
 DATA=d;
 document.getElementById("stamp").textContent=new Date(d.generated_at).toLocaleString("ko-KR");
 const label=d.regime.stable_label||d.regime.candidate_label||d.regime.status;
 document.getElementById("regime").textContent=label;
 document.getElementById("regimeSub").textContent=d.regime.note||"";
 const snap=d.market_snapshot||{};
 const liveText=snap.is_live?"LIVE":(snap.session_label||"장외");
 document.getElementById("kiwoom").textContent=d.system.kiwoom.status+" · "+liveText;
 document.getElementById("kiwoomSub").textContent=(snap.time?"수집 "+new Date(snap.time).toLocaleString("ko-KR"):"")+(snap.stale?" · 지연":"")+(d.system.kiwoom.note?" · "+d.system.kiwoom.note:"");
 const ms=d.material_stats||{};
 document.getElementById("newsStatus").textContent="직접 "+(ms.direct||0)+" · 테마 "+(ms.sector||0);
 const ds=d.system.dartfeed||{};
 document.getElementById("newsSub").textContent="확산 "+(ms.spreading||0)+" · 약한언급 "+(ms.weak||0)+" · DART "+(ds.status||"미연결")+" · Telegram "+(d.system.telegram.count_24h||0).toLocaleString()+"건";
 document.getElementById("turnover").textContent=d.regime_metrics?.rank_turnover_5m==null?"-":pct(d.regime_metrics.rank_turnover_5m);
 document.getElementById("mimosaStatus").textContent=d.system.mimosa?.status||"미연결";
 const re=d.system.research||{};
 const rsEl=document.getElementById("researchStatus");
 if(rsEl)rsEl.textContent="Research Engine "+(re.status||"미연결")+(re.note?" · "+re.note:"");
 document.getElementById("mimosaSub").textContent=d.system.chartfeed?.status?"차트 "+d.system.chartfeed.status:"";
 document.getElementById("analysis").innerHTML=(d.analysis?.lines||[]).map(x=>'<div class="analysis-line">'+esc(x)+'</div>').join("")||'<span class="muted">시장 분석 대기</span>';
 const sig=[];
 if((d.sector_rankings||[])[0])sig.push("조회집중 "+d.sector_rankings[0].name);
 const noMat=(d.query_ranking||[]).filter(x=>x.flow_state==="돈 선행 / 재료 미확인").length;
 if(noMat)sig.push("돈선행 "+noMat+"종목");
 if((d.material_stats?.direct||0)>0)sig.push("직접재료 "+d.material_stats.direct+"종목");
 if((d.material_stats?.spreading||0)>0)sig.push("확산 "+d.material_stats.spreading+"종목");
 if(d.regime_metrics?.rank_turnover_5m!=null)sig.push("교체율 "+pct(d.regime_metrics.rank_turnover_5m));
 document.getElementById("quickSignals").innerHTML=sig.map(x=>'<span class="pill">'+esc(x)+'</span>').join("");
 document.getElementById("homeSectors").innerHTML=sectorCards(d.sector_rankings,8);
 document.getElementById("sectorBoard").innerHTML=sectorCards(d.sector_rankings,20);
 document.getElementById("homeStocks").innerHTML=renderHomeStocks(d.query_ranking);
 document.getElementById("queryRows").innerHTML=(d.query_ranking||[]).map(x=>stockRow(x,"query")).join("")||'<tr><td colspan="10">데이터 대기</td></tr>';
 document.getElementById("tradeRows").innerHTML=(d.trade_ranking||[]).map(x=>stockRow(x,"trade")).join("")||'<tr><td colspan="10">데이터 대기</td></tr>';
 document.getElementById("etfTradeRows").innerHTML=renderEtfRows(d.etf_trade_ranking);
 document.getElementById("officialSectors").innerHTML=(d.sectors||[]).map(x=>'<tr><td class="left"><b>'+esc(x.name)+'</b></td><td class="'+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</td><td>'+esc(money(x.trade_value_krw))+'</td><td>'+esc(x.rising??"-")+'</td><td>'+esc(x.falling??"-")+'</td></tr>').join("");
 document.getElementById("materials").innerHTML=materialCards(d.materials);
 document.getElementById("researchCards").innerHTML=researchCards(d.research_rows);
 document.getElementById("mimosaCards").innerHTML=mimosaCards(d.mimosa_rows);
 const ix=d.index_charts||{};
 const kp=ix.KOSPI||{}, kq=ix.KOSDAQ||{};
 document.getElementById("kospiIntra").innerHTML=sparkChart(kp.intraday,"close","time");
 document.getElementById("kosdaqIntra").innerHTML=sparkChart(kq.intraday,"close","time");
 document.getElementById("kospiDaily").innerHTML=sparkChart(kp.daily,"close","date");
 document.getElementById("kosdaqDaily").innerHTML=sparkChart(kq.daily,"close","date");
 document.getElementById("kospiIntraLast").innerHTML=lastValue(kp.intraday,"close");
 document.getElementById("kosdaqIntraLast").innerHTML=lastValue(kq.intraday,"close");
 document.getElementById("kospiDailyLast").innerHTML=lastValue(kp.daily,"close");
 document.getElementById("kosdaqDailyLast").innerHTML=lastValue(kq.daily,"close");
 const msig=d.mimosa_strategies||{};
 document.getElementById("closeBetCards").innerHTML=strategyCards(msig.CLOSE_BET,"close");
 document.getElementById("oversoldCards").innerHTML=strategyCards(msig.OVERSOLD,"oversold");
 document.getElementById("fallingCards").innerHTML=strategyCards(msig.FALLING_STOCK,"falling");
}
async function load(){
 if(!token){document.getElementById("regime").textContent="접속키 필요";return;}
 try{const r=await fetch("/api/dashboard",{headers:{"x-dashboard-token":token}});if(!r.ok)throw new Error("HTTP "+r.status);render(await r.json());}
 catch(e){document.getElementById("kiwoom").textContent="연결 오류";console.error(e);}
}
load();setInterval(load,10000);
</script></body></html>"""
