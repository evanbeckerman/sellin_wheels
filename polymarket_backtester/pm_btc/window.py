from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


@dataclass(frozen=True)
class Window:
    """Complete local calendar days, with UTC timestamps for source requests."""

    end_date: date  # exclusive, in the requested timezone
    days: int = 30
    timezone_name: str = "Etc/GMT+8"  # fixed UTC-08:00, the user's client timezone

    def __post_init__(self):
        if self.days < 1 or self.days > 366:
            raise ValueError("days must be between 1 and 366")
        tz = ZoneInfo(self.timezone_name)
        start = datetime.combine(self.start_date, time(), tz)
        end = datetime.combine(self.end_date, time(), tz)
        if end > datetime.now(tz):
            raise ValueError("The window must end at a completed calendar-day boundary")
        if int(start.timestamp()) % 900 or int(end.timestamp()) % 900:
            raise ValueError("Timezone boundaries must align with 15-minute market intervals")

    @property
    def start_date(self):
        return self.end_date - timedelta(days=self.days)

    @property
    def start_ts(self):
        return int(datetime.combine(self.start_date, time(), ZoneInfo(self.timezone_name)).timestamp())

    @property
    def end_ts(self):
        return int(datetime.combine(self.end_date, time(), ZoneInfo(self.timezone_name)).timestamp())

    @property
    def slots(self):
        return list(range(self.start_ts, self.end_ts, 900))

    @property
    def key(self):
        return f"{self.start_date}_{self.end_date}_{self.timezone_name.replace('/', '-')}"

    def split(self, timestamp):
        day = datetime.fromtimestamp(timestamp, ZoneInfo(self.timezone_name)).date()
        # Full requested run: first 20 days development, last 10 days held out.
        # Short diagnostic runs never claim a valid 20/10 split.
        if self.days != 30:
            return "diagnostic_only"
        return "development" if day < self.start_date + timedelta(days=20) else "validation"
