"""Seasons: 'current', 'last' or a year, and who won one."""
import re
from datetime import date

from helper.football.client import FootballClient, FootballError, NotAllowed, NotFound
from helper.football.competitions import COMPETITIONS, LEAGUES
from helper.football.matches import score, team_label

ONE_DAY = 86_400
SEASON_HELP = (
    "'current', 'last', or the year the season started: '2024' means 2024/25. "
    "For the World Cup and Euro, the tournament year."
)
TOO_OLD = (
    "the free football-data.org plan does not open that season. Seasons before 2023/24 were "
    "refused when tested. Do not answer from memory."
)


def parse_year(text: str) -> int:
    """'2024', '2024/25' and '2024-2025' all mean 2024."""
    found = re.fullmatch(r"\s*((?:19|20)\d\d)(?:\s*[/-]\s*(\d{2}|\d{4}))?\s*", text)
    if not found:
        raise FootballError(f"'{text}' is not a season. Use current, last, or a year like 2024.")
    year = int(found[1])
    if found[2] and int(found[2]) % 100 != (year + 1) % 100:
        raise FootballError(f"'{text}' is not a season. 2024/25 is written 2024.")
    return year


def start(season: dict) -> int:
    return int(season["startDate"][:4])


def finished(season: dict, today: date) -> bool:
    end = season.get("endDate")
    return bool(end) and date.fromisoformat(end) < today


def label(season: dict) -> str:
    first, last = season["startDate"][:4], (season.get("endDate") or season["startDate"])[:4]
    return first if first == last else f"{first}/{last}"


async def list_seasons(client: FootballClient, code: str) -> list[dict]:
    """Every known season, newest first."""
    data = (await client.get(f"/competitions/{code}", ttl=ONE_DAY)).data
    seasons = [s for s in data.get("seasons") or [] if s.get("startDate")]
    if not seasons:
        raise FootballError(f"there are no seasons for {COMPETITIONS[code]}.")
    return sorted(seasons, key=lambda s: s["startDate"], reverse=True)


async def resolve(client: FootballClient, code: str, season: str, today: date) -> int | None:
    """The start year to send, or None for the current season."""
    season = season.strip().lower()
    if season in ("", "current"):
        return None
    if season != "last":
        return parse_year(season)
    newest, *older = await list_seasons(client, code)
    # Between seasons, the newest one is already over: then it is the last one.
    chosen = newest if finished(newest, today) or not older else older[0]
    return start(chosen)


async def get(client: FootballClient, path: str, params: dict, year: int | None, ttl: float):
    """GET for a season, explaining what a refusal means."""
    if year is None:
        return await client.get(path, params or None, ttl=ttl)
    try:
        return await client.get(path, {**params, "season": year}, ttl=ttl)
    except NotAllowed:
        raise FootballError(TOO_OLD) from None
    except NotFound:
        raise FootballError("football-data.org has no such season here.") from None


async def winner(client: FootballClient, code: str, season: str, today: date):
    """(text, fetched): who won, and how we know."""
    seasons = await list_seasons(client, code)
    if season.strip().lower() in ("", "current"):
        chosen = seasons[0]
    else:
        year = await resolve(client, code, season, today)
        chosen = next((s for s in seasons if start(s) == year), None)
        if chosen is None:
            raise FootballError(f"there was no {COMPETITIONS[code]} season starting in {year}.")
    title = f"{COMPETITIONS[code]} {label(chosen)}"
    fetched = await client.get(f"/competitions/{code}", ttl=ONE_DAY)
    if not finished(chosen, today):
        return f"{title}: not finished yet, so there is no winner.", fetched

    recorded = (chosen.get("winner") or {}).get("name")
    if recorded:
        return f"{title}: won by {recorded} (recorded by the API).", fetched

    # The API leaves recent winners blank, so work it out from its own results.
    year = start(chosen)
    if code in LEAGUES:
        fetched = await get(client, f"/competitions/{code}/standings", {}, year, ONE_DAY)
        for table in fetched.data.get("standings") or []:
            rows = table.get("table") or []
            if table.get("type") == "TOTAL" and rows:
                first = rows[0]
                name = (first.get("team") or {}).get("name") or "n/a"
                return (f"{title}: won by {name}, first in the final table with "
                        f"{first.get('points')} points."), fetched
    else:
        fetched = await get(client, f"/competitions/{code}/matches", {"stage": "FINAL"}, year,
                            ONE_DAY)
        for match in fetched.data.get("matches") or []:
            side = {"HOME_TEAM": "homeTeam", "AWAY_TEAM": "awayTeam"}.get(
                (match.get("score") or {}).get("winner"))
            if match.get("status") == "FINISHED" and side:
                home, away = team_label(match.get("homeTeam")), team_label(match.get("awayTeam"))
                return (f"{title}: won by {(match.get(side) or {}).get('name') or 'n/a'}. "
                        f"Final on {match['utcDate'][:10]}: {home} {score(match)} {away}."), fetched
    raise FootballError(f"the API does not say who won the {title}. Do not answer from memory.")
