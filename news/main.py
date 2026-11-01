"""실행 진입점.

python -m news.main build [--date 2026-11-02]   뉴스 만들기 + 웹페이지 생성
python -m news.main wait-pages                  GitHub Pages 반영 기다리기
python -m news.main send [--no-wait]            카톡 발송 (08:00 전이면 기다렸다가)
python -m news.main notify-failure              실패 알림 카톡
python -m news.main kakao-setup --code CODE     카카오 최초 연결
python -m news.main delete --targets 2026-11-01#2   지난 뉴스를 휴지통으로 (날짜 전체 또는 #번호)
python -m news.main restore --targets <휴지통 번호>  휴지통에서 복구
python -m news.main purge --targets <휴지통 번호>    휴지통에서 바로 영구 삭제
python -m news.main rebuild                     저장된 기록으로 모든 페이지 다시 만들기
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

from . import claude, config, kakao, pipeline, render
from .timewin import KST, label, today_issue_date, window_for

STATE = Path(".state")


def cmd_build(args) -> None:
    issue_date = date.fromisoformat(args.date) if args.date else today_issue_date()
    win = window_for(issue_date)
    articles, excluded = pipeline.run(win)
    path = render.render_day(win, articles, excluded, rebuild=False)
    render.rebuild_all()   # 월 목록·휴지통 정리, 예전 구조 옮기기까지 함께
    url = render.page_url(issue_date)
    text = kakao.compose(label(issue_date), articles)

    STATE.mkdir(exist_ok=True)
    (STATE / "today.json").write_text(json.dumps(
        {"date": issue_date.isoformat(), "url": url, "text": text}, ensure_ascii=False, indent=1), encoding="utf-8")
    (STATE / "usage.json").write_text(json.dumps(
        {"calls": claude.USAGE.calls, "totals": claude.USAGE.totals()}, ensure_ascii=False, indent=1), encoding="utf-8")

    t = claude.USAGE.totals()
    print(f"\n[완료] {path} · 기사 {len(articles)}개, 제외 {len(excluded)}개")
    print(f"[카톡 미리보기]\n{text}\n({len(text)}자)")
    print(f"[사용량] 토큰 {t['input'] + t['cache_read'] + t['cache_write']:,} 입력 / {t['output']:,} 출력, "
          f"검색 {t['searches']}회, 예상 비용 ${t['cost']:.4f}")
    kakao.summary(f"## {label(issue_date)} 오늘의 경제 3\n\n페이지: {url}\n\n"
                  f"```\n{text}\n```\n\n### 토큰 사용량\n\n{claude.USAGE.markdown()}")


def cmd_wait_pages(args) -> None:
    state = json.loads((STATE / "today.json").read_text(encoding="utf-8"))
    url = state["url"]
    deadline = time.time() + 6 * 60
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=15, headers={"Cache-Control": "no-cache"})
            if r.status_code == 200:
                print(f"  · 페이지 반영 확인: {url}")
                return
        except requests.RequestException:
            pass
        time.sleep(15)
    print(f"  · 경고: 6분 안에 페이지가 확인되지 않았어요. 그래도 발송해요: {url}")


def cmd_send(args) -> None:
    state = json.loads((STATE / "today.json").read_text(encoding="utf-8"))
    token = kakao.access_token()
    if not args.no_wait:
        wait_until_send_time()
    kakao.send_text(token, state["text"], state["url"])
    print("  · 카톡 발송 완료")


def wait_until_send_time() -> None:
    now = datetime.now(KST)
    target = now.replace(hour=config.SEND_HOUR, minute=config.SEND_MINUTE, second=0, microsecond=0)
    wait = (target - now).total_seconds()
    if 0 < wait <= config.MAX_WAIT_MINUTES * 60:
        print(f"  · {target:%H:%M}까지 {int(wait // 60)}분 {int(wait % 60)}초 기다려요")
        time.sleep(wait)


def cmd_notify_failure(args) -> None:
    token = kakao.access_token()
    kakao.send_text(token, f"[{label(today_issue_date())} 오늘의 경제 3]\n오늘 뉴스를 만들지 못했어요. "
                           "GitHub 저장소의 Actions 탭에서 오류 기록을 확인해 주세요.",
                    render.pages_base_url(), "페이지 열기")


def cmd_rebuild(args) -> None:
    print(f"  · 페이지 {render.rebuild_all()}개를 다시 만들었어요")


def cmd_delete(args) -> None:
    render.migrate_legacy()
    for line in render.delete_items(render.parse_targets(args.targets)):
        print(f"  · {line}")


def cmd_purge(args) -> None:
    for line in render.purge_items(render.parse_ids(args.targets)):
        print(f"  · {line}")


def cmd_restore(args) -> None:
    render.migrate_legacy()
    for line in render.restore_items(render.parse_ids(args.targets)):
        print(f"  · {line}")


def cmd_kakao_setup(args) -> None:
    kakao.setup(args.code, render.pages_base_url())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="news")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--date", default="")
    sub.add_parser("wait-pages")
    s = sub.add_parser("send")
    s.add_argument("--no-wait", action="store_true")
    sub.add_parser("notify-failure")
    sub.add_parser("rebuild")
    dl = sub.add_parser("delete")
    dl.add_argument("--targets", required=True)
    rs = sub.add_parser("restore")
    rs.add_argument("--targets", required=True)
    pg = sub.add_parser("purge")
    pg.add_argument("--targets", required=True)
    k = sub.add_parser("kakao-setup")
    k.add_argument("--code", required=True)
    args = p.parse_args(argv)
    {
        "build": cmd_build, "wait-pages": cmd_wait_pages, "send": cmd_send,
        "notify-failure": cmd_notify_failure, "kakao-setup": cmd_kakao_setup, "delete": cmd_delete, "restore": cmd_restore,
        "purge": cmd_purge,
        "rebuild": cmd_rebuild,
    }[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
