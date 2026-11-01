"""뉴스 수집 → 점수 → 자료 찾기(1~4단계) → 한국어 요약."""
from __future__ import annotations

import re
from typing import Callable
from urllib.parse import urlparse

from . import claude, config, fetch, prompts
from .timewin import Window, label, plausibly_in_window

OUTLET_BY_DOMAIN = {d: (name, paid) for d, name, paid in config.OUTLETS}
PRIMARY_BY_DOMAIN = {d: name for d, name, *_ in config.PRIMARY_SOURCES}
MIN_FULLTEXT_CHARS = 1200      # 이보다 짧으면 '본문 전체'로 인정하지 않아요
MAX_DOC_CHARS = 30_000         # 요약 단계에 넘기는 본문 최대 길이


def domain_of(url: str) -> str:
    """URL을 설정에 있는 도메인으로 맞춰요 (www., 하위 도메인 처리)."""
    host = urlparse(url).netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    for d in config.OUTLET_DOMAINS + config.PRIMARY_DOMAINS:
        if host == d or host.endswith("." + d):
            return d
    return host


# ── 1. 후보 수집 ────────────────────────────────────────
def collect(win: Window) -> list[dict]:
    """분야별로 검색만 시키고, 후보 목록은 검색 결과에서 코드가 직접 만들어요."""
    found: dict[str, dict] = {}
    skipped_date = 0
    for group, topics in config.COLLECT_GROUPS.items():
        try:
            res = claude.call(
                f"1. 후보 수집 ({config.CATEGORY_LABELS[group]})", config.COLLECT_MODEL,
                [{"role": "user", "content": prompts.collect_prompt(
                    win.describe(), group, topics, config.COLLECT_SEARCHES_PER_GROUP)}],
                system=prompts.COLLECT_SYSTEM,
                tools=[claude.web_search_tool(config.OUTLET_DOMAINS, config.COLLECT_SEARCHES_PER_GROUP)],
                max_tokens=2000,
            )
        except claude.ClaudeError as e:
            print(f"  · {group} 검색 실패로 건너뜀 — {str(e)[:150]}")
            continue
        for key, hit in claude.search_result_urls(res["blocks"]).items():
            dom = domain_of(hit["url"])
            if dom not in OUTLET_BY_DOMAIN or key in found:
                continue
            if not plausibly_in_window(hit["page_age"], win):
                skipped_date += 1
                continue
            name, paid = OUTLET_BY_DOMAIN[dom]
            found[key] = {
                "id": f"c{len(found) + 1}", "outlet": name, "domain": dom, "paid": paid,
                "title": hit["title"], "url": hit["url"], "published": hit["page_age"], "group": group,
            }
    out = list(found.values())
    print(f"  · 후보 {len(out)}개 (날짜가 범위 밖이라 제외 {skipped_date}개)")
    return out


# ── 2. 이슈 묶기·점수 ───────────────────────────────────
SCORE_KEYS = config.SCORE_WEIGHTS


def score(win: Window, candidates: list[dict]) -> list[dict]:
    slim = [{k: c[k] for k in ("id", "outlet", "title", "published", "group")} for c in candidates]
    data, _ = claude.call_json(
        "2. 점수 매기기", config.SCORE_MODEL,
        [{"role": "user", "content": prompts.score_prompt(win.describe(), slim)}],
        system=prompts.SCORE_SYSTEM, max_tokens=8000,
    )
    by_id = {c["id"]: c for c in candidates}
    issues = []
    for it in data.get("issues", []):
        arts = [by_id[i] for i in it.get("candidate_ids", []) if i in by_id]
        if not arts or it.get("category") not in config.CATEGORIES:
            continue
        sc = it.get("scores", {})
        # 점수 범위를 강제하고 합계를 다시 계산해요
        clean = {k: max(0, min(int(sc.get(k, 0) or 0), mx)) for k, mx in SCORE_KEYS.items()}
        issues.append({
            "issue_id": it.get("issue_id") or f"i{len(issues) + 1}",
            "summary_en": it.get("summary_en", ""),
            "category": it["category"],
            "event_type": it.get("event_type", "analysis"),
            "major_release": bool(it.get("major_release")),
            "scores": clean,
            "total": sum(clean.values()),
            "articles": arts,
            "why": it.get("why", ""),
        })
    issues.sort(key=sort_key)
    print(f"  · 이슈 {len(issues)}개")
    for i in issues[:8]:
        print(f"    - {i['issue_id']} [{i['category']}] {i['total']}점, 매체 {len({a['domain'] for a in i['articles']})}곳: {i['summary_en'][:70]}")
    return issues


def sort_key(issue: dict):
    return (-issue["total"], config.EVENT_RANK.get(issue["event_type"], 3))


# ── 3. 자료 찾기 (1~4단계) ──────────────────────────────
_FETCHED: dict[str, dict] = {}


def read(url: str) -> dict:
    """같은 실행 안에서는 한 번만 읽어요."""
    key = claude.normalize_url(url)
    if key not in _FETCHED:
        _FETCHED[key] = fetch.fetch_text(url)
        print(f"      · {fetch.describe(_FETCHED[key])}")
    return _FETCHED[key]


def find_source(win: Window, issue: dict) -> dict | None:
    print(f"  · {issue['issue_id']} 자료 찾기: {issue['summary_en'][:70]}")
    try:
        src = _find_source(win, issue)
    except (claude.ClaudeError, ValueError) as e:
        print(f"    → 실패로 건너뜀 — {str(e)[:150]}")
        issue["exclude_reason"] = "자료를 찾는 중 오류가 나서 건너뜀"
        return None
    if src is None:
        issue.setdefault("exclude_reason", "무료 본문·원래 발표 자료를 찾지 못함")
    return src


def _find_source(win: Window, issue: dict) -> dict | None:
    tried: set[str] = set()

    # 1단계(바로): 이슈에 이미 있는 무료 매체 기사 (Yahoo Finance, CNBC)
    for a in issue["articles"]:
        if a["domain"] in config.FULLTEXT_FREE_DOMAINS:
            tried.add(claude.normalize_url(a["url"]))
            doc = read(a["url"])
            if len(doc["text"]) >= MIN_FULLTEXT_CHARS:
                print("    → 1단계: 무료 본문")
                return full_source(1, doc)

    # 1·2단계(검색): 같은 이슈의 무료 기사나 원래 발표 자료 찾기
    for url in search_free_sources(win, issue):
        if claude.normalize_url(url) in tried:
            continue
        tried.add(claude.normalize_url(url))
        doc = read(url)
        if len(doc["text"]) < MIN_FULLTEXT_CHARS:
            continue
        v, _ = claude.call_json(
            f"3. 같은 기사 확인 ({issue['issue_id']})", config.SOURCE_MODEL,
            [{"role": "user", "content": prompts.verify_prompt(win.describe(), issue, doc)}],
            system=prompts.CHECK_SYSTEM, max_tokens=500,
        )
        if v.get("same_story") and v.get("in_window") is not False:
            tier = 2 if domain_of(doc["url"]) in config.PRIMARY_DOMAINS else 1
            print(f"    → {tier}단계: {'원래 발표 자료' if tier == 2 else '무료 본문'}")
            return full_source(tier, doc)
        print(f"      · 다른 기사로 판단: {str(v.get('reason', ''))[:80]}")

    # 3단계: 3개 이상 매체 교차 확인
    return cross_check(win, issue)


def search_free_sources(win: Window, issue: dict) -> list[str]:
    domains = config.FULLTEXT_FREE_DOMAINS + config.PRIMARY_DOMAINS
    res = claude.call(
        f"3. 자료 검색 ({issue['issue_id']})", config.SOURCE_MODEL,
        [{"role": "user", "content": prompts.find_prompt(win.describe(), issue)}],
        system=prompts.FIND_SYSTEM,
        tools=[claude.web_search_tool(domains, config.SOURCE_MAX_SEARCHES)],
        max_tokens=1500,
    )
    hits = claude.search_result_urls(res["blocks"])
    try:
        picked = [u for u in claude.extract_json(res["text"]).get("urls", []) if isinstance(u, str)]
    except ValueError:
        picked = []
    urls = [hits[claude.normalize_url(u)]["url"] for u in picked if claude.normalize_url(u) in hits]
    if not urls:  # 모델이 고르지 못했으면 검색 결과 앞쪽 몇 개를 확인
        urls = [h["url"] for h in hits.values() if domain_of(h["url"]) in domains][:3]
    return urls[:3]


WIRE_RE = re.compile(r"\((Reuters|AP|Bloomberg|AFP)\)")


def full_source(tier: int, doc: dict) -> dict:
    dom = domain_of(doc["url"])
    if tier == 2:
        name = PRIMARY_BY_DOMAIN.get(dom, dom)
    else:
        name = OUTLET_BY_DOMAIN.get(dom, (dom, False))[0]
        m = WIRE_RE.search(doc["text"][:600])
        if dom == "finance.yahoo.com" and m:
            name = f"Yahoo Finance ({m.group(1)})"
    return {
        "tier": tier, "source_name": name,
        "document": {"url": doc["url"], "title": doc.get("title", ""), "text": doc["text"]},
        "link_url": doc["url"], "link_outlet": name.split(" (")[0], "link_paid": False,
        "tier3": None,
    }


def cross_check(win: Window, issue: dict) -> dict | None:
    by_dom: dict[str, dict] = {}
    for a in issue["articles"]:
        by_dom.setdefault(a["domain"], a)
    if len(by_dom) < config.TIER3_MIN_OUTLETS:
        print(f"    → 제외: 무료 본문 없음, 다룬 매체 {len(by_dom)}곳 (3곳 이상 필요)")
        issue["exclude_reason"] = (f"무료 본문·원래 발표 자료를 찾지 못했고, 다룬 매체가 {len(by_dom)}곳뿐이라 "
                                   f"교차 확인({config.TIER3_MIN_OUTLETS}곳 이상)도 할 수 없음")
        return None

    readings = []
    for dom, a in by_dom.items():
        doc = read(a["url"])
        text = doc["text"]
        readable = "full" if len(text) >= MIN_FULLTEXT_CHARS else "preview" if len(text) >= 200 else "headline-only"
        reason = "" if readable == "full" else (doc["reason"] or "유료벽(공개된 부분만 읽음)")
        readings.append({"outlet": a["outlet"], "url": a["url"], "title": a["title"],
                         "readable": readable, "unreadable_reason": reason, "excerpt": text[:2500]})

    data, _ = claude.call_json(
        f"3. 교차 확인 ({issue['issue_id']})", config.SOURCE_MODEL,
        [{"role": "user", "content": prompts.crosscheck_prompt(win.describe(), issue, readings)}],
        system=prompts.CHECK_SYSTEM, max_tokens=3000,
    )
    if not data.get("consistent") or data.get("conflicts"):
        conflict = str(data.get("conflicts", "")).strip()[:80]
        print(f"    → 제외: 매체 간 내용 불일치 ({conflict})")
        issue["exclude_reason"] = "무료 본문이 없고, 매체마다 내용이 달라 교차 확인 실패" + (f" ({conflict})" if conflict else "")
        return None

    points = {o.get("outlet"): o.get("key_points", "") for o in data.get("outlets", []) if isinstance(o, dict)}
    outlets = [{"outlet": r["outlet"], "url": r["url"], "readable": r["readable"],
                "unreadable_reason": r["unreadable_reason"], "key_points": points.get(r["outlet"]) or r["title"]}
               for r in readings]
    print(f"    → 3단계: {len(outlets)}개 매체 교차 확인 (특이사항)")
    return {
        "tier": 3,
        "source_name": "·".join(r["outlet"] for r in readings) + " 종합",
        "document": None,
        **pick_link(outlets),
        "tier3": {"outlets_checked": outlets, "agreed_on": data.get("agreed_on", ""),
                  "evidence_notes": data.get("evidence_notes", "")},
    }


def pick_link(outlets: list[dict]) -> dict:
    """3단계 기사 링크: 사람이 무료로 볼 수 있는 매체 우선, 없으면 유료 표시."""
    by_dom = {domain_of(o["url"]): o for o in outlets}
    for d in config.HUMAN_FREE_LINK_DOMAINS:
        if d in by_dom:
            return {"link_url": by_dom[d]["url"], "link_outlet": OUTLET_BY_DOMAIN[d][0], "link_paid": False}
    o = outlets[0]
    d = domain_of(o["url"])
    return {"link_url": o["url"], "link_outlet": OUTLET_BY_DOMAIN[d][0], "link_paid": True}


# ── 선정: 분야 균형 + 자료 단계 ─────────────────────────
def select(issues: list[dict], source_fn: Callable[[dict], dict | None]) -> list[tuple[dict, dict]]:
    attempts = 0
    tried: set[str] = set()
    chosen: list[tuple[dict, dict]] = []

    def attempt(issue):
        nonlocal attempts
        if attempts >= config.MAX_SOURCING_ATTEMPTS:
            return None
        attempts += 1
        tried.add(issue["issue_id"])
        return source_fn(issue)

    # (1) 분야별 최고점 1개씩. 지표 발표일엔 그 지표가 거시 1순위.
    for cat in config.CATEGORIES:
        pool = [i for i in issues if i["category"] == cat]
        pool.sort(key=lambda i: ((not i["major_release"]) if cat == "macro" else False, sort_key(i)))
        for issue in pool:
            if issue["total"] < config.WEAK_SCORE and not issue["major_release"]:
                break  # 약한 후보뿐 → 다른 분야 차점으로 채워요
            src = attempt(issue)
            if src:
                chosen.append((issue, src))
                break
            if attempts >= config.MAX_SOURCING_ATTEMPTS:
                break

    # (2) 빈자리는 점수 순으로 채우되 한 분야 최대 2개
    for issue in sorted((i for i in issues if i["issue_id"] not in tried), key=sort_key):
        if len(chosen) >= 3 or attempts >= config.MAX_SOURCING_ATTEMPTS:
            break
        if sum(1 for c, _ in chosen if c["category"] == issue["category"]) >= config.MAX_PER_CATEGORY:
            continue
        src = attempt(issue)
        if src:
            chosen.append((issue, src))

    chosen.sort(key=lambda p: (config.CATEGORIES.index(p[0]["category"]), sort_key(p[0])))
    return chosen[:3]


# ── 4. 한국어 요약 ─────────────────────────────────────
def write(win: Window, chosen: list[tuple[dict, dict]], failed: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    failed = sorted(failed or [], key=sort_key)
    ex_items = [{"id": f"e{n}", "summary_en": i["summary_en"],
                 "headlines": [f"[{a['outlet']}] {a['title']}" for a in i["articles"]]}
                for n, i in enumerate(failed, 1)]
    items, content = [], []
    for n, (issue, src) in enumerate(chosen, 1):
        items.append({
            "slot": n, "category": issue["category"], "tier": src["tier"],
            "summary_en": issue["summary_en"], "source_name": src["source_name"],
            "tier3": src["tier3"],
        })
        doc = src.get("document")
        if doc:
            content.append({"type": "document",
                            "source": {"type": "text", "media_type": "text/plain", "data": doc["text"][:MAX_DOC_CHARS]},
                            "title": f"기사 {n} 본문 — {src['source_name']}"})
    content.append({"type": "text", "text": prompts.write_prompt(label(win.issue_date), items, ex_items)})

    data, _ = claude.call_json(
        "4. 요약 쓰기", config.WRITE_MODEL, [{"role": "user", "content": content}],
        system=prompts.WRITE_SYSTEM, max_tokens=15000,
    )
    written = {int(a.get("slot", 0)): a for a in data.get("articles", [])}
    out = []
    for n, (issue, src) in enumerate(chosen, 1):
        w = written.get(n)
        if not w:
            print(f"  · 경고: 기사 {n} 요약이 비어 있어 건너뛰어요")
            continue
        notice = (w.get("notice") or "").strip() if src["tier"] == 3 else ""
        if src["tier"] == 3 and not notice:
            notice = default_notice(src)
        out.append({
            "slot": len(out) + 1,
            "orig_slot": len(out) + 1,
            "category": issue["category"],
            "category_label": config.CATEGORY_LABELS[issue["category"]],
            "title_ko": w.get("title_ko", "").strip(),
            "kakao_title": (w.get("kakao_title") or w.get("title_ko", "")).strip(),
            "what": w.get("what", "").strip(),
            "details": [d.strip() for d in w.get("details", []) if d and d.strip()],
            "glossary": [g for g in w.get("glossary", []) if g.get("term") and g.get("desc")],
            "korea": w.get("korea", "").strip(),
            "notice": notice,
            "tier": src["tier"],
            "source_name": src["source_name"],
            "link_url": src["link_url"],
            "link_outlet": src["link_outlet"],
            "link_paid": src["link_paid"],
            "score": issue["total"],
            "scores": issue["scores"],
        })

    ko = {e.get("id"): e for e in data.get("excluded", []) if isinstance(e, dict)}
    excluded = [{
        "category": i["category"],
        "category_label": config.CATEGORY_LABELS[i["category"]],
        "score": i["total"],
        "scores": i["scores"],
        "summary_ko": str(ko.get(ex["id"], {}).get("summary_ko", "")).strip() or i["summary_en"],
        "about_ko": str(ko.get(ex["id"], {}).get("about_ko", "")).strip(),
        "outlets": sorted({a["outlet"] for a in i["articles"]}),
        "reason": i.get("exclude_reason", ""),
    } for ex, i in zip(ex_items, failed)]
    return out, excluded


def default_notice(src: dict) -> str:
    """요약 모델이 특이사항을 빠뜨렸을 때 쓰는 기본 문구."""
    t3 = src.get("tier3") or {}
    names = [o.get("outlet", "") for o in t3.get("outlets_checked", [])]
    reasons = sorted({o.get("unreadable_reason") for o in t3.get("outlets_checked", []) if o.get("unreadable_reason")})
    return (
        f"무료로 읽을 수 있는 본문이 없어({', '.join(reasons) or '유료벽·접근 차단'}) "
        f"{'·'.join(names)} {len(names)}개 매체의 제목과 공개된 부분만으로 요약했어요. "
        f"일치한 내용: {t3.get('agreed_on', '')}. 세부 수치와 배경은 원문과 다를 수 있어요."
    )


# ── 전체 실행 ──────────────────────────────────────────
def run(win: Window) -> tuple[list[dict], list[dict]]:
    """반환: (선정 기사, 자료를 못 찾아 제외된 이슈)"""
    print(f"[수집 범위] {win.describe()}")
    print("[1/4] 후보 수집")
    candidates = collect(win)
    if not candidates:
        return [], []
    print("[2/4] 이슈 묶기·점수")
    issues = score(win, candidates)
    print("[3/4] 자료 찾기·선정")
    chosen = select(issues, lambda i: find_source(win, i))
    for issue, src in chosen:
        print(f"  · 선정: [{issue['category']}] {issue['total']}점, {src['tier']}단계 — {issue['summary_en'][:70]}")
    failed = [i for i in issues if i.get("exclude_reason")]
    if not chosen and not failed:
        return [], []
    print("[4/4] 한국어 요약")
    return write(win, chosen, failed)
