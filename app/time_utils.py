from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


def local_now(tz_name):
    return datetime.now(ZoneInfo(tz_name))


def local_day_bounds(day, tz_name):
    zone = ZoneInfo(tz_name)
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    end_day = day.fromordinal(day.toordinal() + 1)
    end_local = datetime.combine(end_day, time.min, tzinfo=zone)
    return (start_local.astimezone(timezone.utc).replace(tzinfo=None),
            end_local.astimezone(timezone.utc).replace(tzinfo=None))


def local_date_start(day, tz_name):
    return local_day_bounds(day, tz_name)[0]
