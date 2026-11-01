"""기사 본문 읽기 (코드가 직접 페이지를 받아 본문만 뽑아요).

- robots.txt에서 금지한 곳은 읽지 않아요.
- 유료벽·차단 페이지를 우회하지 않아요. 공개된 만큼만 읽어요.
- 메뉴·광고를 빼고 본문만 남겨서 Claude에게 넘기는 토큰을 줄여요.
"""
from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

try:
    import trafilatura
except ImportError:  # 테스트 환경 대비
    trafilatura = None

TIMEOUT = 20


def user_agent() -> str:
    repo = os.getenv("GITHUB_REPOSITORY", "personal")
    return f"Mozilla/5.0 (compatible; econ3-news-digest/1.0; +https://github.com/{repo})"


@lru_cache(maxsize=64)
def _robots(origin: str) -> RobotFileParser | None:
    rp = RobotFileParser()
    try:
        r = requests.get(origin + "/robots.txt", headers={"User-Agent": user_agent()}, timeout=10)
    except requests.RequestException:
        return None  # 확인 불가 → 아래에서 허용으로 처리
    if r.status_code >= 500:
        rp.parse(["User-agent: *", "Disallow: /"])
    elif r.status_code >= 400:
        rp.parse([])
    else:
        rp.parse(r.text.splitlines())
    return rp


def allowed_by_robots(url: str) -> bool:
    p = urlparse(url)
    rp = _robots(f"{p.scheme}://{p.netloc}")
    return True if rp is None else rp.can_fetch("econ3-news-digest", url)


def fetch_text(url: str) -> dict:
    """반환: {url, status, text, title, author, sitename, date, reason}

    reason: 본문을 못 읽은 이유 (robots, blocked, paywall-or-short, error) — 읽었으면 ""
    """
    out = {"url": url, "status": 0, "text": "", "title": "", "author": "", "sitename": "", "date": "", "reason": ""}
    if not allowed_by_robots(url):
        out["reason"] = "robots.txt로 자동 접근 금지"
        return out
    try:
        r = requests.get(url, headers={"User-Agent": user_agent(), "Accept-Language": "en-US,en;q=0.9"},
                         timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as e:
        out["reason"] = f"접속 오류 ({type(e).__name__})"
        return out
    out["status"], out["url"] = r.status_code, r.url
    if r.status_code in (401, 402, 403, 451):
        out["reason"] = "자동 접근 차단 또는 유료벽"
        return out
    if r.status_code != 200:
        out["reason"] = f"HTTP {r.status_code}"
        return out
    html = r.text
    if trafilatura is None:
        out["reason"] = "본문 추출 도구 없음"
        return out
    text = trafilatura.extract(html, url=r.url, include_comments=False, include_tables=False,
                               favor_recall=True) or ""
    meta = trafilatura.extract_metadata(html, default_url=r.url)
    if meta:
        out.update({"title": meta.title or "", "author": meta.author or "",
                    "sitename": meta.sitename or "", "date": meta.date or ""})
    out["text"] = text.strip()
    return out


def describe(doc: dict) -> str:
    """로그용 한 줄."""
    host = urlparse(doc["url"]).netloc
    if doc["text"]:
        return f"{host} 본문 {len(doc['text']):,}자"
    return f"{host} 읽기 실패 ({doc['reason'] or doc['status']})"
