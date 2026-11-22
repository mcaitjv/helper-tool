import json
from datetime import datetime
from pathlib import Path
from typing import get_args

import pytest

from helper.football.client import Fetched, FootballError, NotFound
from helper.football.competitions import COMPETITIONS, CompetitionCode
from helper.football.tools import football_tools, format_standings
from helper.tools.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"
AT = datetime(2026, 11, 22, 15, 50)


class FakeClient:
    def __init__(self, data=None):
        self.data, self.calls = data, []

    async def get(self, path, params=None, *, ttl, max_wait=None):
        self.calls.append((path, params))
        if isinstance(self.data, Exception):
            raise self.data
        return Fetched(self.data, AT)


def load(code):
    return json.loads((FIXTURES / f"standings_{code}.json").read_text())


def row(pos, name, **extra):
    return {"position": pos, "team": {"name": name}, "playedGames": 1, "won": 1, "draw": 0,
            "lost": 0, "goalsFor": 2, "goalsAgainst": 0, "goalDifference": 2, "points": 3, **extra}


def test_code_list_matches_the_names():
    assert set(get_args(CompetitionCode)) == set(COMPETITIONS)


def test_league_table():
    text = format_standings("PD", Fetched(load("PD"), AT))
    assert "La Liga (Spain), season 2026/2027, matchday 13" in text
    assert "1 | Barça | 12 | 11 | 0 | 1 | 48 | 13 | 35 | 33" in text
    assert "fetched 22 November 2026 15:50" in text


def test_champions_league_has_one_table():
    text = format_standings("CL", Fetched(load("CL"), AT))
    assert "1 | PSG | 4 | 4 | 0 | 0 | 20 | 5 | 15 | 12" in text
    assert text.count("position | team") == 1


def test_groups_are_labelled_and_home_away_skipped():
    data = {"season": {}, "standings": [
        {"type": "TOTAL", "group": "GROUP_A", "table": [row(1, "Italy")]},
        {"type": "HOME", "group": "GROUP_A", "table": [row(1, "HomeOnly")]},
        {"type": "TOTAL", "group": "GROUP_B", "table": [row(1, "Spain")]},
    ]}
    text = format_standings("EC", Fetched(data, AT))
    assert "GROUP_A" in text and "GROUP_B" in text and "HomeOnly" not in text


def test_missing_values_say_so():
    data = {"season": None, "standings": [
        {"type": "TOTAL", "table": [row(1, None, points=None, team=None)]}]}
    assert "1 | n/a | 1 | 1 | 0 | 0 | 2 | 0 | 2 | n/a" in format_standings("PL", Fetched(data, AT))


def test_full_36_team_table_fits_in_a_tool_result():
    data = {"season": {}, "standings": [
        {"type": "TOTAL", "table": [row(i, f"A fairly long team name {i}") for i in range(1, 37)]}]}
    assert len(format_standings("CL", Fetched(data, AT))) < 8_000


async def test_tool_calls_the_right_path():
    client = FakeClient(load("PD"))
    result = await Registry(*football_tools(client)).call("get_standings", {"competition": "PD"})
    assert result.ok and client.calls == [("/competitions/PD/standings", None)]


async def test_super_lig_is_rejected_before_any_request():
    client = FakeClient()
    result = await Registry(*football_tools(client)).call("get_standings", {"competition": "TSL"})
    assert not result.ok and client.calls == []


@pytest.mark.parametrize("data, word", [
    ({"standings": []}, "no table"),
    (NotFound("football-data.org has no such data."), "no table for FIFA World Cup"),
    (FootballError("the football API limit is used up."), "limit"),
])
async def test_no_table(data, word):
    result = await Registry(*football_tools(FakeClient(data))).call(
        "get_standings", {"competition": "WC"})
    assert not result.ok and word in result.content
