"""API 없이 돌아가는 기본 테스트: python -m pytest -q"""
import json
from datetime import date, datetime

import pytest

from news import claude, config, kakao, pipeline, render
from news.timewin import KST, label, window_for


# ── 시간 범위 ──
def test_monday_window_covers_weekend():
    w = window_for(date(2026, 11, 2))  # 월
    assert w.start == datetime(2026, 10, 30, 8, 0, tzinfo=KST)  # 금 08:00
    assert w.hours == 72


def test_tuesday_window_24h():
    w = window_for(date(2026, 11, 3))  # 화
    assert w.start == datetime(2026, 11, 2, 8, 0, tzinfo=KST)
    assert w.hours == 24


def test_label():
    assert label(date(2026, 11, 2)) == "11/2(월)"


# ── 카톡 본문 ──
def art(title, notice=""):
    return {"kakao_title": title, "title_ko": title, "notice": notice}


def test_compose_fits_200():
    long = "아주 긴 제목 " * 20
    text = kakao.compose("11/2(월)", [art(long), art(long, "x"), art(long)])
    assert len(text) <= 200
    assert text.startswith("[11/2(월) 오늘의 경제 3]")
    assert "특이사항 1건" in text


def test_compose_short_titles_untouched():
    text = kakao.compose("11/2(월)", [art("연준 금리 동결"), art("유가 급등"), art("엔비디아 실적")])
    assert "① 연준 금리 동결" in text and "③ 엔비디아 실적" in text


def test_compose_empty():
    assert "없어요" in kakao.compose("11/2(월)", [])


# ── 선정 규칙 ──
def issue(iid, cat, total, event="decision", major=False):
    return {"issue_id": iid, "category": cat, "total": total, "event_type": event,
            "major_release": major, "summary_en": iid, "articles": []}


def ok(_):
    return {"tier": 1}


def test_select_one_per_category():
    issues = [issue("m1", "macro", 90), issue("m2", "macro", 85), issue("k1", "market", 70), issue("c1", "corporate", 60)]
    picked = [i["issue_id"] for i, _ in pipeline.select(issues, ok)]
    assert picked == ["m1", "k1", "c1"]


def test_weak_category_filled_by_other_max_two():
    issues = [issue("m1", "macro", 90), issue("m2", "macro", 85), issue("m3", "macro", 80),
              issue("k1", "market", 40), issue("c1", "corporate", 70)]
    picked = [i["issue_id"] for i, _ in pipeline.select(issues, ok)]
    assert picked == ["m1", "m2", "c1"]  # 시장은 약해서 빠지고, 거시 최대 2개


def test_major_release_first_in_macro():
    issues = [issue("m1", "macro", 90), issue("cpi", "macro", 70, major=True),
              issue("k1", "market", 70), issue("c1", "corporate", 60)]
    picked = [i["issue_id"] for i, _ in pipeline.select(issues, ok)]
    assert picked[0] == "cpi"


def test_tie_break_decision_first():
    issues = [issue("talk", "macro", 80, "statement"), issue("rel", "macro", 80, "decision"),
              issue("k1", "market", 70), issue("c1", "corporate", 60)]
    picked = [i["issue_id"] for i, _ in pipeline.select(issues, ok)]
    assert picked[0] == "rel"


def test_unsourceable_skipped():
    issues = [issue("m1", "macro", 90), issue("m2", "macro", 85), issue("k1", "market", 70), issue("c1", "corporate", 60)]
    fn = lambda i: None if i["issue_id"] == "m1" else {"tier": 1}
    picked = [i["issue_id"] for i, _ in pipeline.select(issues, fn)]
    assert picked == ["m2", "k1", "c1"]


# ── 자료 단계 검증 ──
def fetch_block(url, text):
    return {"type": "web_fetch_tool_result", "content": {
        "type": "web_fetch_result", "url": url,
        "content": {"type": "document", "title": "t", "source": {"type": "text", "media_type": "text/plain", "data": text}}}}


def search_block(*urls):
    return {"type": "web_search_tool_result", "content": [
        {"type": "web_search_result", "url": u, "title": "t", "page_age": ""} for u in urls]}


Y = "https://finance.yahoo.com/news/abc.html"


def test_tier1_needs_real_fetch():
    iss = issue("m1", "macro", 90)
    data = {"tier": 1, "read_url": Y, "source_name": "Yahoo Finance (Reuters)"}
    assert pipeline.validate_source(iss, data, []) is None              # 읽은 기록 없음 → 제외
    src = pipeline.validate_source(iss, data, [fetch_block(Y, "x" * 3000)])
    assert src["tier"] == 1 and src["link_url"] == Y and not src["link_paid"]


def test_tier1_too_short_rejected():
    iss = issue("m1", "macro", 90)
    data = {"tier": 1, "read_url": Y}
    assert pipeline.validate_source(iss, data, [fetch_block(Y, "short")]) is None


def tier3_data(urls, consistent=True):
    return {"tier": 3, "outlets_checked": [
        {"outlet": "o", "url": u, "readable": "preview", "unreadable_reason": "paywall", "key_points": "Fed holds"}
        for u in urls], "consistency": {"consistent": consistent, "agreed_on": "동결", "conflicts": ""}}


def test_tier3_three_outlets_prefers_free_link():
    urls = ["https://www.wsj.com/a", "https://www.bloomberg.com/b", "https://www.cnbc.com/c"]
    src = pipeline.validate_source(issue("m1", "macro", 90), tier3_data(urls), [search_block(*urls)])
    assert src["tier"] == 3 and src["link_outlet"] == "CNBC" and not src["link_paid"]


def test_tier3_paid_link_when_no_free():
    urls = ["https://www.wsj.com/a", "https://www.bloomberg.com/b", "https://www.ft.com/c"]
    src = pipeline.validate_source(issue("m1", "macro", 90), tier3_data(urls), [search_block(*urls)])
    assert src["link_paid"] is True


def test_tier3_two_outlets_excluded():
    urls = ["https://www.wsj.com/a", "https://www.bloomberg.com/b"]
    assert pipeline.validate_source(issue("m1", "macro", 90), tier3_data(urls), [search_block(*urls)]) is None


def test_tier3_conflict_excluded():
    urls = ["https://www.wsj.com/a", "https://www.bloomberg.com/b", "https://www.cnbc.com/c"]
    assert pipeline.validate_source(issue("m1", "macro", 90), tier3_data(urls, False), [search_block(*urls)]) is None


def test_tier3_invented_url_not_counted():
    urls = ["https://www.wsj.com/a", "https://www.bloomberg.com/b", "https://www.cnbc.com/c"]
    src = pipeline.validate_source(issue("m1", "macro", 90), tier3_data(urls), [search_block(*urls[:2])])
    assert src is None  # 세 번째 URL은 어디서도 나온 적 없음


# ── JSON·비용·도메인 ──
def test_extract_json_from_fence():
    assert claude.extract_json('blah\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}


def test_cost_estimate_haiku_long_tier():
    short = claude.estimate_cost({"model": "claude-haiku-5-5", "input": 50_000, "output": 1000,
                                  "cache_read": 0, "cache_write": 0, "searches": 2})
    long = claude.estimate_cost({"model": "claude-haiku-5-5", "input": 150_000, "output": 1000,
                                 "cache_read": 0, "cache_write": 0, "searches": 0})
    assert short == pytest.approx(0.005 + 0.0005 + 0.02)
    assert long == pytest.approx(0.075 + 0.0025)


def test_domain_of():
    assert pipeline.domain_of("https://www.reuters.com/x") == "reuters.com"
    assert pipeline.domain_of("https://finance.yahoo.com/news/x") == "finance.yahoo.com"
    assert pipeline.domain_of("https://edition.cnn.com/x") == "cnn.com"


# ── 렌더링 ──
def test_render(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOCS_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "soo/econ3")
    a = {"slot": 1, "category": "macro", "category_label": "거시·정책", "title_ko": "제목", "kakao_title": "제목",
         "what": "무슨 일", "details": ["세부1"], "glossary": [{"term": "FOMC", "desc": "설명"}],
         "korea": "한국 영향", "notice": "특이 이유", "tier": 3, "source_name": "WSJ·Bloomberg·CNBC 종합",
         "link_url": "https://www.cnbc.com/c", "link_outlet": "CNBC", "link_paid": False, "score": 80}
    path = render.render_day(window_for(date(2026, 11, 2)), [a])
    html = path.read_text(encoding="utf-8")
    assert "특이사항" in html and "한국엔?" in html and "용어 풀이" in html
    assert (tmp_path / "index.html").exists()
    assert json.loads((tmp_path / "data" / "2026-11-02.json").read_text())["articles"][0]["title_ko"] == "제목"
    assert render.page_url(date(2026, 11, 2)) == "https://soo.github.io/econ3/2026-11-02.html"
