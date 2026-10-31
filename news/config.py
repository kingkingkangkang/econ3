"""오늘의 경제 3 — 설정값.

여기 값만 바꾸면 매체·모델·시간 등을 조정할 수 있어요.
"""
import os

# ── 시간 ────────────────────────────────────────────────
TIMEZONE = "Asia/Seoul"
SEND_HOUR = 8          # 카톡 받는 시각 (한국시간)
SEND_MINUTE = 0
MAX_WAIT_MINUTES = 30  # 일찍 끝나면 08:00까지 기다리는 최대 시간

# ── 모델 ────────────────────────────────────────────────
# 수집·본문 찾기는 저렴한 Haiku, 점수 매기기·요약 쓰기는 Sonnet
COLLECT_MODEL = os.getenv("COLLECT_MODEL", "claude-haiku-5-5")
SOURCE_MODEL = os.getenv("SOURCE_MODEL", "claude-haiku-5-5")
SCORE_MODEL = os.getenv("SCORE_MODEL", "claude-sonnet-5-5")
WRITE_MODEL = os.getenv("WRITE_MODEL", "claude-sonnet-5-5")

# USD / 100만 토큰 (2026-10 기준 공식 가격표). 비용 추정용.
PRICES = {
    "claude-haiku-5-5": {
        "in": 0.10, "out": 0.50, "cache_read": 0.01, "cache_write": 0.125,
        "long_in": 0.50, "long_out": 2.50, "long_cache_read": 0.05,
        "long_cache_write": 0.625, "long_threshold": 100_000,
    },
    "claude-sonnet-5-5": {
        "in": 2.0, "out": 10.0, "cache_read": 0.10, "cache_write": 2.50,
    },
}
WEB_SEARCH_PRICE = 0.01  # 검색 1회당 USD

# ── 이슈 고르기용 매체 (제목·첫 문단 수집) ─────────────────
OUTLETS = [
    # domain,              이름,               유료?
    ("wsj.com",            "WSJ",              True),
    ("ft.com",             "Financial Times",  True),
    ("bloomberg.com",      "Bloomberg",        True),
    ("economist.com",      "The Economist",    True),
    ("barrons.com",        "Barron's",         True),
    ("asia.nikkei.com",    "Nikkei Asia",      True),
    ("reuters.com",        "Reuters",          True),
    ("cnn.com",            "CNN Business",     True),
    ("cnbc.com",           "CNBC",             False),
    ("apnews.com",         "AP",               False),
    ("finance.yahoo.com",  "Yahoo Finance",    False),
    ("theguardian.com",    "The Guardian",     False),
    ("bbc.com",            "BBC",              False),
]
OUTLET_DOMAINS = [d for d, _, _ in OUTLETS]

# 1단계: 본문 전체를 읽을 수 있는 무료 매체
FULLTEXT_FREE_DOMAINS = ["finance.yahoo.com"]

# 2단계: 원래 발표 자료 (목록 페이지 주소는 web_fetch가 열 수 있게 프롬프트에 넣어요)
PRIMARY_SOURCES = [
    ("bls.gov",            "미국 노동통계국(BLS)", "물가(CPI·PPI), 고용보고서",
     "https://www.bls.gov/bls/newsrels.htm"),
    ("bea.gov",            "미국 경제분석국(BEA)", "GDP, 개인소득·소비(PCE)",
     "https://www.bea.gov/news/current-releases"),
    ("ustr.gov",           "미국 무역대표부(USTR)", "관세, 무역협상",
     "https://ustr.gov/about-us/policy-offices/press-office/press-releases"),
    ("federalreserve.gov", "연준(Fed)", "FOMC 성명서, 의사록",
     "https://www.federalreserve.gov/newsevents/pressreleases.htm"),
    ("businesswire.com",   "Business Wire", "기업 실적 보도자료",
     "https://www.businesswire.com/newsroom"),
]
PRIMARY_DOMAINS = [d for d, *_ in PRIMARY_SOURCES]

# 3단계 기사 링크: 사람이 무료로 볼 수 있는 매체 우선 (앞쪽일수록 우선)
HUMAN_FREE_LINK_DOMAINS = [
    "finance.yahoo.com", "apnews.com", "cnbc.com", "theguardian.com", "bbc.com",
]

# ── 선정 규칙 ───────────────────────────────────────────
CATEGORIES = ["macro", "market", "corporate"]
CATEGORY_LABELS = {"macro": "거시·정책", "market": "시장", "corporate": "기업·산업"}
EVENT_RANK = {"decision": 0, "statement": 1, "analysis": 2}  # 동점일 때: 발표·결정 > 발언·전망 > 해설
WEAK_SCORE = 50          # 분야 최고점이 이보다 낮으면 다른 분야 차점으로 채워요
MAX_PER_CATEGORY = 2     # 한 분야 최대 개수
MAX_SOURCING_ATTEMPTS = 8  # 본문 찾기를 시도할 이슈 최대 개수 (비용 상한)
TIER3_MIN_OUTLETS = 3    # 3단계(특이사항) 허용 최소 매체 수

# ── 도구 한도 ───────────────────────────────────────────
COLLECT_MAX_SEARCHES = 12
SOURCE_MAX_SEARCHES = 4
SOURCE_MAX_FETCHES = 6
FETCH_MAX_CONTENT_TOKENS = 7000
MAX_PAUSE_CONTINUATIONS = 6

# ── 출력 ────────────────────────────────────────────────
DOCS_DIR = os.getenv("DOCS_DIR", "docs")
SITE_TITLE = "오늘의 경제 3"
KAKAO_TEXT_LIMIT = 200
