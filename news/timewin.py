"""발송 날짜와 기사 수집 시간 범위 계산.

평일(월~금) 08:00 발송 기준:
- 화~금: 전날 08:00 ~ 당일 08:00 (24시간)
- 월:   금요일 08:00 ~ 월요일 08:00 (금요일 미국 장, 주말 뉴스 포함)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import config

KST = ZoneInfo(config.TIMEZONE)
ET = ZoneInfo("America/New_York")
WEEKDAYS_KO = "월화수목금토일"


@dataclass
class Window:
    issue_date: date      # 발송(호) 날짜
    start: datetime       # KST
    end: datetime         # KST

    @property
    def hours(self) -> int:
        return int((self.end - self.start).total_seconds() // 3600)

    def describe(self) -> str:
        """프롬프트에 넣을 설명 (한국시간 + 뉴욕시간)."""
        def fmt(dt: datetime) -> str:
            return dt.strftime("%Y-%m-%d %H:%M (%a)")
        return (
            f"{fmt(self.start)} KST to {fmt(self.end)} KST "
            f"= {fmt(self.start.astimezone(ET))} ET to {fmt(self.end.astimezone(ET))} ET "
            f"({self.hours} hours)"
        )


def previous_send_day(d: date) -> date:
    """d 직전 발송일(평일). 월요일이면 금요일."""
    p = d - timedelta(days=1)
    while p.weekday() >= 5:  # 토(5)·일(6) 건너뜀
        p -= timedelta(days=1)
    return p


def window_for(issue_date: date) -> Window:
    send_t = time(config.SEND_HOUR, config.SEND_MINUTE)
    end = datetime.combine(issue_date, send_t, KST)
    start = datetime.combine(previous_send_day(issue_date), send_t, KST)
    return Window(issue_date, start, end)


def today_issue_date(now: datetime | None = None) -> date:
    """지금(KST) 기준 이번 호 날짜. 08:00 전 실행(예: 07:40)이어도 오늘 날짜."""
    now = (now or datetime.now(KST)).astimezone(KST)
    return now.date()


def label(d: date) -> str:
    """예: 11/2(월)"""
    return f"{d.month}/{d.day}({WEEKDAYS_KO[d.weekday()]})"


# ── 검색 결과 날짜(page_age) 해석 ─────────────────────────
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_page_age(text: str, now: datetime | None = None) -> date | None:
    """'October 30, 2026', 'Oct 30, 2026', '2026-10-30', '3 days ago', '5 hours ago' 등을 날짜로. 모르면 None."""
    import re
    if not text:
        return None
    s = text.strip().lower()
    now = (now or datetime.now(KST)).astimezone(ET)
    m = re.match(r"(\d+)\s+(minute|hour|day|week)s?\s+ago", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n),
                 "day": timedelta(days=n), "week": timedelta(weeks=n)}[unit]
        return (now - delta).date()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1) in _MONTHS:
        return date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
    return None


def plausibly_in_window(page_age: str, win: "Window") -> bool:
    """날짜를 모르면 통과. 알면 수집 범위 앞뒤 하루 여유를 두고 판단 (최종 판단은 점수 단계에서)."""
    d = parse_page_age(page_age, win.end)
    if d is None:
        return True
    return (win.start.astimezone(ET).date() - timedelta(days=1)) <= d <= win.end.astimezone(ET).date() + timedelta(days=1)
