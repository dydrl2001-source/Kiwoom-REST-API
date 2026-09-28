from __future__ import annotations

MOBILE_HTML = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#111c31">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Market Radar">
<link rel="manifest" href="/mobile/manifest.webmanifest">
<link rel="icon" href="/mobile/icon.svg" type="image/svg+xml">
<title>Market Radar Mobile</title>
<style>
:root{--bg:#f4f7fb;--panel:#fff;--line:#dce4ef;--ink:#142033;--muted:#718096;--red:#d8525a;--blue:#4676c9;--green:#18866b;--amber:#d28d2e;--purple:#775cc8;--nav:#111c31}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Pretendard","Noto Sans KR",Arial,sans-serif}body{padding:env(safe-area-inset-top) 0 calc(70px + env(safe-area-inset-bottom))}
button,input{font:inherit}.app{max-width:720px;margin:0 auto;padding:10px 12px 20px}.top{display:flex;align-items:center;justify-content:space-between;gap:8px}.brand{font-weight:950;font-size:20px;letter-spacing:-.5px}.live{font-size:10px;color:var(--green);font-weight:850}.stamp{font-size:9px;color:var(--muted)}
.hero{margin-top:9px;border-radius:14px;padding:13px;background:linear-gradient(135deg,#13213a,#29436e);color:#fff;box-shadow:0 8px 24px rgba(19,33,58,.16)}.hero-label{font-size:10px;color:#cdd8ea}.hero-main{font-size:18px;font-weight:900;margin-top:4px;line-height:1.35}.hero-sub{display:flex;gap:5px;flex-wrap:wrap;margin-top:9px}.hero-chip{font-size:9px;padding:4px 7px;border-radius:999px;background:rgba(255,255,255,.12);color:#eef4ff}
.grid4{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:8px}.mini{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:9px}.mini .k{font-size:9px;color:var(--muted)}.mini .v{font-size:14px;font-weight:900;margin-top:3px}.mini .s{font-size:9px;color:var(--muted);margin-top:2px;line-height:1.35}
.section{margin-top:16px}.section-head{display:flex;justify-content:space-between;align-items:end;gap:8px;margin-bottom:7px}.section-head h2{font-size:14px;margin:0}.section-head span{font-size:9px;color:var(--muted)}
.scrollx{display:flex;gap:7px;overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:3px}.scrollx::-webkit-scrollbar{display:none}
.theme{min-width:82%;scroll-snap-align:start;background:#fff;border:1px solid var(--line);border-radius:12px;padding:11px;position:relative;overflow:hidden}.theme:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--purple)}.theme-top{display:flex;justify-content:space-between;gap:8px}.theme-name{font-weight:900;font-size:14px}.strength{font-size:12px;font-weight:900}.bar{height:6px;background:#e9eef5;border-radius:99px;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:linear-gradient(90deg,#6d79db,#1a9d83)}.theme-meta{display:flex;gap:7px;flex-wrap:wrap;font-size:9px;color:var(--muted);margin-top:6px}.theme-reason{font-size:10px;line-height:1.5;margin-top:7px;color:#4f5e73}.theme-stocks{margin-top:7px;border-top:1px solid #edf2f7}.theme-stock{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:6px;padding:6px 0;border-top:1px solid #f1f4f8;font-size:10px}.theme-stock:first-child{border-top:0}.name{font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.up{color:var(--red)}.down{color:var(--blue)}
.list{background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}.row{display:grid;grid-template-columns:36px minmax(0,1fr) auto;gap:7px;padding:9px 10px;border-bottom:1px solid #edf2f7;align-items:start}.row:last-child{border-bottom:0}.rank{font-weight:950;font-size:12px}.move{font-size:8px;font-weight:900;display:block;margin-top:2px}.move.up{color:#c94e55}.move.down{color:#3f6fba}.move.new{color:#9a680f}.move.re{color:#19735b}.row-name{font-weight:900;font-size:12px}.row-sub{font-size:9px;color:var(--muted);margin-top:2px}.row-money{text-align:right;font-size:10px;font-weight:850}.material{margin-top:5px;font-size:10px;line-height:1.45}.tag{display:inline-flex;padding:2px 6px;border-radius:999px;font-size:8px;font-weight:850;margin-right:3px}.contract{background:#e8efff;color:#365ea7}.earnings{background:#e7f5ed;color:#197451}.product{background:#fff0df;color:#965a17}.policy{background:#f0e9fb;color:#704da3}.clinical{background:#ffe8ec;color:#a94055}.industry{background:#f3eafe;color:#7850a5}.unknown{background:#eef1f5;color:#667487}.os{margin-top:5px;background:#f3f4ff;border:1px solid #e0e3fb;border-radius:7px;padding:5px 6px;font-size:9px;color:#50577a;line-height:1.4}.signal{font-size:8px;font-weight:900;border-radius:999px;padding:2px 5px;margin-left:3px}.sig-top{background:#ffeded;color:#a73f46}.sig-bottom{background:#e8f1ff;color:#315fa7}
.calendar-scroll{overflow-x:auto}.calendar{min-width:520px;display:grid;grid-template-columns:repeat(5,1fr);border-left:1px solid #e7edf4;border-top:1px solid #e7edf4;background:#fff}.cal-head{font-size:9px;font-weight:850;color:#738096;text-align:center;padding:5px;border-right:1px solid #e7edf4;border-bottom:1px solid #e7edf4;background:#f8fafc}.cal-cell{min-height:66px;padding:5px;border-right:1px solid #e7edf4;border-bottom:1px solid #e7edf4}.cal-date{font-size:8px;color:#7c8798}.cal-theme{font-size:8px;font-weight:800;line-height:1.35;margin-top:3px}.source-links{display:flex;gap:6px;flex-wrap:wrap;margin-top:5px}.source-links a{font-size:8px;font-weight:850;color:#355fa4;text-decoration:none}.candidates{display:grid;gap:7px}.candidate{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px;border-left:4px solid #6f7fd6}.candidate-head{display:flex;justify-content:space-between;gap:7px}.score{font-size:20px;font-weight:950}.candidate-meta{font-size:9px;color:var(--muted);margin-top:3px}
.nav{position:fixed;z-index:50;left:0;right:0;bottom:0;padding:6px 10px calc(6px + env(safe-area-inset-bottom));background:rgba(255,255,255,.96);border-top:1px solid var(--line);backdrop-filter:blur(12px)}.nav-inner{max-width:720px;margin:0 auto;display:grid;grid-template-columns:repeat(5,1fr);gap:3px}.nav button{background:transparent;border:0;border-radius:9px;padding:7px 3px;font-size:9px;color:#68768a;font-weight:800}.nav button.active{background:#17253c;color:#fff}
.page{display:none}.page.active{display:block}.empty{padding:18px;text-align:center;font-size:10px;color:var(--muted)}.auth{position:fixed;inset:0;z-index:100;background:#f4f7fb;display:none;align-items:center;justify-content:center;padding:20px}.auth.show{display:flex}.auth-card{width:min(400px,100%);background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px}.auth-card h1{font-size:18px;margin:0 0 6px}.auth-card p{font-size:10px;color:var(--muted);line-height:1.5}.auth-card input{width:100%;border:1px solid #cbd6e4;border-radius:9px;padding:11px;margin:8px 0}.auth-card button{width:100%;border:0;background:#17253c;color:#fff;border-radius:9px;padding:11px;font-weight:850}
@media(min-width:650px){.theme{min-width:48%}.grid4{grid-template-columns:repeat(4,1fr)}}
</style>
</head>
<body>
<div class="auth" id="auth"><div class="auth-card"><h1>Market Radar</h1><p>Mac mini 대시보드의 읽기 전용 토큰을 한 번 입력하세요. 이 값은 이 기기의 localStorage에만 저장합니다.</p><input id="tokenInput" type="password" autocomplete="off" placeholder="DASHBOARD_TOKEN"><button id="saveToken">연결</button></div></div>
<main class="app">
 <header class="top"><div><div class="brand">MARKET RADAR</div><div class="stamp" id="stamp">연결 중</div></div><div class="live" id="live">● LIVE</div></header>
 <section class="hero"><div class="hero-label">오늘 장</div><div class="hero-main" id="headline">시장 데이터 연결 중</div><div class="hero-sub" id="heroChips"></div></section>
 <div class="grid4" id="statusCards"></div>
 <section id="page-home" class="page active">
   <div class="section"><div class="section-head"><h2>주도 테마</h2><span>강도 · 돈 · 이유</span></div><div class="scrollx" id="themes"></div></div>
   <div class="section"><div class="section-head"><h2>급부상 Top12</h2><span>순위변화 · 거래대금 · 재료</span></div><div class="list" id="surges"></div></div>
   <div class="section"><div class="section-head"><h2>관찰 후보 Top5</h2><span>추천/주문 아님</span></div><div class="candidates" id="candidates"></div></div>
 </section>
 <section id="page-themes" class="page"><div class="section"><div class="section-head"><h2>전체 테마</h2><span>강도순</span></div><div class="candidates" id="allThemes"></div></div><div class="section"><div class="section-head"><h2>최근 4주 주도섹터</h2><span>저장 이력 기준</span></div><div class="calendar-scroll" id="mobileCalendar"></div></div></section>
 <section id="page-money" class="page"><div class="section"><div class="section-head"><h2>거래대금 강세</h2><span>+4% 이상 · 대금순</span></div><div class="list" id="moneyLeaders"></div></div></section>
 <section id="page-watch" class="page"><div class="section"><div class="section-head"><h2>관찰 후보</h2><span>현재 유지 중</span></div><div class="candidates" id="allCandidates"></div></div></section>
 <section id="page-status" class="page"><div class="section"><div class="section-head"><h2>수집 상태</h2><span>읽기 전용</span></div><div class="grid4" id="systemCards"></div><div style="margin-top:10px"><a href="/" style="font-size:11px;color:#345fa5">데스크톱 전체 화면 열기 →</a></div></div></section>
</main>
<nav class="nav"><div class="nav-inner"><button data-page="home" class="active">홈</button><button data-page="themes">테마</button><button data-page="money">대금</button><button data-page="watch">후보</button><button data-page="status">상태</button></div></nav>
<script>
var q=function(id){return document.getElementById(id)};
var esc=function(v){return String(v==null?"":v).replace(/[&<>"']/g,function(m){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]})};
var fmt=function(n,d){d=d==null?1:d;return Number.isFinite(Number(n))?Number(n).toLocaleString("ko-KR",{maximumFractionDigits:d}):"-"};
var rate=function(n){return n==null?"-":(Number(n)>0?"+":"")+fmt(n,1)+"%"};
var money=function(n){n=Number(n);if(!Number.isFinite(n))return "-";if(n>=1e12)return fmt(n/1e12,1)+"조";return fmt(n/1e8,1)+"억"};
var clip=function(s,n){n=n||76;s=String(s||"").replace(/\\s+/g," ").trim();return s.length>n?s.slice(0,n)+"…":s};
var matClass=function(t){return {"수주·공급계약":"contract","실적·가이던스":"earnings","기술·제품·양산":"product","정책·규제":"policy","승인·임상":"clinical","업황·가격":"industry"}[t]||"unknown"};
var moveClass=function(k){return k==="UP"?"up":k==="DOWN"?"down":k==="NEW"?"new":k==="REENTRY"?"re":""};
var DATA=null;
function token(){return localStorage.getItem("marketRadarToken")||""}
async function load(){
 if(!token()){q("auth").classList.add("show");return}
 try{
  var r=await fetch("/api/dashboard",{headers:{"x-dashboard-token":token()},cache:"no-store"});
  if(r.status===401){localStorage.removeItem("marketRadarToken");q("auth").classList.add("show");return}
  if(!r.ok)throw new Error("HTTP "+r.status);
  DATA=await r.json();render();
 }catch(e){q("headline").textContent="연결 지연 · "+e.message;q("live").textContent="● 확인 필요"}
}
function render(){
 var d=DATA||{},b=d.home_brief||{},snap=d.market_snapshot||{},sys=d.system||{};
 q("stamp").textContent=new Date(d.generated_at).toLocaleString("ko-KR")+" · "+((d.session||{}).label||"");
 q("live").textContent=(d.session||{}).is_live?"● LIVE":"● 장외";
 q("headline").textContent=b.headline||"시장 관측 축적 중";
 var sectors=(d.sector_rankings||[]).slice().sort(function(a,b){return Number(b.theme_strength||0)-Number(a.theme_strength||0)});
 var strongest=sectors[0],top=(d.query_ranking||[]).slice(0,12);
 var warn=top.filter(function(x){return (x.reversal_signal||{}).kind==="TOP_WARNING"}).length;
 var bottom=top.filter(function(x){return (x.reversal_signal||{}).kind==="BOTTOM_WATCH"}).length;
 var chips=[strongest?"테마 "+strongest.name+" "+strongest.theme_strength:"","교체율 "+fmt((d.regime_metrics||{}).rank_turnover_5m,1)+"%",warn?"고점경계 "+warn:"",bottom?"바닥감시 "+bottom:""].filter(Boolean);
 q("heroChips").innerHTML=chips.map(function(x){return '<span class="hero-chip">'+esc(x)+'</span>'}).join("");
 q("statusCards").innerHTML=[
  ["실시간 데이터",(sys.kiwoom||{}).status||"-",snap.time?"수집 "+new Date(snap.time).toLocaleTimeString("ko-KR"):""],
  ["Telegram",((sys.telegram||{}).count_24h||0).toLocaleString("ko-KR")+"건","최근 24h"],
  ["테마",strongest?strongest.name:"-",strongest?"강도 "+strongest.theme_strength:""],
  ["차트","고점 "+warn+" · 바닥 "+bottom,"미모사 "+((sys.mimosa||{}).status||"-")]
 ].map(function(x){return '<div class="mini"><div class="k">'+esc(x[0])+'</div><div class="v">'+esc(x[1])+'</div><div class="s">'+esc(x[2])+'</div></div>'}).join("");
 renderThemes();renderSurges();renderCandidates();renderMoney();renderCalendar();renderStatus();
}
function themeCard(g){
 var why=g.reason||{};
 var stocks=(g.stocks||[]).slice(0,3).map(function(x){return '<div class="theme-stock"><span class="name">'+esc(x.name||x.code)+'</span><span class="'+(Number(x.change_rate)>=0?"up":"down")+'">'+esc(rate(x.change_rate))+'</span><span>'+esc(money(x.trade_value_krw))+'</span></div>'}).join("");
 return '<article class="theme"><div class="theme-top"><div><div class="theme-name">'+esc(g.name)+'</div><div class="theme-meta"><span>급부상 '+(g.surge_count||0)+'</span><span>최근 '+money(g.recent_turnover_krw)+'</span><span>누적 '+money(g.trade_value_krw)+'</span></div></div><div class="strength">'+esc(g.theme_strength||0)+'</div></div><div class="bar"><i style="width:'+Math.max(0,Math.min(100,Number(g.theme_strength||0)))+'%"></i></div><div class="theme-reason">'+esc(clip(why.summary||"공통 재료 분석 대기",120))+'</div><div class="theme-stocks">'+stocks+'</div></article>'
}
function renderThemes(){
 var xs=(DATA.sector_rankings||[]).slice().sort(function(a,b){return Number(b.theme_strength||0)-Number(a.theme_strength||0)});
 q("themes").innerHTML=xs.slice(0,4).map(themeCard).join("")||'<div class="empty">테마 데이터 대기</div>';
 q("allThemes").innerHTML=xs.map(themeCard).join("")||'<div class="empty">테마 데이터 대기</div>';
}
function sourceLinks(x){
 var links=[],os=x.external_research||{},cat=x.catalyst||{};
 (os.sources||[]).slice(0,1).forEach(function(v){if(v.url)links.push(["OS 원문",v.url])});
 (cat.dart||[]).slice(0,1).forEach(function(v){if(v.link)links.push(["DART",v.link])});
 (cat.external_news||[]).slice(0,1).forEach(function(v){if(v.link)links.push([v.source||"기사",v.link])});
 if(!links.length)return "";
 return '<div class="source-links">'+links.map(function(v){return '<a href="'+esc(v[1])+'" target="_blank" rel="noopener">'+esc(v[0])+' ↗</a>'}).join("")+'</div>';
}
function surgeRow(x){
 var h=x.rank_history||{},d=x.material_digest||{},sig=x.reversal_signal||{},os=x.external_research;
 var sigText=sig.kind==="TOP_WARNING"?'<span class="signal sig-top">▼ 고점 '+sig.score+'</span>':sig.kind==="BOTTOM_WATCH"?'<span class="signal sig-bottom">▲ 바닥 '+sig.score+'</span>':"";
 var osBox=os?'<div class="os"><b>'+(os.stale?"과거 OS":"OS")+' · '+(os.citation_count||0)+'인용</b><br>'+esc(clip(os.summary,80))+'</div>':"";var links=sourceLinks(x);
 return '<div class="row"><div class="rank">#'+esc(x.rank==null?"-":x.rank)+'<span class="move '+moveClass(h.movement_kind)+'">'+esc(h.movement||"—")+'</span></div><div><div class="row-name">'+esc(x.name||x.code)+' '+sigText+'</div><div class="row-sub">'+esc(x.market_theme||x.official_sector||"미분류")+' · 대금 #'+esc(x.trade_rank==null?"-":x.trade_rank)+'</div><div class="material"><span class="tag '+matClass(d.material_type)+'">'+esc(d.material_type||"미확인")+'</span>'+esc(clip(d.summary||"직접 재료 미확인"))+'</div>'+links+osBox+'</div><div class="row-money"><div class="'+(Number(x.change_rate)>=0?"up":"down")+'">'+esc(rate(x.change_rate))+'</div><div>'+esc(money(x.trade_value_krw))+'</div><div class="row-sub">최근 '+esc(money(x.recent_turnover_krw))+'</div></div></div>'
}
function renderSurges(){q("surges").innerHTML=(DATA.query_ranking||[]).slice(0,12).map(surgeRow).join("")||'<div class="empty">급부상 데이터 대기</div>'}
function candidateCard(x){
 var sig=x.reversal_signal||{},mv=(x.rank_history||{}).movement||"—";
 var sigText=sig.kind==="TOP_WARNING"?'<span class="signal sig-top">▼ 고점 '+sig.score+'</span>':sig.kind==="BOTTOM_WATCH"?'<span class="signal sig-bottom">▲ 바닥 '+sig.score+'</span>':"";
 return '<article class="candidate"><div class="candidate-head"><div><div class="row-name">'+esc(x.name||x.code)+'</div><div class="candidate-meta">'+esc(x.market_theme||"테마 미확인")+' · '+esc(x.primary_type||"관찰")+'</div></div><div class="score">'+esc(x.attention_score==null?"-":x.attention_score)+'</div></div><div class="candidate-meta">등락 '+esc(rate(x.change_rate))+' · 조회 #'+esc(x.rank==null?"-":x.rank)+' '+esc(mv)+' · 대금 #'+esc(x.trade_rank==null?"-":x.trade_rank)+'</div><div class="candidate-meta">최근 '+esc(money(x.recent_turnover_krw))+' · 누적 '+esc(money(x.trade_value_krw))+'</div><div style="margin-top:6px"><span class="tag '+matClass(x.event_type)+'">'+esc(x.event_type||"재료 미확인")+'</span>'+sigText+'</div></article>'
}
function renderCandidates(){var xs=DATA.home_candidates||[];var html=xs.map(candidateCard).join("")||'<div class="empty">현재 유지 중인 후보 없음</div>';q("candidates").innerHTML=html;q("allCandidates").innerHTML=html}
function renderMoney(){var xs=((DATA.leader_desk||{}).strong_stocks)||[];q("moneyLeaders").innerHTML=xs.map(function(x){return '<div class="row"><div class="rank">#'+esc(x.trade_rank==null?"-":x.trade_rank)+'</div><div><div class="row-name">'+esc(x.name||x.code)+'</div><div class="row-sub">'+esc(x.theme||"미분류")+'</div></div><div class="row-money"><div class="up">'+esc(rate(x.change_rate))+'</div><div>'+esc(money(x.trade_value_krw))+'</div></div></div>'}).join("")||'<div class="empty">+4% 거래대금 강세 종목 없음</div>'}
function renderCalendar(){
 var cal=((DATA.leader_desk||{}).calendar)||{},cells=cal.cells||[],week=["월","화","수","목","금"];
 var html='<div class="calendar">'+week.map(function(x){return '<div class="cal-head">'+x+'</div>'}).join("");
 html+=cells.map(function(c){var ts=(c.themes||[]).slice(0,2).map(function(t){return '<div class="cal-theme">• '+esc(t.theme)+' <span class="'+(Number(t.avg_change_rate)>=0?"up":"down")+'">'+esc(rate(t.avg_change_rate))+'</span></div>'}).join("");return '<div class="cal-cell"><div class="cal-date">'+esc(c.day)+'</div>'+(ts||'<div class="cal-theme" style="color:#a0a9b7">-</div>')+'</div>'}).join("");
 html+='</div>';
 q("mobileCalendar").innerHTML=html;
}
function renderStatus(){var s=DATA.system||{};q("systemCards").innerHTML=[["Kiwoom",(s.kiwoom||{}).status||"-",(s.kiwoom||{}).note||""],["Telegram",(s.telegram||{}).status||"OK",((s.telegram||{}).count_24h||0)+"건"],["뉴스",(s.newsfeed||{}).status||"-",(s.newsfeed||{}).note||""],["차트",(s.chartfeed||{}).status||"-",(s.chartfeed||{}).note||""]].map(function(x){return '<div class="mini"><div class="k">'+esc(x[0])+'</div><div class="v">'+esc(x[1])+'</div><div class="s">'+esc(x[2])+'</div></div>'}).join("")}
q("saveToken").onclick=function(){var v=q("tokenInput").value.trim();if(v){localStorage.setItem("marketRadarToken",v);q("auth").classList.remove("show");load()}};
document.querySelectorAll(".nav button").forEach(function(b){b.onclick=function(){document.querySelectorAll(".nav button").forEach(function(x){x.classList.remove("active")});b.classList.add("active");document.querySelectorAll(".page").forEach(function(x){x.classList.remove("active")});q("page-"+b.dataset.page).classList.add("active");scrollTo(0,0)}});
load();setInterval(load,20000);
if("serviceWorker"in navigator)navigator.serviceWorker.register("/mobile/sw.js").catch(function(){});
</script>
</body></html>'''

MOBILE_MANIFEST = r'''{
  "name":"Market Radar Mobile",
  "short_name":"Market Radar",
  "start_url":"/mobile",
  "display":"standalone",
  "background_color":"#f4f7fb",
  "theme_color":"#111c31",
  "icons":[{"src":"/mobile/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]
}'''

MOBILE_SW = r'''const CACHE="market-radar-mobile-v1";
self.addEventListener("install",function(e){e.waitUntil(caches.open(CACHE).then(function(c){return c.addAll(["/mobile","/mobile/manifest.webmanifest","/mobile/icon.svg"])}))});
self.addEventListener("activate",function(e){e.waitUntil(self.clients.claim())});
self.addEventListener("fetch",function(e){if(e.request.url.includes("/api/"))return;e.respondWith(fetch(e.request).catch(function(){return caches.match(e.request)}))});'''

MOBILE_ICON = r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="112" fill="#111c31"/>
<path d="M96 352V160h52l62 104 62-104h52v192h-48V236l-66 108-66-108v116z" fill="#fff"/>
<path d="M340 156h76v48h-76zm0 76h76v48h-76zm0 76h76v48h-76z" fill="#32b49a"/>
</svg>'''
