"""Claude Messages API 호출 (requests로 직접 호출, SDK 버전 문제 없음).

- 서버 도구(web_search / web_fetch)의 pause_turn 이어 받기
- 토큰 사용량·비용 기록
- 응답에서 검색 결과 URL, 읽은 본문(web_fetch) 추출
- 응답 텍스트에서 JSON 꺼내기
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

import requests

from . import config

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
WEB_FETCH_BETA = "web-fetch-2025-09-10"  # 일부 계정·버전에서만 필요 (자동 재시도)


class ClaudeError(RuntimeError):
    pass


# ── 도구 정의 ───────────────────────────────────────────
def web_search_tool(allowed_domains: list[str], max_uses: int) -> dict:
    return {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": max_uses,
        "allowed_domains": allowed_domains,
    }


def web_fetch_tool(allowed_domains: list[str], max_uses: int) -> dict:
    return {
        "type": "web_fetch_20250910",
        "name": "web_fetch",
        "max_uses": max_uses,
        "allowed_domains": allowed_domains,
        "max_content_tokens": config.FETCH_MAX_CONTENT_TOKENS,
    }


# ── 사용량 기록 ─────────────────────────────────────────
@dataclass
class UsageLog:
    calls: list[dict] = field(default_factory=list)

    def add(self, stage: str, model: str, usage: dict) -> None:
        u = usage or {}
        rec = {
            "stage": stage,
            "model": model,
            "input": u.get("input_tokens", 0),
            "output": u.get("output_tokens", 0),
            "cache_read": u.get("cache_read_input_tokens", 0) or 0,
            "cache_write": u.get("cache_creation_input_tokens", 0) or 0,
            "searches": (u.get("server_tool_use") or {}).get("web_search_requests", 0) or 0,
            "fetches": (u.get("server_tool_use") or {}).get("web_fetch_requests", 0) or 0,
        }
        rec["cost"] = estimate_cost(rec)
        self.calls.append(rec)

    def totals(self) -> dict:
        keys = ["input", "output", "cache_read", "cache_write", "searches", "fetches", "cost"]
        return {k: sum(c[k] for c in self.calls) for k in keys}

    def markdown(self) -> str:
        t = self.totals()
        lines = [
            "| 단계 | 모델 | 입력 | 출력 | 검색 | 읽기 | 비용(USD) |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for c in self.calls:
            lines.append(
                f"| {c['stage']} | {c['model']} | {c['input'] + c['cache_read'] + c['cache_write']:,} "
                f"| {c['output']:,} | {c['searches']} | {c['fetches']} | {c['cost']:.4f} |"
            )
        lines.append(
            f"| **합계** | | **{t['input'] + t['cache_read'] + t['cache_write']:,}** | **{t['output']:,}** "
            f"| **{t['searches']}** | **{t['fetches']}** | **{t['cost']:.4f}** |"
        )
        return "\n".join(lines)


def estimate_cost(rec: dict) -> float:
    p = config.PRICES.get(rec["model"])
    if not p:
        return 0.0
    prompt = rec["input"] + rec["cache_read"] + rec["cache_write"]
    long = "long_threshold" in p and prompt > p["long_threshold"]
    pre = "long_" if long else ""
    cost = (
        rec["input"] * p[pre + "in"]
        + rec["output"] * p[pre + "out"]
        + rec["cache_read"] * p[pre + "cache_read"]
        + rec["cache_write"] * p[pre + "cache_write"]
    ) / 1_000_000
    cost += rec["searches"] * config.WEB_SEARCH_PRICE
    return round(cost, 6)


USAGE = UsageLog()


# ── API 호출 ────────────────────────────────────────────
def _post(payload: dict, beta: str | None = None) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ClaudeError("ANTHROPIC_API_KEY가 설정되지 않았어요.")
    headers = {
        "x-api-key": key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    if beta:
        headers["anthropic-beta"] = beta
    delay = 5
    for attempt in range(6):
        r = requests.post(API_URL, headers=headers, json=payload, timeout=600)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504, 529) and attempt < 5:
            wait = int(r.headers.get("retry-after", delay))
            print(f"  · API {r.status_code}, {wait}초 후 재시도")
            time.sleep(wait)
            delay = min(delay * 2, 60)
            continue
        raise ClaudeError(f"API 오류 {r.status_code}: {r.text[:500]}")
    raise ClaudeError("API 재시도 횟수 초과")


def call(stage: str, model: str, messages: list, *, system: str | None = None,
         tools: list | None = None, max_tokens: int = 8000) -> dict:
    """도구 사용 포함 호출. pause_turn이면 이어서 호출하고, 모든 응답 블록을 합쳐 돌려줘요.

    반환: {"text": 마지막 텍스트, "blocks": 전체 응답 블록 목록}
    """
    msgs = list(messages)
    all_blocks: list[dict] = []
    beta = None
    uses_fetch = any(t.get("name") == "web_fetch" for t in (tools or []))
    for _ in range(config.MAX_PAUSE_CONTINUATIONS + 1):
        payload = {"model": model, "max_tokens": max_tokens, "messages": msgs}
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = tools
        try:
            resp = _post(payload, beta)
        except ClaudeError as e:
            # 구버전 계정에서 web_fetch 베타 헤더가 필요한 경우 한 번 더 시도
            if uses_fetch and beta is None and "400" in str(e) and "fetch" in str(e).lower():
                beta = WEB_FETCH_BETA
                resp = _post(payload, beta)
            else:
                raise
        USAGE.add(stage, model, resp.get("usage", {}))
        content = resp.get("content", [])
        all_blocks.extend(content)
        if resp.get("stop_reason") == "pause_turn":
            msgs = msgs + [{"role": "assistant", "content": content}]
            continue
        if resp.get("stop_reason") == "max_tokens":
            print(f"  · 경고: {stage} 응답이 max_tokens에서 잘렸어요")
        break
    text = "\n".join(b.get("text", "") for b in all_blocks if b.get("type") == "text")
    return {"text": text, "blocks": all_blocks}


# ── 응답 블록에서 정보 꺼내기 ──────────────────────────────
def search_result_urls(blocks: list[dict]) -> dict[str, dict]:
    """web_search 결과로 실제 나온 URL → {title, page_age}"""
    out: dict[str, dict] = {}
    for b in blocks:
        if b.get("type") != "web_search_tool_result":
            continue
        content = b.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if item.get("type") == "web_search_result" and item.get("url"):
                out[normalize_url(item["url"])] = {
                    "url": item["url"],
                    "title": item.get("title", ""),
                    "page_age": item.get("page_age", ""),
                }
    return out


def fetched_documents(blocks: list[dict]) -> dict[str, dict]:
    """web_fetch로 실제 읽은 본문 → {url, title, media_type, data}"""
    out: dict[str, dict] = {}
    for b in blocks:
        if b.get("type") != "web_fetch_tool_result":
            continue
        c = b.get("content") or {}
        if c.get("type") != "web_fetch_result":
            continue
        doc = c.get("content") or {}
        src = doc.get("source") or {}
        data = src.get("data")
        if not data:
            continue
        url = c.get("url", "")
        out[normalize_url(url)] = {
            "url": url,
            "title": doc.get("title", ""),
            "media_type": src.get("media_type", "text/plain"),
            "source_type": src.get("type", "text"),
            "data": data,
        }
    return out


def fetch_errors(blocks: list[dict]) -> list[str]:
    errs = []
    for b in blocks:
        if b.get("type") == "web_fetch_tool_result":
            c = b.get("content") or {}
            if c.get("type") == "web_fetch_tool_result_error":
                errs.append(c.get("error_code", "unknown"))
    return errs


def normalize_url(url: str) -> str:
    u = url.strip()
    u = re.sub(r"#.*$", "", u)
    u = re.sub(r"\?(utm_[^&]*&?)+$", "", u)
    return u.rstrip("/").lower()


# ── JSON 꺼내기 ────────────────────────────────────────
def extract_json(text: str):
    """응답 텍스트에서 마지막 JSON 덩어리를 파싱."""
    fences = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    candidates = list(reversed(fences)) + [text]
    for cand in candidates:
        cand = cand.strip()
        for opener, closer in (("{", "}"), ("[", "]")):
            s, e = cand.find(opener), cand.rfind(closer)
            if s != -1 and e > s:
                try:
                    return json.loads(cand[s:e + 1])
                except json.JSONDecodeError:
                    continue
    raise ValueError("JSON을 찾지 못했어요:\n" + text[:800])


def call_json(stage: str, model: str, messages: list, **kw):
    """JSON 응답을 기대하는 호출. 파싱 실패 시 한 번 더 요청."""
    res = call(stage, model, messages, **kw)
    try:
        return extract_json(res["text"]), res["blocks"]
    except ValueError:
        retry_msgs = list(messages) + [
            {"role": "assistant", "content": [{"type": "text", "text": res["text"] or "(no text)"}]},
            {"role": "user", "content": "Return ONLY the final JSON in a ```json code block, nothing else."},
        ]
        res2 = call(stage + " (재요청)", model, retry_msgs, system=kw.get("system"), max_tokens=kw.get("max_tokens", 8000))
        return extract_json(res2["text"]), res["blocks"] + res2["blocks"]
