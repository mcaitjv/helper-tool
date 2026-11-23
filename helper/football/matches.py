"""Match dates and formatting. Everything the user sees is in their local time."""
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from tzlocal import get_localzone_name

from helper.football.client import FootballError

MAX_ROWS = 40
NOT_STARTED = {"SCHEDULED", "TIMED"}
IN_PROGRESS = {"IN_PLAY", "PAUSED", "EXTRA_TIME", "PENALTY_SHOOTOUT"}
DONE = {"FINISHED", "AWARDED"}


@dataclass(frozen=True)
class Days:
    """Local calendar days, both included."""
    first: date
    last: date

    def api_params(self) -> dict:
        """UTC range that surely covers these local days.

        The API's dateTo leaves out the end day (docs disagree; tested), and a local
        day can spread over two UTC days. So ask for a little more, filter after.
        """
        start = datetime.combine(self.first, time.min).astimezone(UTC).date()
        end = datetime.combine(self.last + timedelta(days=1), time.min).astimezone(UTC).date()
        return {"dateFrom": start.isoformat(), "dateTo": (end + timedelta(days=1)).isoformat()}

    def __str__(self) -> str:
        if self.first == self.last:
            return f"{self.first:%a %d %b %Y}"
        return f"{self.first:%a %d %b %Y} to {self.last:%a %d %b %Y}"


def resolve_days(when: str, date_from: str, date_to: str, today: date, max_days: int) -> Days:
    """Turn the model's words into dates. Models are poor at date arithmetic."""
    if date_from or date_to:
        try:
            first = date.fromisoformat(date_from or date_to)
            last = date.fromisoformat(date_to or date_from)
        except ValueError:
            raise FootballError("dates must look like 2026-11-22.") from None
        if last < first:
            raise FootballError("date_to is before date_from.")
        if (last - first).days + 1 > max_days:
            raise FootballError(f"the period is too long. The maximum here is {max_days} days.")
        return Days(first, last)
    start, end = {
        "yesterday": (-1, -1),
        "today": (0, 0),
        "tomorrow": (1, 1),
        "last_7_days": (-7, 0),
        "next_7_days": (0, 7),
    }[when]
    return Days(today + timedelta(days=start), today + timedelta(days=end))


def utc_time(match: dict) -> datetime:
    return datetime.fromisoformat(match["utcDate"])


def local_day(match: dict) -> date:
    when = utc_time(match)
    # SCHEDULED = the day is known but not the kick-off time, so don't shift it.
    return when.date() if match.get("status") == "SCHEDULED" else when.astimezone().date()


def score(match: dict) -> str | None:
    s = match.get("score") or {}
    full, pens = s.get("fullTime") or {}, s.get("penalties") or {}
    home, away = full.get("home"), full.get("away")
    if home is None or away is None:
        return None
    if s.get("duration") == "PENALTY_SHOOTOUT" and None not in (pens.get("home"), pens.get("away")):
        # The API counts shoot-out goals in fullTime: 1-1 (3-4 on penalties) is sent as 4-5.
        home, away = home - pens["home"], away - pens["away"]
        return f"{home}-{away} ({pens['home']}-{pens['away']} on penalties)"
    return f"{home}-{away}" + (" after extra time" if s.get("duration") == "EXTRA_TIME" else "")


def record(matches: list[dict], team_id: int) -> tuple[int, int, int]:
    """Won, drawn, lost. A shoot-out counts for whoever won it."""
    won = drawn = lost = 0
    for match in matches:
        winner = (match.get("score") or {}).get("winner")
        at_home = (match.get("homeTeam") or {}).get("id") == team_id
        if winner == "DRAW":
            drawn += 1
        elif winner in ("HOME_TEAM", "AWAY_TEAM"):
            won += (winner == "HOME_TEAM") == at_home
            lost += (winner == "HOME_TEAM") != at_home
    return won, drawn, lost


def team_label(team: dict | None) -> str:
    team = team or {}
    return team.get("shortName") or team.get("name") or "to be decided"


def zone_name() -> str:
    """'Europe/Istanbul'. Named in every time we show: "local time" alone made the model
    think a kick-off was London time and convert it wrongly."""
    try:
        return get_localzone_name() or "UTC"
    except Exception:  # unusual setups; fall back to the offset
        return datetime.now().astimezone().strftime("UTC%z")


def match_line(match: dict, now: datetime) -> str:
    status, result = match.get("status"), score(match)
    when = f"{local_day(match):%a %d %b %Y}"
    when += (" time not set" if status == "SCHEDULED"
             else f" {utc_time(match).astimezone():%H:%M} {zone_name()} time")
    if status in DONE:
        state = "finished" if status == "FINISHED" else "result awarded"
        middle = result or "score n/a"
    elif status in IN_PROGRESS:
        state, middle = "in progress, score may be delayed", result or "score n/a"
    elif status in NOT_STARTED:
        late = status == "TIMED" and utc_time(match) < now
        state = "should have started, no result yet" if late else "not started"
        middle = "vs"
    else:
        state, middle = str(status or "status n/a").lower(), "vs"
    code = (match.get("competition") or {}).get("code") or "n/a"
    home, away = team_label(match.get("homeTeam")), team_label(match.get("awayTeam"))
    return f"{when} | {code} | {home} {middle} {away} | {state}"


def match_lines(matches: list[dict], now: datetime) -> list[str]:
    """One line per match, oldest first, capped."""
    lines = [match_line(m, now) for m in sorted(matches, key=utc_time)]
    extra = len(lines) - MAX_ROWS
    if extra > 0:
        lines = lines[:MAX_ROWS] + [f"({extra} more not shown. Choose one competition or fewer days.)"]
    return lines
