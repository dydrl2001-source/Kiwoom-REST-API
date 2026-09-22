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
.material-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.material-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:11px}
.material-top{display:flex;justify-content:space-between;gap:6px}.material-card h3{font-size:14px;margin:0}.material-summary{font-weight:750;margin:8px 0 5px;line-height:1.5}.material-why{font-size:11px;color:#516078;background:#f6f8fb;padding:7px;border-radius:7px}
details{margin-top:7px}summary{cursor:pointer;color:#526785;font-size:11px}.evidence{border-top:1px solid #edf1f6;margin-top:7px;padding-top:7px;font-size:11px}.evidence p{margin:4px 0}.links{display:flex;gap:7px;flex-wrap:wrap}
.mimosa-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.m-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px}.m-head{display:flex;justify-content:space-between}.m-state{font-size:13px;font-weight:900;margin-top:6px}.score{font-weight:900}.reason{font-size:10px;color:var(--muted);margin-top:5px}
.bottom{display:none}
@media(max-width:1100px){.sector-grid{grid-template-columns:repeat(2,1fr)}.material-grid{grid-template-columns:repeat(2,1fr)}.mimosa-grid{grid-template-columns:repeat(2,1fr)}.statusbar{grid-template-columns:1fr 1fr 1fr}.analysis{grid-template-columns:1fr}}
@media(max-width:700px){
 .app{padding:10px 8px 82px}.head{margin-bottom:6px}.brand{font-size:20px}.statusbar{grid-template-columns:1fr 1fr;gap:6px}.stat{min-height:61px;padding:8px}
 .statusbar .stat:first-child{grid-column:1/-1}.tabs{display:none}.sector-grid{grid-template-columns:1fr 1fr;gap:6px}.stock-list{grid-template-columns:1fr}.stock-mini{border-right:0}
 .material-grid,.mimosa-grid{grid-template-columns:1fr}.section-title{margin-top:10px}.bottom{display:flex;position:fixed;bottom:0;left:0;right:0;z-index:40;background:#fff;border-top:1px solid var(--line);padding:5px 4px calc(5px + env(safe-area-inset-bottom));justify-content:space-around}
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
 <button class="tab" data-view="query">조회순위</button>
 <button class="tab" data-view="sector">섹터</button>
 <button class="tab" data-view="trade">거래대금</button>
 <button class="tab" data-view="material">재료·뉴스</button>
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
 <div class="section-title"><h2>거래대금 순위</h2><span>관심이 아니라 실제 돈의 순위</span></div>
 <div class="panel"><div class="tblwrap"><table class="tbl"><thead><tr><th>대금순위</th><th class="left">종목</th><th>등락</th><th>거래대금</th><th>조회순위</th><th>시총대비*</th><th class="left">섹터</th><th class="left">흐름</th><th class="left">재료 요약</th><th class="left">미모사</th></tr></thead><tbody id="tradeRows"></tbody></table></div></div>
</section>

<section class="view" id="view-material">
 <div class="section-title"><h2>재료·뉴스 종합</h2><span>원문 나열보다 요약·판정 먼저</span></div>
 <div class="material-grid" id="materials"></div>
</section>

<section class="view" id="view-mimosa">
 <div class="section-title"><h2>미모사 차트 상태</h2><span>강의 원칙을 기반으로 한 내부 상태 분류</span></div>
 <div class="panel pad" style="margin-bottom:8px"><b>핵심 기준</b><div class="legend" style="margin-top:7px"><span class="pill">M 수렴</span><span class="pill">M 수렴 후 돌파 시도</span><span class="pill">전고점 접근</span><span class="pill">돌파 후 지지</span><span class="pill">분봉 추세 유지</span><span class="pill">분봉 추세 훼손</span></div><div class="sub" style="margin-top:7px">미모사 2강의 M 수렴·급등 초입 관점과 5강 피드백의 ‘거래대금·신고가·분봉 추세 유지’ 원칙을 상태 분류로 옮긴 것입니다.</div></div>
 <div class="mimosa-grid" id="mimosaCards"></div>
</section>
</div>

<div class="bottom" id="bottom">
 <button class="active" data-view="home"><b>⌂</b>홈</button><button data-view="query"><b>⌕</b>조회</button><button data-view="sector"><b>▦</b>섹터</button><button data-view="trade"><b>₩</b>대금</button><button data-view="material"><b>◆</b>재료</button><button data-view="mimosa"><b>M</b>미모사</button>
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
 (c?.external_news||[]).slice(0,5).forEach(n=>{out+='<div class="evidence"><b>'+esc(n.source||"뉴스")+'</b><p>'+esc(n.title||"")+'</p><div class="links"><a href="'+esc(n.link)+'" target="_blank">기사 열기</a></div></div>'});
 (c?.items||[]).slice(0,4).forEach(i=>{out+='<div class="evidence"><b>'+esc(i.channel||"Telegram")+'</b><p>'+esc(i.text||"")+'</p><div class="links">'+(i.telegram_url?'<a href="'+esc(i.telegram_url)+'" target="_blank">원문</a>':"")+'</div></div>'});
 return out;
}
function materialCards(list){
 return (list||[]).slice(0,30).map(x=>{
   const d=x.digest||{},c=x.catalyst||{};
   return '<article class="material-card"><div class="material-top"><h3>'+esc(x.name||x.code)+'</h3><span class="'+klass(x.change_rate)+'"><b>'+esc(rate(x.change_rate))+'</b></span></div><div class="sub">조회 #'+esc(x.query_rank??"-")+' · 대금 #'+esc(x.trade_rank??"-")+' · '+esc(x.sector||"미분류")+'</div><div class="material-summary">'+esc(d.summary||"직접 재료 미확인")+'</div><div class="legend"><span class="pill">'+esc(d.assessment||"미확인")+'</span><span class="pill">'+esc(x.flow_state||"관찰")+'</span></div><div class="material-why">'+esc(d.interpretation||"추가 확인 필요")+'<div class="sub" style="margin-top:4px">'+esc(d.quality_note||"")+'</div></div><details><summary>근거 원문·기사 보기</summary>'+evidence(c)+'</details></article>';
 }).join("")||'<div class="panel pad muted">재료 데이터 대기 중</div>';
}
function mimosaCards(list){
 return (list||[]).slice(0,30).map(x=>{
   const reasons=(x.reasons||[]).map(r=>'<span class="pill">'+esc(r)+'</span>').join("");
   return '<div class="m-card"><div class="m-head"><div><b>'+esc(x.name||x.code)+'</b><div class="sub">조회 #'+esc(x.query_rank??"-")+' · 대금 #'+esc(x.trade_rank??"-")+'</div></div><div class="score">'+esc(Math.round(Number(x.score||0)))+'</div></div><div class="m-state">'+esc(x.state_ko||"차트 데이터 대기")+'</div><div class="sub">'+esc(x.minute_trend||"분봉 미확인")+' · '+esc(x.daily_context||"일봉 미확인")+'</div><div class="reason">'+reasons+'</div></div>';
 }).join("")||'<div class="panel pad muted">미모사 차트 데이터 대기 중</div>';
}
function render(d){
 DATA=d;
 document.getElementById("stamp").textContent=new Date(d.generated_at).toLocaleString("ko-KR");
 const label=d.regime.stable_label||d.regime.candidate_label||d.regime.status;
 document.getElementById("regime").textContent=label;
 document.getElementById("regimeSub").textContent=d.regime.note||"";
 const snap=d.market_snapshot||{};
 document.getElementById("kiwoom").textContent=d.system.kiwoom.status+(snap.stale?" · 마감/지연":" · LIVE");
 document.getElementById("kiwoomSub").textContent=(snap.time?"데이터 "+new Date(snap.time).toLocaleString("ko-KR"):"")+(d.system.kiwoom.note?" · "+d.system.kiwoom.note:"");
 const ms=d.material_stats||{};
 document.getElementById("newsStatus").textContent="직접 "+(ms.direct||0)+" · 테마 "+(ms.sector||0);
 document.getElementById("newsSub").textContent="확산 "+(ms.spreading||0)+" · 약한언급 "+(ms.weak||0)+" · Telegram "+(d.system.telegram.count_24h||0).toLocaleString()+"건";
 document.getElementById("turnover").textContent=d.regime_metrics?.rank_turnover_5m==null?"-":pct(d.regime_metrics.rank_turnover_5m);
 document.getElementById("mimosaStatus").textContent=d.system.mimosa?.status||"미연결";
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
 document.getElementById("officialSectors").innerHTML=(d.sectors||[]).map(x=>'<tr><td class="left"><b>'+esc(x.name)+'</b></td><td class="'+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</td><td>'+esc(money(x.trade_value_krw))+'</td><td>'+esc(x.rising??"-")+'</td><td>'+esc(x.falling??"-")+'</td></tr>').join("");
 document.getElementById("materials").innerHTML=materialCards(d.materials);
 document.getElementById("mimosaCards").innerHTML=mimosaCards(d.mimosa_rows);
}
async function load(){
 if(!token){document.getElementById("regime").textContent="접속키 필요";return;}
 try{const r=await fetch("/api/dashboard",{headers:{"x-dashboard-token":token}});if(!r.ok)throw new Error("HTTP "+r.status);render(await r.json());}
 catch(e){document.getElementById("kiwoom").textContent="연결 오류";console.error(e);}
}
load();setInterval(load,10000);
</script></body></html>"""
