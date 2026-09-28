"""Evidence identity guards shared by public-news and dashboard synthesis.

The goal is precision over coverage: if a headline/message may refer to a
different entity or merely lists many tickers, do not promote it to a catalyst.
"""
from __future__ import annotations
import re

LIST_PATTERNS=(
    "상한가 및 급등","특징 상한가","특징주 정리","급등종목","상승종목",
    "오늘의 종목","관심종목","종목추천","추천주","장마감","마감시황",
    "급등일보","테마주 정리","관련주 정리",
)

# Known listed-company names that collide with well-known foreign/non-listed entities.
# This is deliberately small and explicit; new collisions can be added from feedback.
AMBIGUOUS_GUARDS={
    "레메디":{
        "positive":("의료","의료기기","엑스레이","x-ray","x선","방사선","영상","진단","치료","장비","nasA".lower()),
        "negative":("게임","신작","컨트롤","레조넌트","맨해튼","액션","remedy entertainment",
                    "플레이스테이션","xbox","스팀","콘솔"),
    },
}

SECTOR_CONTEXT={
    "의료":("의료","의료기기","진단","영상","엑스레이","x-ray","방사선","치료"),
    "정밀기기":("의료","장비","센서","정밀","영상","엑스레이","x-ray"),
    "제약":("제약","신약","임상","fda","치료제","바이오","의약"),
    "바이오":("바이오","신약","임상","fda","진단","유전자","치료제"),
    "반도체":("반도체","hbm","dram","낸드","파운드리","패키징"),
    "전기":("전기","전자","부품","전력","mlcc","기판"),
    "전자":("전자","부품","기판","스마트폰","카메라","디스플레이"),
    "화학":("화학","태양광","소재","에너지","석유화학"),
    "건설":("건설","수주","플랜트","주택","토목","공사"),
}

def compact_name(name):
    return re.sub(r"[\s㈜()주식회사]+","",str(name or "")).lower()

def normalize(text):
    return re.sub(r"\s+"," ",str(text or "")).strip().lower()

def name_present(name,text):
    n=compact_name(name)
    if len(n)<2:return False
    compact=compact_name(text)
    return n in compact

def identity_quality(name,text,source_kind="",official_sector=None):
    t=normalize(text)
    source=str(source_kind or "").upper()
    if source=="DART":
        return "VERIFIED"
    if not name_present(name,t):
        return "MISSING_NAME"
    if any(p.lower() in t for p in LIST_PATTERNS):
        return "LIST_MENTION"
    guard=AMBIGUOUS_GUARDS.get(str(name or "").strip())
    if guard:
        pos=any(x.lower() in t for x in guard["positive"])
        neg=any(x.lower() in t for x in guard["negative"])
        if neg and not pos:
            return "ENTITY_CONFLICT"
        if pos:
            return "CONTEXT_VERIFIED"
    sector=normalize(official_sector)
    for key,words in SECTOR_CONTEXT.items():
        if key in sector and any(w in t for w in words):
            return "CONTEXT_VERIFIED"
    return "NAME_MATCH"

def stock_context(text,name,radius=130):
    raw=str(text or "")
    n=str(name or "").strip()
    if not n:return ""
    low=raw.lower();needle=n.lower()
    spans=[]
    start=0
    while True:
        i=low.find(needle,start)
        if i<0:break
        spans.append(raw[max(0,i-radius):min(len(raw),i+len(n)+radius)])
        start=i+len(needle)
        if len(spans)>=3:break
    return " ".join(spans)

def usable_as_catalyst(quality):
    return quality in ("VERIFIED","CONTEXT_VERIFIED","NAME_MATCH")

def usable_for_theme(quality):
    return quality in ("VERIFIED","CONTEXT_VERIFIED")
