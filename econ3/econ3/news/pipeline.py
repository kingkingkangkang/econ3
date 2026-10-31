"""뉴스 수집 → 점수 → 자료 찾기(1~4단계) → 한국어 요약."""
from __future__ import annotations

from typing import Callable
from urllib.parse import urlparse

from . import claude, config, prompts
from .timewin import Window, label

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
    data, blocks = claude.call_json(
        "1. 후보 수집", config.COLLECT_MODEL,
        [{"role": "user", "content": prompts.collect_prompt(win.describe())}],
        system=prompts.COLLECT_SYSTEM,
        tools=[claude.web_search_tool(config.OUTLET_DOMAINS, config.COLLECT_MAX_SEARCHES)],
        max_tokens=8000,
    )
    seen = claude.search_result_urls(blocks)
    out, dropped = [], 0
    for c in data.get("candidates", []):
        url = c.get("url", "")
        hit = seen.get(claude.normalize_url(url))
        dom = domain_of(url)
        if not hit or dom not in OUTLET_BY_DOMAIN:
            dropped += 1          # 검색 결과에 없던 URL은 버려요 (지어낸 URL 방지)
            continue
        name, paid = OUTLET_BY_DOMAIN[dom]
        out.append({
            "id": c.get("id") or f"c{len(out) + 1}",
            "outlet": name, "domain": dom, "paid": paid,
            "title": c.get("title") or hit["title"],
            "url": hit["url"],
            "published": c.get("published") or hit["page_age"],
            "category": c.get("category", ""),
            "facts": c.get("facts", ""),
        })
    print(f"  · 후보 {len(out)}개 (검증 실패로 제외 {dropped}개)")
    return out


# ── 2. 이슈 묶기·점수 ───────────────────────────────────
SCORE_KEYS = {"impact": 30, "korea": 25, "novelty": 20, "followup": 15, "explainability": 10}


def score(win: Window, candidates: list[dict]) -> list[dict]:
    slim = [{k: c[k] for k in ("id", "outlet", "title", "published", "category", "facts")} for c in candidates]
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
    return issues


def sort_key(issue: dict):
    return (-issue["total"], config.EVENT_RANK.get(issue["event_type"], 3))


# ── 3. 자료 찾기 (1~4단계) ──────────────────────────────
def find_source(win: Window, issue: dict) -> dict | None:
    domains = config.OUTLET_DOMAINS + config.PRIMARY_DOMAINS
    data, blocks = claude.call_json(
        f"3. 자료 찾기 ({issue['issue_id']})", config.SOURCE_MODEL,
        [{"role": "user", "content": prompts.source_prompt(win.describe(), issue, issue["articles"])}],
        system=prompts.SOURCE_SYSTEM,
        tools=[
            claude.web_search_tool(domains, config.SOURCE_MAX_SEARCHES),
            claude.web_fetch_tool(domains, config.SOURCE_MAX_FETCHES),
        ],
        max_tokens=4000,
    )
    return validate_source(issue, data, blocks)


def validate_source(issue: dict, data: dict, blocks: list[dict]) -> dict | None:
    """모델이 말한 단계를 실제로 읽은 기록과 대조해요. 근거가 없으면 단계를 낮추거나 제외."""
    docs = claude.fetched_documents(blocks)
    seen = claude.search_result_urls(blocks)
    known = {claude.normalize_url(a["url"]) for a in issue["articles"]} | set(seen) | set(docs)
    tier = int(data.get("tier", 4) or 4)
    read_url = data.get("read_url") or ""

    if tier in (1, 2):
        allowed = config.FULLTEXT_FREE_DOMAINS if tier == 1 else config.PRIMARY_DOMAINS
        doc = docs.get(claude.normalize_url(read_url))
        if not doc:
            # 리다이렉트 등으로 주소가 달라진 경우: 해당 종류의 문서가 딱 하나면 그걸로 인정
            same_kind = [d for d in docs.values() if domain_of(d["url"]) in allowed]
            if len(same_kind) == 1:
                doc = same_kind[0]
        dom = domain_of(doc["url"]) if doc else domain_of(read_url)
        ok_domain = dom in allowed
        long_enough = doc and (doc["source_type"] == "base64" or len(doc["data"]) >= MIN_FULLTEXT_CHARS)
        if doc and ok_domain and long_enough:
            return {
                "tier": tier,
                "source_name": data.get("source_name") or (
                    "Yahoo Finance" if tier == 1 else PRIMARY_BY_DOMAIN.get(dom, dom)),
                "document": doc,
                "link_url": doc["url"], "link_outlet": data.get("source_name") or dom,
                "link_paid": False,
                "tier3": None,
            }
        print(f"  · {issue['issue_id']}: {tier}단계 주장했지만 본문 기록이 없어 3단계 조건을 확인해요")
        tier = 3

    if tier == 3:
        outlets = [o for o in data.get("outlets_checked", [])
                   if o.get("key_points") and claude.normalize_url(o.get("url", "")) in known
                   and domain_of(o.get("url", "")) in OUTLET_BY_DOMAIN]
        distinct = {domain_of(o["url"]) for o in outlets}
        cons = data.get("consistency") or {}
        if len(distinct) >= config.TIER3_MIN_OUTLETS and cons.get("consistent") and not cons.get("conflicts"):
            link = pick_link(outlets)
            return {
                "tier": 3,
                "source_name": data.get("source_name") or "·".join(
                    OUTLET_BY_DOMAIN[d][0] for d in sorted(distinct)) + " 종합",
                "document": None,
                **link,
                "tier3": {
                    "outlets_checked": outlets,
                    "agreed_on": cons.get("agreed_on", ""),
                    "evidence_notes": data.get("evidence_notes", ""),
                },
            }
        print(f"  · {issue['issue_id']}: 3단계 조건 미달 (매체 {len(distinct)}곳, 일치 {cons.get('consistent')}) → 제외")
        return None

    print(f"  · {issue['issue_id']}: 제외 — {data.get('exclude_reason', '')[:80]}")
    return None


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
def write(win: Window, chosen: list[tuple[dict, dict]]) -> list[dict]:
    items, content = [], []
    for n, (issue, src) in enumerate(chosen, 1):
        items.append({
            "slot": n, "category": issue["category"], "tier": src["tier"],
            "summary_en": issue["summary_en"], "source_name": src["source_name"],
            "tier3": src["tier3"],
        })
        doc = src.get("document")
        if doc:
            if doc["source_type"] == "base64":
                source = {"type": "base64", "media_type": doc["media_type"], "data": doc["data"]}
            else:
                source = {"type": "text", "media_type": "text/plain", "data": doc["data"][:MAX_DOC_CHARS]}
            content.append({"type": "document", "source": source,
                            "title": f"기사 {n} 본문 — {src['source_name']}"})
    content.append({"type": "text", "text": prompts.write_prompt(label(win.issue_date), items)})

    data, _ = claude.call_json(
        "4. 요약 쓰기", config.WRITE_MODEL, [{"role": "user", "content": content}],
        system=prompts.WRITE_SYSTEM, max_tokens=8000,
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
        })
    return out


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
def run(win: Window) -> list[dict]:
    print(f"[수집 범위] {win.describe()}")
    print("[1/4] 후보 수집")
    candidates = collect(win)
    if not candidates:
        return []
    print("[2/4] 이슈 묶기·점수")
    issues = score(win, candidates)
    print("[3/4] 자료 찾기·선정")
    chosen = select(issues, lambda i: find_source(win, i))
    for issue, src in chosen:
        print(f"  · 선정: [{issue['category']}] {issue['total']}점, {src['tier']}단계 — {issue['summary_en'][:70]}")
    if not chosen:
        return []
    print("[4/4] 한국어 요약")
    return write(win, chosen)
