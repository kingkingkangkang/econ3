"""가짜 API 응답으로 전체 흐름(수집→점수→자료→요약→페이지→카톡 본문)을 점검."""
import json
from datetime import date

from news import claude, config, kakao, pipeline, render
from news.timewin import window_for

U = {
    "wsj": "https://www.wsj.com/economy/fed-holds",
    "rtr": "https://www.reuters.com/markets/fed-holds",
    "cnbc": "https://www.cnbc.com/2026/10/30/fed-holds.html",
    "yahoo": "https://finance.yahoo.com/news/fed-holds-rates-123.html",
    "oil": "https://www.bloomberg.com/news/oil-jumps",
    "nvda": "https://www.reuters.com/technology/nvidia-results",
    "nvda_y": "https://finance.yahoo.com/news/nvidia-results-456.html",
}


def text(s):
    return {"type": "text", "text": s}


def resp(content, stop="end_turn", searches=0):
    return {"content": content, "stop_reason": stop,
            "usage": {"input_tokens": 1000, "output_tokens": 200,
                      "server_tool_use": {"web_search_requests": searches}}}


def search_block(*urls):
    return {"type": "web_search_tool_result", "tool_use_id": "s",
            "content": [{"type": "web_search_result", "url": u, "title": "t", "page_age": "Oct 30, 2026"} for u in urls]}


def fetch_block(url, body):
    return {"type": "web_fetch_tool_result", "tool_use_id": "f", "content": {
        "type": "web_fetch_result", "url": url, "retrieved_at": "x",
        "content": {"type": "document", "title": "t", "source": {"type": "text", "media_type": "text/plain", "data": body}}}}


def fake_post_factory():
    calls = {"n": 0}
    candidates = {"candidates": [
        {"id": "c1", "outlet": "WSJ", "domain": "wsj.com", "title": "Fed holds rates", "url": U["wsj"], "category": "macro", "facts": "held at 3.75-4%"},
        {"id": "c2", "outlet": "Reuters", "domain": "reuters.com", "title": "Fed keeps rates steady", "url": U["rtr"], "category": "macro", "facts": ""},
        {"id": "c3", "outlet": "CNBC", "domain": "cnbc.com", "title": "Fed holds", "url": U["cnbc"], "category": "macro", "facts": ""},
        {"id": "c4", "outlet": "Bloomberg", "domain": "bloomberg.com", "title": "Oil jumps 4%", "url": U["oil"], "category": "market", "facts": ""},
        {"id": "c5", "outlet": "Reuters", "domain": "reuters.com", "title": "Nvidia results beat", "url": U["nvda"], "category": "corporate", "facts": ""},
        {"id": "c6", "outlet": "WSJ", "domain": "wsj.com", "title": "Invented", "url": "https://www.wsj.com/made-up", "category": "macro", "facts": ""},
    ]}
    issues = {"issues": [
        {"issue_id": "i1", "summary_en": "Fed holds rates", "category": "macro", "event_type": "decision", "major_release": True,
         "scores": {"impact": 28, "korea": 20, "novelty": 18, "followup": 12, "explainability": 9}, "candidate_ids": ["c1", "c2", "c3"]},
        {"issue_id": "i2", "summary_en": "Oil jumps", "category": "market", "event_type": "decision", "major_release": False,
         "scores": {"impact": 20, "korea": 15, "novelty": 15, "followup": 8, "explainability": 9}, "candidate_ids": ["c4"]},
        {"issue_id": "i3", "summary_en": "Nvidia beats", "category": "corporate", "event_type": "decision", "major_release": False,
         "scores": {"impact": 22, "korea": 22, "novelty": 18, "followup": 10, "explainability": 9}, "candidate_ids": ["c5"]},
    ]}

    def fake_post(payload, beta=None):
        calls["n"] += 1
        prompt = json.dumps(payload["messages"][0]["content"], ensure_ascii=False)
        if "Collect candidate" in prompt:
            if len(payload["messages"]) == 1:   # 첫 응답은 pause_turn
                return resp([search_block(U["wsj"], U["rtr"])], stop="pause_turn", searches=1)
            return resp([search_block(U["cnbc"], U["oil"], U["nvda"]),
                         text("```json\n" + json.dumps(candidates) + "\n```")], searches=1)
        if "Group candidates" in prompt:
            return resp([text("```json\n" + json.dumps(issues) + "\n```")])
        if "Story: Fed holds" in prompt:      # 1단계 성공 (Yahoo 본문)
            return resp([search_block(U["yahoo"]), fetch_block(U["yahoo"], "Fed body " * 400),
                         text(json.dumps({"tier": 1, "read_url": U["yahoo"], "source_name": "Yahoo Finance (Reuters)"}))])
        if "Story: Oil jumps" in prompt:      # 매체 1곳뿐 → 제외
            return resp([text(json.dumps({"tier": 4, "exclude_reason": "only one outlet"}))])
        if "Story: Nvidia" in prompt:         # 3단계: 3개 매체 일치
            urls = [U["nvda"], "https://www.wsj.com/tech/nvidia", "https://www.cnbc.com/nvidia"]
            data = {"tier": 3, "source_name": "Reuters·WSJ·CNBC 종합",
                    "outlets_checked": [{"outlet": n, "url": u, "readable": "preview", "unreadable_reason": "paywall",
                                         "key_points": "revenue beat"} for n, u in zip(["Reuters", "WSJ", "CNBC"], urls)],
                    "consistency": {"consistent": True, "agreed_on": "매출 예상 상회", "conflicts": ""}}
            return resp([search_block(*urls[1:]), text("```json\n" + json.dumps(data) + "\n```")])
        if "요약해 주세요" in json.dumps(payload["messages"][0]["content"][-1], ensure_ascii=False):
            arts = {"articles": [
                {"slot": 1, "title_ko": "연준, 기준금리 동결", "kakao_title": "연준 금리 동결", "what": "동결했어요.",
                 "details": ["a", "b"], "glossary": [], "korea": "환율 영향", "notice": ""},
                {"slot": 2, "title_ko": "엔비디아 실적 예상 상회", "kakao_title": "엔비디아 실적 호조", "what": "좋았어요.",
                 "details": ["c"], "glossary": [], "korea": "SK하이닉스", "notice": ""},   # 특이사항 누락 → 기본 문구
            ]}
            return resp([text(json.dumps(arts, ensure_ascii=False))])
        raise AssertionError("예상 못 한 호출: " + prompt[:200])

    return fake_post, calls


def test_full_pipeline(tmp_path, monkeypatch):
    fake_post, calls = fake_post_factory()
    monkeypatch.setattr(claude, "_post", fake_post)
    monkeypatch.setattr(config, "DOCS_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "soo/econ3")
    win = window_for(date(2026, 11, 2))
    articles = pipeline.run(win)

    assert [a["title_ko"] for a in articles] == ["연준, 기준금리 동결", "엔비디아 실적 예상 상회"]
    assert articles[0]["tier"] == 1 and articles[0]["link_url"] == U["yahoo"]
    assert articles[1]["tier"] == 3 and articles[1]["link_outlet"] == "CNBC"
    assert "세부 수치와 배경은 원문과 다를 수 있어요" in articles[1]["notice"]   # 기본 특이사항 문구

    render.render_day(win, articles)
    text_ = kakao.compose("11/2(월)", articles)
    assert len(text_) <= 200 and "기사가 2개" in text_ and "특이사항 1건" in text_
    assert claude.USAGE.totals()["searches"] >= 2
