from datetime import datetime, timedelta
import pytz


def now(tz_name: str = "Asia/Shanghai") -> datetime:
    tz = pytz.timezone(tz_name)
    return datetime.now(tz)


def yesterday(tz_name: str = "Asia/Shanghai") -> datetime:
    return now(tz_name) - timedelta(days=1)


def format_date(dt: datetime, fmt: str = "%Y-%m-%d") -> str:
    return dt.strftime(fmt)
