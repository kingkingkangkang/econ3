"""GitHub Pages용 모바일 웹페이지 만들기 (docs/ 폴더).

폴더 구조
  docs/index.html                     월 목록 (첫 화면, 카카오 인증 코드 표시)
  docs/2026-11/index.html             그 달의 날짜 목록 (편집·삭제)
  docs/2026-11/2026-11-02.html        날짜별 뉴스 페이지
  docs/trash.html                     휴지통 (15일 보관, 복구)
  docs/data/2026-11/2026-11-02.json   날짜별 기록 (페이지는 이 기록으로 다시 만들 수 있어요)
  docs/data/trash.json                휴지통 기록
"""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config
from .timewin import KST, WEEKDAYS_KO, Window, label, window_for

TEMPLATES = Path(__file__).parent / "templates"
env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))

DAY_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")
MONTH_DIR_RE = re.compile(r"^\d{4}-\d{2}$")
TRASH_DAYS = 15


# ── 경로 ────────────────────────────────────────────────
def docs_dir() -> Path:
    d = Path(config.DOCS_DIR)
    (d / "data").mkdir(parents=True, exist_ok=True)
    (d / ".nojekyll").touch()
    return d


def month_of(dt: date) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def data_path(dt: date) -> Path:
    return docs_dir() / "data" / month_of(dt) / f"{dt.isoformat()}.json"


def page_path(dt: date) -> Path:
    return docs_dir() / month_of(dt) / f"{dt.isoformat()}.html"


def pages_base_url() -> str:
    """https://<아이디>.github.io/<저장소>/ (환경변수 PAGES_BASE_URL로 바꿀 수 있어요)."""
    if os.getenv("PAGES_BASE_URL"):
        return os.environ["PAGES_BASE_URL"].rstrip("/") + "/"
    repo = os.getenv("GITHUB_REPOSITORY", "owner/repo")
    owner, name = repo.split("/", 1)
    if name.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner.lower()}.github.io/"
    return f"https://{owner.lower()}.github.io/{name}/"


def page_url(issue_date: date) -> str:
    return pages_base_url() + f"{month_of(issue_date)}/{issue_date.isoformat()}.html"


def _now() -> datetime:
    return datetime.now(KST)


def _common() -> dict:
    return {"site_title": config.SITE_TITLE, "repo": os.getenv("GITHUB_REPOSITORY", "")}


# ── 날짜 페이지 ──────────────────────────────────────────
def render_day(win: Window, articles: list[dict], excluded: list[dict] | None = None,
               rebuild: bool = True) -> Path:
    excluded = excluded or []
    s, e = win.start, win.end
    range_text = (f"{s.month}/{s.day}({WEEKDAYS_KO[s.weekday()]}) {s:%H:%M} ~ "
                  f"{e.month}/{e.day}({WEEKDAYS_KO[e.weekday()]}) {e:%H:%M} 한국시간")
    dt = win.issue_date
    html = env.get_template("day.html").render(
        **_common(),
        label=label(dt),
        month=month_of(dt),
        date_long=f"{dt.month}월 {dt.day}일 {WEEKDAYS_KO[dt.weekday()]}요일",
        range_text=range_text,
        articles=articles,
        excluded=excluded,
        score_labels=config.SCORE_LABELS,
        score_weights=config.SCORE_WEIGHTS,
        outlet_count=len(config.OUTLETS),
        outlet_names='·'.join(name for _, name, _ in config.OUTLETS),
    )
    path = page_path(dt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    dpath = data_path(dt)
    dpath.parent.mkdir(parents=True, exist_ok=True)
    data = {"date": dt.isoformat(), "label": label(dt), "window": win.describe(),
            "articles": articles, "excluded": excluded}
    dpath.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if rebuild:
        rebuild_archive()
    return path


def load_day(dt: date) -> dict | None:
    p = data_path(dt)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def iter_days() -> list[tuple[date, dict]]:
    """저장된 날짜 기록 (최신순)."""
    out = []
    for f in (docs_dir() / "data").glob("*/*.json"):
        m = DAY_FILE_RE.match(f.name)
        if not m:
            continue
        try:
            out.append((date.fromisoformat(m.group(1)), json.loads(f.read_text(encoding="utf-8"))))
        except (ValueError, json.JSONDecodeError):
            continue
    return sorted(out, key=lambda x: x[0], reverse=True)


# ── 목록 페이지 (월 목록, 월별 날짜 목록, 휴지통) ──────────────
def rebuild_archive() -> Path:
    d = docs_dir()
    trash = purge_trash()
    days = iter_days()
    months: dict[str, list] = {}
    for dt, data in days:
        months.setdefault(month_of(dt), []).append({
            "date": dt.isoformat(), "label": label(dt),
            "arts": [{"slot": a["slot"], "title": a["title_ko"]} for a in data.get("articles", [])],
        })

    for m, items in months.items():
        (d / m).mkdir(exist_ok=True)
        y, mo = m.split("-")
        (d / m / "index.html").write_text(env.get_template("month.html").render(
            **_common(), month=m, month_title=f"{int(y)}년 {int(mo)}월", issues=items,
            trash_count=len(trash)), encoding="utf-8")
    # 날짜가 모두 지워진 달의 목록 페이지는 없애요
    for sub in d.iterdir():
        if sub.is_dir() and MONTH_DIR_RE.match(sub.name) and sub.name not in months:
            (sub / "index.html").unlink(missing_ok=True)

    month_cards = [{
        "month": m, "title": f"{int(m[:4])}년 {int(m[5:])}월", "count": len(items),
        "latest": items[0]["label"], "titles": [a["title"] for a in items[0]["arts"]][:3],
    } for m, items in sorted(months.items(), reverse=True)]
    (d / "trash.html").write_text(env.get_template("trash.html").render(
        **_common(), groups=trash_groups(trash), keep_days=TRASH_DAYS), encoding="utf-8")
    path = d / "index.html"
    path.write_text(env.get_template("index.html").render(
        **_common(), months=month_cards, trash_count=len(trash)), encoding="utf-8")
    return path


def rebuild_index() -> Path:  # 예전 이름 호환
    return rebuild_archive()


def migrate_legacy() -> int:
    """예전 구조(docs/data/날짜.json, docs/날짜.html)를 월별 폴더로 옮기고, 예전 주소는 새 주소로 이동시켜요."""
    d = docs_dir()
    n = 0
    for f in sorted((d / "data").glob("*.json")):
        m = DAY_FILE_RE.match(f.name)
        if not m:
            continue
        dt = date.fromisoformat(m.group(1))
        target = data_path(dt)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            f.unlink()
        else:
            f.rename(target)
        old_html = d / f"{dt.isoformat()}.html"
        new_rel = f"./{month_of(dt)}/{dt.isoformat()}.html"
        old_html.write_text(
            f'<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex">'
            f'<meta http-equiv="refresh" content="0; url={new_rel}">'
            f'<p><a href="{new_rel}">새 주소로 이동</a></p>', encoding="utf-8")
        n += 1
    return n


def rebuild_all() -> int:
    """기록으로 모든 날짜 페이지와 목록을 다시 만들어요 (디자인·구조를 바꿨을 때)."""
    migrate_legacy()
    n = 0
    for dt, data in iter_days():
        render_day(window_for(dt), data.get("articles", []), data.get("excluded", []), rebuild=False)
        n += 1
    rebuild_archive()
    return n


# ── 휴지통 ──────────────────────────────────────────────
def trash_path() -> Path:
    return docs_dir() / "data" / "trash.json"


def load_trash() -> list[dict]:
    p = trash_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def save_trash(entries: list[dict]) -> None:
    trash_path().write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")


def purge_trash(now: datetime | None = None) -> list[dict]:
    """보관 기간(15일)이 지난 항목을 영구 삭제하고 남은 목록(최근 삭제 순)을 돌려줘요."""
    now = now or _now()
    entries = load_trash()
    keep = [e for e in entries if datetime.fromisoformat(e["expires_at"]) > now]
    if len(keep) != len(entries) or trash_path().exists():
        save_trash(keep)
    return sorted(keep, key=lambda e: e["deleted_at"], reverse=True)


def _trash_entry(dt: date, now: datetime, article: dict | None, whole: bool, excluded: list | None) -> dict:
    """휴지통 항목은 기사 하나 단위로 저장하고, 화면에서는 날짜별 한 칸으로 묶어 보여줘요."""
    return {
        "id": f"{dt:%Y%m%d}-{secrets.token_hex(3)}",
        "date": dt.isoformat(), "label": label(dt),
        "deleted_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(days=TRASH_DAYS)).isoformat(timespec="seconds"),
        "article": article,          # None이면 '선정 기사 없던 날' 전체를 지운 것
        "whole": whole,              # 하루 전체를 지울 때 함께 들어온 항목인지
        "excluded": excluded,        # 하루 전체를 지운 경우, 그날의 '제외' 목록 (복구할 때 되살려요)
    }


def orig_slot(a: dict) -> int:
    """처음 발행됐을 때의 번호 (지우고 복구해도 원래 순서를 지키기 위해)."""
    return int(a.get("orig_slot") or a.get("slot") or 99)


def trash_groups(entries: list[dict]) -> list[dict]:
    """휴지통 화면용: 날짜별 한 칸, 그 안에 지운 기사들 (원래 번호 순)."""
    groups: dict[str, dict] = {}
    for e in entries:
        g = groups.setdefault(e["date"], {"date": e["date"], "label": e["label"], "lines": [], "whole": False})
        g["whole"] = g["whole"] or bool(e.get("whole"))
        art = e.get("article")
        g["lines"].append({
            "id": e["id"], "expires_at": e["expires_at"], "deleted_at": e["deleted_at"],
            "num": orig_slot(art) if art else None,
            "title": art["title_ko"] if art else "(선정 기사 없던 날)",
        })
    for g in groups.values():
        g["lines"].sort(key=lambda x: (x["num"] is None, x["num"] or 0))
        g["first_expiry"] = min(x["expires_at"] for x in g["lines"])
    return sorted(groups.values(), key=lambda g: g["date"], reverse=True)


# ── 지우기·복구 (「뉴스 지우기·복구」 워크플로에서 실행) ──────────
_TARGET_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:#(\d{1,2}))?$")
_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,48}$")


def parse_targets(text: str) -> dict:
    """'2026-11-01, 2026-11-02#2' → {date: {None} 또는 {2, 3}}. 형식이 틀리면 ValueError."""
    out: dict = {}
    for t in [x.strip() for x in text.split(",") if x.strip()]:
        m = _TARGET_RE.match(t)
        if not m:
            raise ValueError(f"형식이 잘못됐어요: {t!r} (예: 2026-11-01 또는 2026-11-01#2)")
        out.setdefault(date.fromisoformat(m.group(1)), set()).add(int(m.group(2)) if m.group(2) else None)
    return out


def parse_ids(text: str) -> list[str]:
    ids = [x.strip() for x in text.split(",") if x.strip()]
    for i in ids:
        if not _ID_RE.match(i):
            raise ValueError(f"휴지통 항목 번호 형식이 잘못됐어요: {i!r}")
    return ids


def delete_items(targets: dict, now: datetime | None = None) -> list[str]:
    """날짜 전체 또는 일부 기사를 휴지통으로 옮겨요. 반환: 처리 내역."""
    now = now or _now()
    trash = load_trash()
    done = []
    for dt, slots in sorted(targets.items()):
        data = load_day(dt)
        if data is None:
            done.append(f"{dt}: 기록이 없어 건너뜀")
            continue
        arts = data.get("articles", [])
        for a in arts:
            a.setdefault("orig_slot", a.get("slot"))
        if None in slots:
            excluded = data.get("excluded", [])
            for a in arts:
                trash.append(_trash_entry(dt, now, a, True, excluded))
            if not arts:
                trash.append(_trash_entry(dt, now, None, True, excluded))
            data_path(dt).unlink()
            page_path(dt).unlink(missing_ok=True)
            done.append(f"{dt}: 하루 전체를 휴지통으로")
            continue
        for a in arts:
            if a.get("slot") in slots:
                trash.append(_trash_entry(dt, now, a, False, None))
        keep = [a for a in arts if a.get("slot") not in slots]
        for n, a in enumerate(keep, 1):
            a["slot"] = n
        render_day(window_for(dt), keep, data.get("excluded", []), rebuild=False)
        done.append(f"{dt}: 기사 {len(arts) - len(keep)}개를 휴지통으로")
    save_trash(trash)
    rebuild_archive()
    return done


def purge_items(ids: list[str]) -> list[str]:
    """휴지통 항목을 15일을 기다리지 않고 바로 영구 삭제해요."""
    trash = load_trash()
    want = set(ids)
    keep = [e for e in trash if e["id"] not in want]
    found = {e["id"] for e in trash} & want
    save_trash(keep)
    rebuild_archive()
    return [f"{i}: 영구 삭제" for i in ids if i in found] + [f"{i}: 휴지통에 없음" for i in ids if i not in found]


def restore_items(ids: list[str]) -> list[str]:
    """휴지통 항목을 원래 날짜의 원래 순서로 되돌려요."""
    trash = load_trash()
    want = set(ids)
    picked = [e for e in trash if e["id"] in want]
    done = [f"{i}: 휴지통에 없음 (이미 복구됐거나 보관 기간이 지났어요)"
            for i in ids if i not in {e["id"] for e in picked}]
    by_date: dict[str, list[dict]] = {}
    for e in picked:
        by_date.setdefault(e["date"], []).append(e)
    for d, entries in sorted(by_date.items()):
        dt = date.fromisoformat(d)
        cur = load_day(dt)
        arts = list((cur or {}).get("articles", []))
        have = {a["title_ko"] for a in arts}
        restored = [e["article"] for e in entries if e.get("article") and e["article"]["title_ko"] not in have]
        arts = sorted(arts + restored, key=orig_slot)
        for n, a in enumerate(arts, 1):
            a.setdefault("orig_slot", a.get("slot"))
            a["slot"] = n
        if cur is not None:
            excluded = cur.get("excluded", [])
        else:
            excluded = next((e["excluded"] for e in entries if e.get("excluded")), [])
        render_day(window_for(dt), arts, excluded, rebuild=False)
        done.append(f"{d}: 기사 {len(restored)}개 복구" if restored else f"{d}: 날짜 복구")
    save_trash([e for e in trash if e["id"] not in want])
    rebuild_archive()
    return done
