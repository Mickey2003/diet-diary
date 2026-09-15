"""时间工具：统一使用本地时区（默认 Asia/Shanghai）的“朴素”时间存储与计算。"""
from datetime import date, datetime, timedelta
from typing import Optional, Tuple

from .. import config

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    _TZ = ZoneInfo(config.TIMEZONE)
except Exception:  # noqa: BLE001  缺少 tzdata 时退回系统本地时间
    _TZ = None


def now_local() -> datetime:
    if _TZ is None:
        return datetime.now()
    return datetime.now(_TZ).replace(tzinfo=None)


def today_local() -> date:
    return now_local().date()


def to_local_naive(dt: datetime) -> datetime:
    """带时区的 datetime → 本地时区的朴素时间。"""
    if dt.tzinfo is None:
        return dt
    if _TZ is None:
        return dt.astimezone().replace(tzinfo=None)
    return dt.astimezone(_TZ).replace(tzinfo=None)


def week_bounds(d: date) -> Tuple[date, date]:
    """周一为一周开始；返回 [start, end] 闭区间日期。"""
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def month_bounds(d: date) -> Tuple[date, date]:
    start = d.replace(day=1)
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1)
    else:
        nxt = start.replace(month=start.month + 1)
    return start, nxt - timedelta(days=1)


def resolve_preset(preset: str, start: Optional[str] = None, end: Optional[str] = None,
                   today: Optional[date] = None) -> Tuple[Optional[date], Optional[date], str]:
    """把预设时间范围解析成 (start_date, end_date, 中文标签)。all 返回 (None, None)。"""
    t = today or today_local()
    if preset == "today":
        return t, t, "今天"
    if preset == "yesterday":
        y = t - timedelta(days=1)
        return y, y, "昨天"
    if preset == "this_week":
        s, e = week_bounds(t)
        return s, e, "本周"
    if preset == "last_week":
        s, e = week_bounds(t - timedelta(days=7))
        return s, e, "上周"
    if preset == "last_7d":
        return t - timedelta(days=6), t, "最近 7 天"
    if preset == "last_30d":
        return t - timedelta(days=29), t, "最近 30 天"
    if preset == "this_month":
        s, e = month_bounds(t)
        return s, e, "本月"
    if preset == "last_month":
        s, e = month_bounds(month_bounds(t)[0] - timedelta(days=1))
        return s, e, "上月"
    if preset == "custom" and start:
        s = date.fromisoformat(start)
        e = date.fromisoformat(end) if end else s
        if e < s:
            s, e = e, s
        return s, e, f"{s.isoformat()} 至 {e.isoformat()}"
    return None, None, "全部时间"


def day_range(s: Optional[date], e: Optional[date]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """闭区间日期 → 半开区间 datetime [start 00:00, end+1 00:00)。"""
    if s is None or e is None:
        return None, None
    return datetime.combine(s, datetime.min.time()), datetime.combine(e + timedelta(days=1), datetime.min.time())
