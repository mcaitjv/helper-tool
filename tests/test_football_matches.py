from datetime import UTC, date, datetime, timedelta

import pytest

from helper.football.client import Fetched, FootballError
from helper.football.matches import MAX_ROWS, Days, match_line, match_lines, resolve_days, score
from helper.football.teams import Team, TeamIndex
from helper.football.tools import football_tools
from helper.tools.registry import Registry

TODAY = date(2026, 11, 22)
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
ARSENAL = Team(57, "Arsenal FC", "Arsenal", "ARS", ("PL", "CL"))


def match(utc, status="FINISHED", home=1, away=0, **extra):
    return {"utcDate": utc, "status": status, "competition": {"code": "PL"},
            "homeTeam": {"shortName": "Home"}, "awayTeam": {"shortName": "Away"},
            "score": {"duration": "REGULAR", "fullTime": {"home": home, "away": away}}, **extra}


class FakeClient:
    def __init__(self, data):
        self.data, self.calls = data, []

    async def get(self, path, params=None, *, ttl, max_wait=None):
        self.calls.append((path, params))
        return Fetched(self.data, NOW)


def setup(*matches):
    client = FakeClient({"matches": list(matches)})
    index = TeamIndex([ARSENAL], NOW)
    return client, Registry(*football_tools(client, lambda: index, lambda: NOW.astimezone()))


# --- dates

@pytest.mark.parametrize("when, first, last", [
    ("yesterday", 21, 21), ("today", 22, 22), ("tomorrow", 23, 23),
    ("last_7_days", 15, 22), ("next_7_days", 22, 29),
])
def test_words_become_dates(when, first, last):
    assert resolve_days(when, "", "", TODAY, 8) == Days(date(2026, 11, first), date(2026, 11, last))


def test_exact_dates_win():
    assert resolve_days("today", "2026-11-01", "", TODAY, 8) == Days(*[date(2026, 11, 1)] * 2)


@pytest.mark.parametrize("a, b, word", [
    ("22/11/2026", "", "look like"), ("2026-11-05", "2026-11-01", "before"),
    ("2026-11-01", "2026-11-30", "too long"),
])
def test_bad_dates(a, b, word):
    with pytest.raises(FootballError, match=word):
        resolve_days("today", a, b, TODAY, 8)


def test_api_range_east_of_utc(istanbul):
    # Local 22 Nov is 21 Nov 21:00 to 22 Nov 21:00 UTC; dateTo leaves out its own day.
    assert Days(TODAY, TODAY).api_params() == {"dateFrom": "2026-11-21", "dateTo": "2026-11-23"}


def test_api_range_west_of_utc(new_york):
    assert Days(TODAY, TODAY).api_params() == {"dateFrom": "2026-11-22", "dateTo": "2026-11-24"}


@pytest.mark.parametrize("zone", ["istanbul", "new_york"])
def test_longest_range_stays_within_the_api_limit(zone, request):
    request.getfixturevalue(zone)
    for when in ("last_7_days", "next_7_days"):
        p = resolve_days(when, "", "", TODAY, 8).api_params()
        assert date.fromisoformat(p["dateTo"]) - date.fromisoformat(p["dateFrom"]) <= timedelta(10)


async def test_filter_uses_the_local_day(istanbul):
    _, tools = setup(
        match("2026-11-21T20:30:00Z", home=7),   # 21 Nov 23:30 local: out
        match("2026-11-21T21:30:00Z", home=8),   # 22 Nov 00:30 local: in
        match("2026-11-22T20:30:00Z", home=9),   # 22 Nov 23:30 local: in
        match("2026-11-22T21:30:00Z", home=6),   # 23 Nov 00:30 local: out
    )
    text = (await tools.call("get_matches", {"when": "today"})).content
    assert "2 matches" in text and "8-0" in text and "9-0" in text
    assert "7-0" not in text and "6-0" not in text


# --- scores and status

def test_shootout_goals_are_taken_out_of_the_score():
    s = {"duration": "PENALTY_SHOOTOUT", "fullTime": {"home": 4, "away": 5},
         "penalties": {"home": 3, "away": 4}}
    assert score({"score": s}) == "1-1 (3-4 on penalties)"


def test_extra_time_and_missing_scores():
    s = {"duration": "EXTRA_TIME", "fullTime": {"home": 3, "away": 2}}
    assert score({"score": s}) == "3-2 after extra time"
    assert score({"score": {"fullTime": {"home": None, "away": None}}}) is None
    assert score({}) is None


@pytest.mark.parametrize("m, expected", [
    (match("2026-11-21T17:30:00Z"),
     "Sat 21 Nov 2026 20:30 Europe/Istanbul time | PL | Home 1-0 Away | finished"),
    (match("2026-11-24T20:00:00Z", "TIMED", None, None), "Home vs Away | not started"),
    (match("2026-11-22T09:00:00Z", "TIMED", None, None), "should have started, no result yet"),
    (match("2026-11-22T11:30:00Z", "IN_PLAY"), "Home 1-0 Away | in progress, score may be delayed"),
    (match("2026-12-01T00:00:00Z", "SCHEDULED", None, None), "Tue 01 Dec 2026 time not set"),
    (match("2026-11-24T20:00:00Z", "POSTPONED", None, None), "Home vs Away | postponed"),
    (match("2026-11-24T20:00:00Z", "TIMED", None, None, homeTeam={"name": None}),
     "to be decided vs Away"),
])
def test_match_line(istanbul, m, expected):
    assert expected in match_line(m, NOW)


def test_long_lists_are_capped_and_say_so():
    lines = match_lines([match("2026-11-21T17:30:00Z")] * (MAX_ROWS + 5), NOW)
    assert len(lines) == MAX_ROWS + 1 and "5 more not shown" in lines[-1]


# --- tools

async def test_competition_path_and_longer_period():
    client, tools = setup()
    args = {"competition": "PL", "date_from": "2026-11-01", "date_to": "2026-11-30"}
    assert (await tools.call("get_matches", args)).ok
    assert client.calls[0][0] == "/competitions/PL/matches"
    assert not (await tools.call("get_matches", {**args, "competition": "ALL"})).ok


async def test_upcoming_gives_the_soonest_not_the_last():
    client, tools = setup(
        match("2027-03-01T20:00:00Z", "TIMED", None, None, awayTeam={"shortName": "Far"}),
        match("2026-11-24T20:00:00Z", "TIMED", None, None, awayTeam={"shortName": "Soon"}),
        match("2026-11-21T17:30:00Z", awayTeam={"shortName": "Past"}),
        match("2026-11-20T17:30:00Z", "TIMED", None, None, awayTeam={"shortName": "Stale"}),
    )
    r = await tools.call("get_team_matches", {"team": "arsenal", "which": "upcoming", "limit": 1})
    assert "Soon" in r.content
    assert not any(w in r.content for w in ("Far", "Past", "Stale"))
    assert client.calls[0][0] == "/teams/57/matches" and "limit" not in client.calls[0][1]


async def test_recent_gives_the_latest_results():
    _, tools = setup(
        match("2026-09-01T17:30:00Z", awayTeam={"shortName": "Old"}),
        match("2026-11-21T17:30:00Z", awayTeam={"shortName": "New"}),
        match("2026-11-24T20:00:00Z", "TIMED", None, None, awayTeam={"shortName": "Next"}),
    )
    r = await tools.call("get_team_matches", {"team": "Arsenal", "which": "recent", "limit": 1})
    assert "New" in r.content and "Old" not in r.content and "Next" not in r.content
    assert "other matches may exist" in r.content and "WARNING" not in r.content


async def test_scorers_limit_and_missing_assists():
    client = FakeClient({"season": {}, "scorers": [
        {"player": {"name": f"P{i}"}, "team": {"shortName": "T"}, "goals": 9 - i, "assists": None,
         "penalties": None, "playedMatches": 4} for i in range(5)]})
    r = await Registry(*football_tools(client)).call(
        "get_top_scorers", {"competition": "PL", "limit": 2})
    assert "1 | P0 | T | 9 | n/a | n/a | 4" in r.content and "P2" not in r.content


async def test_team_info_with_gaps():
    client = FakeClient({"name": "Arsenal FC", "coach": {"name": None}, "squad": []})
    index = TeamIndex([ARSENAL], NOW)
    r = await Registry(*football_tools(client, lambda: index)).call(
        "get_team_info", {"team": "ARS"})
    assert r.ok and "Coach: n/a" in r.content and "Squad (0): n/a" in r.content


async def test_missing_team_list_is_explained():
    r = await Registry(*football_tools(FakeClient({}))).call("get_team_info", {"team": "Arsenal"})
    assert not r.ok and "team list is missing" in r.content


async def test_warns_when_the_teams_league_is_not_covered():
    client = FakeClient({"matches": [match("2026-11-24T17:45:00Z", "TIMED", None, None)]})
    index = TeamIndex([ARSENAL, Team(610, "Galatasaray SK", "Galatasaray", "GAL", ("CL",))], NOW)
    tools = Registry(*football_tools(client, lambda: index, lambda: NOW.astimezone()))
    for name, warned in (("Galatasaray", True), ("Arsenal", False)):
        r = await tools.call("get_team_matches", {"team": name, "which": "upcoming"})
        assert ("WARNING" in r.content) is warned and "UEFA Champions League" in r.content


@pytest.mark.parametrize("name, args", [
    ("get_team_matches", {"which": "upcoming"}), ("get_team_info", {})])
async def test_national_teams_are_explained_without_a_request(name, args):
    client = FakeClient({})
    index = TeamIndex([Team(803, "Turkey", "Turkey", "TUR", ("EC", "WC"))], NOW)
    r = await Registry(*football_tools(client, lambda: index)).call(name, {"team": "Turkey", **args})
    assert not r.ok and "national team" in r.content and client.calls == []
