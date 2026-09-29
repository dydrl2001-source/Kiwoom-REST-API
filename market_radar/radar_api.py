import os, json, re, secrets, threading, time as pytime
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
try:
    from flow_core import delta as radar_flow_delta, reversal_signals as radar_reversal_signals
except Exception:
    radar_flow_delta = None
    radar_reversal_signals = None
try:
    from report_library import clean_report as radar_clean_report
except Exception:
    radar_clean_report = None
try:
    from evidence_identity import identity_quality, usable_as_catalyst, usable_for_theme, stock_context
except Exception:
    def identity_quality(name,text,source_kind="",official_sector=None): return "NAME_MATCH"
    def usable_as_catalyst(q): return q not in ("ENTITY_CONFLICT","LIST_MENTION","MISSING_NAME")
    def usable_for_theme(q): return q in ("VERIFIED","CONTEXT_VERIFIED")
    def stock_context(text,name,radius=130): return str(text or "")
try:
    from ai_brokerage.decision_engine import DecisionEngine as AIBrokerageDecisionEngine
    from ai_brokerage.adapter import context_from_dashboard_row as ai_context_from_dashboard_row
    from ai_brokerage.analytics import summarize_strategy_rows as ai_summarize_strategy_rows
    from ai_brokerage.analytics import build_context_matrix as ai_build_context_matrix
    from ai_brokerage.analytics import lifecycle_candidates as ai_lifecycle_candidates
    from ai_brokerage.analytics import build_daily_review as ai_build_daily_review
    from ai_brokerage.capacity import execution_adjusted_strategy_rows as ai_execution_adjusted_strategy_rows
    from ai_brokerage.capacity import build_capacity_matrix as ai_build_capacity_matrix
    from ai_brokerage.capacity import strategy_capacity_rows as ai_strategy_capacity_rows
    from ai_brokerage.capacity import execution_adjusted_lifecycle as ai_execution_adjusted_lifecycle
    from ai_brokerage.allocation import AllocationPolicy as AIAllocationPolicy
    from ai_brokerage.allocation import correlation_matrix as ai_correlation_matrix
    from ai_brokerage.allocation import optimize_allocations as ai_optimize_allocations
    from ai_brokerage.execution_model import SizingPolicy as AISizingPolicy
    from ai_brokerage.execution_model import BookPolicy as AIBookPolicy
    from ai_brokerage.execution_model import estimate_book_capacity as ai_estimate_book_capacity
    from ai_brokerage.risk_control import RiskControlPolicy as AIRiskControlPolicy
    from ai_brokerage.risk_control import evaluate_kill_switch as ai_evaluate_kill_switch
    from ai_brokerage.risk_control import evaluate_live_readiness as ai_evaluate_live_readiness
    from ai_brokerage.risk_control import rebalance_portfolio as ai_rebalance_portfolio
except Exception:
    try:
        from market_radar.ai_brokerage.decision_engine import DecisionEngine as AIBrokerageDecisionEngine
        from market_radar.ai_brokerage.adapter import context_from_dashboard_row as ai_context_from_dashboard_row
        from market_radar.ai_brokerage.analytics import summarize_strategy_rows as ai_summarize_strategy_rows
        from market_radar.ai_brokerage.analytics import build_context_matrix as ai_build_context_matrix
        from market_radar.ai_brokerage.analytics import lifecycle_candidates as ai_lifecycle_candidates
        from market_radar.ai_brokerage.analytics import build_daily_review as ai_build_daily_review
        from market_radar.ai_brokerage.capacity import execution_adjusted_strategy_rows as ai_execution_adjusted_strategy_rows
        from market_radar.ai_brokerage.capacity import build_capacity_matrix as ai_build_capacity_matrix
        from market_radar.ai_brokerage.capacity import strategy_capacity_rows as ai_strategy_capacity_rows
        from market_radar.ai_brokerage.capacity import execution_adjusted_lifecycle as ai_execution_adjusted_lifecycle
        from market_radar.ai_brokerage.allocation import AllocationPolicy as AIAllocationPolicy
        from market_radar.ai_brokerage.allocation import correlation_matrix as ai_correlation_matrix
        from market_radar.ai_brokerage.allocation import optimize_allocations as ai_optimize_allocations
        from market_radar.ai_brokerage.execution_model import SizingPolicy as AISizingPolicy
        from market_radar.ai_brokerage.execution_model import BookPolicy as AIBookPolicy
        from market_radar.ai_brokerage.execution_model import estimate_book_capacity as ai_estimate_book_capacity
        from market_radar.ai_brokerage.risk_control import RiskControlPolicy as AIRiskControlPolicy
        from market_radar.ai_brokerage.risk_control import evaluate_kill_switch as ai_evaluate_kill_switch
        from market_radar.ai_brokerage.risk_control import evaluate_live_readiness as ai_evaluate_live_readiness
        from market_radar.ai_brokerage.risk_control import rebalance_portfolio as ai_rebalance_portfolio
    except Exception:
        AIBrokerageDecisionEngine = None
        ai_context_from_dashboard_row = None
        ai_summarize_strategy_rows = None
        ai_build_context_matrix = None
        ai_lifecycle_candidates = None
        ai_build_daily_review = None
        ai_execution_adjusted_strategy_rows = None
        ai_build_capacity_matrix = None
        ai_strategy_capacity_rows = None
        ai_execution_adjusted_lifecycle = None
        AIAllocationPolicy = None
        ai_correlation_matrix = None
        ai_optimize_allocations = None
        AISizingPolicy = None
        AIBookPolicy = None
        ai_estimate_book_capacity = None
        AIRiskControlPolicy = None
        ai_evaluate_kill_switch = None
        ai_evaluate_live_readiness = None
        ai_rebalance_portfolio = None

AI_BROKERAGE_ENGINE = AIBrokerageDecisionEngine() if AIBrokerageDecisionEngine else None

DB = os.getenv("DATABASE_URL", "")
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")
KIWOOM_INGEST_TOKEN = os.getenv("KIWOOM_INGEST_TOKEN", "")
DASHBOARD_CACHE_SECONDS = max(5, min(60, int(os.getenv("DASHBOARD_CACHE_SECONDS", "20"))))
_LEADER_CALENDAR_CACHE_SECONDS = max(60, min(3600, int(os.getenv("LEADER_CALENDAR_CACHE_SECONDS", "300"))))
_DASH_CACHE_LOCK = threading.Lock()
_DASH_CACHE = None
_DASH_CACHE_AT = 0.0
_LEADER_CAL_CACHE_LOCK = threading.Lock()
_LEADER_CAL_CACHE = None
_LEADER_CAL_CACHE_AT = 0.0
_LEADER_CAL_CACHE_KEY = None
app = FastAPI(title="Market Radar", version="0.7.0")

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
    "태양광/에너지": ["태양광", "솔라", "태양광 모듈", "폴리실리콘"],
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
    "OCI홀딩스":"태양광/에너지","한화솔루션":"태양광/에너지",
    "SK이노베이션":"2차전지/배터리",
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
    # Theme inference is accepted only when the evidence was identity/context verified
    # and the theme came from text close to the actual stock name.
    if strength >= 2 and usable_for_theme((catalyst or {}).get("best_identity_quality")):
        t=(catalyst or {}).get("theme")
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

def column_exists(cur, table: str, column: str) -> bool:
    cur.execute("""SELECT EXISTS(
                   SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=%s AND column_name=%s)""",
                (table,column))
    return bool(cur.fetchone()[0])

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
        compact = str(name).replace("주식회사","").replace("㈜","")
        compact = re.sub(r"[\s()]+", "", compact)
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

def catalyst_for_stock(messages, code, name, official_sector=None):
    aliases = stock_aliases(code, name)
    matched = []
    rejected = 0
    for m in messages:
        txt = m["text"] or ""
        compact = re.sub(r"\s+", "", txt)
        if not any((a in txt) or (len(a) >= 2 and a in compact) for a in aliases):
            continue
        q=identity_quality(name,txt,"Telegram",official_sector)
        if not usable_as_catalyst(q):
            rejected += 1
            continue
        mm=dict(m)
        mm["identity_quality"]=q
        matched.append(mm)
    if not matched:
        return {
            "summary": None, "status": "NO_MATCH", "channels": 0, "theme": None,
            "first_seen": None, "last_seen": None, "items": [], "article_links": [],
            "identity_rejected":rejected,
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
        q=x.get("identity_quality")
        if not usable_for_theme(q):
            continue
        context=stock_context(x.get("text") or "",name)
        theme = infer_theme(context)
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
            "identity_quality":x.get("identity_quality"),
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
        "identity_rejected":rejected,
        "note": None,
    }

def sector_reason_summary(group):
    """Explain the observed sector move only as far as collected evidence supports it."""
    stocks=group.get("stocks") or []
    evidence=[]
    for x in stocks:
        d=x.get("material_digest") or {}
        strength=int(d.get("material_strength") or 0)
        identity=d.get("identity_quality") or "UNVERIFIED"
        if strength>=2:
            evidence.append({
                "code":x.get("code"),"name":x.get("name"),
                "summary":d.get("summary"),"assessment":d.get("assessment"),
                "source_kind":d.get("source_kind"),"strength":strength,
                "material_type":d.get("material_type"),"identity_quality":identity
            })
    evidence.sort(key=lambda x:(-x["strength"],0 if x["identity_quality"] in ("VERIFIED","CONTEXT_VERIFIED") else 1,x.get("name") or ""))
    verified_direct=[x for x in evidence if x["strength"]>=3 and x["identity_quality"] in ("VERIFIED","CONTEXT_VERIFIED")]
    name_direct=[x for x in evidence if x["strength"]>=3 and x["identity_quality"]=="NAME_MATCH"]
    sector=[x for x in evidence if x["strength"]==2]
    positive=int(group.get("positive") or 0)
    count=int(group.get("change_n") or group.get("count") or 0)
    breadth=f"{positive}/{count}종목 상승" if count else "상승폭 표본 부족"
    recent=group.get("recent_turnover_krw") or 0

    if len(verified_direct)>=2:
        names=", ".join(x["name"] for x in verified_direct[:3] if x.get("name"))
        reason=f"복수 종목에 신원 확인된 개별 재료가 있음({names}). {breadth}. 다만 서로 다른 사건일 수 있어 섹터 공통 원인으로 확정하지 않음."
        level="PARTIAL"
        label="복수 개별재료"
    elif verified_direct:
        x=verified_direct[0]
        reason=f"{x.get('name')}: {x.get('summary') or '직접 재료 확인'}. {breadth}. 섹터 전체 공통 원인 여부는 미확인."
        level="PARTIAL"
        label="신원확인 직접재료"
    elif name_direct:
        x=name_direct[0]
        reason=f"{x.get('name')} 관련 직접재료 후보가 있으나 종목명 일치 수준이라 동명이인·맥락 확인이 더 필요함. {breadth}."
        level="UNCONFIRMED"
        label="신원 추가확인"
    elif sector:
        x=sector[0]
        reason=f"업종·테마형 재료가 관측됨: {x.get('summary') or x.get('assessment') or '테마 재료'}. {breadth}. 공통 촉발 원인은 미확정."
        level="PARTIAL"
        label="테마형 재료"
    elif recent and recent>0:
        reason=f"공통 촉발 재료는 아직 확인되지 않음. 다만 {breadth}이고 최근 관측구간 거래대금이 집중되는 상태."
        level="UNCONFIRMED"
        label="돈·관심 선행"
    else:
        reason=f"현재 수집 범위에서 섹터 공통 상승 재료를 확인하지 못함. {breadth}; 원인 확정은 보류."
        level="UNCONFIRMED"
        label="공통재료 미확인"
    return {
        "summary":reason,"level":level,"label":label,
        "evidence":evidence[:4],
        "note":"섹터 구성종목의 뉴스·공시·Telegram·거래 관측 요약. 신원 검증과 공통 인과는 별개"
    }

def theme_strength_for_groups(groups):
    """Operational 0-100 *current-theme observation strength*, not return probability.

    Components:
      interest 20  = relative query concentration in the current sample
      money    30  = relative recent SOR turnover; cumulative turnover fallback is capped
      breadth  20  = share of observed sector stocks currently positive
      price    10  = positive average move, capped at +8%
      surge    10  = count represented in query Top12, capped at 4 stocks
      material 10  = evidence coverage (supported / partial / unconfirmed)
    """
    if not groups:
        return groups
    max_query=max([float(g.get("query_score") or 0) for g in groups] or [0])
    max_recent=max([float(g.get("recent_turnover_krw") or 0) for g in groups] or [0])
    max_total=max([float(g.get("trade_value_krw") or 0) for g in groups] or [0])
    for g in groups:
        interest=20*(float(g.get("query_score") or 0)/max_query) if max_query>0 else 0
        if g.get("recent_turnover_known") and max_recent>0:
            money=30*(float(g.get("recent_turnover_krw") or 0)/max_recent)
            money_basis="RECENT_SOR"
        else:
            # Fallback is deliberately capped below the real-time component.
            money=20*(float(g.get("trade_value_krw") or 0)/max_total) if max_total>0 else 0
            money_basis="CUMULATIVE_FALLBACK"
        breadth=20*max(0,min(1,float(g.get("positive_ratio") or 0)))
        avg=float(g.get("avg_change_rate") or 0)
        price=10*max(0,min(1,avg/8.0))
        surge=10*max(0,min(1,float(g.get("surge_count") or 0)/4.0))
        level=(g.get("reason") or {}).get("level")
        material=10 if level=="SUPPORTED" else 5 if level=="PARTIAL" else 0
        score=round(max(0,min(100,interest+money+breadth+price+surge+material)))
        if score>=80: label="매우 강"
        elif score>=65: label="강"
        elif score>=50: label="보통"
        elif score>=35: label="약"
        else: label="미약"
        g["theme_strength"]=score
        g["theme_strength_label"]=label
        g["theme_strength_components"]={
            "interest":round(interest,1),"money":round(money,1),"breadth":round(breadth,1),
            "price":round(price,1),"surge":round(surge,1),"material":round(material,1)
        }
        g["theme_strength_money_basis"]=money_basis
        g["theme_strength_note"]="현재 조회·거래대금·상승확산·가격·급부상종목수·재료근거를 합친 운영 관찰도이며 수익확률이 아님"
    return groups


def build_sector_groups(rows):
    groups = {}
    for x in rows:
        sector = x.get("market_theme") or x.get("official_sector") or "미분류"
        g = groups.setdefault(sector, {
            "name": sector, "count": 0, "query_score": 0.0, "rank_sum": 0.0,
            "change_sum": 0.0, "change_n": 0, "positive": 0,
            "trade_value_krw": 0.0, "recent_turnover_krw": 0.0,
            "recent_turnover_known": 0, "surge_count": 0, "stocks": []
        })
        rank = x.get("rank")
        g["count"] += 1
        if rank is not None:
            g["query_score"] += max(1, 31 - int(rank))
            g["rank_sum"] += float(rank)
            if int(rank) <= 12:
                g["surge_count"] += 1
        chg = x.get("change_rate")
        if chg is not None:
            g["change_sum"] += float(chg)
            g["change_n"] += 1
            if float(chg) > 0:
                g["positive"] += 1
        tv = x.get("trade_value_krw")
        if tv is not None:
            g["trade_value_krw"] += float(tv)
        recent=x.get("recent_turnover_krw")
        if recent is not None:
            g["recent_turnover_krw"] += float(recent)
            g["recent_turnover_known"] += 1
        g["stocks"].append({
            "rank": rank, "rank_change": x.get("rank_change"),
            "trade_rank":x.get("trade_rank"),
            "code": x.get("code"), "name": x.get("name"),
            "change_rate": chg, "flow_state": x.get("flow_state"),
            "trade_value_krw":x.get("trade_value_krw"),
            "recent_turnover_krw":x.get("recent_turnover_krw"),
            "recent_turnover_seconds":x.get("recent_turnover_seconds"),
            "material_digest":x.get("material_digest") or {},
            "chart_state":x.get("chart_state")
        })
    out = []
    for g in groups.values():
        g["avg_rank"] = g["rank_sum"] / g["count"] if g["count"] else None
        g["avg_change_rate"] = g["change_sum"] / g["change_n"] if g["change_n"] else None
        g["positive_ratio"] = g["positive"] / g["change_n"] if g["change_n"] else None
        # Money-first ordering inside a sector; query rank breaks ties.
        g["stocks"] = sorted(
            g["stocks"],
            key=lambda z:(z.get("recent_turnover_krw") is None,
                          -(float(z.get("recent_turnover_krw") or 0)),
                          z.get("trade_rank") is None,z.get("trade_rank") or 999,
                          z.get("rank") is None,z.get("rank") or 999)
        )[:8]
        g["reason"]=sector_reason_summary(g)
        out.append(g)
    theme_strength_for_groups(out)
    out.sort(
        key=lambda z:(z["query_score"],
                      z.get("recent_turnover_krw") or 0,
                      z["trade_value_krw"],z["count"]),
        reverse=True
    )
    for i, g in enumerate(out, 1):
        g["sector_rank"] = i
    return out

def build_leader_calendar(cur, now):
    """Recent four work-week grid from locally stored end-of-day-like trade snapshots.

    Each date uses the latest stored trade-value snapshot for that KST date, then
    groups stocks that were up at least 4%. Missing days stay blank; no history is invented.
    """
    global _LEADER_CAL_CACHE,_LEADER_CAL_CACHE_AT,_LEADER_CAL_CACHE_KEY
    cache_key=now.astimezone(KST).date().isoformat()
    with _LEADER_CAL_CACHE_LOCK:
        if (_LEADER_CAL_CACHE is not None and _LEADER_CAL_CACHE_KEY==cache_key
                and pytime.monotonic()-_LEADER_CAL_CACHE_AT<_LEADER_CALENDAR_CACHE_SECONDS):
            return _LEADER_CAL_CACHE
    monday=(now.astimezone(KST)-timedelta(days=now.astimezone(KST).weekday())).date()
    start=monday-timedelta(days=21)
    end=monday+timedelta(days=4)
    agg={}
    if table_exists(cur,"market_trade_value_snapshots"):
        try:
            cur.execute("""WITH day_last AS (
                             SELECT (snapshot_time AT TIME ZONE 'Asia/Seoul')::date AS d,
                                    MAX(snapshot_time) AS t
                             FROM market_trade_value_snapshots
                             WHERE snapshot_time >= %s AND snapshot_time < %s
                             GROUP BY 1
                           ), strong AS (
                             SELECT (m.snapshot_time AT TIME ZONE 'Asia/Seoul')::date AS d,
                                    COALESCE(NULLIF(m.market_theme,''),NULLIF(m.official_sector,''),'미분류') AS theme,
                                    m.stock_code,m.trade_value_krw,m.change_rate
                             FROM market_trade_value_snapshots m
                             JOIN day_last dl ON m.snapshot_time=dl.t
                             WHERE m.change_rate>=4 AND COALESCE(m.rank_no,999)<=100
                           )
                           SELECT d,theme,COUNT(*),COALESCE(SUM(trade_value_krw),0),
                                  AVG(change_rate)
                           FROM strong
                           GROUP BY d,theme
                           ORDER BY d,COUNT(*) DESC,SUM(trade_value_krw) DESC""",
                        (datetime.combine(start,dtime.min,tzinfo=KST).astimezone(timezone.utc),
                         datetime.combine(end+timedelta(days=1),dtime.min,tzinfo=KST).astimezone(timezone.utc)))
            for d,theme,count,total,avg in cur.fetchall():
                agg.setdefault(d,[]).append({
                    "theme":theme,"count":int(count or 0),
                    "trade_value_krw":float(total or 0),
                    "avg_change_rate":float(avg) if avg is not None else None
                })
        except Exception:
            agg={}
    cells=[]
    today=now.astimezone(KST).date()
    d=start
    while d<=end:
        if d.weekday()<5:
            themes=sorted(agg.get(d,[]),key=lambda x:(-x["count"],-x["trade_value_krw"]))[:3]
            cells.append({
                "date":d.isoformat(),"day":d.day,"weekday":d.weekday(),
                "future":d>today,"themes":themes
            })
        d+=timedelta(days=1)
    observed=[x["date"] for x in cells if x["themes"]]
    payload={
        "start":start.isoformat(),"end":end.isoformat(),"cells":cells,
        "observed_days":len(observed),
        "coverage_start":min(observed) if observed else None,
        "note":"각 날짜의 마지막 저장 거래대금 스냅샷에서 +4% 이상 종목을 테마별 집계. 데이터가 없는 과거 날짜는 비워 둠"
    }
    with _LEADER_CAL_CACHE_LOCK:
        _LEADER_CAL_CACHE=payload
        _LEADER_CAL_CACHE_AT=pytime.monotonic()
        _LEADER_CAL_CACHE_KEY=cache_key
    return payload


def build_leader_desk(cur, trade_map, query_rows, now, sector_groups=None):
    """Reference-style home leader desk using current local market observations."""
    qmap={x.get("code"):x for x in query_rows}
    strong=[]
    for code,tv in sorted(trade_map.items(),key=lambda kv:(kv[1].get("rank") is None,kv[1].get("rank") or 999)):
        name=tv.get("name") or code
        if is_etf_like(name):continue
        chg=tv.get("change_rate")
        try:
            if chg is None or float(chg)<4:continue
        except (TypeError,ValueError):
            continue
        q=qmap.get(code) or {}
        theme=q.get("market_theme") or STOCK_THEME_HINTS.get(name) or tv.get("theme") or tv.get("sector") or "미분류"
        strong.append({
            "code":code,"name":name,"trade_rank":tv.get("rank"),
            "trade_value_krw":tv.get("trade_value"),
            "change_rate":float(chg),"current_price_krw":tv.get("current_price"),
            "theme":theme,"query_rank":q.get("rank"),
            "rank_history":q.get("rank_history") or {},
            "material_type":(q.get("material_digest") or {}).get("material_type"),
        })
        if len(strong)>=16:break

    groups={}
    for x in strong:
        g=groups.setdefault(x["theme"],{"name":x["theme"],"count":0,"trade_value_krw":0.0,
                                       "change_sum":0.0,"stocks":[]})
        g["count"]+=1
        g["trade_value_krw"]+=float(x.get("trade_value_krw") or 0)
        g["change_sum"]+=float(x.get("change_rate") or 0)
        g["stocks"].append(x)
    sectors=[]
    for g in groups.values():
        g["avg_change_rate"]=g["change_sum"]/g["count"] if g["count"] else None
        g["stocks"]=sorted(g["stocks"],key=lambda x:(x.get("trade_rank") is None,x.get("trade_rank") or 999))[:5]
        sectors.append(g)
    sectors.sort(key=lambda g:(-g["count"],-g["trade_value_krw"],-(g["avg_change_rate"] or 0)))
    sector_info={g.get("name"):g for g in (sector_groups or [])}
    for g in sectors:
        ref=sector_info.get(g.get("name")) or {}
        g["theme_strength"]=ref.get("theme_strength")
        g["theme_strength_label"]=ref.get("theme_strength_label")
        g["reason"]=ref.get("reason") or {}

    return {
        "threshold_pct":4,
        "strong_stocks":strong[:12],
        "leading_sectors":sectors[:4],
        "calendar":build_leader_calendar(cur,now),
        "note":"거래대금 상위 100 표본 중 +4% 이상 종목을 현재 테마로 묶은 실시간 관찰. 전체 시장 전수·매수추천이 아님"
    }


def build_paper_lab(cur):
    """Read-only Home summary of the local paper experiment."""
    empty={
        "status":"NOT_INITIALIZED","rule_version":"paper-v1-observation",
        "open":[],"recent_closed":[],"summary":{"closed":0,"positive_pct":None,"median_return_pct":None,
        "avg_return_pct":None,"median_mfe_pct":None,"median_mae_pct":None},
        "note":"1단위 가상 관찰 · 실계좌 주문/수수료/슬리피지 없음"
    }
    if not table_exists(cur,"radar_paper_trades"):
        return empty
    status={"status":"READY","open_count":0,"closed_today":0,"note":empty["note"]}
    if table_exists(cur,"radar_paper_status"):
        cur.execute("SELECT status,updated_at,open_count,closed_today,note FROM radar_paper_status WHERE id=1")
        r=cur.fetchone()
        if r:
            status={"status":r[0],"updated_at":iso(r[1]),"open_count":r[2],
                    "closed_today":r[3],"note":r[4] or empty["note"]}
    cur.execute("""SELECT id,stock_code,stock_name,rule_version,opened_at,entry_price_krw,
                          last_mark_at,last_mark_price_krw,return_pct,mfe_pct,mae_pct,
                          entry_score,primary_type,market_theme,event_type,chart_state_entry,entry_reason
                   FROM radar_paper_trades
                   WHERE status='OPEN' ORDER BY opened_at""")
    open_rows=[]
    for r in cur.fetchall():
        open_rows.append({
            "id":r[0],"code":r[1],"name":r[2],"rule_version":r[3],"opened_at":iso(r[4]),
            "entry_price_krw":float(r[5]) if r[5] is not None else None,
            "mark_at":iso(r[6]),"mark_price_krw":float(r[7]) if r[7] is not None else None,
            "return_pct":r[8],"mfe_pct":r[9],"mae_pct":r[10],"entry_score":r[11],
            "primary_type":r[12],"market_theme":r[13],"event_type":r[14],
            "chart_state":r[15],"entry_reason":r[16] or []
        })
    cur.execute("""SELECT id,stock_code,stock_name,rule_version,opened_at,closed_at,
                          entry_price_krw,exit_price_krw,return_pct,mfe_pct,mae_pct,
                          entry_score,exit_score,primary_type,market_theme,event_type,
                          exit_reason,exit_price_basis
                   FROM radar_paper_trades
                   WHERE status IN('CLOSED','CLOSED_NO_PRICE')
                   ORDER BY closed_at DESC NULLS LAST LIMIT 12""")
    closed=[]
    for r in cur.fetchall():
        closed.append({
            "id":r[0],"code":r[1],"name":r[2],"rule_version":r[3],"opened_at":iso(r[4]),"closed_at":iso(r[5]),
            "entry_price_krw":float(r[6]) if r[6] is not None else None,
            "exit_price_krw":float(r[7]) if r[7] is not None else None,
            "return_pct":r[8],"mfe_pct":r[9],"mae_pct":r[10],
            "entry_score":r[11],"exit_score":r[12],"primary_type":r[13],
            "market_theme":r[14],"event_type":r[15],"exit_reason":r[16],"exit_price_basis":r[17]
        })
    cur.execute("""SELECT COUNT(*),
                          AVG(return_pct),
                          percentile_cont(0.5) WITHIN GROUP(ORDER BY return_pct),
                          AVG(CASE WHEN return_pct>0 THEN 1.0 ELSE 0.0 END),
                          percentile_cont(0.5) WITHIN GROUP(ORDER BY mfe_pct),
                          percentile_cont(0.5) WITHIN GROUP(ORDER BY mae_pct)
                   FROM radar_paper_trades
                   WHERE status='CLOSED' AND return_pct IS NOT NULL
                     AND closed_at>now()-interval '30 days'""")
    r=cur.fetchone()
    summary={
        "closed":int(r[0] or 0),"avg_return_pct":float(r[1]) if r[1] is not None else None,
        "median_return_pct":float(r[2]) if r[2] is not None else None,
        "positive_pct":float(r[3])*100 if r[3] is not None else None,
        "median_mfe_pct":float(r[4]) if r[4] is not None else None,
        "median_mae_pct":float(r[5]) if r[5] is not None else None,
        "small_sample":int(r[0] or 0)<20
    }
    return {**status,"rule_version":"paper-v1-observation","open":open_rows,
            "recent_closed":closed,"summary":summary,
            "note":"자동 가상진입/청산 실험. 실제 주문·포지션 크기·수수료·슬리피지를 포함하지 않음"}


def build_paper_feedback(cur):
    empty={
        "status":"NOT_INITIALIZED","rule_version":"paper-v1-observation",
        "closed_count":0,"payload":{
            "state":"SAMPLE_BUILDING","label":"표본 축적",
            "overall":{"n":0},"types":[],"score_bands":[],"exit_reasons":[],
            "checks":[{"rule":"전체","status":"SAMPLE_BUILDING","label":"표본 축적",
                       "message":"Paper Lab 완료 표본을 기다리는 중.","evidence":{"n":0}}],
            "gates":{"min_type_samples":20,"min_rule_samples":30},
            "note":"자동 피드백은 규칙 변경 후보만 제시하고 실제 임계값은 변경하지 않음"
        }
    }
    if not table_exists(cur,"radar_paper_feedback_status"):
        return empty
    try:
        cur.execute("""SELECT status,updated_at,rule_version,closed_count,payload,note
                       FROM radar_paper_feedback_status WHERE id=1""")
        r=cur.fetchone()
        if not r:return empty
        return {"status":r[0],"updated_at":iso(r[1]),"rule_version":r[2],
                "closed_count":int(r[3] or 0),"payload":r[4] or {},
                "note":r[5] or ""}
    except Exception:
        return empty


def build_ai_morning_brief(regime, sector_groups, ai_brokerage, paper_lab):
    label=(regime or {}).get("stable_label") or (regime or {}).get("candidate_label") or (regime or {}).get("status") or "장세 대기"
    sectors=[]
    for g in (sector_groups or [])[:3]:
        sectors.append({
            "name":g.get("name"),"strength":g.get("theme_strength"),
            "change_rate":g.get("avg_change_rate"),"recent_turnover_krw":g.get("recent_turnover_krw")
        })
    candidates=(ai_brokerage or {}).get("candidates") or []
    paper_entries=[x for x in candidates if x.get("state")=="PAPER_ENTRY"]
    ready=[x for x in candidates if x.get("state")=="READY"]
    blocked=[x for x in candidates if x.get("state")=="BLOCKED"]
    strategies=[]
    seen=set()
    for x in paper_entries+ready:
        st=x.get("selected_strategy") or {}
        sid=st.get("strategy_id")
        if sid and sid not in seen:
            seen.add(sid)
            strategies.append({"strategy_id":sid,"name":st.get("name"),"family":st.get("family"),"fit":st.get("fit_score")})
    return {
        "as_of":datetime.now(KST).isoformat(),
        "regime":label,
        "top_sectors":sectors,
        "paper_entry_count":len(paper_entries),
        "ready_count":len(ready),
        "blocked_count":len(blocked),
        "active_strategy_candidates":strategies[:5],
        "paper_open_count":len((paper_lab or {}).get("open") or []),
        "headline":f"{label} · PAPER {len(paper_entries)} · READY {len(ready)} · BLOCKED {len(blocked)}",
        "note":"07:30형 운영 브리프 구조. 현재 저장·수집된 데이터만 사용하며 수익예측이 아님"
    }


def build_ai_strategy_performance(cur):
    empty={"status":"WAITING","rows":[],"unassigned":0,
           "note":"AI 전략이 귀속된 Paper Trade 표본을 기다리는 중"}
    if not ai_summarize_strategy_rows or not ai_build_context_matrix or not ai_lifecycle_candidates or not table_exists(cur,"radar_paper_trades"):
        return empty
    try:
        if not column_exists(cur,"radar_paper_trades","strategy_id"):return empty
        cur.execute("""SELECT status,return_pct,mfe_pct,mae_pct,opened_at,closed_at,
                              strategy_id,strategy_name,strategy_family,strategy_lifecycle,
                              strategy_fit,ai_conviction,regime_label,
                              ai_regime_trend,ai_regime_flow,ai_regime_sentiment,
                              ai_catalyst_strength,ai_catalyst_identity,ai_chart_state,
                              chart_state_entry
                       FROM radar_paper_trades
                       WHERE opened_at>now()-interval '90 days'
                       ORDER BY opened_at""")
        rows=[{
            "status":r[0],"return_pct":r[1],"mfe_pct":r[2],"mae_pct":r[3],
            "opened_at":iso(r[4]),"closed_at":iso(r[5]),"strategy_id":r[6],
            "strategy_name":r[7],"strategy_family":r[8],"strategy_lifecycle":r[9],
            "strategy_fit":r[10],"ai_conviction":r[11],"regime_label":r[12],
            "ai_regime_trend":r[13],"ai_regime_flow":r[14],"ai_regime_sentiment":r[15],
            "ai_catalyst_strength":r[16],"ai_catalyst_identity":r[17],
            "ai_chart_state":r[18],"chart_state_entry":r[19]
        } for r in cur.fetchall()]
        registry={}
        if AI_BROKERAGE_ENGINE:
            registry={x.strategy_id:x.to_dict() for x in AI_BROKERAGE_ENGINE.registry.all()}
        out=ai_summarize_strategy_rows(rows,registry)
        matrix=ai_build_context_matrix(rows)
        lifecycle=ai_lifecycle_candidates(out,matrix)
        return {
            "status":"OK" if out else "WAITING",
            "rows":out,
            "context_matrix":matrix,
            "lifecycle_review":lifecycle,
            "gates":{
                "min_closed":30,"min_positive_pct":55,"min_median_return_pct":0.20,
                "min_profit_factor":1.20,"min_context_cells":2,"min_cell_samples":5,
                "max_context_concentration":0.70
            },
            "unassigned":sum(1 for x in rows if not x.get("strategy_id")),
            "window_days":90,
            "note":"전향적 Paper 표본만 사용. 승격·강등은 자동 적용하지 않고 후보로만 제시"
        }
    except Exception as e:
        return {"error":str(type(e).__name__),"status":"ERROR","rows":[],"unassigned":0,
                "note":"전략 성과 집계 실패"}


def build_ai_daily_review(cur, paper_feedback):
    empty={"status":"WAITING","decisions":{"decisions":0,"states":{},"top_strategies":[],"top_blockers":[]},
           "paper":{"opened":0,"closed":0},"feedback_state":None,
           "note":"오늘의 AI Brokerage 의사결정 이력을 기다리는 중"}
    if not ai_build_daily_review:
        return empty
    try:
        decisions=[]
        if table_exists(cur,"ai_brokerage_decisions"):
            cur.execute("""SELECT DISTINCT ON(stock_code,state,COALESCE(strategy_id,''))
                                  snapshot_time,stock_code,stock_name,state,conviction,strategy_id,
                                  strategy_name,strategy_family,packet
                           FROM ai_brokerage_decisions
                           WHERE (snapshot_time AT TIME ZONE 'Asia/Seoul')::date
                                 =(now() AT TIME ZONE 'Asia/Seoul')::date
                           ORDER BY stock_code,state,COALESCE(strategy_id,''),snapshot_time DESC""")
            decisions=[{
                "snapshot_time":iso(r[0]),"stock_code":r[1],"stock_name":r[2],"state":r[3],
                "conviction":r[4],"strategy_id":r[5],"strategy_name":r[6],
                "strategy_family":r[7],"packet":r[8] or {}
            } for r in cur.fetchall()]
        trades=[]
        if table_exists(cur,"radar_paper_trades") and column_exists(cur,"radar_paper_trades","strategy_id"):
            cur.execute("""SELECT status,return_pct,mfe_pct,mae_pct,opened_at,closed_at,
                                  strategy_id,primary_type,exit_reason
                           FROM radar_paper_trades
                           WHERE (opened_at AT TIME ZONE 'Asia/Seoul')::date
                                 =(now() AT TIME ZONE 'Asia/Seoul')::date
                           ORDER BY opened_at""")
            trades=[{
                "status":r[0],"return_pct":r[1],"mfe_pct":r[2],"mae_pct":r[3],
                "opened_at":iso(r[4]),"closed_at":iso(r[5]),"strategy_id":r[6],
                "primary_type":r[7],"exit_reason":r[8]
            } for r in cur.fetchall()]
        out=ai_build_daily_review(decisions,trades,paper_feedback)
        out["status"]="OK" if decisions or trades else "WAITING"
        out["as_of"]=datetime.now(KST).isoformat()
        out["note"]="19:00형 복기 구조. 반복 스냅샷은 종목·상태·전략 단위로 축약"
        return out
    except Exception as e:
        return {**empty,"status":"ERROR","note":f"Daily Review 집계 실패: {type(e).__name__}"}


def build_ai_capacity_analysis(cur, strategy_performance):
    empty={
        "status":"WAITING","execution_rows":[],"capacity_matrix":[],
        "strategy_capacity":[],"final_lifecycle":[],
        "note":"BOOK_V2 Shadow 표본 축적 대기"
    }
    funcs=(ai_execution_adjusted_strategy_rows,ai_build_capacity_matrix,
           ai_strategy_capacity_rows,ai_execution_adjusted_lifecycle)
    if any(x is None for x in funcs) or not table_exists(cur,"ai_shadow_trades"):
        return empty
    required=("entry_model_mode","entry_book_capacity_krw","entry_spread_bps",
              "paper_return_pct","net_return_pct","return_drag_pct","round_trip_is_bps")
    if any(not column_exists(cur,"ai_shadow_trades",x) for x in required):
        return {**empty,"status":"WAITING_FOR_V2_SCHEMA","note":"Capacity v2 스키마 마이그레이션 대기"}
    try:
        cur.execute("""SELECT strategy_id,strategy_name,strategy_family,status,entry_model_mode,
                              regime_label,requested_notional_krw,entry_book_capacity_krw,
                              entry_spread_bps,entry_fill_ratio,paper_return_pct,net_return_pct,
                              return_drag_pct,round_trip_is_bps,entry_at
                       FROM ai_shadow_trades
                       WHERE strategy_id IS NOT NULL
                         AND entry_at>now()-interval '120 days'
                       ORDER BY entry_at""")
        rows=[{
            "strategy_id":r[0],"strategy_name":r[1],"strategy_family":r[2],
            "status":r[3],"entry_model_mode":r[4],"regime_label":r[5],
            "requested_notional_krw":float(r[6]) if r[6] is not None else None,
            "entry_book_capacity_krw":float(r[7]) if r[7] is not None else None,
            "entry_spread_bps":r[8],"entry_fill_ratio":r[9],
            "paper_return_pct":r[10],"net_return_pct":r[11],
            "return_drag_pct":r[12],"round_trip_is_bps":r[13],
            "entry_at":iso(r[14])
        } for r in cur.fetchall()]
        execution=ai_execution_adjusted_strategy_rows(rows)
        matrix=ai_build_capacity_matrix(rows)
        capacities=ai_strategy_capacity_rows(rows)
        paper_review=(strategy_performance or {}).get("lifecycle_review") or []
        final=ai_execution_adjusted_lifecycle(paper_review,execution,capacities)
        return {
            "status":"OK" if rows else "WAITING",
            "execution_rows":execution,
            "capacity_matrix":matrix,
            "strategy_capacity":capacities,
            "final_lifecycle":final,
            "window_days":120,
            "gates":{
                "shadow_closed":20,"book_coverage_pct":60,"median_net_return_pct":0.10,
                "positive_pct":50,"profit_factor":1.10,"max_drag_pct":0.50,
                "max_round_trip_is_bps":40,
                "capacity_min_book_closed":20,"capacity_min_bucket_closed":5,
                "capacity_min_regimes":2
            },
            "note":"최종 승격은 Paper + execution-adjusted Shadow + BOOK_V2 capacity를 모두 검토하며 auto_apply=false"
        }
    except Exception as e:
        return {**empty,"status":"ERROR","note":f"Capacity 분석 실패: {type(e).__name__}"}


def _allocation_volatility_bps(cur,code):
    if not table_exists(cur,"market_minute_bars"):
        return None
    cur.execute("""SELECT close_price FROM market_minute_bars
                   WHERE stock_code=%s AND interval_min=3
                   ORDER BY bar_time DESC LIMIT 21""",(code,))
    xs=[]
    for r in reversed(cur.fetchall()):
        try:
            v=float(r[0])
            if v>0:xs.append(v)
        except Exception:
            pass
    if len(xs)<6:return None
    vals=[abs(b/a-1.0)*10000 for a,b in zip(xs[:-1],xs[1:]) if a>0]
    if not vals:return None
    vals.sort()
    n=len(vals)
    return vals[n//2] if n%2 else (vals[n//2-1]+vals[n//2])/2


def _allocation_price_series(cur,codes):
    if not codes or not table_exists(cur,"market_minute_bars"):
        return {}
    cur.execute("""SELECT stock_code,bar_time,close_price
                   FROM market_minute_bars
                   WHERE stock_code=ANY(%s) AND interval_min=3
                     AND bar_time>now()-interval '6 hours'
                   ORDER BY stock_code,bar_time""",(list(codes),))
    out={}
    for code,bar_time,close in cur.fetchall():
        try:
            px=float(close)
            if px>0:out.setdefault(str(code),{})[bar_time.isoformat()]=px
        except Exception:
            continue
    return out


def _allocation_book_capacity(cur,code):
    if not ai_estimate_book_capacity or not AIBookPolicy or not table_exists(cur,"market_orderbook_snapshots"):
        return None
    max_age=max(5,min(120,int(os.getenv("SHADOW_BOOK_MAX_AGE_SECONDS","30"))))
    cur.execute("""SELECT snapshot_time,best_ask_krw,best_bid_krw,spread_bps,asks,bids,quality_flags
                   FROM market_orderbook_snapshots
                   WHERE stock_code=%s
                   ORDER BY snapshot_time DESC LIMIT 1""",(code,))
    r=cur.fetchone()
    if not r:return None
    snap=r[0]
    if snap and (datetime.now(timezone.utc)-snap.astimezone(timezone.utc)).total_seconds()>max_age:
        return None
    flags=list(r[6] or [])
    if "CROSSED_BOOK" in flags:return None
    book={
        "best_ask_krw":float(r[1]) if r[1] is not None else None,
        "best_bid_krw":float(r[2]) if r[2] is not None else None,
        "spread_bps":float(r[3]) if r[3] is not None else None,
        "asks":list(r[4] or []),"bids":list(r[5] or []),
    }
    policy=AIBookPolicy(
        displayed_liquidity_haircut=max(.05,min(1.0,float(os.getenv("SHADOW_BOOK_LIQUIDITY_HAIRCUT","0.5")))),
        max_levels=10,
        max_spread_bps=max(5.0,min(500.0,float(os.getenv("SHADOW_BOOK_MAX_SPREAD_BPS","120")))),
        commission_bps=max(0.0,float(os.getenv("SHADOW_COMMISSION_BPS","0"))),
        sell_tax_bps=max(0.0,float(os.getenv("SHADOW_SELL_TAX_BPS","0"))),
    )
    cap=ai_estimate_book_capacity(
        "BUY",book,policy,
        max_implementation_shortfall_bps=max(5.0,min(200.0,float(os.getenv("SHADOW_BOOK_CAPACITY_MAX_IS_BPS","30"))))
    )
    cap["snapshot_time"]=iso(snap)
    return cap


def build_ai_allocation(cur, rows, ai_brokerage, ai_capacity):
    empty={
        "status":"WAITING","paper_only":True,"allocations":[],"rejected":[],
        "correlations":{},"summary":{},"note":"PAPER_ENTRY 후보와 capacity 근거 대기"
    }
    if not ai_optimize_allocations or not AIAllocationPolicy or not AISizingPolicy:
        return empty
    packets=(ai_brokerage or {}).get("candidates") or []
    paper_entries=[x for x in packets if x.get("state")=="PAPER_ENTRY"]
    if not paper_entries:
        return empty
    row_map={str(x.get("code") or ""):x for x in (rows or [])}
    final_map={x.get("strategy_id"):x for x in ((ai_capacity or {}).get("final_lifecycle") or [])}
    exec_map={x.get("strategy_id"):x for x in ((ai_capacity or {}).get("execution_rows") or [])}
    cap_map={x.get("strategy_id"):x for x in ((ai_capacity or {}).get("strategy_capacity") or [])}

    open_positions=[]
    open_codes=set()
    if table_exists(cur,"ai_shadow_trades") and column_exists(cur,"ai_shadow_trades","risk_at_entry_krw"):
        cur.execute("""SELECT stock_code,market_theme,strategy_family,risk_at_entry_krw
                       FROM ai_shadow_trades WHERE status='OPEN'""")
        for code,theme,family,risk in cur.fetchall():
            open_codes.add(str(code))
            open_positions.append({
                "stock_code":str(code),"market_theme":theme,
                "strategy_family":family,"risk_krw":float(risk or 0)
            })

    policy=AIAllocationPolicy(
        account_equity_krw=max(1_000_000,float(os.getenv("SHADOW_ACCOUNT_EQUITY_KRW","100000000"))),
        max_total_risk_pct=max(.1,min(20.0,float(os.getenv("SHADOW_PORTFOLIO_MAX_TOTAL_RISK_PCT","2.0")))),
        max_single_risk_pct=max(.05,min(5.0,float(os.getenv("SHADOW_RISK_PER_TRADE_PCT","0.5")))),
        max_theme_risk_pct=max(.05,min(10.0,float(os.getenv("SHADOW_PORTFOLIO_MAX_THEME_RISK_PCT","0.8")))),
        max_family_risk_pct=max(.05,min(10.0,float(os.getenv("SHADOW_PORTFOLIO_MAX_FAMILY_RISK_PCT","1.2")))),
        max_position_pct=max(.5,min(50.0,float(os.getenv("SHADOW_MAX_POSITION_PCT","10")))),
        max_positions=max(1,min(50,int(os.getenv("SHADOW_PORTFOLIO_MAX_OPEN","5")))),
        risk_chunk_pct=max(.01,min(.5,float(os.getenv("ALLOCATION_RISK_CHUNK_PCT","0.05")))),
        correlation_penalty_weight=max(0.0,min(1.0,float(os.getenv("ALLOCATION_CORRELATION_PENALTY","0.65")))),
        unknown_correlation_penalty=max(0.0,min(.5,float(os.getenv("ALLOCATION_UNKNOWN_CORRELATION_PENALTY","0.15")))),
        high_correlation_threshold=max(.3,min(.99,float(os.getenv("ALLOCATION_HIGH_CORRELATION","0.80")))),
        pending_evidence_scale=max(.05,min(1.0,float(os.getenv("ALLOCATION_PENDING_SCALE","0.35")))),
        sample_building_scale=max(.01,min(.5,float(os.getenv("ALLOCATION_SAMPLE_SCALE","0.20")))),
    )
    sizing_policy=AISizingPolicy(
        account_equity_krw=policy.account_equity_krw,
        risk_per_trade_pct=policy.max_single_risk_pct,
        max_position_pct=policy.max_position_pct,
    )

    candidates=[]
    pre_rejected=[]
    codes=[]
    for packet in paper_entries:
        code=str(packet.get("stock_code") or "")
        if not code:continue
        if code in open_codes:
            pre_rejected.append({"stock_code":code,"stock_name":packet.get("stock_name"),
                                 "reasons":["ALREADY_OPEN_SHADOW"]})
            continue
        st=packet.get("selected_strategy") or {}
        sid=st.get("strategy_id")
        if not sid:
            pre_rejected.append({"stock_code":code,"stock_name":packet.get("stock_name"),
                                 "reasons":["NO_SELECTED_STRATEGY"]})
            continue
        row=row_map.get(code) or {}
        price=row.get("price_krw")
        try:price=float(price) if price is not None else None
        except Exception:price=None
        vol=_allocation_volatility_bps(cur,code)
        sizing=sizing_policy.size(price,vol) if price else {}
        stop=sizing.get("stop_pct")
        final=final_map.get(sid) or {}
        exe=exec_map.get(sid) or {}
        cap=cap_map.get(sid) or {}
        point=_allocation_book_capacity(cur,code)
        candidates.append({
            "stock_code":code,"stock_name":packet.get("stock_name") or row.get("name"),
            "state":packet.get("state"),"conviction":packet.get("conviction"),
            "strategy_id":sid,"strategy_name":st.get("name"),
            "strategy_family":st.get("family") or exe.get("strategy_family"),
            "strategy_fit":st.get("fit_score"),"market_theme":row.get("market_theme"),
            "price_krw":price,"stop_pct":stop,"volatility_bps":vol,
            "final_action":final.get("action"),"capacity_state":cap.get("state"),
            "evidence_capacity_krw":cap.get("evidence_capacity_krw"),
            "point_in_time_capacity_krw":(point or {}).get("capacity_notional_krw"),
            "point_in_time_capacity_is_bps":(point or {}).get("capacity_is_bps"),
            "median_net_return_pct":exe.get("median_net_return_pct"),
            "profit_factor":exe.get("profit_factor"),"positive_pct":exe.get("positive_pct"),
            "median_round_trip_is_bps":exe.get("median_round_trip_is_bps"),
            "median_return_drag_pct":exe.get("median_return_drag_pct"),
            "book_coverage_pct":exe.get("book_coverage_pct"),
        })
        codes.append(code)

    series=_allocation_price_series(cur,codes)
    correlations=ai_correlation_matrix(series,min_obs=max(10,min(60,int(os.getenv("ALLOCATION_CORRELATION_MIN_OBS","20"))))) if ai_correlation_matrix else {}
    out=ai_optimize_allocations(candidates,correlations,open_positions,policy)
    out["rejected"]=pre_rejected+(out.get("rejected") or [])
    out["correlations"]=correlations
    out["as_of"]=datetime.now(KST).isoformat()
    out["note"]="Shadow capital allocation only · no broker orders · edge/capacity/correlation/risk constraints are inspectable"
    return out


def _truthy_env(name,default="0"):
    return os.getenv(name,default).strip().lower() in ("1","true","yes","on")


def _age_from_iso(value):
    if not value:return None
    try:
        dt=datetime.fromisoformat(str(value))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return max(0.0,(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return None


def build_ai_risk_control(
    cur, rows, ai_brokerage, ai_capacity, ai_allocation, shadow_execution,
    kiwoom, orderbook, regime, chartfeed
):
    empty={
        "status":"WAITING",
        "kill_switch_raw":{"state":"DEGRADED","allow_new_shadow_entries":True,
        "hard_triggers":[],"warnings":[{"code":"RISK_CONTROL_NOT_READY"}]},
        "kill_switch":{"state":"HALT","allow_new_shadow_entries":False,
        "hard_triggers":[{"code":"RISK_CONTROL_STATUS_MISSING"}],"warnings":[]},
        "live_readiness":{"stage":"RESEARCH_ONLY","live_enabled":False,"gates":[],"failed_gates":[]},
        "rebalance":{"status":"WAITING","actions":[],"replacements":[],"summary":{}},
        "metrics":{},"note":"운영 통제 데이터 축적 대기"
    }
    if not AIRiskControlPolicy or not ai_evaluate_kill_switch or not ai_evaluate_live_readiness or not ai_rebalance_portfolio:
        return empty

    policy=AIRiskControlPolicy(
        max_daily_loss_pct=max(.1,min(20.0,float(os.getenv("RISK_MAX_DAILY_LOSS_PCT","2.0")))),
        hard_risk_utilization_pct=max(100.0,min(200.0,float(os.getenv("RISK_HARD_UTILIZATION_PCT","105")))),
        warn_risk_utilization_pct=max(50.0,min(100.0,float(os.getenv("RISK_WARN_UTILIZATION_PCT","90")))),
        max_critical_feed_age_sec=max(30,min(900,int(os.getenv("RISK_CRITICAL_FEED_MAX_AGE_SECONDS","180")))),
        max_orderbook_age_sec=max(15,min(600,int(os.getenv("RISK_ORDERBOOK_MAX_AGE_SECONDS","90")))),
        max_median_round_trip_is_bps=max(5.0,min(300.0,float(os.getenv("RISK_MAX_MEDIAN_IS_BPS","60")))),
        warn_median_round_trip_is_bps=max(5.0,min(200.0,float(os.getenv("RISK_WARN_MEDIAN_IS_BPS","40")))),
        max_execution_reject_pct=max(5.0,min(100.0,float(os.getenv("RISK_MAX_EXECUTION_REJECT_PCT","50")))),
        warn_execution_reject_pct=max(1.0,min(100.0,float(os.getenv("RISK_WARN_EXECUTION_REJECT_PCT","30")))),
        min_book_coverage_pct=max(0.0,min(100.0,float(os.getenv("RISK_MIN_BOOK_COVERAGE_PCT","50")))),
        max_portfolio_corr=max(.5,min(.999,float(os.getenv("RISK_MAX_PORTFOLIO_CORR","0.92")))),
        warn_portfolio_corr=max(.3,min(.99,float(os.getenv("RISK_WARN_PORTFOLIO_CORR","0.80")))),
        max_unknown_corr_pairs=max(0,min(50,int(os.getenv("RISK_MAX_UNKNOWN_CORR_PAIRS","3")))),
        min_live_paper_closed=max(20,int(os.getenv("LIVE_READINESS_MIN_PAPER_CLOSED","100"))),
        min_live_shadow_closed=max(20,int(os.getenv("LIVE_READINESS_MIN_SHADOW_CLOSED","60"))),
        min_live_book_closed=max(10,int(os.getenv("LIVE_READINESS_MIN_BOOK_CLOSED","40"))),
        min_live_operating_days=max(3,int(os.getenv("LIVE_READINESS_MIN_OPERATING_DAYS","10"))),
        min_live_book_coverage_pct=max(50.0,min(100.0,float(os.getenv("LIVE_READINESS_MIN_BOOK_COVERAGE_PCT","80")))),
        min_live_supported_strategies=max(1,int(os.getenv("LIVE_READINESS_MIN_SUPPORTED_STRATEGIES","1"))),
    )
    equity=max(1_000_000,float(os.getenv("SHADOW_ACCOUNT_EQUITY_KRW","100000000")))

    paper_closed=0
    if table_exists(cur,"radar_paper_trades"):
        cur.execute("SELECT COUNT(*) FROM radar_paper_trades WHERE status='CLOSED' AND return_pct IS NOT NULL")
        paper_closed=int(cur.fetchone()[0] or 0)

    shadow_closed=book_closed=operating_days=0
    daily_shadow_return=None
    execution_reject_pct=None
    if table_exists(cur,"ai_shadow_trades"):
        cur.execute("""SELECT COUNT(*) FILTER(WHERE status='CLOSED'),
                              COUNT(*) FILTER(WHERE status='CLOSED' AND entry_model_mode='BOOK_V2'),
                              COUNT(DISTINCT (entry_at AT TIME ZONE 'Asia/Seoul')::date)
                       FROM ai_shadow_trades""")
        r=cur.fetchone()
        shadow_closed=int(r[0] or 0);book_closed=int(r[1] or 0);operating_days=int(r[2] or 0)
        cur.execute("""SELECT SUM(net_pnl_krw)
                       FROM ai_shadow_trades
                       WHERE status='CLOSED'
                         AND (exit_at AT TIME ZONE 'Asia/Seoul')::date
                             =(now() AT TIME ZONE 'Asia/Seoul')::date""")
        pnl=cur.fetchone()[0]
        if pnl is not None:
            daily_shadow_return=float(pnl)/equity*100.0
        cur.execute("""SELECT COUNT(*) AS n,
                              COUNT(*) FILTER(WHERE status='REJECTED') AS rejected
                       FROM (
                         SELECT status FROM ai_shadow_trades
                         ORDER BY created_at DESC LIMIT 50
                       ) x""")
        rr=cur.fetchone()
        if rr and int(rr[0] or 0)>0:
            execution_reject_pct=int(rr[1] or 0)/int(rr[0])*100.0

    allocation_days=0
    if table_exists(cur,"ai_allocation_snapshots"):
        cur.execute("""SELECT COUNT(DISTINCT (snapshot_time AT TIME ZONE 'Asia/Seoul')::date)
                       FROM ai_allocation_snapshots""")
        allocation_days=int(cur.fetchone()[0] or 0)

    allocations=(ai_allocation or {}).get("allocations") or []
    max_corr=max([float(x.get("max_positive_corr") or 0) for x in allocations] or [0.0])
    unknown_corr=sum(int(x.get("unknown_correlation_peers") or 0) for x in allocations)
    risk_util=((ai_allocation or {}).get("summary") or {}).get("risk_utilization_pct")
    shadow_summary=(shadow_execution or {}).get("summary") or {}
    book_cov=shadow_summary.get("book_coverage_pct")
    median_is=shadow_summary.get("median_round_trip_is_bps")

    critical_feeds={
        "kiwoom":{
            "status":(kiwoom or {}).get("status"),
            "age_sec":_age_from_iso((kiwoom or {}).get("last_success")),
        },
        "regime":{
            "status":(regime or {}).get("status"),
            "age_sec":_age_from_iso((regime or {}).get("last_market_data_at") or (regime or {}).get("updated_at")),
        },
        "chart":{
            "status":(chartfeed or {}).get("status"),
            "age_sec":_age_from_iso((chartfeed or {}).get("last_success")),
        },
    }
    orderbook_feed={
        "status":(orderbook or {}).get("status"),
        "age_sec":_age_from_iso((orderbook or {}).get("updated_at")),
    }
    metrics={
        "daily_shadow_return_pct":daily_shadow_return,
        "risk_utilization_pct":risk_util,
        "median_round_trip_is_bps":median_is,
        "execution_reject_pct":execution_reject_pct,
        "book_coverage_pct":book_cov,
        "max_portfolio_corr":max_corr,
        "unknown_corr_pairs":unknown_corr,
        "critical_feeds":critical_feeds,
        "orderbook_feed":orderbook_feed,
        "manual_halt":_truthy_env("RISK_MANUAL_HALT","0"),
    }
    raw_kill=ai_evaluate_kill_switch(metrics,policy)

    # Effective operational state includes the persisted recovery latch.
    kill=dict(raw_kill)
    recovery={
        "state":"UNPERSISTED","incident_id":None,"recovery_state":"STARTING",
        "healthy_streak":0,"healthy_streak_required":max(1,min(20,int(os.getenv("RISK_RECOVERY_HEALTHY_STREAK","3")))),
        "ack_required":os.getenv("RISK_RECOVERY_REQUIRE_ACK","1").strip().lower() in ("1","true","yes","on"),
        "acknowledged_at":None,"halted_at":None,"recovered_at":None,"status_age_sec":None,
    }
    status_required=os.getenv("RISK_CONTROL_REQUIRED","1").strip().lower() in ("1","true","yes","on")
    status_max_age=max(30,min(600,int(os.getenv("RISK_CONTROL_STATUS_MAX_AGE_SECONDS","120"))))
    if table_exists(cur,"ai_risk_control_status") and column_exists(cur,"ai_risk_control_status","incident_id"):
        cur.execute("""SELECT updated_at,state,raw_state,allow_new_shadow_entries,incident_id,
                              recovery_state,healthy_streak,healthy_streak_required,ack_required,
                              acknowledged_at,halted_at,recovered_at
                       FROM ai_risk_control_status WHERE id=1""")
        rr=cur.fetchone()
        if rr:
            age=max(0.0,(datetime.now(timezone.utc)-rr[0].astimezone(timezone.utc)).total_seconds()) if rr[0] else None
            recovery={
                "state":rr[1],"raw_state":rr[2],"allow_new_shadow_entries":bool(rr[3]),
                "incident_id":rr[4],"recovery_state":rr[5],
                "healthy_streak":int(rr[6] or 0),"healthy_streak_required":int(rr[7] or 0),
                "ack_required":bool(rr[8]),"acknowledged_at":iso(rr[9]),
                "halted_at":iso(rr[10]),"recovered_at":iso(rr[11]),"status_age_sec":age,
            }
            if age is not None and age>status_max_age and status_required:
                kill={**raw_kill,"state":"HALT","allow_new_shadow_entries":False}
                kill["hard_triggers"]=list(raw_kill.get("hard_triggers") or [])+[{
                    "code":"RISK_CONTROL_STATUS_STALE","age_sec":age,"limit":status_max_age
                }]
                kill["incident_id"]=rr[4]
                kill["recovery_state"]="STATUS_STALE"
            elif str(rr[1] or "").upper()=="HALT":
                kill={**raw_kill,"state":"HALT","allow_new_shadow_entries":False}
                hard=list(raw_kill.get("hard_triggers") or [])
                if not any(x.get("code")=="RECOVERY_LATCH" for x in hard):
                    hard.append({"code":"RECOVERY_LATCH","incident_id":rr[4],
                                 "recovery_state":rr[5],"healthy_streak":int(rr[6] or 0),
                                 "required":int(rr[7] or 0),"acknowledged":bool(rr[9])})
                kill["hard_triggers"]=hard
                kill["incident_id"]=rr[4]
                kill["recovery_state"]=rr[5]
                kill["healthy_streak"]=int(rr[6] or 0)
                kill["healthy_streak_required"]=int(rr[7] or 0)
                kill["ack_required"]=bool(rr[8])
                kill["acknowledged_at"]=iso(rr[9])
            else:
                kill={**raw_kill,"state":str(rr[1] or raw_kill.get("state")),
                      "allow_new_shadow_entries":bool(rr[3]) and raw_kill.get("state")!="HALT"}
                kill["incident_id"]=rr[4]
                kill["recovery_state"]=rr[5]
    elif status_required:
        kill={**raw_kill,"state":"HALT","allow_new_shadow_entries":False}
        kill["hard_triggers"]=list(raw_kill.get("hard_triggers") or [])+[{
            "code":"RISK_CONTROL_STATUS_MISSING"
        }]
        kill["recovery_state"]="STARTING"

    final_rows=(ai_capacity or {}).get("final_lifecycle") or []
    supported=sum(1 for x in final_rows if x.get("action")=="PROMOTE_CANDIDATE_EXECUTION_ADJUSTED")
    def _live_feed_ready(feed):
        st=str((feed or {}).get("status") or "").upper()
        age=(feed or {}).get("age_sec")
        if not st or st in ("ERROR","FAILED","DOWN","NOT_CONFIGURED","WAITING_FOR_CREDENTIALS"):
            return False
        if st.startswith("WAITING") or st.startswith("NOT_") or st.startswith("ERROR"):
            return False
        return age is None or float(age)<=policy.max_critical_feed_age_sec

    critical_feeds_ok=all(_live_feed_ready(v) for v in critical_feeds.values())
    orderbook_ok=(
        str(orderbook_feed.get("status") or "")=="OK"
        and (orderbook_feed.get("age_sec") is None or float(orderbook_feed.get("age_sec"))<=policy.max_orderbook_age_sec)
    )
    readiness_metrics={
        "broker_mode":(kiwoom or {}).get("mode"),
        "paper_closed":paper_closed,
        "shadow_closed":shadow_closed,
        "book_closed":book_closed,
        "operating_days":operating_days,
        "book_coverage_pct":book_cov,
        "supported_strategies":supported,
        "costs_configured":_truthy_env("LIVE_READINESS_COSTS_CONFIRMED","0"),
        "orderbook_ok":orderbook_ok,
        "critical_feeds_ok":critical_feeds_ok,
        "allocation_snapshots":allocation_days,
        "live_order_path_present":False,
    }
    readiness=ai_evaluate_live_readiness(readiness_metrics,kill,policy)

    row_map={str(x.get("code") or ""):x for x in (rows or [])}
    packet_map={str(x.get("stock_code") or ""):x for x in ((ai_brokerage or {}).get("candidates") or [])}
    final_map={x.get("strategy_id"):x for x in final_rows}
    open_positions=[]
    if table_exists(cur,"ai_shadow_trades"):
        cur.execute("""SELECT stock_code,stock_name,market_theme,strategy_id,strategy_family,
                              risk_at_entry_krw,stop_pct,entry_fill_price_krw,entry_at
                       FROM ai_shadow_trades WHERE status='OPEN'""")
        raw_open=cur.fetchall()
        codes=[str(x[0]) for x in raw_open if x and x[0]]
        latest_prices={}
        if codes and table_exists(cur,"radar_flow_quotes"):
            cur.execute("""SELECT DISTINCT ON(stock_code) stock_code,payload
                           FROM radar_flow_quotes
                           WHERE stock_code=ANY(%s)
                           ORDER BY stock_code,batch_time DESC""",(codes,))
            for code,payload in cur.fetchall():
                try:
                    px=float((payload or {}).get("price_krw"))
                    if px>0:latest_prices[str(code)]=px
                except Exception:
                    pass
        series=_allocation_price_series(cur,codes+[str(x.get("stock_code")) for x in allocations if x.get("stock_code")])
        corr=ai_correlation_matrix(series,min_obs=max(10,min(60,int(os.getenv("ALLOCATION_CORRELATION_MIN_OBS","20"))))) if ai_correlation_matrix else {}
        for code,name,theme,sid,family,risk,stop,entry_px,entry_at in raw_open:
            code=str(code)
            packet=packet_map.get(code) or {}
            final=final_map.get(sid) or {}
            px=latest_prices.get(code) or (row_map.get(code) or {}).get("price_krw")
            try:px=float(px) if px is not None else None
            except Exception:px=None
            try:entry=float(entry_px) if entry_px is not None else None
            except Exception:entry=None
            current_ret=(px/entry-1.0)*100.0 if px and entry and entry>0 else None
            peers=[]
            for other in codes:
                if other==code:continue
                v=(corr.get(code) or {}).get(other)
                if v is not None:peers.append(float(v))
            max_pos_corr=max([v for v in peers if v>0] or [0.0])
            conviction=float(packet.get("conviction") or 50)
            action=final.get("action")
            scale=1.0 if action=="PROMOTE_CANDIDATE_EXECUTION_ADJUSTED" else .35 if action=="EXECUTION_GATE_PENDING" else .2
            if action in ("EXECUTION_BLOCKED","DEMOTE_OR_REWORK"):scale=0.0
            open_positions.append({
                "stock_code":code,"stock_name":name,"market_theme":theme,
                "strategy_id":sid,"strategy_family":family,
                "risk_krw":float(risk or 0),"stop_pct":float(stop or 0) if stop is not None else None,
                "current_return_pct":current_ret,"ai_state":packet.get("state") or "UNKNOWN",
                "final_action":action,"priority_score":(conviction/100.0)*scale,
                "max_positive_corr":max_pos_corr,"entry_at":iso(entry_at),
            })
    rebalance=ai_rebalance_portfolio(open_positions,allocations,kill,{
        "watch_reduce_fraction":max(.1,min(.9,float(os.getenv("REBALANCE_WATCH_REDUCE_FRACTION","0.5")))),
        "high_corr_reduce_fraction":max(.1,min(.9,float(os.getenv("REBALANCE_HIGH_CORR_REDUCE_FRACTION","0.25")))),
        "high_corr_threshold":max(.5,min(.99,float(os.getenv("REBALANCE_HIGH_CORR_THRESHOLD","0.90")))),
        "replacement_priority_gap":max(.05,min(.8,float(os.getenv("REBALANCE_REPLACEMENT_PRIORITY_GAP","0.15")))),
    })

    return {
        "status":"OK",
        "kill_switch_raw":raw_kill,
        "kill_switch":kill,
        "recovery":recovery,
        "live_readiness":readiness,
        "rebalance":rebalance,
        "metrics":{
            **metrics,
            **readiness_metrics,
            "critical_feeds_ok":critical_feeds_ok,
            "orderbook_ok":orderbook_ok,
        },
        "note":"운영 통제·rebalance·live-readiness 모두 shadow/read-only 제안; live execution은 비활성",
    }


def build_shadow_execution_lab(cur):
    empty={
        "status":"WAITING","open_count":0,"closed_count":0,"rejected_count":0,
        "partial_exit_count":0,"risk_reject_count":0,
        "summary":{
            "closed":0,"median_gross_return_pct":None,"median_net_return_pct":None,
            "median_fill_ratio_pct":None,"median_notional_krw":None,
            "book_coverage_pct":None,"median_entry_is_bps":None,"median_exit_is_bps":None,
            "median_round_trip_is_bps":None,"median_return_drag_pct":None
        },
        "recent":[],
        "note":"Shadow Simulator 표본 대기 · 실계좌 주문 없음"
    }
    if not table_exists(cur,"ai_shadow_trades"):
        return empty
    if not column_exists(cur,"ai_shadow_trades","entry_model_mode"):
        return {**empty,"status":"WAITING_FOR_V2_SCHEMA","note":"Shadow v2 스키마 마이그레이션 대기"}
    try:
        status=dict(empty)
        if table_exists(cur,"ai_shadow_status"):
            cur.execute("""SELECT status,updated_at,open_count,closed_count,rejected_count,note
                           FROM ai_shadow_status WHERE id=1""")
            r=cur.fetchone()
            if r:
                status.update({"status":r[0],"updated_at":iso(r[1]),"open_count":int(r[2] or 0),
                               "closed_count":int(r[3] or 0),"rejected_count":int(r[4] or 0),
                               "note":r[5] or empty["note"]})
        cur.execute("""SELECT COUNT(*),
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY gross_return_pct),
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY net_return_pct),
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY entry_fill_ratio*100),
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY requested_notional_krw),
                              AVG(CASE WHEN entry_model_mode='BOOK_V2' THEN 1.0 ELSE 0.0 END),
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY entry_implementation_shortfall_bps),
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY exit_implementation_shortfall_bps),
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY round_trip_is_bps),
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY return_drag_pct)
                       FROM ai_shadow_trades
                       WHERE status='CLOSED' AND entry_at>now()-interval '90 days'""")
        r=cur.fetchone()
        status["summary"]={
            "closed":int(r[0] or 0),
            "median_gross_return_pct":float(r[1]) if r[1] is not None else None,
            "median_net_return_pct":float(r[2]) if r[2] is not None else None,
            "median_fill_ratio_pct":float(r[3]) if r[3] is not None else None,
            "median_notional_krw":float(r[4]) if r[4] is not None else None,
            "book_coverage_pct":float(r[5])*100 if r[5] is not None else None,
            "median_entry_is_bps":float(r[6]) if r[6] is not None else None,
            "median_exit_is_bps":float(r[7]) if r[7] is not None else None,
            "median_round_trip_is_bps":float(r[8]) if r[8] is not None else None,
            "median_return_drag_pct":float(r[9]) if r[9] is not None else None,
        }
        cur.execute("""SELECT COUNT(*) FROM ai_shadow_trades
                       WHERE status='CLOSED_PARTIAL_LIQUIDITY'""")
        status["partial_exit_count"]=int(cur.fetchone()[0] or 0)
        cur.execute("""SELECT COUNT(*) FROM ai_shadow_trades
                       WHERE status='REJECTED'
                         AND entry_model_quality='PORTFOLIO_RISK_GATE'""")
        status["risk_reject_count"]=int(cur.fetchone()[0] or 0)

        cur.execute("""SELECT stock_code,stock_name,market_theme,strategy_id,strategy_family,status,
                              requested_shares,filled_shares,requested_notional_krw,stop_pct,
                              risk_at_entry_krw,entry_at,entry_ref_price_krw,entry_arrival_mid_krw,
                              entry_fill_price_krw,entry_slippage_bps,entry_implementation_shortfall_bps,
                              entry_fill_ratio,entry_model_quality,entry_model_mode,
                              exit_at,exit_ref_price_krw,exit_arrival_mid_krw,exit_fill_price_krw,
                              exit_slippage_bps,exit_implementation_shortfall_bps,
                              exit_filled_shares,exit_fill_ratio,remaining_shares,round_trip_is_bps,
                              paper_return_pct,gross_return_pct,net_return_pct,return_drag_pct,
                              net_pnl_krw,costs_krw,risk_gate,entry_model,exit_model
                       FROM ai_shadow_trades
                       ORDER BY COALESCE(exit_at,entry_at) DESC LIMIT 12""")
        names=[d.name for d in cur.description]
        recent=[]
        for raw in cur.fetchall():
            row=dict(zip(names,raw))
            for k in ("requested_notional_krw","risk_at_entry_krw","entry_ref_price_krw",
                      "entry_arrival_mid_krw","entry_fill_price_krw","exit_ref_price_krw",
                      "exit_arrival_mid_krw","exit_fill_price_krw","net_pnl_krw","costs_krw"):
                row[k]=float(row[k]) if row.get(k) is not None else None
            row["entry_at"]=iso(row.get("entry_at"))
            row["exit_at"]=iso(row.get("exit_at"))
            row["risk_gate"]=row.get("risk_gate") or {}
            row["entry_model"]=row.get("entry_model") or {}
            row["exit_model"]=row.get("exit_model") or {}
            recent.append(row)
        status["recent"]=recent
        status["model_note"]="BOOK_V2 우선: Kiwoom ka10004 10호가를 haircut 후 VWAP 체결. 신선한 book이 없을 때만 명시적 PROXY_V1 fallback."
        return status
    except Exception as e:
        return {**empty,"status":"ERROR","note":f"Shadow v2 집계 실패: {type(e).__name__}"}

def build_home_candidates(cur, rows):
    """Read the current local candidate tracker for a compact Home Top5."""
    if not table_exists(cur,"radar_candidate_episodes"):
        return []
    rowmap={x.get("code"):x for x in rows}
    try:
        cur.execute("""SELECT stock_code,stock_name,entry_score,last_score,peak_score,primary_type,
                              market_theme,event_type,chart_state,started_at,last_seen_at
                       FROM radar_candidate_episodes
                       WHERE status='ACTIVE' AND last_seen_at>now()-interval '10 minutes'
                       ORDER BY last_score DESC,peak_score DESC,last_seen_at DESC
                       LIMIT 12""")
        out=[]
        for code,name,entry,last,peak,ptype,theme,event,chart,started,last_seen in cur.fetchall():
            r=rowmap.get(code) or {}
            out.append({
                "code":code,"name":name or r.get("name") or code,
                "attention_score":last,"entry_score":entry,"peak_score":peak,
                "primary_type":ptype,"market_theme":theme or r.get("market_theme"),
                "event_type":event or (r.get("material_digest") or {}).get("material_type"),
                "chart_state":chart or r.get("chart_state"),
                "started_at":iso(started),"last_seen_at":iso(last_seen),
                "change_rate":r.get("change_rate"),
                "rank":r.get("rank"),"trade_rank":r.get("trade_rank"),
                "trade_value_krw":r.get("trade_value_krw"),
                "recent_turnover_krw":r.get("recent_turnover_krw"),
                "rank_history":r.get("rank_history") or {},
                "reversal_signal":r.get("reversal_signal"),
            })
        return out[:5]
    except Exception:
        return []


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
    "장마감","마감시황","종목추천","추천주","vs ","수익률","급등일보","유튜브","youtube",
    "상한가 및 급등","특징 상한가","특징주 정리","급등종목","테마주 정리","관련주 정리"
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

def enrich_catalyst(cat, stock_name=None, official_sector=None):
    candidates=[]
    warnings=[]
    for d in cat.get("dart") or []:
        txt=d.get("report_nm") or ""
        score,kind=evidence_strength(txt)
        # DART verifies identity/source authenticity, not causal relevance.
        # Generic filings remain weak; contract/earnings/approval text can score higher.
        score=max(1,score)
        candidates.append((score,kind if kind!="NONE" else "DART","DART",txt,d,"VERIFIED"))
    for n in cat.get("external_news") or []:
        txt=n.get("title") or ""
        q=identity_quality(stock_name,txt,"NEWS",official_sector)
        if not usable_as_catalyst(q):
            warnings.append({"source":"뉴스","quality":q,"text":txt[:180]})
            continue
        score,kind=evidence_strength(txt)
        candidates.append((score,kind,"뉴스",txt,n,q))
    for it in cat.get("items") or []:
        txt=it.get("text") or ""
        q=it.get("identity_quality") or identity_quality(stock_name,txt,"Telegram",official_sector)
        if not usable_as_catalyst(q):
            warnings.append({"source":"Telegram","quality":q,"text":txt[:180]})
            continue
        score,kind=evidence_strength(txt)
        candidates.append((score,kind,"Telegram",txt,it,q))
    candidates.sort(key=lambda x:(x[0], 1 if x[5] in ("VERIFIED","CONTEXT_VERIFIED") else 0),reverse=True)
    best=candidates[0] if candidates else (0,"NONE","미확인","",None,"UNVERIFIED")
    # Only infer a theme from verified/context-verified text adjacent to the stock name.
    inferred=None
    if usable_for_theme(best[5]):
        inferred=infer_theme(stock_context(best[3],stock_name))
    if inferred:
        cat["theme"]=inferred
    cat["material_strength"]=best[0]
    cat["material_class"]=best[1]
    cat["best_source"]=best[2]
    cat["best_text"]=best[3]
    cat["best_evidence"]=best[4]
    cat["best_identity_quality"]=best[5]
    cat["identity_warnings"]=warnings[:4]
    if best[1] == "DART":
        cat["quality_note"]="DART 공식 공시 · 종목 신원 확인"
    elif best[5]=="CONTEXT_VERIFIED" and best[0]>=2:
        cat["quality_note"]="종목명+업종 문맥 확인된 공개 재료"
    elif best[5]=="NAME_MATCH" and best[0]>=2:
        cat["quality_note"]="종목명 일치 · 동명이인/맥락 추가 확인 필요"
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

def classify_material_type(cat, external_event=None):
    """Stable visual category for the home dashboard; not a causal verdict."""
    allowed={"수주·공급계약","실적·가이던스","기술·제품·양산","정책·규제",
             "승인·임상","자본·주주환원","업황·가격","인수·사업재편","기타·미확인"}
    if external_event in allowed and external_event!="기타·미확인":
        return external_event
    text=" ".join([
        str(cat.get("best_text") or ""),
        " ".join(str(x.get("report_nm") or "") for x in (cat.get("dart") or [])[:3]),
        " ".join(str(x.get("title") or "") for x in (cat.get("external_news") or [])[:3]),
    ]).lower()
    rules=[
        ("승인·임상",("fda","임상","승인","허가","nda","bnda")),
        ("수주·공급계약",("공급계약","수주","계약 체결","mou","납품","공급 계약")),
        ("실적·가이던스",("영업이익","매출","실적","가이던스","전망","흑자","적자")),
        ("자본·주주환원",("자사주","배당","소각","유상증자","무상증자","전환사채","cb")),
        ("인수·사업재편",("인수","합병","m&a","분할","매각","지분 취득")),
        ("기술·제품·양산",("특허","양산","신제품","출시","기술 확보","개발 완료","인증")),
        ("정책·규제",("정책","법안","관세","규제","정부","지원책")),
        ("업황·가격",("업황","가격 상승","가격 인상","수요","공급 부족","hbm","반도체","원전","로봇","전력")),
    ]
    for name,words in rules:
        if any(w in text for w in words):
            return name
    return "기타·미확인"


def compact_external_report(report, completed_at=None, model=None):
    if not radar_clean_report:
        return None
    clean=radar_clean_report(report)
    if not clean:return None
    text=clean.get("text") or ""
    event=None
    m=re.search(r"(?m)^\s*재료분류\s*[:：]\s*([^\n]+)",text)
    if m:event=m.group(1).strip().strip("*")
    # Home shows only the 핵심 재료 section or a compact first paragraph.
    sec=re.search(r"(?ms)(?:^|\n)\s*(?:#{1,4}\s*)?(?:\*\*)?핵심 재료(?:\*\*)?\s*[:：]?\s*\n?(.*?)(?=\n\s*(?:#{1,4}\s*)?(?:\*\*)?(?:새로움과 반복|시장 연결|반대 근거·미확인)|\Z)",text)
    body=(sec.group(1) if sec else text).strip()
    body=re.sub(r"\s+"," ",body)
    body=re.sub(r"\[[^\]]{0,40}\]"," ",body)
    body=re.sub(r"\s+"," ",body).strip()
    summary=(body[:190]+"…") if len(body)>190 else body
    age_sec=None
    try:
        age_sec=int((datetime.now(timezone.utc)-completed_at).total_seconds()) if completed_at else None
    except Exception:
        age_sec=None
    return {
        "summary":summary or "인용 포함 외부 조사 보고서",
        "event_type":event,
        "citation_count":len(clean.get("citations") or []),
        "source_count":len(clean.get("sources") or []),
        "sources":(clean.get("sources") or [])[:3],
        "completed_at":iso(completed_at),
        "age_sec":age_sec,
        "stale":bool(age_sec is not None and age_sec>21600),
        "model":model,
        "status":"CITED_REPORT"
    }


def build_rank_history(cur, current_time, codes):
    out={code:{"rank_30s":None,"rank_5m":None,"best_today":None,"first_today":None,
               "movement":"—","movement_kind":"FLAT"} for code in codes}
    if not codes or not current_time or not table_exists(cur,"market_rank_snapshots"):
        return out
    day_start=current_time.astimezone(KST).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
    queries=[
        ("rank_30s",current_time-timedelta(seconds=20),current_time-timedelta(seconds=100)),
        ("rank_5m",current_time-timedelta(minutes=4,seconds=30),current_time-timedelta(minutes=7)),
    ]
    for key,upper,lower in queries:
        cur.execute("""SELECT DISTINCT ON(stock_code) stock_code,rank_no,snapshot_time
                       FROM market_rank_snapshots
                       WHERE stock_code=ANY(%s) AND snapshot_time<=%s AND snapshot_time>=%s
                       ORDER BY stock_code,snapshot_time DESC""",(list(codes),upper,lower))
        for code,rank_no,snapshot_time in cur.fetchall():
            if code in out:out[code][key]=rank_no
    cur.execute("""SELECT stock_code,MIN(rank_no),MIN(snapshot_time),COUNT(*)
                   FROM market_rank_snapshots
                   WHERE stock_code=ANY(%s) AND snapshot_time>=%s AND snapshot_time<=%s
                   GROUP BY stock_code""",(list(codes),day_start,current_time))
    for code,best,first_seen,count in cur.fetchall():
        if code in out:
            out[code]["best_today"]=best
            out[code]["first_today"]=iso(first_seen)
            out[code]["seen_today"]=int(count or 0)
            out[code]["had_earlier"]=bool(first_seen and first_seen < current_time-timedelta(minutes=2))
    return out


def apply_rank_movement(row, history):
    h=history.get(row.get("code")) or {}
    current=row.get("rank")
    prior=h.get("rank_30s")
    five=h.get("rank_5m")
    best=h.get("best_today")
    movement="—";kind="FLAT";delta=None
    if current is not None and prior is not None:
        delta=int(prior)-int(current)
        if delta>0:movement=f"▲{delta}";kind="UP"
        elif delta<0:movement=f"▼{abs(delta)}";kind="DOWN"
    elif current is not None:
        # If it was seen materially earlier today but vanished from the recent comparison window, call it re-entry.
        if five is not None or h.get("had_earlier"):movement="RE";kind="REENTRY"
        else:movement="NEW";kind="NEW"
    row["rank_history"]={
        **h,"delta_30s":delta,"movement":movement,"movement_kind":kind,
        "current":current,"best_today":best
    }
    return row


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
        "identity_quality": cat.get("best_identity_quality") or "UNVERIFIED",
        "identity_warning_count": len(cat.get("identity_warnings") or []) + int(cat.get("identity_rejected") or 0),
        "material_type": classify_material_type(cat),
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
    global _DASH_CACHE,_DASH_CACHE_AT
    require_token(x_dashboard_token)
    now_mono=pytime.monotonic()
    with _DASH_CACHE_LOCK:
        if _DASH_CACHE is not None and now_mono-_DASH_CACHE_AT<DASHBOARD_CACHE_SECONDS:
            return _DASH_CACHE
    with get_db() as c:
        with c.cursor() as cur:
            # system
            telegram = {"latest": None, "count_24h": 0}
            if table_exists(cur, "telegram_messages"):
                cur.execute("SELECT MAX(message_date), COUNT(*) FILTER (WHERE collected_at > now()-interval '24 hours') FROM telegram_messages")
                r = cur.fetchone()
                telegram = {"latest": iso(r[0]), "count_24h": int(r[1] or 0)}

            kiwoom = {"status": "NOT_CONFIGURED", "mode": None, "last_success": None, "note": None}
            if table_exists(cur, "kiwoom_feed_status"):
                cur.execute("SELECT status,mode,last_success_at,note FROM kiwoom_feed_status WHERE id=1")
                r = cur.fetchone()
                if r:
                    kiwoom = {"status": r[0], "mode": r[1], "last_success": iso(r[2]), "note": r[3]}

            orderbook = {"status":"NOT_CONFIGURED","updated_at":None,"mode":None,
                         "target_count":0,"saved_count":0,"note":None}
            if table_exists(cur,"orderbook_feed_status"):
                cur.execute("""SELECT status,updated_at,mode,target_count,saved_count,note
                               FROM orderbook_feed_status WHERE id=1""")
                r=cur.fetchone()
                if r:
                    orderbook={"status":r[0],"updated_at":iso(r[1]),"mode":r[2],
                               "target_count":int(r[3] or 0),"saved_count":int(r[4] or 0),
                               "note":r[5]}

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
                cur.execute("""SELECT snapshot_time,candidate_trend_state,candidate_flow_state,candidate_sentiment_state,
                                      confidence,data_freshness_sec,rank_turnover_5m,top5_trade_share,
                                      top10_trade_share,top_sector_share,top3_sector_share,largecap_trade_share,
                                      positive_rank_share,avg_rank_change_rate,sector_count_top20,explanation
                               FROM market_regime_snapshots ORDER BY snapshot_time DESC LIMIT 1""")
                r = cur.fetchone()
                if r:
                    regime_metrics = {
                        "snapshot_time": iso(r[0]), "trend": r[1], "flow": r[2], "sentiment": r[3],
                        "confidence": r[4], "freshness_sec": r[5],
                        "rank_turnover_5m": r[6], "top5_trade_share": r[7], "top10_trade_share": r[8],
                        "top_sector_share": r[9], "top3_sector_share": r[10], "largecap_trade_share": r[11],
                        "positive_rank_share": r[12], "avg_rank_change_rate": r[13],
                        "sector_count_top20": r[14], "explanation": r[15] or {}
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

            reversal_map={}
            if radar_reversal_signals and ranks and table_exists(cur,"market_minute_bars"):
                try:
                    rank_codes=[x[0] for x in ranks if x and x[0]]
                    cur.execute("""SELECT stock_code,bar_time,open_price,high_price,low_price,close_price,volume
                                   FROM (
                                     SELECT stock_code,bar_time,open_price,high_price,low_price,close_price,volume,
                                            row_number() OVER(PARTITION BY stock_code ORDER BY bar_time DESC) AS rn
                                     FROM market_minute_bars
                                     WHERE interval_min=3 AND stock_code=ANY(%s)
                                   ) q
                                   WHERE rn<=60
                                   ORDER BY stock_code,bar_time""",(rank_codes,))
                    hist={}
                    for code,bt,o,h,l,c,v in cur.fetchall():
                        hist.setdefault(code,[]).append({
                            "time":iso(bt),"open":float(o) if o is not None else None,
                            "high":float(h) if h is not None else None,"low":float(l) if l is not None else None,
                            "close":float(c) if c is not None else None,"volume":float(v) if v is not None else None
                        })
                    for code,bars in hist.items():
                        pack=radar_reversal_signals(bars,strategy_map.get(code,{}) or {},max_signals=6)
                        reversal_map[code]={
                            "latest":pack.get("latest"),
                            "recent":(pack.get("signals") or [])[-3:],
                            "note":pack.get("note")
                        }
                except Exception:
                    reversal_map={}

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

            # Latest validated SOR observation delta for intuitive per-stock "how much just traded".
            flow_map={}
            if radar_flow_delta and table_exists(cur,"radar_flow_quotes"):
                try:
                    cur.execute("""SELECT stock_code,batch_time,payload FROM (
                                     SELECT stock_code,batch_time,payload,
                                            row_number() OVER(PARTITION BY stock_code ORDER BY batch_time DESC) AS rn
                                     FROM radar_flow_quotes
                                     WHERE batch_time>now()-interval '4 minutes'
                                   ) q WHERE rn<=2 ORDER BY stock_code,batch_time DESC""")
                    flow_hist={}
                    for code,bt,payload in cur.fetchall():
                        flow_hist.setdefault(code,[]).append(payload or {})
                    for code,h in flow_hist.items():
                        current=h[0] if h else None
                        previous=h[1] if len(h)>1 else None
                        value,state,seconds=radar_flow_delta(current,previous) if current else (None,"NO_SAMPLE",None)
                        exchange_at=None
                        try:
                            exchange_at=datetime.fromisoformat(current.get("exchange_at")) if current and current.get("exchange_at") else None
                            if exchange_at and exchange_at.tzinfo is None:exchange_at=exchange_at.replace(tzinfo=timezone.utc)
                        except Exception:
                            exchange_at=None
                        if state=="OK" and (not exchange_at or (datetime.now(timezone.utc)-exchange_at.astimezone(timezone.utc)).total_seconds()>120):
                            value=None
                            state="STALE_EXCHANGE"
                        flow_map[code]={
                            "recent_turnover_krw":value if state=="OK" else None,
                            "recent_turnover_seconds":seconds,
                            "recent_turnover_state":state,
                            "sor_turnover_krw":current.get("turnover_krw") if current else None,
                            "price_krw":current.get("price_krw") if current else None,
                            "exchange_at":current.get("exchange_at") if current else None
                        }
                except Exception:
                    flow_map={}

            # Cached cited OS/web research for home cards. Read-only; does not trigger a model call.
            external_report_map={}
            if radar_clean_report and table_exists(cur,"web_research_runs") and ranks:
                try:
                    rank_codes=[x[0] for x in ranks if x and x[0]]
                    cur.execute("""SELECT DISTINCT ON(stock_code)
                                          stock_code,completed_at,model,report
                                   FROM web_research_runs
                                   WHERE stock_code=ANY(%s) AND status='CITED_REPORT'
                                     AND completed_at>now()-interval '7 days'
                                   ORDER BY stock_code,completed_at DESC,id DESC""",(rank_codes,))
                    for code,completed_at,model,report in cur.fetchall():
                        compact=compact_external_report(report,completed_at,model)
                        if compact:external_report_map[code]=compact
                except Exception:
                    external_report_map={}

            rank_codes=[x[0] for x in ranks if x and x[0]]
            rank_history_map=build_rank_history(cur,rank_time,rank_codes)

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
                cat = catalyst_for_stock(messages, code, name, sector2)
                cat["external_news"] = news_map.get(code, [])
                cat["dart"] = dart_map.get(code, [])
                if cat["status"] == "NO_MATCH" and (cat["external_news"] or cat["dart"]):
                    cat["status"] = "NEWS_ONLY"
                    cat["note"] = "Telegram 직접매칭 없음 · 외부뉴스/공시 fallback"
                cat=enrich_catalyst(cat,name,sector2)
                theme2 = choose_market_theme(name, sector2, cat)
                flow = stock_flow_state(rank_no, rank_change, tv.get("rank"), cat)
                row = {
                    "rank": rank_no, "rank_change": rank_change, "code": code, "name": name,
                    "change_rate": chg, "trade_rank": tv.get("rank"), "trade_value_krw": trade_value,
                    "market_cap_krw": cap2, "trade_to_cap_pct": ratio,
                    "official_sector": sector2, "market_theme": theme2,
                    "recent_turnover_krw":(flow_map.get(code) or {}).get("recent_turnover_krw"),
                    "recent_turnover_seconds":(flow_map.get(code) or {}).get("recent_turnover_seconds"),
                    "recent_turnover_state":(flow_map.get(code) or {}).get("recent_turnover_state"),
                    "sor_turnover_krw":(flow_map.get(code) or {}).get("sor_turnover_krw"),
                    "price_krw":(flow_map.get(code) or {}).get("price_krw"),
                    "quote_exchange_at":(flow_map.get(code) or {}).get("exchange_at"),
                    "catalyst": cat, "flow_state": flow,
                    "chart_state": (chart_map.get(code) or {}).get("state_ko","대기"),
                    "reversal_signal":(reversal_map.get(code) or {}).get("latest"),
                    "recent_reversal_signals":(reversal_map.get(code) or {}).get("recent") or [],
                    "mimosa": chart_map.get(code) or {"state":"WAITING_FOR_CHART","state_ko":"차트 데이터 대기","score":0},
                    "mimosa_strategies": strategy_map.get(code,{})
                }
                row["analysis"] = stock_analysis(row)
                row["material_digest"] = material_digest(cat,flow,name)
                row["material_digest"].update(material_synthesis(
                    row["material_digest"],rank_no,tv.get("rank"),chg,flow
                ))
                row["external_research"]=external_report_map.get(code)
                if row["external_research"]:
                    event=row["external_research"].get("event_type")
                    row["material_digest"]["material_type"]=classify_material_type(cat,event)
                apply_rank_movement(row,rank_history_map)
                rows.append(row)

            sector_groups = build_sector_groups(rows)
            leader_desk=build_leader_desk(cur,trade_map,rows,datetime.now(timezone.utc),sector_groups)
            home_candidates=build_home_candidates(cur,rows)
            paper_lab=build_paper_lab(cur)
            paper_feedback=build_paper_feedback(cur)

            # AI Brokerage v1: explainable PAPER-only decisions for current Top candidates.
            ai_brokerage={
                "status":"NOT_CONFIGURED","paper_only":True,
                "registry":{},"candidates":[],
                "note":"6-Desk 판단 모듈 미로딩"
            }
            if AI_BROKERAGE_ENGINE and ai_context_from_dashboard_row:
                try:
                    candidate_map={x.get("code"):x for x in home_candidates if x.get("code")}
                    theme_strength_map={
                        g.get("name"):g.get("theme_strength")
                        for g in sector_groups if g.get("name") and g.get("theme_strength") is not None
                    }
                    max_open=max(1,min(20,int(os.getenv("PAPER_MAX_OPEN","5"))))
                    packets=[]
                    for row in rows:
                        candidate=candidate_map.get(row.get("code"))
                        if not candidate:
                            continue
                        row["candidate"]={
                            "score":candidate.get("attention_score"),
                            "last_score":candidate.get("attention_score"),
                            "entry_score":candidate.get("entry_score"),
                            "peak_score":candidate.get("peak_score"),
                            "primary_type":candidate.get("primary_type"),
                            "event_type":candidate.get("event_type"),
                        }
                        ctx=ai_context_from_dashboard_row(
                            row,regime,regime_metrics,theme_strength_map,paper_lab,max_open=max_open
                        )
                        packet=AI_BROKERAGE_ENGINE.evaluate(ctx).to_dict()
                        row["ai_brokerage"]=packet
                        packets.append(packet)
                    state_order={"PAPER_ENTRY":0,"READY":1,"WATCH":2,"BLOCKED":3,"IGNORE":4}
                    packets.sort(key=lambda x:(state_order.get(x.get("state"),9),-(x.get("conviction") or 0)))
                    ai_brokerage={
                        "status":"OK","paper_only":True,
                        "registry":AI_BROKERAGE_ENGINE.registry.lifecycle_counts(),
                        "candidates":packets,
                        "note":"실거래 주문 없음 · candidate tracker Top 후보를 6개 Desk가 평가"
                    }
                except Exception as e:
                    ai_brokerage={
                        "status":"ERROR","paper_only":True,
                        "registry":AI_BROKERAGE_ENGINE.registry.lifecycle_counts(),
                        "candidates":[],
                        "note":f"AI Brokerage 평가 실패: {type(e).__name__}: {e}"
                    }

            ai_morning_brief=build_ai_morning_brief(regime,sector_groups,ai_brokerage,paper_lab)
            ai_strategy_performance=build_ai_strategy_performance(cur)
            ai_capacity=build_ai_capacity_analysis(cur,ai_strategy_performance)
            ai_allocation=build_ai_allocation(cur,rows,ai_brokerage,ai_capacity)
            shadow_execution=build_shadow_execution_lab(cur)
            shadow_execution["orderbook_feed"]=orderbook
            ai_risk_control=build_ai_risk_control(
                cur,rows,ai_brokerage,ai_capacity,ai_allocation,shadow_execution,
                kiwoom,orderbook,regime,chartfeed
            )
            ai_daily_review=build_ai_daily_review(cur,paper_feedback)
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
                cat=catalyst_for_stock(messages,code,name,tv.get("sector"))
                cat["external_news"]=news_map.get(code,[])
                cat["dart"]=dart_map.get(code,[])
                if cat["status"]=="NO_MATCH" and (cat["external_news"] or cat["dart"]):
                    cat["status"]="NEWS_ONLY";cat["note"]="Telegram 직접매칭 없음 · 외부뉴스/공시 fallback"
                cat=enrich_catalyst(cat,name,tv.get("sector"))
                cap=tv.get("market_cap"); value=tv.get("trade_value")
                ratio=(float(value)/float(cap)*100) if value is not None and cap and float(cap)>0 else None
                theme=choose_market_theme(name, tv.get("sector"), cat)
                flow=stock_flow_state(None,None,tv.get("rank"),cat)
                x={"rank":None,"rank_change":None,"code":code,"name":name,"change_rate":tv.get("change_rate"),
                   "trade_rank":tv.get("rank"),"trade_value_krw":value,"market_cap_krw":cap,"trade_to_cap_pct":ratio,
                   "official_sector":tv.get("sector"),"market_theme":theme,
                   "recent_turnover_krw":(flow_map.get(code) or {}).get("recent_turnover_krw"),
                   "recent_turnover_seconds":(flow_map.get(code) or {}).get("recent_turnover_seconds"),
                   "recent_turnover_state":(flow_map.get(code) or {}).get("recent_turnover_state"),
                   "sor_turnover_krw":(flow_map.get(code) or {}).get("sor_turnover_krw"),
                   "catalyst":cat,"flow_state":flow,
                   "chart_state":(chart_map.get(code) or {}).get("state_ko","대기"),
                   "reversal_signal":(reversal_map.get(code) or {}).get("latest"),
                   "recent_reversal_signals":(reversal_map.get(code) or {}).get("recent") or [],
                   "mimosa":chart_map.get(code) or {"state":"WAITING_FOR_CHART","state_ko":"차트 데이터 대기","score":0},
                   "mimosa_strategies":strategy_map.get(code,{})}
                x["analysis"]=stock_analysis(x)
                x["material_digest"]=material_digest(cat,flow,name)
                x["material_digest"].update(material_synthesis(
                    x["material_digest"],None,tv.get("rank"),tv.get("change_rate"),flow
                ))
                x["external_research"]=external_report_map.get(code)
                if x["external_research"]:
                    x["material_digest"]["material_type"]=classify_material_type(cat,x["external_research"].get("event_type"))
                x["rank_history"]={"movement":"—","movement_kind":"FLAT","current":None,"rank_30s":None,"rank_5m":None,"best_today":None}
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
            home_strength=sorted(sector_groups,key=lambda g:(g.get("theme_strength") or 0),reverse=True)
            strongest=home_strength[0] if home_strength else None
            fastest=sorted(sector_groups,key=lambda g:(g.get("recent_turnover_krw") or 0),reverse=True)
            fastest=fastest[0] if fastest and (fastest[0].get("recent_turnover_krw") or 0)>0 else None
            top_up=sum(1 for x in rows[:12] if (x.get("rank_history") or {}).get("movement_kind")=="UP")
            top_new=sum(1 for x in rows[:12] if (x.get("rank_history") or {}).get("movement_kind") in ("NEW","REENTRY"))
            cited=sum(1 for x in rows[:12] if x.get("external_research"))
            brief_bits=[]
            if strongest:brief_bits.append(f"테마강도 {strongest['name']} {strongest.get('theme_strength','-')}")
            if fastest and (not strongest or fastest.get("name")!=strongest.get("name")):
                brief_bits.append(f"최근대금 {fastest['name']} +{int((fastest.get('recent_turnover_krw') or 0)/100000000):,}억")
            if top_up:brief_bits.append(f"순위상승 {top_up}종목")
            if top_new:brief_bits.append(f"신규·재진입 {top_new}종목")
            if cited:brief_bits.append(f"OS검증 {cited}종목")
            home_brief={"headline":" · ".join(brief_bits) if brief_bits else "시장 관측 축적 중",
                        "strongest_theme":strongest.get("name") if strongest else None,
                        "top_up":top_up,"top_new":top_new,"os_verified":cited}

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

    payload={
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system": {"telegram": telegram, "kiwoom": kiwoom, "orderbook": orderbook, "newsfeed": newsfeed, "dartfeed": dartfeed, "chartfeed": chartfeed, "mimosa": mimosa, "research": research, "deepresearch": deepresearch},
        "regime": regime,
        "regime_metrics": regime_metrics,
        "rank_time": iso(rank_time),
        "trade_time": iso(trade_time),
        "rows": rows,
        "query_ranking": rows,
        "trade_ranking": trade_rows,
        "etf_trade_ranking": etf_trade_rows,
        "sector_rankings": sector_groups,
        "leader_desk": leader_desk,
        "materials": material_rows,
        "material_stats": material_stats,
        "home_brief": home_brief,
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
        "home_candidates": home_candidates,
        "paper_lab": paper_lab,
        "paper_feedback": paper_feedback,
        "ai_brokerage": ai_brokerage,
        "ai_morning_brief": ai_morning_brief,
        "ai_strategy_performance": ai_strategy_performance,
        "ai_capacity": ai_capacity,
        "ai_allocation": ai_allocation,
        "ai_risk_control": ai_risk_control,
        "ai_daily_review": ai_daily_review,
        "shadow_execution": shadow_execution,
        "cache_seconds": DASHBOARD_CACHE_SECONDS,
    }
    with _DASH_CACHE_LOCK:
        _DASH_CACHE=payload
        _DASH_CACHE_AT=pytime.monotonic()
    return payload

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


def require_kiwoom_ingest_token(x_kiwoom_ingest_token: Optional[str] = Header(None)):
    if not KIWOOM_INGEST_TOKEN or not x_kiwoom_ingest_token or not secrets.compare_digest(x_kiwoom_ingest_token, KIWOOM_INGEST_TOKEN):
        raise HTTPException(status_code=401, detail="unauthorized")

def ensure_kiwoom_ingest_schema(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS kiwoom_feed_status(
      id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
      updated_at TIMESTAMPTZ NOT NULL,
      status TEXT NOT NULL,
      mode TEXT,
      last_success_at TIMESTAMPTZ,
      note TEXT,
      last_error TEXT
    );
    CREATE TABLE IF NOT EXISTS stock_master(
      stock_code TEXT PRIMARY KEY,
      stock_name TEXT,
      market_name TEXT,
      official_sector TEXT,
      size_class TEXT,
      nxt_enabled TEXT,
      updated_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE IF NOT EXISTS market_rank_snapshots(
      snapshot_time TIMESTAMPTZ NOT NULL,
      stock_code TEXT NOT NULL,
      stock_name TEXT,
      rank_no INTEGER,
      rank_change INTEGER,
      change_rate DOUBLE PRECISION,
      market_cap_krw NUMERIC,
      official_sector TEXT,
      market_theme TEXT,
      current_price_krw NUMERIC,
      PRIMARY KEY(snapshot_time,stock_code)
    );
    CREATE INDEX IF NOT EXISTS idx_rank_time ON market_rank_snapshots(snapshot_time DESC);
    CREATE TABLE IF NOT EXISTS market_trade_value_snapshots(
      snapshot_time TIMESTAMPTZ NOT NULL,
      stock_code TEXT NOT NULL,
      stock_name TEXT,
      rank_no INTEGER,
      trade_value_krw NUMERIC,
      change_rate DOUBLE PRECISION,
      market_cap_krw NUMERIC,
      official_sector TEXT,
      market_theme TEXT,
      current_price_krw NUMERIC,
      PRIMARY KEY(snapshot_time,stock_code)
    );
    CREATE INDEX IF NOT EXISTS idx_trade_time ON market_trade_value_snapshots(snapshot_time DESC);
    CREATE TABLE IF NOT EXISTS market_sector_snapshots(
      snapshot_time TIMESTAMPTZ NOT NULL,
      sector_code TEXT NOT NULL,
      sector_name TEXT NOT NULL,
      change_rate DOUBLE PRECISION,
      trade_value_krw NUMERIC,
      rising_count INTEGER,
      flat_count INTEGER,
      falling_count INTEGER,
      PRIMARY KEY(snapshot_time,sector_code)
    );
    CREATE INDEX IF NOT EXISTS idx_sector_time ON market_sector_snapshots(snapshot_time DESC);
    CREATE TABLE IF NOT EXISTS market_index_snapshots(
      snapshot_time TIMESTAMPTZ NOT NULL,
      index_code TEXT NOT NULL,
      index_name TEXT NOT NULL,
      current_value DOUBLE PRECISION,
      change_rate DOUBLE PRECISION,
      open_value DOUBLE PRECISION,
      high_value DOUBLE PRECISION,
      low_value DOUBLE PRECISION,
      PRIMARY KEY(snapshot_time,index_code)
    );
    CREATE INDEX IF NOT EXISTS idx_index_time ON market_index_snapshots(snapshot_time DESC);
    ALTER TABLE market_rank_snapshots ADD COLUMN IF NOT EXISTS current_price_krw NUMERIC;
    ALTER TABLE market_trade_value_snapshots ADD COLUMN IF NOT EXISTS current_price_krw NUMERIC;
    """)

def _num(v, cast=float):
    if v is None or v == "":
        return None
    try:
        return cast(v)
    except Exception:
        return None

@app.post("/api/kiwoom/ingest")
def kiwoom_ingest(payload: dict = Body(...), _auth=Header(None, alias="x-kiwoom-ingest-token")):
    require_kiwoom_ingest_token(_auth)
    mode = str(payload.get("mode") or "external").strip().lower()
    if mode not in ("demo","real","external"):
        raise HTTPException(status_code=400, detail="invalid mode")
    try:
        snap_raw = payload.get("snapshot_time")
        snap = datetime.fromisoformat(str(snap_raw).replace("Z","+00:00")) if snap_raw else datetime.now(timezone.utc)
        if snap.tzinfo is None:
            snap = snap.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if abs((now - snap.astimezone(timezone.utc)).total_seconds()) > 3600:
            raise HTTPException(status_code=400, detail="snapshot_time too old or too far in future")

        rank = payload.get("rank") or []
        trade = payload.get("trade") or []
        sectors = payload.get("sectors") or []
        indices = payload.get("indices") or []
        meta = payload.get("stock_meta") or []
        if not isinstance(rank,list) or not isinstance(trade,list) or not isinstance(sectors,list) or not isinstance(indices,list):
            raise HTTPException(status_code=400, detail="invalid payload shape")
        if len(rank) > 200 or len(trade) > 200 or len(sectors) > 500 or len(indices) > 20 or len(meta) > 5000:
            raise HTTPException(status_code=413, detail="payload too large")

        with get_db() as c, c.cursor() as cur:
            ensure_kiwoom_ingest_schema(cur)

            for m in meta:
                code=str(m.get("stock_code") or "").replace("_AL","").replace("_NX","").strip()
                if not code: continue
                cur.execute("""INSERT INTO stock_master(stock_code,stock_name,market_name,official_sector,size_class,nxt_enabled,updated_at)
                               VALUES(%s,%s,%s,%s,%s,%s,now())
                               ON CONFLICT(stock_code) DO UPDATE SET stock_name=COALESCE(excluded.stock_name,stock_master.stock_name),
                               market_name=COALESCE(excluded.market_name,stock_master.market_name),
                               official_sector=COALESCE(excluded.official_sector,stock_master.official_sector),
                               size_class=COALESCE(excluded.size_class,stock_master.size_class),
                               nxt_enabled=COALESCE(excluded.nxt_enabled,stock_master.nxt_enabled),updated_at=now()""",
                            (code,m.get("stock_name"),m.get("market_name"),m.get("official_sector"),m.get("size_class"),m.get("nxt_enabled")))

            for r in rank:
                code=str(r.get("stock_code") or "").replace("_AL","").replace("_NX","").strip()
                if not code: continue
                cur.execute("""INSERT INTO market_rank_snapshots(snapshot_time,stock_code,stock_name,rank_no,rank_change,change_rate,
                               market_cap_krw,official_sector,market_theme,current_price_krw)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT(snapshot_time,stock_code) DO UPDATE SET
                               stock_name=excluded.stock_name,rank_no=excluded.rank_no,rank_change=excluded.rank_change,
                               change_rate=excluded.change_rate,market_cap_krw=excluded.market_cap_krw,
                               official_sector=excluded.official_sector,market_theme=excluded.market_theme,current_price_krw=excluded.current_price_krw""",
                            (snap,code,r.get("stock_name"),_num(r.get("rank_no"),int),_num(r.get("rank_change"),int),
                             _num(r.get("change_rate")),_num(r.get("market_cap_krw")),r.get("official_sector"),
                             r.get("market_theme"),_num(r.get("current_price_krw"))))

            for r in trade:
                code=str(r.get("stock_code") or "").replace("_AL","").replace("_NX","").strip()
                if not code: continue
                cur.execute("""INSERT INTO market_trade_value_snapshots(snapshot_time,stock_code,stock_name,rank_no,trade_value_krw,
                               change_rate,market_cap_krw,official_sector,market_theme,current_price_krw)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT(snapshot_time,stock_code) DO UPDATE SET
                               stock_name=excluded.stock_name,rank_no=excluded.rank_no,trade_value_krw=excluded.trade_value_krw,
                               change_rate=excluded.change_rate,market_cap_krw=excluded.market_cap_krw,
                               official_sector=excluded.official_sector,market_theme=excluded.market_theme,current_price_krw=excluded.current_price_krw""",
                            (snap,code,r.get("stock_name"),_num(r.get("rank_no"),int),_num(r.get("trade_value_krw")),
                             _num(r.get("change_rate")),_num(r.get("market_cap_krw")),r.get("official_sector"),
                             r.get("market_theme"),_num(r.get("current_price_krw"))))

            for r in sectors:
                scode=str(r.get("sector_code") or r.get("sector_name") or "").strip()
                if not scode: continue
                cur.execute("""INSERT INTO market_sector_snapshots(snapshot_time,sector_code,sector_name,change_rate,trade_value_krw,
                               rising_count,flat_count,falling_count)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT(snapshot_time,sector_code) DO UPDATE SET
                               sector_name=excluded.sector_name,change_rate=excluded.change_rate,trade_value_krw=excluded.trade_value_krw,
                               rising_count=excluded.rising_count,flat_count=excluded.flat_count,falling_count=excluded.falling_count""",
                            (snap,scode,r.get("sector_name") or scode,_num(r.get("change_rate")),_num(r.get("trade_value_krw")),
                             _num(r.get("rising_count"),int),_num(r.get("flat_count"),int),_num(r.get("falling_count"),int)))

            for r in indices:
                icode=str(r.get("index_code") or "").strip()
                if not icode: continue
                cur.execute("""INSERT INTO market_index_snapshots(snapshot_time,index_code,index_name,current_value,change_rate,
                               open_value,high_value,low_value)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT(snapshot_time,index_code) DO UPDATE SET
                               index_name=excluded.index_name,current_value=excluded.current_value,change_rate=excluded.change_rate,
                               open_value=excluded.open_value,high_value=excluded.high_value,low_value=excluded.low_value""",
                            (snap,icode,r.get("index_name") or icode,_num(r.get("current_value")),_num(r.get("change_rate")),
                             _num(r.get("open_value")),_num(r.get("high_value")),_num(r.get("low_value"))))

            note=f"windows_ingest rank={len(rank)} trade={len(trade)} sectors={len(sectors)} indices={len(indices)}"
            cur.execute("""INSERT INTO kiwoom_feed_status(id,updated_at,status,mode,last_success_at,note,last_error)
                           VALUES(1,now(),'OK',%s,now(),%s,NULL)
                           ON CONFLICT(id) DO UPDATE SET updated_at=now(),status='OK',mode=excluded.mode,
                           last_success_at=now(),note=excluded.note,last_error=NULL""",(mode,note))
            c.commit()
        return {"ok":True,"snapshot_time":snap.isoformat(),"rank":len(rank),"trade":len(trade),"sectors":len(sectors),"indices":len(indices)}
    except HTTPException:
        raise
    except Exception as e:
        try:
            with get_db() as c, c.cursor() as cur:
                ensure_kiwoom_ingest_schema(cur)
                cur.execute("""INSERT INTO kiwoom_feed_status(id,updated_at,status,mode,last_success_at,note,last_error)
                               VALUES(1,now(),'ERROR',%s,NULL,'Windows ingest error',%s)
                               ON CONFLICT(id) DO UPDATE SET updated_at=now(),status='ERROR',mode=excluded.mode,
                               note='Windows ingest error',last_error=excluded.last_error""",(mode,str(e)[:500]))
                c.commit()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="ingest failed")

@app.get("/", response_class=HTMLResponse)
def root():
    return HTMLResponse(DASHBOARD_HTML_V2 or DASHBOARD_HTML)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT","8080")))
