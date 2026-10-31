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
