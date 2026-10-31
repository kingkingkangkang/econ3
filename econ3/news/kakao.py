"""카카오톡 '나에게 보내기'.

필요한 GitHub Secrets
- KAKAO_REST_API_KEY   : [앱] > [플랫폼 키] > [REST API 키]
- KAKAO_CLIENT_SECRET  : 같은 화면의 [클라이언트 시크릿] 코드 (꺼 두었다면 비워도 돼요)
- KAKAO_REDIRECT_URI   : 같은 화면에 등록한 리다이렉트 URI (최초 연결 때만 사용)
- KAKAO_REFRESH_TOKEN  : 「카카오 연결 (최초 1회)」 실행 시 자동 저장
- GH_PAT               : 리프레시 토큰이 갱신될 때 Secret을 자동으로 바꾸기 위한 토큰
"""
from __future__ import annotations

import json
import os
import subprocess

import requests

from . import config

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
CIRCLED = "①②③④⑤"

HINTS = {
    "KOE006": "리다이렉트 URI가 카카오 앱에 등록한 값과 달라요. KAKAO_REDIRECT_URI를 확인하세요.",
    "KOE010": "클라이언트 시크릿이 틀렸어요. KAKAO_CLIENT_SECRET을 확인하세요.",
    "KOE320": "인증 코드가 만료됐거나 이미 사용됐어요. 카카오 로그인부터 다시 해서 새 코드를 받아주세요.",
    "KOE322": "리프레시 토큰이 만료됐어요. 「카카오 연결 (최초 1회)」을 다시 실행하세요.",
    "KOE237": "토큰 요청이 너무 많아요. 잠시 후 다시 시도하세요.",
    "-402": "카카오톡 메시지 전송 동의가 없어요. 동의항목 설정 후 카카오 연결을 다시 하세요.",
}


class KakaoError(RuntimeError):
    pass


def _mask(value: str) -> None:
    if value and os.getenv("GITHUB_ACTIONS"):
        print(f"::add-mask::{value}")


def _raise(resp: requests.Response, what: str):
    body = resp.text[:400]
    hint = next((h for code, h in HINTS.items() if code in body), "")
    raise KakaoError(f"{what} 실패 ({resp.status_code}): {body}\n{hint}")


def _base_params() -> dict:
    key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    if not key:
        raise KakaoError("KAKAO_REST_API_KEY가 없어요.")
    p = {"client_id": key}
    secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
    if secret:
        p["client_secret"] = secret
    return p


def save_secret(name: str, value: str) -> bool:
    """GitHub Secret 갱신 (GH_PAT 필요)."""
    pat = os.environ.get("GH_PAT", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not pat or not repo:
        print(f"  · 경고: GH_PAT이 없어 {name}을(를) 자동 저장하지 못했어요.")
        summary(f"[주의] {name} 자동 저장 실패 — GH_PAT Secret을 등록하세요. 약 2개월 뒤 카카오 연결이 끊길 수 있어요.")
        return False
    r = subprocess.run(["gh", "secret", "set", name, "--repo", repo],
                       input=value, text=True, capture_output=True,
                       env={**os.environ, "GH_TOKEN": pat})
    if r.returncode != 0:
        print(f"  · 경고: {name} 저장 실패: {r.stderr.strip()[:200]}")
        summary(f"[주의] {name} 자동 저장 실패 — GH_PAT 권한(Secrets: Read and write)을 확인하세요.")
        return False
    print(f"  · {name} 저장 완료")
    return True


def access_token() -> str:
    refresh = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if not refresh:
        raise KakaoError("KAKAO_REFRESH_TOKEN이 없어요. 「카카오 연결 (최초 1회)」을 먼저 실행하세요.")
    r = requests.post(TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": refresh, **_base_params()},
                      timeout=30)
    if r.status_code != 200:
        _raise(r, "카카오 토큰 갱신")
    data = r.json()
    _mask(data["access_token"])
    new_refresh = data.get("refresh_token")
    if new_refresh:  # 만료 1개월 미만일 때만 새로 발급돼요
        _mask(new_refresh)
        print("  · 카카오 리프레시 토큰이 새로 발급돼 저장해요")
        save_secret("KAKAO_REFRESH_TOKEN", new_refresh)
    return data["access_token"]


def send_text(token: str, text: str, url: str, button: str = "자세히 보기") -> None:
    if len(text) > config.KAKAO_TEXT_LIMIT:
        raise KakaoError(f"메시지가 {len(text)}자예요 (최대 {config.KAKAO_TEXT_LIMIT}자).")
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": url, "mobile_web_url": url},
        "button_title": button,
    }
    r = requests.post(MEMO_URL, headers={"Authorization": f"Bearer {token}"},
                      data={"template_object": json.dumps(template, ensure_ascii=False)}, timeout=30)
    if r.status_code != 200 or r.json().get("result_code") != 0:
        _raise(r, "카카오톡 발송")


def compose(label: str, articles: list[dict]) -> str:
    """200자 안에 들어가는 카톡 본문. 넘치면 제목을 줄여요."""
    head = f"[{label} 오늘의 경제 3]"
    notices = sum(1 for a in articles if a.get("notice"))
    tail = []
    if not articles:
        tail.append("오늘은 선정 기준을 통과한 기사가 없어요.")
    elif len(articles) < 3:
        tail.append(f"오늘은 기사가 {len(articles)}개예요.")
    if notices:
        tail.append(f"※ 특이사항 {notices}건 (이유는 페이지에)")
    titles = [a.get("kakao_title") or a.get("title_ko", "") for a in articles]

    for limit in (60, 40, 30, 24, 20, 16, 12):
        lines = [head] + [f"{CIRCLED[i]} {_cut(t, limit)}" for i, t in enumerate(titles)] + tail
        text = "\n".join(lines)
        if len(text) <= config.KAKAO_TEXT_LIMIT:
            return text
    return text[: config.KAKAO_TEXT_LIMIT]


def _cut(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def setup(code: str, home_url: str) -> None:
    """최초 1회: 인증 코드 → 토큰 발급 → Secret 저장 → 테스트 메시지."""
    redirect = os.environ.get("KAKAO_REDIRECT_URI", "").strip()
    if not redirect:
        raise KakaoError("KAKAO_REDIRECT_URI가 없어요.")
    r = requests.post(TOKEN_URL, data={"grant_type": "authorization_code", "redirect_uri": redirect,
                                       "code": code.strip(), **_base_params()}, timeout=30)
    if r.status_code != 200:
        _raise(r, "카카오 토큰 발급")
    data = r.json()
    _mask(data["access_token"])
    _mask(data["refresh_token"])
    if "talk_message" not in (data.get("scope") or ""):
        print("  · 경고: 토큰에 talk_message 권한이 없어요. 동의항목 설정과 로그인 주소의 scope를 확인하세요.")
    if not save_secret("KAKAO_REFRESH_TOKEN", data["refresh_token"]):
        raise KakaoError("리프레시 토큰을 저장하지 못했어요. GH_PAT Secret을 먼저 등록하세요.")
    send_text(data["access_token"],
              "카카오 연결 완료! 평일 아침 8시에 「오늘의 경제 3」을 보내드릴게요.", home_url, "페이지 열기")
    print("  · 테스트 메시지를 보냈어요")


def summary(text: str) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n\n")
