import os, json, re
from datetime import datetime, timedelta, timezone, time as dtime
from zoneinfo import ZoneInfo
from typing import Optional
import psycopg
from fastapi import FastAPI, Header, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
try:
    from radar_ui_v2 import DASHBOARD_HTML_V2
except Exception:
    DASHBOARD_HTML_V2 = None

DB = os.getenv("DATABASE_URL", "")
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")
app = FastAPI(title="Market Radar", version="0.6.1")

THEME_KEYWORDS = {
    "반도체/HBM": ["HBM", "반도체", "패키징", "테스트", "파운드리", "D램", "DRAM", "낸드"],
    "PCB/반도체기판": ["PCB", "기판", "FC-BGA", "CCL", "회로", "패키지기판"],
    "2차전지/배터리": ["2차전지", "배터리", "양극재", "음극재", "전고체"],
    "전력/변압기/케이블": ["전력", "변압기", "케이블", "데이터센터 전력"],
    "원전/SMR": ["원전", "SMR", "핵발전", "원자력"],
    "방산": ["방산", "군수", "미사일", "무기"],
    "조선/LNG": ["조선", "LNG", "해운"],
    "바이오/제약": ["바이오", "제약", "임상", "FDA"],
    "로봇": ["로봇", "휴머노이드", "자동화"],
    "자동차/EV": ["자동차", "전기차", "EV", "자율주행"],
    "AI/데이터센터": ["AI 데이터센터", "데이터센터", "AI 팩토리", "NPU", "GPU", "AI 서버"],
    "항공/여행": ["항공", "대한항공", "여객", "여행", "공항"],
    "정유/유가": ["정유", "유가", "WTI", "브렌트", "석유"],
    "화장품": ["화장품", "뷰티"],
    "금융": ["은행", "금융", "증권", "보험"],
}


KST=ZoneInfo("Asia/Seoul")

ETF_PREFIXES=(
    "KODEX","TIGER","RISE","ACE","KOSEF","HANARO","SOL ","ARIRANG","TIMEFOLIO",
    "PLUS ","WOORI ","FOCUS ","1Q ","KIWOOM ","BNK ","HK","KBSTAR"
)

STOCK_THEME_HINTS = {
    "삼성전자":"반도체/HBM","SK하이닉스":"반도체/HBM","한미반도체":"반도체/HBM",
    "HPSP":"반도체/HBM","테크윙":"반도체/HBM","주성엔지니어링":"반도체/HBM",
    "코리아써키트":"PCB/반도체기판","심텍":"PCB/반도체기판","티엘비":"PCB/반도체기판",
    "대덕전자":"PCB/반도체기판","이수페타시스":"PCB/반도체기판",
    "대한전선":"전력/변압기/케이블","가온전선":"전력/변압기/케이블","LS ELECTRIC":"전력/변압기/케이블",
    "효성중공업":"전력/변압기/케이블","HD현대일렉트릭":"전력/변압기/케이블",
    "대한항공":"항공/여행",
    "현대차":"자동차/EV","기아":"자동차/EV",
}

def is_etf_like(name):
    n=(name or "").strip().upper()
    return any(n.startswith(p.upper()) for p in ETF_PREFIXES) or " ETN" in n or n.endswith("ETN")

def market_session_state(now=None):
    now=(now or datetime.now(KST)).astimezone(KST)
    wd=now.weekday()
    t=now.time()
    if wd >= 5:
        return {"code":"CLOSED","label":"주말 장외","is_live":False}
    # 한국 주식 통합 관찰 창: 프리마켓/NXT/정규/애프터마켓을 넓게 포함.
    if dtime(8,0) <= t <= dtime(20,0):
        if dtime(9,0) <= t <= dtime(15,30):
            label="정규장"
        elif t < dtime(9,0):
            label="장전/NXT"
        else:
            label="장후/NXT"
        return {"code":"OPEN","label":label,"is_live":True}
    return {"code":"CLOSED","label":"장외","is_live":False}

def choose_market_theme(name, official_sector, catalyst):
    if name in STOCK_THEME_HINTS:
        return STOCK_THEME_HINTS[name]
    strength=int((catalyst or {}).get("material_strength") or 0)
    if strength >= 2:
        t=infer_theme((catalyst or {}).get("best_text") or "")
        if t:
            return t
    return official_sector or "미분류"

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

URL_RE = re.compile(r'https?://[^\s<>"\']+')

def stock_aliases(code, name):
    out = []
    for x in (code, name):
        if x and str(x).strip():
            out.append(str(x).strip())
    if name:
        compact = re.sub(r"[\s㈜()주식회사]+", "", str(name))
        if len(compact) >= 2 and compact not in out:
            out.append(compact)
    return out

def extract_links(text):
    links = []
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,)]}>")
        if u not in links:
            links.append(u)
    return links[:8]

def catalyst_for_stock(messages, code, name):
    aliases = stock_aliases(code, name)
    matched = []
    for m in messages:
        txt = m["text"] or ""
        compact = re.sub(r"\s+", "", txt)
        if any((a in txt) or (len(a) >= 2 and a in compact) for a in aliases):
            matched.append(m)
    if not matched:
        return {
            "summary": None, "status": "NO_MATCH", "channels": 0, "theme": None,
            "first_seen": None, "last_seen": None, "items": [], "article_links": [],
            "note": "최근 24시간 Telegram 직접 일치 재료 미확인"
        }

    matched.sort(key=lambda x: x["message_date"] or x["collected_at"])
    channels = len(set((x["channel_name"] or "") for x in matched))
    first, last = matched[0], matched[-1]
    now = datetime.now(timezone.utc)
    last_dt = last["message_date"] or last["collected_at"]
    age_min = (now - last_dt).total_seconds() / 60 if last_dt else 9999
    if channels >= 3:
        status = "SPREADING"
    elif channels >= 2:
        status = "MULTI_CHANNEL"
    elif age_min <= 90:
        status = "NEW_MENTION"
    else:
        status = "SINGLE_OR_REPEAT"

    theme = None
    for x in reversed(matched):
        theme = infer_theme(x["text"])
        if theme:
            break

    items = []
    article_links = []
    for x in reversed(matched[-8:]):
        txt = re.sub(r"\s+", " ", x["text"] or "").strip()
        links = extract_links(x["text"] or "")
        for u in links:
            if u not in article_links and "t.me/" not in u:
                article_links.append(u)
        items.append({
            "time": iso(x["message_date"] or x["collected_at"]),
            "channel": x["channel_name"],
            "text": txt[:6000],
            "telegram_url": x.get("message_url"),
            "links": links,
        })
    summary = re.sub(r"\s+", " ", last["text"] or "").strip()
    return {
        "summary": summary[:1200] if summary else None,
        "status": status,
        "channels": channels,
        "theme": theme,
        "first_seen": iso(first["message_date"] or first["collected_at"]),
        "last_seen": iso(last_dt),
        "items": items,
        "article_links": article_links[:8],
        "note": None,
    }

def build_sector_groups(rows):
    groups = {}
    for x in rows:
        sector = x.get("market_theme") or x.get("official_sector") or "미분류"
        g = groups.setdefault(sector, {
            "name": sector, "count": 0, "query_score": 0.0, "rank_sum": 0.0,
            "change_sum": 0.0, "change_n": 0, "positive": 0,
            "trade_value_krw": 0.0, "stocks": []
        })
        rank = x.get("rank")
        g["count"] += 1
        if rank is not None:
            g["query_score"] += max(1, 31 - int(rank))
            g["rank_sum"] += float(rank)
        chg = x.get("change_rate")
        if chg is not None:
            g["change_sum"] += float(chg)
            g["change_n"] += 1
            if float(chg) > 0:
                g["positive"] += 1
        tv = x.get("trade_value_krw")
        if tv is not None:
            g["trade_value_krw"] += float(tv)
        g["stocks"].append({
            "rank": rank, "code": x.get("code"), "name": x.get("name"),
            "change_rate": chg, "flow_state": x.get("flow_state")
        })
    out = []
    for g in groups.values():
        g["avg_rank"] = g["rank_sum"] / g["count"] if g["count"] else None
        g["avg_change_rate"] = g["change_sum"] / g["change_n"] if g["change_n"] else None
        g["positive_ratio"] = g["positive"] / g["change_n"] if g["change_n"] else None
        g["stocks"] = sorted(g["stocks"], key=lambda z: (z["rank"] is None, z["rank"] or 999))[:8]
        out.append(g)
    out.sort(key=lambda z: (z["query_score"], z["count"], z["trade_value_krw"]), reverse=True)
    for i, g in enumerate(out, 1):
        g["sector_rank"] = i
    return out

def stock_flow_state(rank_no, rank_change, trade_rank, catalyst):
    material = int(catalyst.get("material_strength") or 0) >= 2
    money = trade_rank is not None and int(trade_rank) <= 20
    interest = (rank_no is not None and int(rank_no) <= 10) or (rank_change is not None and int(rank_change) >= 5)
    if material and money:
        return "재료↔돈 동행"
    if money and not material:
        return "돈 선행 / 재료 미확인"
    if material and not money:
        return "재료 확인 / 돈 미약"
    if interest:
        return "관심 선행"
    return "관찰"

def stock_analysis(row):
    bits = []
    if row.get("rank") is not None and row["rank"] <= 5:
        bits.append("조회 최상위")
    if row.get("rank_change") is not None and row["rank_change"] >= 5:
        bits.append("조회순위 급상승")
    if row.get("trade_rank") is not None and row["trade_rank"] <= 20:
        bits.append("거래대금 상위권")
    strength=int(row.get("catalyst", {}).get("material_strength") or 0)
    if strength >= 3:
        bits.append("직접 재료 후보")
    elif strength == 2:
        bits.append("테마형 재료")
    elif strength == 1:
        bits.append("언급은 있으나 인과 약함")
    else:
        bits.append("직접 재료 미확인")
    return " · ".join(bits) if bits else "추가 확인 필요"

def build_global_analysis(regime, metrics, rows, sector_groups):
    lines = []
    label = regime.get("stable_label") or regime.get("candidate_label")
    if label:
        lines.append("장세 판독: " + str(label))
    if not rows:
        lines.append("실시간 종목조회 데이터가 아직 없습니다. 장중 데이터 수신 여부와 Kiwoom Feed 상태를 확인해야 합니다.")
        return lines
    if sector_groups:
        g = sector_groups[0]
        names = ", ".join([x.get("name") or x.get("code") or "" for x in g["stocks"][:4]])
        lines.append(f"조회상위 집중 섹터: {g['name']} · {g['count']}종목 · 대표 {names}")
    material_n = sum(1 for x in rows if int(x.get("catalyst", {}).get("material_strength") or 0) >= 2)
    money_no_material = sum(1 for x in rows if x.get("flow_state") == "돈 선행 / 재료 미확인")
    lines.append(f"가격 설명력이 있는 재료 후보: {material_n}/{len(rows)}종목. 거래대금이 먼저 잡혔지만 직접 재료를 못 찾은 종목은 {money_no_material}개입니다.")
    if metrics and metrics.get("rank_turnover_5m") is not None:
        lines.append(f"조회 Top20 5분 교체율: {float(metrics['rank_turnover_5m'])*100:.1f}%. 높을수록 관심이 빠르게 순환하는 장으로 해석합니다.")
    lines.append("이 패널은 현재 규칙 기반 Radar 해석입니다. ChatGPT 모델의 별도 LLM 분석은 아직 대시보드에 직접 연결하지 않았습니다.")
    return lines

def clean_material_text(text):
    t=re.sub(r"https?://\S+"," ",text or "")
    t=re.sub(r"\[[^\]]{0,40}\]"," ",t)
    t=re.sub(r"\s+"," ",t).strip(" -|·")
    return t

NOISE_PATTERNS = [
    "상한가 및 상승종목","상승종목","급등주","오늘의 종목","관심종목","공략법","매매전략",
    "장마감","마감시황","종목추천","추천주","vs ","수익률","급등일보","유튜브","youtube"
]
DIRECT_PATTERNS = [
    "공시","공급계약","수주","계약 체결","mou","승인","허가","fda","임상","특허","양산",
    "기술 확보","개발 완료","납품","공급","실적","영업이익","매출","증설","투자 결정",
    "선정","인수","합병","지분","자사주","배당","신제품","출시","인증","독점"
]
SECTOR_PATTERNS = [
    "업황","훈풍","수혜","정책","법안","관세","반도체","hbm","원전","smr","로봇",
    "전력","변압기","케이블","방산","조선","lng","2차전지","배터리","데이터센터","ai"
]

def evidence_strength(text):
    t=(text or "").lower()
    if not t:
        return 0,"NONE"
    if any(p.lower() in t for p in NOISE_PATTERNS):
        return 0,"NOISE"
    if any(p.lower() in t for p in DIRECT_PATTERNS):
        return 3,"DIRECT"
    if any(p.lower() in t for p in SECTOR_PATTERNS):
        return 2,"SECTOR"
    return 1,"MENTION"

def enrich_catalyst(cat, stock_name=None):
    candidates=[]
    for d in cat.get("dart") or []:
        txt=d.get("report_nm") or ""
        candidates.append((4,"DART","DART",txt,d))
    for n in cat.get("external_news") or []:
        txt=n.get("title") or ""
        score,kind=evidence_strength(txt)
        candidates.append((score,kind,"뉴스",txt,n))
    for it in cat.get("items") or []:
        txt=it.get("text") or ""
        score,kind=evidence_strength(txt)
        candidates.append((score,kind,"Telegram",txt,it))
    candidates.sort(key=lambda x:x[0],reverse=True)
    best=candidates[0] if candidates else (0,"NONE","미확인","",None)
    inferred=infer_theme(best[3]) if best and best[3] else None
    if inferred:
        cat["theme"]=inferred
    cat["material_strength"]=best[0]
    cat["material_class"]=best[1]
    cat["best_source"]=best[2]
    cat["best_text"]=best[3]
    cat["best_evidence"]=best[4]
    if best[1] == "DART":
        cat["quality_note"]="DART 공식 공시"
    elif best[0] == 0 and candidates:
        cat["quality_note"]="가격 설명력이 낮은 시황·리스트·매매콘텐츠 가능성"
    elif best[0] == 1:
        cat["quality_note"]="종목 언급은 있으나 직접 촉발 재료로 보기엔 약함"
    elif best[0] == 2:
        cat["quality_note"]="업종·테마형 재료"
    elif best[0] >= 3:
        cat["quality_note"]="개별 종목 직접 재료 후보"
    else:
        cat["quality_note"]="직접 재료 미확인"
    return cat

def material_digest(cat, flow_state, stock_name=None):
    news=cat.get("external_news") or []
    items=cat.get("items") or []
    dart=cat.get("dart") or []
    summary=clean_material_text(cat.get("best_text"))
    source_kind=cat.get("best_source") or "미확인"
    if not summary and news:
        summary=clean_material_text(news[0].get("title"))
        source_kind="뉴스"
    if not summary and items:
        summary=clean_material_text(items[0].get("text"))
        source_kind="Telegram"
    if summary:
        parts=re.split(r"(?<=[.!?。])\s+| - ",summary)
        summary=(parts[0] if parts else summary)[:220]
    status=cat.get("status") or "NO_MATCH"
    strength=int(cat.get("material_strength") or 0)
    mclass=cat.get("material_class") or "NONE"
    if strength==0 and mclass=="NOISE":
        assessment="시황·리스트성 / 직접재료 아님"
    elif strength==1:
        assessment="종목 언급 / 인과 약함"
    elif strength==2:
        assessment="테마·업종 재료"
    elif strength>=3:
        assessment="직접 재료 후보"
    elif status=="SPREADING":
        assessment="복수 채널 확산"
    elif status=="MULTI_CHANNEL":
        assessment="복수 채널 확인"
    elif status=="NEW_MENTION":
        assessment="신규 언급"
    elif status=="NEWS_ONLY":
        assessment="외부 뉴스 확인"
    elif status=="SINGLE_OR_REPEAT":
        assessment="단일·반복 가능성"
    else:
        assessment="직접 재료 미확인"
    if flow_state=="돈 선행 / 재료 미확인":
        interpretation="거래대금은 강하지만 직접 연결되는 재료는 아직 확인되지 않음"
    elif flow_state=="재료↔돈 동행":
        interpretation="재료와 거래대금이 함께 확인되는 상태"
    elif flow_state=="재료 확인 / 돈 미약":
        interpretation="재료는 확인되지만 거래대금 상위권 동행은 약함"
    else:
        interpretation=flow_state or "관찰"
    return {
        "summary": summary or f"{stock_name or '종목'} 관련 직접 재료 미확인",
        "assessment": assessment,
        "interpretation": interpretation,
        "source_kind": source_kind,
        "channels": cat.get("channels") or 0,
        "first_seen": cat.get("first_seen"),
        "last_seen": cat.get("last_seen"),
        "news_count": len(news),
        "telegram_count": len(items),
        "dart_count": len(dart),
        "material_strength": strength,
        "material_class": mclass,
        "quality_note": cat.get("quality_note"),
    }

def response_band(query_rank, trade_rank, trade_value=None):
    if query_rank is not None and query_rank <= 5 and trade_rank is not None and trade_rank <= 10:
        return "조회·거래대금 모두 강함"
    if query_rank is not None and query_rank <= 10 and trade_rank is not None and trade_rank <= 30:
        return "조회 강함 · 거래대금 동행"
    if query_rank is not None and query_rank <= 10 and (trade_rank is None or trade_rank > 30):
        return "조회 관심 선행 · 거래대금 동행 약함"
    if trade_rank is not None and trade_rank <= 20:
        return "거래대금 선행"
    return "관찰 단계"

def material_synthesis(digest, query_rank=None, trade_rank=None, change_rate=None, flow_state=None):
    now=datetime.now(timezone.utc)
    first=digest.get("first_seen")
    last=digest.get("last_seen")
    first_dt=None
    try:
        first_dt=datetime.fromisoformat(first) if first else None
    except Exception:
        first_dt=None
    if first_dt and (now-first_dt).total_seconds() <= 90*60:
        newness="신규 후보"
    elif (digest.get("channels") or 0) >= 3:
        newness="확산·재부각"
    elif (digest.get("material_strength") or 0) >= 2:
        newness="확인 필요"
    else:
        newness="직접 재료 미확인"

    response=response_band(query_rank,trade_rank)
    strength=int(digest.get("material_strength") or 0)
    if strength >= 3:
        base="개별 종목 직접 재료가 확인되는 편"
    elif strength == 2:
        base="업종·테마형 재료와 연결되는 편"
    elif strength == 1:
        base="종목 언급은 있으나 현재 가격 움직임의 직접 원인으로 보기엔 약함"
    else:
        base="현재 수집 범위에서는 가격 움직임을 설명할 직접 재료가 뚜렷하지 않음"

    if flow_state=="재료↔돈 동행":
        conclusion=f"{base}. 조회 관심과 거래대금도 함께 확인됩니다."
    elif flow_state=="돈 선행 / 재료 미확인":
        conclusion="거래대금이 먼저 강해졌지만 현재 수집 범위에서는 직접 촉발 재료가 확인되지 않았습니다."
    elif flow_state=="재료 확인 / 돈 미약":
        conclusion=f"{base}. 다만 거래대금 상위권 동행은 아직 제한적입니다."
    elif flow_state=="관심 선행":
        conclusion=f"{base}. 조회 관심이 먼저 붙는 단계로 보입니다."
    else:
        conclusion=base+"."

    if change_rate is not None and abs(float(change_rate)) >= 20 and strength <= 1:
        conclusion += " 등락폭에 비해 설명 가능한 재료 강도가 약해 추가 확인이 필요합니다."

    return {
        "newness":newness,
        "market_response":response,
        "synthesis":conclusion,
    }

def ensure_feedback_table(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS radar_feedback(
      id BIGSERIAL PRIMARY KEY,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      category TEXT NOT NULL,
      stock_code TEXT,
      predicted_state TEXT,
      verdict TEXT NOT NULL,
      note TEXT,
      payload JSONB NOT NULL DEFAULT '{}'::jsonb
    );
    CREATE INDEX IF NOT EXISTS idx_radar_feedback_cat_time ON radar_feedback(category,created_at DESC);
    """)

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


@app.post("/api/feedback")
def feedback(payload: dict = Body(...), x_dashboard_token: Optional[str] = Header(None)):
    require_token(x_dashboard_token)
    category=str(payload.get("category") or "").strip()
    verdict=str(payload.get("verdict") or "").strip()
    if category not in ("material","mimosa"):
        raise HTTPException(status_code=400,detail="invalid category")
    if verdict not in ("correct","wrong"):
        raise HTTPException(status_code=400,detail="invalid verdict")
    stock_code=str(payload.get("stock_code") or "").strip() or None
    predicted_state=str(payload.get("predicted_state") or "").strip() or None
    note=str(payload.get("note") or "").strip() or None
    with get_db() as c:
        with c.cursor() as cur:
            ensure_feedback_table(cur)
            cur.execute("""INSERT INTO radar_feedback(category,stock_code,predicted_state,verdict,note,payload)
                           VALUES(%s,%s,%s,%s,%s,%s::jsonb)""",
                        (category,stock_code,predicted_state,verdict,note,json.dumps(payload,ensure_ascii=False)))
            c.commit()
    return {"status":"ok"}

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

            newsfeed = {"status": "NOT_CONFIGURED", "last_success": None, "note": None}
            if table_exists(cur, "news_feed_status"):
                cur.execute("SELECT status,last_success_at,note FROM news_feed_status WHERE id=1")
                r = cur.fetchone()
                if r:
                    newsfeed = {"status": r[0], "last_success": iso(r[1]), "note": r[2]}

            dartfeed = {"status":"NOT_CONFIGURED","last_success":None,"note":None}
            if table_exists(cur,"dart_feed_status"):
                cur.execute("SELECT status,last_success_at,note FROM dart_feed_status WHERE id=1")
                r=cur.fetchone()
                if r: dartfeed={"status":r[0],"last_success":iso(r[1]),"note":r[2]}

            research = {"status":"NOT_CONFIGURED","last_success":None,"note":None}
            if table_exists(cur, "research_engine_status"):
                cur.execute("SELECT status,last_success_at,note FROM research_engine_status WHERE id=1")
                r=cur.fetchone()
                if r:
                    research={"status":r[0],"last_success":iso(r[1]),"note":r[2]}

            deepresearch = {"status":"NOT_CONFIGURED","last_success":None,"note":None}
            if table_exists(cur,"deep_research_status"):
                cur.execute("SELECT status,last_success_at,note FROM deep_research_status WHERE id=1")
                r=cur.fetchone()
                if r: deepresearch={"status":r[0],"last_success":iso(r[1]),"note":r[2]}

            chartfeed = {"status": "NOT_CONFIGURED", "last_success": None, "note": None}
            if table_exists(cur, "chart_feed_status"):
                cur.execute("SELECT status,last_success_at,note FROM chart_feed_status WHERE id=1")
                r=cur.fetchone()
                if r: chartfeed={"status":r[0],"last_success":iso(r[1]),"note":r[2]}

            mimosa = {"status": "NOT_CONFIGURED", "last_success": None, "note": None}
            if table_exists(cur, "mimosa_status"):
                cur.execute("SELECT status,last_success_at,note FROM mimosa_status WHERE id=1")
                r=cur.fetchone()
                if r: mimosa={"status":r[0],"last_success":iso(r[1]),"note":r[2]}

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
                cur.execute("""SELECT collected_at,message_date,channel_name,text,message_url
                               FROM telegram_messages
                               WHERE collected_at > now()-interval '24 hours'
                               ORDER BY collected_at DESC LIMIT 2000""")
                messages = [{"collected_at":x[0],"message_date":x[1],"channel_name":x[2],"text":x[3],"message_url":x[4]} for x in cur.fetchall()]

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
                    cur.execute("""SELECT stock_code,stock_name,rank_no,trade_value_krw,change_rate,market_cap_krw,official_sector,market_theme,current_price_krw
                                   FROM market_trade_value_snapshots WHERE snapshot_time=%s ORDER BY rank_no NULLS LAST LIMIT 100""",(trade_time,))
                    for x in cur.fetchall():
                        trade_map[x[0]] = {
                            "name": x[1], "rank": x[2], "trade_value": x[3], "change_rate": x[4],
                            "market_cap": x[5], "sector": x[6], "theme": x[7], "current_price": x[8]
                        }

            chart_map = {}
            if table_exists(cur, "chart_states"):
                try:
                    cur.execute("""SELECT DISTINCT ON (stock_code) stock_code,state,state_ko,score,current_price,prior_high,
                                          minute_trend,daily_context,m_contraction,breakout,reasons,snapshot_time
                                   FROM chart_states ORDER BY stock_code,snapshot_time DESC""")
                    for x in cur.fetchall():
                        chart_map[x[0]]={
                            "state":x[1],"state_ko":x[2],"score":x[3],"current_price":x[4],"prior_high":x[5],
                            "minute_trend":x[6],"daily_context":x[7],"m_contraction":x[8],"breakout":x[9],
                            "reasons":x[10] or [],"snapshot_time":iso(x[11])
                        }
                except Exception:
                    chart_map = {}

            strategy_map = {}
            if table_exists(cur, "mimosa_strategy_signals"):
                try:
                    cur.execute("""SELECT DISTINCT ON (stock_code,strategy)
                                          stock_code,strategy,state,state_ko,score,metrics,reasons,source_note,snapshot_time
                                   FROM mimosa_strategy_signals
                                   ORDER BY stock_code,strategy,snapshot_time DESC""")
                    for x in cur.fetchall():
                        strategy_map.setdefault(x[0],{})[x[1]]={
                            "strategy":x[1],"state":x[2],"state_ko":x[3],"score":x[4],
                            "metrics":x[5] or {},"reasons":x[6] or [],"source_note":x[7],
                            "snapshot_time":iso(x[8])
                        }
                except Exception:
                    strategy_map = {}

            news_map = {}
            if table_exists(cur, "stock_news_cache"):
                cur.execute("""SELECT stock_code,stock_name,title,source,published_at,link
                               FROM stock_news_cache
                               WHERE COALESCE(published_at,fetched_at) > now()-interval '48 hours'
                               ORDER BY stock_code,COALESCE(published_at,fetched_at) DESC""")
                for x in cur.fetchall():
                    arr = news_map.setdefault(x[0], [])
                    if len(arr) < 6:
                        arr.append({
                            "stock_name": x[1], "title": x[2], "source": x[3],
                            "published_at": iso(x[4]), "link": x[5]
                        })

            dart_map={}
            if table_exists(cur,"dart_disclosures"):
                cur.execute("""SELECT stock_code,rcept_no,report_nm,category,rcept_dt,disclosure_url,flr_nm
                               FROM dart_disclosures
                               WHERE stock_code IS NOT NULL AND stock_code<>'' AND rcept_dt>=current_date-interval '3 days'
                               ORDER BY stock_code,rcept_dt DESC,rcept_no DESC""")
                for x in cur.fetchall():
                    arr=dart_map.setdefault(x[0],[])
                    if len(arr)<8:
                        arr.append({"rcept_no":x[1],"report_nm":x[2],"category":x[3],
                                    "rcept_dt":x[4].isoformat() if x[4] else None,
                                    "link":x[5],"filer":x[6]})

            rows = []
            for r in ranks:
                code,name,rank_no,rank_change,chg,cap,sector,theme = r
                tv = trade_map.get(code) or {}
                trade_value = tv.get("trade_value")
                cap2 = cap if cap is not None else tv.get("market_cap")
                sector2 = sector or tv.get("sector")
                theme2 = theme or tv.get("theme")
                ratio = None
                try:
                    if trade_value is not None and cap2 and float(cap2) > 0:
                        ratio = float(trade_value)/float(cap2)*100
                except Exception:
                    ratio = None
                cat = catalyst_for_stock(messages, code, name)
                cat["external_news"] = news_map.get(code, [])
                cat["dart"] = dart_map.get(code, [])
                if cat["status"] == "NO_MATCH" and (cat["external_news"] or cat["dart"]):
                    cat["status"] = "NEWS_ONLY"
                    cat["note"] = "Telegram 직접매칭 없음 · 외부뉴스/공시 fallback"
                cat=enrich_catalyst(cat,name)
                theme2 = choose_market_theme(name, sector2, cat)
                flow = stock_flow_state(rank_no, rank_change, tv.get("rank"), cat)
                row = {
                    "rank": rank_no, "rank_change": rank_change, "code": code, "name": name,
                    "change_rate": chg, "trade_rank": tv.get("rank"), "trade_value_krw": trade_value,
                    "market_cap_krw": cap2, "trade_to_cap_pct": ratio,
                    "official_sector": sector2, "market_theme": theme2,
                    "catalyst": cat, "flow_state": flow,
                    "chart_state": (chart_map.get(code) or {}).get("state_ko","대기"),
                    "mimosa": chart_map.get(code) or {"state":"WAITING_FOR_CHART","state_ko":"차트 데이터 대기","score":0},
                    "mimosa_strategies": strategy_map.get(code,{})
                }
                row["analysis"] = stock_analysis(row)
                row["material_digest"] = material_digest(cat,flow,name)
                row["material_digest"].update(material_synthesis(
                    row["material_digest"],rank_no,tv.get("rank"),chg,flow
                ))
                rows.append(row)

            sector_groups = build_sector_groups(rows)
            global_analysis = build_global_analysis(regime, regime_metrics, rows, sector_groups)

            query_by_code={x["code"]:x for x in rows}
            trade_rows=[]
            etf_trade_rows=[]
            for code,tv in sorted(trade_map.items(),key=lambda kv:(kv[1].get("rank") is None,kv[1].get("rank") or 999))[:30]:
                if code in query_by_code:
                    x=dict(query_by_code[code])
                    x["trade_rank"]=tv.get("rank")
                    if is_etf_like(x.get("name")):
                        etf_trade_rows.append(x)
                    else:
                        trade_rows.append(x)
                    continue
                name=tv.get("name") or code
                cat=catalyst_for_stock(messages,code,name)
                cat["external_news"]=news_map.get(code,[])
                cat["dart"]=dart_map.get(code,[])
                if cat["status"]=="NO_MATCH" and (cat["external_news"] or cat["dart"]):
                    cat["status"]="NEWS_ONLY";cat["note"]="Telegram 직접매칭 없음 · 외부뉴스/공시 fallback"
                cat=enrich_catalyst(cat,name)
                cap=tv.get("market_cap"); value=tv.get("trade_value")
                ratio=(float(value)/float(cap)*100) if value is not None and cap and float(cap)>0 else None
                theme=choose_market_theme(name, tv.get("sector"), cat)
                flow=stock_flow_state(None,None,tv.get("rank"),cat)
                x={"rank":None,"rank_change":None,"code":code,"name":name,"change_rate":tv.get("change_rate"),
                   "trade_rank":tv.get("rank"),"trade_value_krw":value,"market_cap_krw":cap,"trade_to_cap_pct":ratio,
                   "official_sector":tv.get("sector"),"market_theme":theme,"catalyst":cat,"flow_state":flow,
                   "chart_state":(chart_map.get(code) or {}).get("state_ko","대기"),
                   "mimosa":chart_map.get(code) or {"state":"WAITING_FOR_CHART","state_ko":"차트 데이터 대기","score":0},
                   "mimosa_strategies":strategy_map.get(code,{})}
                x["analysis"]=stock_analysis(x)
                x["material_digest"]=material_digest(cat,flow,name)
                x["material_digest"].update(material_synthesis(
                    x["material_digest"],None,tv.get("rank"),tv.get("change_rate"),flow
                ))
                if is_etf_like(name):
                    etf_trade_rows.append(x)
                else:
                    trade_rows.append(x)

            material_seen=set(); material_rows=[]
            for x in rows+trade_rows:
                if x["code"] in material_seen: continue
                material_seen.add(x["code"])
                material_rows.append({
                    "code":x["code"],"name":x["name"],"change_rate":x.get("change_rate"),
                    "query_rank":x.get("rank"),"trade_rank":x.get("trade_rank"),
                    "sector":x.get("official_sector") or x.get("market_theme") or "미분류",
                    "flow_state":x.get("flow_state"),"digest":x.get("material_digest"),
                    "catalyst":x.get("catalyst")
                })
            material_rows.sort(key=lambda x:(
                x["digest"]["assessment"]=="직접 재료 미확인",
                x["trade_rank"] is None,x["trade_rank"] or 999,x["query_rank"] is None,x["query_rank"] or 999
            ))

            mimosa_rows=[]
            for x in rows:
                m=x.get("mimosa") or {}
                mimosa_rows.append({
                    "code":x["code"],"name":x["name"],"change_rate":x.get("change_rate"),
                    "query_rank":x.get("rank"),"trade_rank":x.get("trade_rank"),
                    "sector":x.get("market_theme") or x.get("official_sector") or "미분류",
                    "strategies":x.get("mimosa_strategies") or {},
                    **m
                })
            mimosa_rows.sort(key=lambda x:(-(float(x.get("score") or 0)),x.get("query_rank") or 999))

            strategy_lists={"CLOSE_BET":[],"OVERSOLD":[],"FALLING_STOCK":[]}
            seen_strategy=set()
            for x in rows+trade_rows:
                if x["code"] in seen_strategy: continue
                seen_strategy.add(x["code"])
                for sk in strategy_lists:
                    sig=(x.get("mimosa_strategies") or {}).get(sk)
                    if not sig: continue
                    item={"code":x["code"],"name":x["name"],"change_rate":x.get("change_rate"),
                          "query_rank":x.get("rank"),"trade_rank":x.get("trade_rank"),
                          "sector":x.get("market_theme") or x.get("official_sector") or "미분류",**sig}
                    strategy_lists[sk].append(item)
            for sk in strategy_lists:
                strategy_lists[sk].sort(key=lambda z:(
                    z.get("state","").endswith("_NO"),
                    -(float(z.get("score") or 0)),
                    z.get("query_rank") or 999
                ))

            material_stats={
                "direct":sum(1 for x in material_rows if int((x.get("digest") or {}).get("material_strength") or 0)>=3),
                "sector":sum(1 for x in material_rows if int((x.get("digest") or {}).get("material_strength") or 0)==2),
                "weak":sum(1 for x in material_rows if int((x.get("digest") or {}).get("material_strength") or 0)<=1),
                "spreading":sum(1 for x in material_rows if (x.get("catalyst") or {}).get("channels",0)>=3),
            }
            if sector_groups:
                tops=", ".join([f"{g['name']}({g['count']})" for g in sector_groups[:3]])
                global_analysis.append(f"상위 조회집중 섹터: {tops}.")
            global_analysis.append(
                f"재료 품질: 직접 재료 후보 {material_stats['direct']}개, 테마형 {material_stats['sector']}개, "
                f"약한 언급/미확인 {material_stats['weak']}개."
            )
            latest_market=max([x for x in (rank_time,trade_time) if x],default=None)
            market_age_sec=int((datetime.now(timezone.utc)-latest_market).total_seconds()) if latest_market else None
            session=market_session_state()
            fresh=bool(market_age_sec is not None and market_age_sec<=180)
            market_snapshot={
                "time":iso(latest_market),"age_sec":market_age_sec,
                "session_code":session["code"],"session_label":session["label"],
                "is_live":bool(session["is_live"] and fresh),
                "stale":bool(not fresh),
            }

            sectors = []
            if table_exists(cur, "market_sector_snapshots"):
                cur.execute("SELECT MAX(snapshot_time) FROM market_sector_snapshots")
                st = cur.fetchone()[0]
                if st:
                    cur.execute("""SELECT sector_name,change_rate,trade_value_krw,rising_count,falling_count
                                   FROM market_sector_snapshots WHERE snapshot_time=%s
                                   ORDER BY trade_value_krw DESC NULLS LAST LIMIT 10""",(st,))
                    sectors=[{"name":x[0],"change_rate":x[1],"trade_value_krw":x[2],"rising":x[3],"falling":x[4]} for x in cur.fetchall()]

            index_charts={}
            if table_exists(cur, "index_minute_bars") or table_exists(cur, "index_daily_bars"):
                for idx_code,idx_name in (("001","KOSPI"),("101","KOSDAQ")):
                    intraday=[];daily=[]
                    if table_exists(cur, "index_minute_bars"):
                        cur.execute("""SELECT bar_time,open_value,high_value,low_value,close_value,volume
                                       FROM index_minute_bars
                                       WHERE index_code=%s
                                       ORDER BY bar_time DESC LIMIT 120""",(idx_code,))
                        rr=list(reversed(cur.fetchall()))
                        intraday=[{"time":iso(x[0]),"open":x[1],"high":x[2],"low":x[3],"close":x[4],"volume":x[5]} for x in rr]
                    if table_exists(cur, "index_daily_bars"):
                        cur.execute("""SELECT trade_date,open_value,high_value,low_value,close_value,volume,trade_value
                                       FROM index_daily_bars
                                       WHERE index_code=%s
                                       ORDER BY trade_date DESC LIMIT 120""",(idx_code,))
                        rr=list(reversed(cur.fetchall()))
                        daily=[{"date":x[0].isoformat(),"open":x[1],"high":x[2],"low":x[3],"close":x[4],"volume":x[5],"trade_value":x[6]} for x in rr]
                    index_charts[idx_name]={"code":idx_code,"intraday":intraday,"daily":daily}

            research_rows=[]
            if table_exists(cur,"research_jobs") and table_exists(cur,"research_results"):
                cur.execute("""SELECT j.id,j.created_at,j.stock_code,j.stock_name,j.priority,j.trigger_types,
                                      j.status,r.mode,r.headline,r.summary,r.evidence,r.deep_research_needed
                               FROM research_jobs j
                               JOIN research_results r ON r.job_id=j.id
                               WHERE j.created_at>now()-interval '24 hours'
                               ORDER BY j.priority DESC,j.created_at DESC
                               LIMIT 40""")
                research_rows=[{
                    "id":x[0],"created_at":iso(x[1]),"code":x[2],"name":x[3],"priority":x[4],
                    "triggers":x[5] or [],"status":x[6],"mode":x[7],"headline":x[8],"summary":x[9],
                    "evidence":x[10] or [],"deep_research_needed":bool(x[11])
                } for x in cur.fetchall()]

            deep_reports=[]
            if table_exists(cur,"deep_research_reports"):
                cur.execute("""SELECT job_id,created_at,stock_code,stock_name,priority,confidence,headline,
                                      why_now,catalyst_summary,market_response,sector_confirmation,mimosa_summary,
                                      risk_flags,evidence_summary,agent_outputs,report_version
                               FROM deep_research_reports
                               WHERE created_at>now()-interval '24 hours'
                               ORDER BY priority DESC,created_at DESC
                               LIMIT 30""")
                deep_reports=[{
                    "job_id":x[0],"created_at":iso(x[1]),"code":x[2],"name":x[3],"priority":x[4],
                    "confidence":x[5],"headline":x[6],"why_now":x[7],"catalyst_summary":x[8],
                    "market_response":x[9],"sector_confirmation":x[10],"mimosa_summary":x[11],
                    "risk_flags":x[12] or [],"evidence_summary":x[13] or {},
                    "agent_outputs":x[14] or {},"report_version":x[15]
                } for x in cur.fetchall()]

            # recent telegram: full text is preserved in the API/UI
            recent_telegram=[]
            for m in messages[:40]:
                txt=re.sub(r"\s+"," ",m["text"] or "").strip()
                recent_telegram.append({
                    "time":iso(m["message_date"] or m["collected_at"]),
                    "channel":m["channel_name"],
                    "text":txt[:6000],
                    "message_url":m.get("message_url"),
                    "links":extract_links(m["text"] or "")
                })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system": {"telegram": telegram, "kiwoom": kiwoom, "newsfeed": newsfeed, "dartfeed": dartfeed, "chartfeed": chartfeed, "mimosa": mimosa, "research": research, "deepresearch": deepresearch},
        "regime": regime,
        "regime_metrics": regime_metrics,
        "rank_time": iso(rank_time),
        "trade_time": iso(trade_time),
        "rows": rows,
        "query_ranking": rows,
        "trade_ranking": trade_rows,
        "etf_trade_ranking": etf_trade_rows,
        "sector_rankings": sector_groups,
        "materials": material_rows,
        "material_stats": material_stats,
        "market_snapshot": market_snapshot,
        "mimosa_rows": mimosa_rows,
        "mimosa_strategies": strategy_lists,
        "index_charts": index_charts,
        "research_rows": research_rows,
        "deep_reports": deep_reports,
        "analysis": {
            "mode": "RULE_BASED",
            "lines": global_analysis,
            "note": "실시간 조회순위·거래대금·Telegram 직접매칭을 조합한 규칙 기반 해석"
        },
        "sectors": sectors,
        "telegram_recent": recent_telegram,
    }

DASHBOARD_HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Radar</title>
<style>
:root{--bg:#0b1020;--card:#131a2d;--line:#27324d;--txt:#eef2ff;--muted:#91a0bf;--good:#42d392;--bad:#ff6b7d;--warn:#f7c948;--accent:#7c9cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1720px;margin:auto;padding:20px}.top{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:15px}
h1{font-size:26px;margin:0}.sub,.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.card,.panel{background:var(--card);border:1px solid var(--line);border-radius:14px}.card{padding:14px}.label{color:var(--muted);font-size:12px}.big{font-size:19px;font-weight:750;margin-top:5px}
.panel{margin-top:14px;overflow:hidden}.panel h2{font-size:15px;margin:0;padding:13px 14px;border-bottom:1px solid var(--line)}.pad{padding:13px 14px}
.analysis-line{padding:7px 0;border-bottom:1px solid #202942}.analysis-line:last-child{border:0}
table{width:100%;border-collapse:collapse}th,td{padding:9px 8px;border-bottom:1px solid #202942;text-align:right;vertical-align:top}th{color:var(--muted);font-size:12px;position:sticky;top:0;background:var(--card);z-index:2}
.left{text-align:left}.up{color:var(--good)}.dn{color:var(--bad)}.wait{color:var(--warn)}
.pill{display:inline-block;padding:3px 7px;border:1px solid var(--line);border-radius:999px;font-size:11px;color:#cbd5e1;margin:1px 3px 1px 0}
.wrapcell{white-space:normal;min-width:260px;max-width:560px;text-align:left}.stockcell{min-width:130px;text-align:left}.sectorcell{min-width:130px;text-align:left}
details{white-space:normal}summary{cursor:pointer;color:#dbe4ff}.item{padding:8px 0;border-top:1px solid #202942}.item p{margin:3px 0;color:#d2daec}.item a{color:#9eb4ff;text-decoration:none;margin-right:8px}
.two{display:grid;grid-template-columns:1.1fr .9fr;gap:14px}.scroll{overflow:auto;max-height:650px}
.sector-stock{display:inline-block;margin:2px 5px 2px 0;padding:2px 6px;border:1px solid var(--line);border-radius:8px;font-size:11px}
.note{font-size:12px;color:var(--muted);padding-top:7px}
@media(max-width:1000px){.grid{grid-template-columns:1fr 1fr}.two{grid-template-columns:1fr}.wrap{padding:10px}.panel{overflow:auto}}
</style></head>
<body><div class="wrap">
<div class="top"><div><h1>MARKET RADAR</h1><div class="sub">시장 → 섹터 → 조회관심 → 돈 → 재료/뉴스 → 차트</div></div><div class="sub" id="stamp">연결 중…</div></div>

<div class="grid">
<div class="card"><div class="label">오늘 시장</div><div class="big" id="regime">대기</div></div>
<div class="card"><div class="label">Kiwoom Feed</div><div class="big" id="kiwoom">대기</div></div>
<div class="card"><div class="label">Telegram / 외부뉴스</div><div class="big" id="telegram">대기</div><div class="label" id="newsfeed">뉴스 대기</div></div>
<div class="card"><div class="label">조회 Top20 교체율</div><div class="big" id="turnover">-</div></div>
</div>

<div class="panel"><h2>RADAR 분석 <span class="muted">· 규칙 기반</span></h2><div class="pad" id="analysis"></div></div>

<div class="panel"><h2>실시간 조회상위 · 섹터별 집중 순위</h2>
<div class="scroll"><table><thead><tr><th>섹터순위</th><th class="left">섹터</th><th>조회상위 종목수</th><th>평균 조회순위</th><th>평균 등락</th><th>합산 거래대금</th><th class="left">상위 종목</th></tr></thead><tbody id="sectorRanks"></tbody></table></div>
<div class="pad note">※ 이 순위는 공식 업종지수 순위가 아니라, 실시간 종목조회 상위권에 어떤 섹터가 얼마나 몰렸는지를 집계한 ‘조회관심 집중도’입니다.</div>
</div>

<div class="panel"><h2>실시간 종목조회 레이더</h2><div class="scroll"><table><thead><tr>
<th>조회순위</th><th class="left">종목</th><th>등락률</th><th>거래대금순위</th><th>거래대금</th><th>시총대비*</th>
<th class="left">섹터</th><th class="left">흐름</th><th class="left">재료·기사</th><th class="left">RADAR 해석</th><th class="left">차트</th>
</tr></thead><tbody id="tbody"></tbody></table></div>
<div class="pad note">* 시총대비 거래대금은 Kiwoom 원시 단위 첫 실전장 검증 전까지 잠정값으로 취급합니다.</div>
</div>

<div class="two">
<div class="panel"><h2>공식 업종 데이터</h2><div id="sectors"></div></div>
<div class="panel"><h2>Telegram 최신 · 원문 보존</h2><div class="scroll" id="tels"></div></div>
</div>
</div>
<script>
let token=location.hash.slice(1)||localStorage.getItem("marketRadarToken")||"";
if(location.hash){localStorage.setItem("marketRadarToken",token);history.replaceState(null,"",location.pathname);}
const fmt=(v)=>v==null?"-":Number(v).toLocaleString("ko-KR",{maximumFractionDigits:1});
const pct=(v)=>v==null?"-":(Number(v)*100).toFixed(1)+"%";
const cls=(v)=>Number(v)>0?"up":Number(v)<0?"dn":"";
const esc=(v)=>String(v??"").replace(/[&<>"']/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));
function linkHtml(u,label){if(!u)return"";return '<a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(label||"링크")+'</a>';}
function renderCatalyst(c){
 if(!c) return '<span class="pill wait">재료 미확인</span>';
 let head='<span class="pill">'+esc(c.status||"NO_MATCH")+'</span>';
 if(c.channels) head+='<span class="pill">'+esc(c.channels)+'ch</span>';
 let items=(c.items||[]).map(function(it){
   let links=(it.links||[]).map(function(u,i){return linkHtml(u,"기사/링크 "+(i+1));}).join("");
   if(it.telegram_url) links+=linkHtml(it.telegram_url,"Telegram 원문");
   return '<div class="item"><b>'+esc(it.channel||"")+' · '+esc(it.time?new Date(it.time).toLocaleTimeString("ko-KR",{hour:"2-digit",minute:"2-digit"}):"")+'</b><p>'+esc(it.text||"")+'</p><div>'+links+'</div></div>';
 }).join("");
 let news=(c.external_news||[]).map(function(n){
   return '<div class="item"><b>외부뉴스 · '+esc(n.source||"source")+'</b><p>'+esc(n.title||"")+'</p><div>'+linkHtml(n.link,"기사 열기")+'</div></div>';
 }).join("");
 if(!items && !news) return head+'<div class="muted">'+esc(c.note||"최근 24시간 직접매칭 없음")+'</div>';
 return head+'<details><summary>'+esc(c.summary||((c.external_news||[])[0]?.title)||"관련 재료·기사 보기")+'</summary>'+items+news+'</details>';
}
async function load(){
 if(!token){document.getElementById("regime").innerHTML='<span class="wait">접속키 필요</span>';return;}
 try{
  const r=await fetch("/api/dashboard",{headers:{"x-dashboard-token":token}});
  if(!r.ok) throw new Error("HTTP "+r.status);
  const d=await r.json();
  document.getElementById("stamp").textContent=new Date(d.generated_at).toLocaleString("ko-KR");
  document.getElementById("regime").textContent=d.regime.stable_label||d.regime.candidate_label||d.regime.status;
  document.getElementById("kiwoom").textContent=d.system.kiwoom.status+(d.system.kiwoom.note?" · "+d.system.kiwoom.note:"");
  document.getElementById("telegram").textContent=(d.system.telegram.count_24h||0).toLocaleString()+"건 / 24h";
  document.getElementById("newsfeed").textContent="외부뉴스: "+(d.system.newsfeed?.status||"미연결")+(d.system.newsfeed?.note?" · "+d.system.newsfeed.note:"");
  document.getElementById("turnover").textContent=d.regime_metrics?.rank_turnover_5m==null?"-":pct(d.regime_metrics.rank_turnover_5m);

  document.getElementById("analysis").innerHTML=(d.analysis?.lines||[]).map(function(x){return '<div class="analysis-line">'+esc(x)+'</div>';}).join("")||'<div class="wait">분석 데이터 대기</div>';

  const sr=d.sector_rankings||[];
  document.getElementById("sectorRanks").innerHTML=sr.length?sr.map(function(g){
    let stocks=(g.stocks||[]).map(function(x){return '<span class="sector-stock">#'+esc(x.rank??"-")+' '+esc(x.name||x.code)+' '+(x.change_rate==null?"":esc(fmt(x.change_rate))+"%")+'</span>';}).join("");
    return '<tr><td>'+esc(g.sector_rank)+'</td><td class="left"><b>'+esc(g.name)+'</b></td><td>'+esc(g.count)+'</td><td>'+esc(g.avg_rank==null?"-":g.avg_rank.toFixed(1))+'</td><td class="'+cls(g.avg_change_rate)+'">'+esc(g.avg_change_rate==null?"-":fmt(g.avg_change_rate)+"%")+'</td><td>'+esc(g.trade_value_krw?fmt(g.trade_value_krw/1e8)+"억":"-")+'</td><td class="left">'+stocks+'</td></tr>';
  }).join(""):'<tr><td colspan="7" class="wait">실시간 조회순위 데이터 대기 중</td></tr>';

  const rows=d.rows||[];
  document.getElementById("tbody").innerHTML=rows.length?rows.map(function(x){
   let arrow=x.rank_change==null?"":(x.rank_change>0?"↑":x.rank_change<0?"↓":"")+Math.abs(x.rank_change||0);
   return '<tr>'+
   '<td>'+esc(x.rank??"-")+' <span class="'+cls(x.rank_change)+'">'+esc(arrow)+'</span></td>'+
   '<td class="stockcell"><b>'+esc(x.name||x.code)+'</b><div class="label">'+esc(x.code)+'</div></td>'+
   '<td class="'+cls(x.change_rate)+'">'+esc(x.change_rate==null?"-":fmt(x.change_rate)+"%")+'</td>'+
   '<td>'+esc(x.trade_rank??"-")+'</td>'+
   '<td>'+esc(x.trade_value_krw==null?"-":fmt(x.trade_value_krw/1e8)+"억")+'</td>'+
   '<td>'+esc(x.trade_to_cap_pct==null?"-":Number(x.trade_to_cap_pct).toFixed(1)+"%")+'</td>'+
   '<td class="sectorcell">'+esc(x.official_sector||x.market_theme||"미분류")+'</td>'+
   '<td class="wrapcell"><span class="pill">'+esc(x.flow_state||"관찰")+'</span></td>'+
   '<td class="wrapcell">'+renderCatalyst(x.catalyst)+'</td>'+
   '<td class="wrapcell">'+esc(x.analysis||"")+'</td>'+
   '<td class="left">'+esc(x.chart_state||"대기")+'</td></tr>';
  }).join(""):'<tr><td colspan="11" class="wait">키움 실시간 종목조회 데이터 대기 중</td></tr>';

  document.getElementById("sectors").innerHTML=(d.sectors||[]).map(function(x){
    return '<div class="item"><b>'+esc(x.name)+'</b> <span class="'+cls(x.change_rate)+'">'+esc(x.change_rate==null?"":fmt(x.change_rate)+"%")+'</span><p>거래대금 '+esc(x.trade_value_krw==null?"-":fmt(x.trade_value_krw/1e8)+"억")+' · 상승 '+esc(x.rising??"-")+' / 하락 '+esc(x.falling??"-")+'</p></div>';
  }).join("")||'<div class="pad wait">업종 데이터 대기 중</div>';

  document.getElementById("tels").innerHTML=(d.telegram_recent||[]).map(function(x){
    let links=(x.links||[]).map(function(u,i){return linkHtml(u,"기사/링크 "+(i+1));}).join("");
    if(x.message_url)links+=linkHtml(x.message_url,"Telegram 원문");
    return '<div class="item pad"><b>'+esc(x.time?new Date(x.time).toLocaleTimeString("ko-KR",{hour:"2-digit",minute:"2-digit"}):"")+' · '+esc(x.channel)+'</b><details><summary>'+esc((x.text||"").slice(0,220))+(x.text&&x.text.length>220?"…":"")+'</summary><p>'+esc(x.text||"")+'</p><div>'+links+'</div></details></div>';
  }).join("");
 }catch(e){document.getElementById("kiwoom").textContent="연결 오류";console.error(e);}
}
load();setInterval(load,10000);
</script></body></html>"""

@app.get("/", response_class=HTMLResponse)
def root():
    return HTMLResponse(DASHBOARD_HTML_V2 or DASHBOARD_HTML)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","8080")))
