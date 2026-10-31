"""GitHub Pages용 모바일 웹페이지 만들기 (docs/ 폴더)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config
from .timewin import WEEKDAYS_KO, Window, label

TEMPLATES = Path(__file__).parent / "templates"
env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


def docs_dir() -> Path:
    d = Path(config.DOCS_DIR)
    (d / "data").mkdir(parents=True, exist_ok=True)
    (d / ".nojekyll").touch()
    return d


def pages_base_url() -> str:
    """https://<아이디>.github.io/<저장소>/ (환경변수 PAGES_BASE_URL로 바꿀 수 있어요)."""
    if os.getenv("PAGES_BASE_URL"):
        return os.environ["PAGES_BASE_URL"].rstrip("/") + "/"
    repo = os.getenv("GITHUB_REPOSITORY", "owner/repo")
    owner, name = repo.split("/", 1)
    if name.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner.lower()}.github.io/"
    return f"https://{owner.lower()}.github.io/{name}/"


def page_url(issue_date) -> str:
    return pages_base_url() + f"{issue_date.isoformat()}.html"


def render_day(win: Window, articles: list[dict]) -> Path:
    d = docs_dir()
    s, e = win.start, win.end
    range_text = (f"{s.month}/{s.day}({WEEKDAYS_KO[s.weekday()]}) {s:%H:%M} ~ "
                  f"{e.month}/{e.day}({WEEKDAYS_KO[e.weekday()]}) {e:%H:%M} 한국시간")
    dt = win.issue_date
    html = env.get_template("day.html").render(
        site_title=config.SITE_TITLE,
        label=label(dt),
        date_long=f"{dt.month}월 {dt.day}일 {WEEKDAYS_KO[dt.weekday()]}요일",
        range_text=range_text,
        articles=articles,
    )
    path = d / f"{dt.isoformat()}.html"
    path.write_text(html, encoding="utf-8")
    data = {"date": dt.isoformat(), "label": label(dt), "window": win.describe(), "articles": articles}
    (d / "data" / f"{dt.isoformat()}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    rebuild_index()
    return path


def rebuild_index() -> Path:
    d = docs_dir()
    issues = []
    for f in sorted((d / "data").glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        issues.append({
            "date": data["date"], "label": data["label"],
            "titles": [a["title_ko"] for a in data.get("articles", [])],
        })
    html = env.get_template("index.html").render(site_title=config.SITE_TITLE, issues=issues)
    path = d / "index.html"
    path.write_text(html, encoding="utf-8")
    return path
