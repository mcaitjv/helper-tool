from datetime import date, datetime

import pytest

from helper.football.client import Fetched, FootballError, NotAllowed, NotFound
from helper.football.matches import record
from helper.football.seasons import parse_year, resolve, winner
from helper.football.teams import Team, TeamIndex
from helper.football.tools import football_tools
from helper.tools.registry import Registry

TODAY = date(2026, 11, 22)
NOW = datetime(2026, 11, 22, 12).astimezone()


def season(year, end=None, won=None):
    return {"startDate": f"{year}-08-01", "endDate": end or f"{year + 1}-05-30",
            "winner": {"name": won} if won else None}


SEASONS = {"seasons": [season(2026), season(2025), season(2024), season(2022, won="Old FC")]}


class FakeClient:
    """Answers by path; records every request."""

    def __init__(self, **paths):
        self.paths, self.calls = paths, []

    async def get(self, path, params=None, *, ttl, max_wait=None):
        self.calls.append((path, params))
        reply = self.paths[path.rsplit("/", 1)[-1]]
        if isinstance(reply, Exception):
            raise reply
        return Fetched(reply, NOW)


def tools(client, index=None):
    return Registry(*football_tools(client, lambda: index, lambda: NOW))


def table(points=84):
    return {"season": season(2024), "standings": [
        {"type": "TOTAL", "table": [{"position": 1, "team": {"name": "Liverpool FC"},
                                     "points": points}]}]}


@pytest.mark.parametrize("text", ["2024", " 2024 ", "2024/25", "2024-2025", "2024 / 2025"])
def test_year_spellings(text):
    assert parse_year(text) == 2024


@pytest.mark.parametrize("text", ["24", "abc", "2024/27", "1850", "2024/25/26", "last year"])
def test_bad_years(text):
    with pytest.raises(FootballError, match="not a season"):
        parse_year(text)


async def test_current_needs_no_request():
    client = FakeClient()
    assert await resolve(client, "PL", "current", TODAY) is None
    assert client.calls == []


async def test_last_during_a_season_and_between_seasons():
    client = FakeClient(PL=SEASONS)
    assert await resolve(client, "PL", "last", TODAY) == 2025
    assert await resolve(client, "PL", "last", date(2027, 6, 15)) == 2026   # 2026 just ended


async def test_recorded_winner():
    text, _ = await winner(FakeClient(PL=SEASONS), "PL", "2022", TODAY)
    assert "2022/2023: won by Old FC" in text


async def test_blank_league_winner_comes_from_the_final_table():
    client = FakeClient(PL=SEASONS, standings=table())
    text, _ = await winner(client, "PL", "2024/25", TODAY)
    assert "won by Liverpool FC, first in the final table with 84 points" in text
    assert client.calls[-1] == ("/competitions/PL/standings", {"season": 2024})


async def test_blank_cup_winner_comes_from_the_final_not_the_table():
    final = {"matches": [{
        "utcDate": "2025-05-31T19:00:00Z", "status": "FINISHED",
        "homeTeam": {"name": "Paris Saint-Germain FC", "shortName": "PSG"},
        "awayTeam": {"name": "Inter", "shortName": "Inter"},
        "score": {"winner": "HOME_TEAM", "duration": "REGULAR", "fullTime": {"home": 5, "away": 0}}}]}
    client = FakeClient(CL=SEASONS, matches=final)
    text, _ = await winner(client, "CL", "2024", TODAY)
    assert "won by Paris Saint-Germain FC" in text and "PSG 5-0 Inter" in text
    assert client.calls[-1] == ("/competitions/CL/matches", {"stage": "FINAL", "season": 2024})


async def test_no_winner_is_invented():
    with pytest.raises(FootballError, match="does not say who won"):
        await winner(FakeClient(CL=SEASONS, matches={"matches": []}), "CL", "2024", TODAY)
    text, _ = await winner(FakeClient(PL=SEASONS), "PL", "current", TODAY)
    assert "not finished yet" in text
    with pytest.raises(FootballError, match="no .* season starting in 1990"):
        await winner(FakeClient(PL=SEASONS), "PL", "1990", TODAY)


@pytest.mark.parametrize("error, word", [(NotAllowed("x"), "2023/24"), (NotFound("x"), "no such season")])
async def test_refused_season_is_explained(error, word):
    r = await tools(FakeClient(standings=error)).call(
        "get_standings", {"competition": "PL", "season": "2020"})
    assert not r.ok and word in r.content


async def test_standings_and_scorers_send_the_season():
    client = FakeClient(standings=table(), scorers={"season": season(2024), "scorers": [
        {"player": {"name": "P"}, "team": {"name": "T"}, "goals": 9}]})
    r = await tools(client).call("get_standings", {"competition": "PL", "season": "2024/25"})
    assert r.ok and "2024/2025, final table" in r.content
    assert (await tools(client).call(
        "get_top_scorers", {"competition": "PL", "season": "2024"})).ok
    assert [c[1] for c in client.calls] == [{"season": 2024}, {"limit": 20, "season": 2024}]


async def test_old_champions_league_table_has_a_warning():
    data = {**table(), "season": season(2023)}
    r = await tools(FakeClient(standings=data)).call(
        "get_standings", {"competition": "CL", "season": "2023"})
    assert "WARNING" in r.content


def played(home, away, result, day):
    return {"utcDate": f"2024-10-{day:02}T15:00:00Z", "status": "FINISHED",
            "competition": {"code": "PL"}, "homeTeam": home, "awayTeam": away,
            "score": {"winner": result, "fullTime": {"home": 1, "away": 1}}}


ARS, CHE, LUT = ({"id": 57, "name": "Arsenal FC"}, {"id": 61, "name": "Chelsea FC"},
                 {"id": 9, "name": "Luton Town FC"})
GAMES = [played(ARS, CHE, "HOME_TEAM", 1), played(CHE, ARS, "HOME_TEAM", 2),
         played(LUT, ARS, "AWAY_TEAM", 3), played(ARS, LUT, "DRAW", 4)]


def test_record():
    assert record(GAMES, 57) == (2, 1, 1)


async def test_team_season_and_opponent():
    index = TeamIndex([Team(57, "Arsenal FC", "Arsenal", "ARS", ("PL", "CL"))], NOW)
    client = FakeClient(matches={"matches": GAMES})
    args = {"team": "Arsenal", "which": "recent", "season": "2024"}
    r = await tools(client, index).call("get_team_matches", args)
    assert "4 matches, 2 won, 1 drawn, 1 lost" in r.content
    r = await tools(client, index).call("get_team_matches", {**args, "opponent": "Chelsea"})
    assert "against Chelsea: 2 matches, 1 won, 0 drawn, 1 lost" in r.content
    assert "Luton" not in r.content
    assert client.calls[0] == ("/teams/57/matches", {"season": 2024})
