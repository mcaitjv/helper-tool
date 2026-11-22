from datetime import UTC, datetime, timedelta

import pytest

from helper.football.client import Fetched, FootballError, NotFound
from helper.football.competitions import COMPETITIONS
from helper.football.teams import Team, TeamIndex, build_index, load_index, normalize

NOW = datetime(2026, 11, 22, tzinfo=UTC)


def team(id, name, short="", tla="", comps=("PL",)):
    return Team(id, name, short, tla, comps)


INDEX = TeamIndex([
    team(57, "Arsenal FC", "Arsenal", "ARS"),
    team(65, "Manchester City FC", "Man City", "MCI"),
    team(66, "Manchester United FC", "Man United", "MUN"),
    team(73, "Tottenham Hotspur FC", "Tottenham", "TOT"),
    team(81, "FC Barcelona", "Barça", "FCB", ("PD", "CL")),
    team(5, "FC Bayern München", "Bayern", "FCB", ("BL1", "CL")),
    team(254, "Málaga CF", "Málaga", "MAL", ("PD",)),
    team(98, "AC Milan", "Milan", "MIL", ("SA",)),
    team(108, "FC Internazionale Milano", "Inter", "INT", ("SA",)),
], NOW)


@pytest.mark.parametrize("query, id", [
    ("Arsenal", 57), ("ARSENAL FC", 57), ("ars", 57), ("Barcelona", 81), ("barca", 81),
    ("Malaga", 254), ("Bayern Munchen", 5), ("man united", 66), ("Man Utd", 66), ("Spurs", 73),
    ("Milan", 98), ("Inter", 108), ("City", 65),
])
def test_finds(query, id):
    assert INDEX.find(query).id == id


@pytest.mark.parametrize("query", ["Manchester", "FCB"])
def test_ambiguous_names_list_the_options(query):
    with pytest.raises(FootballError, match="several teams.*Ask the user"):
        INDEX.find(query)


def test_typo_is_suggested_but_not_chosen():
    with pytest.raises(FootballError, match="Similar names: Arsenal FC"):
        INDEX.find("Arsenol")


def test_unknown_team():
    with pytest.raises(FootballError, match="no team called 'Galatasaray'"):
        INDEX.find("Galatasaray")


@pytest.mark.parametrize("query", ["", "  ", "!!!"])
def test_empty(query):
    with pytest.raises(FootballError):
        INDEX.find(query)


def test_normalize():
    assert normalize("FC Barça") == "barca"
    assert normalize("AC") == "ac"   # never becomes empty


def test_age():
    assert not INDEX.is_old(NOW + timedelta(days=6))
    assert INDEX.is_old(NOW + timedelta(days=8))


class FakeClient:
    def __init__(self):
        self.paths = []

    async def get(self, path, params=None, *, ttl, max_wait=None):
        self.paths.append(path)
        if "/EC/" in path:
            raise NotFound("none")
        return Fetched({"teams": [{"id": 57, "name": "Arsenal FC", "shortName": None, "tla": "ARS"},
                                  {"id": None, "name": None}]}, NOW)


async def test_build_save_and_load(tmp_path):
    path, client = tmp_path / "data" / "teams.json", FakeClient()
    built = await build_index(client, path)
    assert len(client.paths) == 12
    assert len(built.teams) == 1 and built.teams[0].competitions == tuple(
        c for c in COMPETITIONS if c != "EC")
    assert load_index(path).teams == built.teams


async def test_failed_build_keeps_the_old_file(tmp_path):
    path = tmp_path / "teams.json"
    path.write_text("old")

    class Broken(FakeClient):
        async def get(self, *a, **k):
            raise FootballError("down")

    with pytest.raises(FootballError):
        await build_index(Broken(), path)
    assert path.read_text() == "old"


@pytest.mark.parametrize("content", ["", "{", "[]", '{"built": "x"}', '{"teams": [1], "built": "x"}'])
def test_damaged_file_is_ignored(tmp_path, content):
    (tmp_path / "t.json").write_text(content)
    assert load_index(tmp_path / "t.json") is None
