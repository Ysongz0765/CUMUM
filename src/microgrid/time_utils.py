from datetime import date, datetime, time, timedelta
import re
import pandas as pd

def parse_time_label(value) -> tuple[int, int, int]:
    """Parse Excel time labels; 0:00+1 means next-day midnight."""
    s = str(value).strip()
    plus = "+1" in s
    s = s.replace("+1", "")
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if not m: raise ValueError(f"非法时间标签: {value!r}")
    h, minute = map(int, m.groups())
    if h == 24: h, plus = 0, True
    if not (0 <= h < 24 and 0 <= minute < 60): raise ValueError(value)
    return h, minute, int(plus)

def canonical_grid(day: str | date | datetime) -> pd.DataFrame:
    d = pd.Timestamp(day).normalize()
    starts = [d + pd.Timedelta(minutes=10*i) for i in range(144)]
    return pd.DataFrame({"slot": range(1,145), "interval_start": starts,
        "interval_end": [x + pd.Timedelta(minutes=10) for x in starts],
        "timestamp_end": [x + pd.Timedelta(minutes=10) for x in starts],
        "time_label": [f"{x.hour}:{x.minute:02d}" for x in starts]})

def parse_excel_time(value) -> tuple[int,int,int]:
    if isinstance(value, time): return value.hour, value.minute, 0
    return parse_time_label(value)

def power_to_energy(power_kw): return power_kw / 6.0

def interval_label(start: pd.Timestamp, day: pd.Timestamp) -> str:
    """Format a 10-minute interval, preserving the next-day suffix."""
    end = start + pd.Timedelta(minutes=10)
    suffix = "+1" if end.normalize() > day.normalize() else ""
    return f"{start.hour}:{start.minute:02d}-{end.hour}:{end.minute:02d}{suffix}"
