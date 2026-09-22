import os, json, re
from datetime import datetime, timedelta, timezone
from typing import Optional
import psycopg
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

DB = os.getenv("DATABASE_URL", "")
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")
app = FastAPI(title="Market Radar", version="0.2.0")

THEME_KEYWORDS = {
    "반도체/HBM": ["HBM", "반도체", "하이닉스", "삼성전자", "패키징", "테스트", "퀄"],
    "2차전지/배터리": ["2차전지", "배터리", "양극재", "음극재", "전고체"],
    "전력/변압기/케이블": ["전력", "변압기", "케이블", "데이터센터 전력"],
    "원전/SMR": ["원전", "SMR", "핵발전", "원자력"],
    "방산": ["방산", "군수", "미사일", "무기"],
    "조선/LNG": ["조선", "LNG", "해운"],
    "바이오/제약": ["바이오", "제약", "임상", "FDA"],
    "로봇": ["로봇", "휴머노이드", "자동화"],
    "자동차/EV": ["자동차", "전기차", "EV", "자율주행"],
    "정유/유가": ["정유", "유가", "WTI", "브렌트", "석유"],
    "화장품": ["화장품", "뷰티"],
    "금융": ["은행", "금융", "증권", "보험"],
}

def get_db():
    if not DB:
        raise RuntimeError("DATABASE_URL missing")
    return psycopg.connect(DB)

def table_exists(cur, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"public.{name}",))
    return cur.fetchone()[0] is not None

def iso(v):
    return v.isoformat() if v else None

def require_token(x_dashboard_token: Optional[str] = Header(None)):
    if not DASHBOARD_TOKEN or x_dashboard_token != DASHBOARD_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")

def infer_theme(text: str) -> Optional[str]:
    t = (text or "").lower()
    for theme, kws in THEME_KEYWORDS.items():
        if any(k.lower() in t for k in kws):
            return theme
    return None

def catalyst_for_stock(messages, code, name):
    matched = []
    for m in messages:
        txt = m["text"] or ""
        if (code and code in txt) or (name and len(name) >= 2 and name in txt):
            matched.append(m)
    if not matched:
        return {"text": None, "status": None, "channels": 0, "theme": None, "first_seen": None, "last_seen": None}
    matched.sort(key=lambda x: x["message_date"] or x["collected_at"])
    chs = len(set(x["channel_name"] for x in matched))
    last = matched[-1]
    first = matched[0]
    now = datetime.now(timezone.utc)
    last_dt = last["message_date"] or last["collected_at"]
    age_min = (now - last_dt).total_seconds()/60 if last_dt else 9999
    status = "SPREADING" if chs >= 2 else ("NEW" if age_min <= 90 else "REPEAT")
    theme = None
    for x in reversed(matched):
        theme = infer_theme(x["text"])
        if theme:
            break
    txt = re.sub(r"\s+", " ", last["text"] or "").strip()
    return {
        "text": txt[:160] if txt else None,
        "status": status,
        "channels": chs,
        "theme": theme,
        "first_seen": iso(first["message_date"] or first["collected_at"]),
        "last_seen": iso(last_dt),
    }

@app.get("/health")
def health():
    try:
        with get_db() as c:
            with c.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

@app.get("/api/dashboard")
def dashboard(x_dashboard_token: Optional[str] = Header(None)):
    require_token(x_dashboard_token)
    with get_db() as c:
        with c.cursor() as cur:
            # system
            telegram = {"latest": None, "count_24h": 0}
            if table_exists(cur, "telegram_messages"):
                cur.execute("SELECT MAX(message_date), COUNT(*) FILTER (WHERE collected_at > now()-interval '24 hours') FROM telegram_messages")
                r = cur.fetchone()
                telegram = {"latest": iso(r[0]), "count_24h": int(r[1] or 0)}

            kiwoom = {"status": "NOT_CONFIGURED", "last_success": None, "note": None}
            if table_exists(cur, "kiwoom_feed_status"):
                cur.execute("SELECT status,last_success_at,note FROM kiwoom_feed_status WHERE id=1")
                r = cur.fetchone()
                if r:
                    kiwoom = {"status": r[0], "last_success": iso(r[1]), "note": r[2]}

            regime = {"status": "WAITING_FOR_MARKET_DATA", "stable_label": None, "candidate_label": None, "confidence": None}
            if table_exists(cur, "market_regime_status"):
                cur.execute("SELECT status,last_market_data_at,stable_label,candidate_label,candidate_count,note,updated_at FROM market_regime_status WHERE id=1")
                r = cur.fetchone()
                if r:
                    regime = {
                        "status": r[0], "last_market_data_at": iso(r[1]), "stable_label": r[2],
                        "candidate_label": r[3], "candidate_count": r[4], "note": r[5], "updated_at": iso(r[6])
                    }
            regime_metrics = None
            if table_exists(cur, "market_regime_snapshots"):
                cur.execute("""SELECT snapshot_time,confidence,data_freshness_sec,rank_turnover_5m,top5_trade_share,
                                      top10_trade_share,top_sector_share,top3_sector_share,largecap_trade_share,
                                      positive_rank_share,avg_rank_change_rate,sector_count_top20,explanation
                               FROM market_regime_snapshots ORDER BY snapshot_time DESC LIMIT 1""")
                r = cur.fetchone()
                if r:
                    regime_metrics = {
                        "snapshot_time": iso(r[0]), "confidence": r[1], "freshness_sec": r[2],
                        "rank_turnover_5m": r[3], "top5_trade_share": r[4], "top10_trade_share": r[5],
                        "top_sector_share": r[6], "top3_sector_share": r[7], "largecap_trade_share": r[8],
                        "positive_rank_share": r[9], "avg_rank_change_rate": r[10],
                        "sector_count_top20": r[11], "explanation": r[12] or {}
                    }

            # latest telegram sample for catalyst matching
            messages = []
            if table_exists(cur, "telegram_messages"):
                cur.execute("""SELECT collected_at,message_date,channel_name,text
                               FROM telegram_messages
                               WHERE collected_at > now()-interval '8 hours'
                               ORDER BY collected_at DESC LIMIT 500""")
                messages = [{"collected_at":x[0],"message_date":x[1],"channel_name":x[2],"text":x[3]} for x in cur.fetchall()]

            # latest ranks
            ranks = []
            rank_time = None
            if table_exists(cur, "market_rank_snapshots"):
                cur.execute("SELECT MAX(snapshot_time) FROM market_rank_snapshots")
                rank_time = cur.fetchone()[0]
                if rank_time:
                    cur.execute("""SELECT stock_code,stock_name,rank_no,rank_change,change_rate,market_cap_krw,official_sector,market_theme
                                   FROM market_rank_snapshots WHERE snapshot_time=%s ORDER BY rank_no NULLS LAST LIMIT 30""",(rank_time,))
                    ranks = cur.fetchall()

            # latest trade values
            trade_map = {}
            trade_time = None
            if table_exists(cur, "market_trade_value_snapshots"):
                cur.execute("SELECT MAX(snapshot_time) FROM market_trade_value_snapshots")
                trade_time = cur.fetchone()[0]
                if trade_time:
                    cur.execute("""SELECT stock_code,rank_no,trade_value_krw,change_rate,market_cap_krw,official_sector,market_theme
                                   FROM market_trade_value_snapshots WHERE snapshot_time=%s ORDER BY rank_no NULLS LAST LIMIT 100""",(trade_time,))
                    for x in cur.fetchall():
                        trade_map[x[0]] = x

            rows = []
            for r in ranks:
                code,name,rank_no,rank_change,chg,cap,sector,theme = r
                tv = trade_map.get(code)
                trade_value = tv[2] if tv else None
                cap2 = cap if cap is not None else (tv[4] if tv else None)
                sector2 = sector or (tv[5] if tv else None)
                theme2 = theme or (tv[6] if tv else None)
                ratio = None
                try:
                    if trade_value is not None and cap2 and float(cap2) > 0:
                        ratio = float(trade_value)/float(cap2)*100
                except Exception:
                    ratio = None
                cat = catalyst_for_stock(messages, code, name)
                if not theme2:
                    theme2 = cat["theme"]
                chart_state = "대기"
                if table_exists(cur, "chart_states"):
                    try:
                        cur.execute("SELECT state FROM chart_states WHERE stock_code=%s ORDER BY snapshot_time DESC LIMIT 1",(code,))
                        rr=cur.fetchone()
                        if rr: chart_state=rr[0]
                    except Exception:
                        c.rollback()
                rows.append({
                    "rank": rank_no, "rank_change": rank_change, "code": code, "name": name,
                    "change_rate": chg, "trade_value_krw": trade_value, "market_cap_krw": cap2,
                    "trade_to_cap_pct": ratio, "official_sector": sector2, "market_theme": theme2,
                    "catalyst": cat, "chart_state": chart_state
                })

            sectors = []
            if table_exists(cur, "market_sector_snapshots"):
                cur.execute("SELECT MAX(snapshot_time) FROM market_sector_snapshots")
                st = cur.fetchone()[0]
                if st:
                    cur.execute("""SELECT sector_name,change_rate,trade_value_krw,rising_count,falling_count
                                   FROM market_sector_snapshots WHERE snapshot_time=%s
                                   ORDER BY trade_value_krw DESC NULLS LAST LIMIT 10""",(st,))
                    sectors=[{"name":x[0],"change_rate":x[1],"trade_value_krw":x[2],"rising":x[3],"falling":x[4]} for x in cur.fetchall()]

            # recent telegram
            recent_telegram=[]
            for m in messages[:20]:
                txt=re.sub(r"\s+"," ",m["text"] or "").strip()
                recent_telegram.append({"time":iso(m["message_date"] or m["collected_at"]),"channel":m["channel_name"],"text":txt[:180]})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system": {"telegram": telegram, "kiwoom": kiwoom},
        "regime": regime,
        "regime_metrics": regime_metrics,
        "rank_time": iso(rank_time),
        "trade_time": iso(trade_time),
        "rows": rows,
        "sectors": sectors,
        "telegram_recent": recent_telegram,
    }

DASHBOARD_HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Radar</title>
<style>
:root{--bg:#0b1020;--card:#131a2d;--line:#27324d;--txt:#eef2ff;--muted:#91a0bf;--good:#42d392;--bad:#ff6b7d;--warn:#f7c948;--accent:#7c9cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1500px;margin:auto;padding:22px}.top{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:16px}
h1{font-size:26px;margin:0}.sub{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}.label{color:var(--muted);font-size:12px}.big{font-size:20px;font-weight:700;margin-top:5px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:14px;margin-top:14px;overflow:hidden}.panel h2{font-size:15px;margin:0;padding:14px;border-bottom:1px solid var(--line)}
table{width:100%;border-collapse:collapse}th,td{padding:10px 9px;border-bottom:1px solid #202942;text-align:right;white-space:nowrap}th{color:var(--muted);font-weight:600;font-size:12px}th:nth-child(2),td:nth-child(2),th:nth-child(7),td:nth-child(7),th:nth-child(8),td:nth-child(8),th:nth-child(9),td:nth-child(9),th:nth-child(10),td:nth-child(10){text-align:left}
.up{color:var(--good)}.dn{color:var(--bad)}.pill{display:inline-block;padding:3px 7px;border:1px solid var(--line);border-radius:999px;font-size:11px;color:#cbd5e1}
.wait{color:var(--warn)}.tele{padding:10px 14px;border-bottom:1px solid #202942}.tele b{font-size:12px}.tele p{margin:3px 0 0;color:#cbd5e1}.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}.two{grid-template-columns:1fr}.wrap{padding:12px}.panel{overflow:auto}}
</style></head>
<body><div class="wrap">
<div class="top"><div><h1>MARKET RADAR</h1><div class="sub">장세 → 섹터 → 관심 → 돈 → 재료 → 차트</div></div><div class="sub" id="stamp">연결 중…</div></div>
<div class="grid">
<div class="card"><div class="label">오늘 시장</div><div class="big" id="regime">대기</div></div>
<div class="card"><div class="label">Kiwoom Feed</div><div class="big" id="kiwoom">대기</div></div>
<div class="card"><div class="label">Telegram</div><div class="big" id="telegram">대기</div></div>
<div class="card"><div class="label">조회 Top20 교체율</div><div class="big" id="turnover">-</div></div>
</div>
<div class="panel"><h2>실시간 종목조회 레이더</h2><table><thead><tr>
<th>순위</th><th>종목</th><th>등락률</th><th>거래대금</th><th>시총</th><th>시총대비</th><th>섹터</th><th>테마</th><th>재료</th><th>차트</th>
</tr></thead><tbody id="tbody"></tbody></table></div>
<div class="two">
<div class="panel"><h2>주도 섹터</h2><div id="sectors"></div></div>
<div class="panel"><h2>Telegram 최신</h2><div id="tels"></div></div>
</div>
</div>
<script>
let token=location.hash.slice(1)||localStorage.getItem("marketRadarToken")||"";
if(location.hash){localStorage.setItem("marketRadarToken",token);history.replaceState(null,"",location.pathname);}
const fmt=(v)=>v==null?"-":Number(v).toLocaleString("ko-KR",{maximumFractionDigits:1});
const pct=(v)=>v==null?"-":(Number(v)*100).toFixed(1)+"%";
const cls=(v)=>Number(v)>0?"up":Number(v)<0?"dn":"";
async function load(){
 if(!token){document.getElementById("regime").innerHTML='<span class="wait">접속키 필요</span>';return;}
 try{
  const r=await fetch("/api/dashboard",{headers:{"x-dashboard-token":token}});
  if(!r.ok) throw new Error("HTTP "+r.status);
  const d=await r.json();
  document.getElementById("stamp").textContent=new Date(d.generated_at).toLocaleString("ko-KR");
  document.getElementById("regime").textContent=d.regime.stable_label||d.regime.candidate_label||d.regime.status;
  document.getElementById("kiwoom").textContent=d.system.kiwoom.status;
  document.getElementById("telegram").textContent=(d.system.telegram.count_24h||0).toLocaleString()+"건 / 24h";
  document.getElementById("turnover").textContent=d.regime_metrics?.rank_turnover_5m==null?"-":pct(d.regime_metrics.rank_turnover_5m);
  const rows=d.rows||[];
  document.getElementById("tbody").innerHTML=rows.length?rows.map(x=>`<tr>
   <td>${x.rank??"-"} <span class="${cls(x.rank_change)}">${x.rank_change==null?"":(x.rank_change>0?"↑":"↓")+Math.abs(x.rank_change)}</span></td>
   <td><b>${x.name||x.code}</b><div class="label">${x.code}</div></td>
   <td class="${cls(x.change_rate)}">${x.change_rate==null?"-":fmt(x.change_rate)+"%"}</td>
   <td>${x.trade_value_krw==null?"-":fmt(x.trade_value_krw/1e8)+"억"}</td>
   <td>${x.market_cap_krw==null?"-":fmt(x.market_cap_krw/1e8)+"억"}</td>
   <td>${x.trade_to_cap_pct==null?"-":x.trade_to_cap_pct.toFixed(1)+"%"}</td>
   <td>${x.official_sector||"-"}</td><td>${x.market_theme||"-"}</td>
   <td><span class="pill">${x.catalyst?.status||"-"}</span> ${x.catalyst?.text||""}</td>
   <td>${x.chart_state||"대기"}</td>
  </tr>`).join(""):'<tr><td colspan="10" class="wait">키움 시장 데이터 연결 대기 중</td></tr>';
  document.getElementById("sectors").innerHTML=(d.sectors||[]).map(x=>`<div class="tele"><b>${x.name}</b> <span class="${cls(x.change_rate)}">${x.change_rate==null?"":fmt(x.change_rate)+"%"}</span><p>거래대금 ${x.trade_value_krw==null?"-":fmt(x.trade_value_krw/1e8)+"억"} · 상승 ${x.rising??"-"} / 하락 ${x.falling??"-"}</p></div>`).join("")||'<div class="tele wait">업종 데이터 대기 중</div>';
  document.getElementById("tels").innerHTML=(d.telegram_recent||[]).map(x=>`<div class="tele"><b>${new Date(x.time).toLocaleTimeString("ko-KR",{hour:"2-digit",minute:"2-digit"})} · ${x.channel}</b><p>${x.text}</p></div>`).join("");
 }catch(e){document.getElementById("kiwoom").textContent="연결 오류";console.error(e);}
}
load();setInterval(load,10000);
</script></body></html>"""

@app.get("/", response_class=HTMLResponse)
def root():
    return HTMLResponse(DASHBOARD_HTML)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","8080")))
