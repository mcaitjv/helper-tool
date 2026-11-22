"""Football tools. Each returns short text with only the fields the model needs."""
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field

from helper.football import matches as m
from helper.football.client import Fetched, FootballClient, FootballError, NotFound
from helper.football.competitions import (
    COMPETITION_HELP, COMPETITIONS, LEAGUES, TOURNAMENTS, CompetitionCode, CompetitionOrAll,
)
from helper.football.teams import TeamIndex
from helper.tools.registry import Tool, ToolArgs, ToolOutput

ONE_MINUTE, TEN_MINUTES, ONE_HOUR = 60, 600, 3600
TEAM_WINDOW = timedelta(days=120)  # how far a team's matches are searched

UNAVAILABLE = "For a competition that is not listed, such as the Turkish Super Lig, use OTHER."
TEAM_HELP = "Team name in English as the user means it, e.g. 'Arsenal' or 'Spain'."


class StandingsArgs(ToolArgs):
    competition: CompetitionCode = Field(description=COMPETITION_HELP)


class ScorersArgs(ToolArgs):
    competition: CompetitionCode = Field(description=COMPETITION_HELP)
    limit: int = Field(default=10, ge=1, le=20, description="How many players, 1 to 20.")


class MatchesArgs(ToolArgs):
    competition: CompetitionOrAll = Field(
        default="ALL", description=COMPETITION_HELP + ", ALL=every competition"
    )
    when: Literal["yesterday", "today", "tomorrow", "last_7_days", "next_7_days"] = Field(
        default="today", description="Which days. Ignored when date_from is given."
    )
    date_from: str = Field(
        default="", description="Only for exact dates: first day, YYYY-MM-DD. Otherwise empty."
    )
    date_to: str = Field(
        default="", description="Only for exact dates: last day, YYYY-MM-DD. Otherwise empty."
    )


class TeamMatchesArgs(ToolArgs):
    team: str = Field(min_length=1, max_length=80, description=TEAM_HELP)
    which: Literal["upcoming", "recent"] = Field(
        description="upcoming = next matches, recent = latest results"
    )
    limit: int = Field(default=5, ge=1, le=10, description="How many matches, 1 to 10.")


class TeamInfoArgs(ToolArgs):
    team: str = Field(min_length=1, max_length=80, description=TEAM_HELP)


def value(x) -> str:
    """Missing data is shown as missing, so the model doesn't fill it in."""
    return "n/a" if x is None or x == "" else str(x)


def team_name(team: dict | None) -> str:
    team = team or {}
    return team.get("shortName") or team.get("name") or "n/a"


def season_name(season: dict | None) -> str:
    season = season or {}
    start, end = (season.get("startDate") or "")[:4], (season.get("endDate") or "")[:4]
    return start if start == end else f"{start}/{end}"


def footer(fetched: Fetched) -> str:
    return (f"Source: football-data.org, fetched {fetched.at:%d %B %Y %H:%M}. "
            "Results can be delayed.")


def check_available(code: str) -> None:
    if code == "OTHER":
        raise FootballError(
            "that competition is not available in the free football data. Tell the user so, "
            "and do not use another competition instead."
        )


def sourced(text: str, fetched: Fetched) -> ToolOutput:
    return ToolOutput(f"{text}\n{footer(fetched)}", footer(fetched))


def no_table(code: str) -> FootballError:
    return FootballError(f"there is no table for {COMPETITIONS[code]} right now.")


def format_standings(code: str, fetched: Fetched) -> str:
    data = fetched.data
    # Some competitions also return HOME and AWAY tables. We want the overall one.
    tables = [s for s in data.get("standings") or [] if s.get("type") == "TOTAL" and s.get("table")]
    if not tables:
        raise no_table(code)

    season = data.get("season") or {}
    lines = [f"{COMPETITIONS[code]}, season {season_name(season)}, "
             f"matchday {value(season.get('currentMatchday'))}"]
    for table in tables:
        if len(tables) > 1:
            lines.append(f"\n{value(table.get('group'))}")
        lines.append("position | team | played | won | drawn | lost | goals for | "
                     "goals against | goal difference | points")
        for row in table["table"]:
            cells = [row.get("position"), team_name(row.get("team"))]
            cells += [row.get(k) for k in ("playedGames", "won", "draw", "lost", "goalsFor",
                                           "goalsAgainst", "goalDifference", "points")]
            lines.append(" | ".join(value(c) for c in cells))
    return "\n".join(lines)


def format_scorers(code: str, limit: int, fetched: Fetched) -> str:
    rows = (fetched.data.get("scorers") or [])[:limit]
    if not rows:
        raise FootballError(f"there are no scorers for {COMPETITIONS[code]} right now.")
    lines = [f"{COMPETITIONS[code]}, season {season_name(fetched.data.get('season'))}, top scorers",
             "rank | player | team | goals | assists | penalties | matches"]
    for rank, row in enumerate(rows, 1):
        player = (row.get("player") or {}).get("name")
        cells = [rank, player, team_name(row.get("team"))]
        cells += [row.get(k) for k in ("goals", "assists", "penalties", "playedMatches")]
        lines.append(" | ".join(value(c) for c in cells))
    return "\n".join(lines)


def format_team(fetched: Fetched) -> str:
    data = fetched.data
    coach = (data.get("coach") or {}).get("name")
    codes = [c.get("code") for c in data.get("runningCompetitions") or [] if c.get("code")]
    lines = [
        f"Team: {value(data.get('name'))}", f"Coach: {value(coach)}",
        f"Stadium: {value(data.get('venue'))}", f"Founded: {value(data.get('founded'))}",
        f"Colours: {value(data.get('clubColors'))}", f"Plays in: {', '.join(codes) or 'n/a'}",
    ]
    squad = [f"{value(p.get('name'))} ({value(p.get('position'))}, {value(p.get('nationality'))})"
             for p in data.get("squad") or []]
    lines.append(f"Squad ({len(squad)}): {'; '.join(squad) or 'n/a'}")
    return "\n".join(lines)


def football_tools(
    client: FootballClient,
    teams: Callable[[], TeamIndex | None] = lambda: None,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> list[Tool]:

    def find_team(name: str):
        index = teams()
        if index is None:
            raise FootballError(
                "the team list is missing. The user can build it with: "
                "python -m helper.football.teams"
            )
        team = index.find(name)
        if TOURNAMENTS.issuperset(team.competitions):  # the API answers 403 for these
            raise FootballError(
                f"{team.name} is a national team. The free plan has no national team pages, so "
                "its fixtures, results, coach and squad are not available. Only World Cup and "
                "Euro tournament matches are, with get_matches and exact dates."
            )
        return team

    async def standings(args: StandingsArgs) -> ToolOutput:
        check_available(args.competition)
        path = f"/competitions/{args.competition}/standings"
        try:
            fetched = await client.get(path, ttl=TEN_MINUTES)
        except NotFound:  # seen for the World Cup and the Euros between tournaments
            raise no_table(args.competition) from None
        return sourced(format_standings(args.competition, fetched), fetched)

    async def scorers(args: ScorersArgs) -> ToolOutput:
        check_available(args.competition)
        path = f"/competitions/{args.competition}/scorers"
        # Always fetch 20, so a different limit can reuse the cached answer.
        fetched = await client.get(path, {"limit": 20}, ttl=TEN_MINUTES)
        return sourced(format_scorers(args.competition, args.limit, fetched), fetched)

    async def get_matches(args: MatchesArgs) -> ToolOutput:
        check_available(args.competition)
        everything = args.competition == "ALL"
        # /matches allows 10 days. api_params adds up to 2, so 8 is safe.
        days = m.resolve_days(args.when, args.date_from, args.date_to, now().date(),
                              max_days=8 if everything else 31)
        path = "/matches" if everything else f"/competitions/{args.competition}/matches"
        fetched = await client.get(path, days.api_params(), ttl=ONE_MINUTE)
        found = [x for x in fetched.data.get("matches") or []
                 if days.first <= m.local_day(x) <= days.last]
        where = "All available competitions" if everything else COMPETITIONS[args.competition]
        lines = [f"{where}, {days}: {len(found)} matches (local time)"]
        return sourced("\n".join([*lines, *m.match_lines(found, now())]), fetched)

    async def team_matches(args: TeamMatchesArgs) -> ToolOutput:
        team, current = find_team(args.team), now()
        today, upcoming = current.date(), args.which == "upcoming"
        days = m.Days(today, today + TEAM_WINDOW) if upcoming else m.Days(today - TEAM_WINDOW, today)
        # No `limit` parameter here: the API would return the LAST matches of the period.
        fetched = await client.get(f"/teams/{team.id}/matches", days.api_params(), ttl=ONE_MINUTE)
        wanted = m.NOT_STARTED | m.IN_PROGRESS if upcoming else m.DONE
        found = sorted((x for x in fetched.data.get("matches") or [] if x.get("status") in wanted),
                       key=m.utc_time)
        if upcoming:  # a kick-off long past that still says "not started" is stale
            found = [x for x in found if m.utc_time(x) > current - timedelta(hours=3)]
        found = found[:args.limit] if upcoming else found[-args.limit:]
        lines = [f"{team.name}, {args.which} matches within {TEAM_WINDOW.days} days: {len(found)} "
                 "shown (local time, oldest first)"]
        lines += m.match_lines(found, current)
        covered = ", ".join(COMPETITIONS[c] for c in team.competitions)
        if LEAGUES.isdisjoint(team.competitions):
            # E.g. Galatasaray: we see its Champions League games but not its league.
            lines.append(f"WARNING, tell the user: only {covered} matches are visible for this "
                         "team. Its other matches, such as its domestic league or friendlies, "
                         "are NOT included, so this may not be its real next or latest match.")
        else:
            lines.append(f"Covers {covered} only. Other cups are not included, "
                         "so other matches may exist.")
        return sourced("\n".join(lines), fetched)

    async def team_info(args: TeamInfoArgs) -> ToolOutput:
        team = find_team(args.team)
        fetched = await client.get(f"/teams/{team.id}", ttl=ONE_HOUR)
        return sourced(format_team(fetched), fetched)

    return [
        Tool("get_standings",
             "Get the current league table (positions, points, goals) of a football competition. "
             + UNAVAILABLE, StandingsArgs, standings),
        Tool("get_top_scorers",
             "Get the players with the most goals in a football competition this season. "
             + UNAVAILABLE, ScorersArgs, scorers),
        Tool("get_matches",
             "Get football matches of a day or period: results and fixtures of a competition. "
             "For one team's matches use get_team_matches. " + UNAVAILABLE,
             MatchesArgs, get_matches),
        Tool("get_team_matches",
             "Get one football team's next matches or latest results.",
             TeamMatchesArgs, team_matches),
        Tool("get_team_info",
             "Get a football team's coach, stadium, founding year and squad players.",
             TeamInfoArgs, team_info),
    ]
