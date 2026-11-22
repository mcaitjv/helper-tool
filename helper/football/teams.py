"""Team name -> id. The API only understands ids, people only use names.

Rebuild by hand:  python -m helper.football.teams
"""
import asyncio
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from difflib import get_close_matches
from pathlib import Path

from helper.config import ROOT, load_config
from helper.football.client import FootballClient, FootballError, NotFound
from helper.football.competitions import COMPETITIONS

INDEX_FILE = ROOT / "data" / "teams.json"
MAX_AGE = timedelta(days=7)

# Words that don't identify a team.
FILLER = {"fc", "cf", "afc", "sc", "ac", "as", "ssc", "sv", "cd", "ud", "rc", "club", "de", "the"}
# Nicknames the API doesn't know.
NICKNAMES = {
    "spurs": "tottenham", "man utd": "man united", "juve": "juventus", "wolves": "wolverhampton",
    "bayern munich": "bayern", "inter milan": "inter", "athletic bilbao": "athletic club",
    "sporting lisbon": "sporting cp", "turkiye": "turkey",
}


@dataclass(frozen=True)
class Team:
    id: int
    name: str
    short_name: str
    tla: str
    competitions: tuple[str, ...]


def normalize(text: str) -> str:
    """'FC Barcelona' -> 'barcelona', 'Málaga' -> 'malaga'."""
    text = unicodedata.normalize("NFKD", text.casefold().replace("ı", "i"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    words = re.findall(r"\w+", text)
    return " ".join([w for w in words if w not in FILLER] or words)


class TeamIndex:
    def __init__(self, teams: list[Team], built: datetime):
        self.teams = teams
        self.built = built

    def is_old(self, now: datetime) -> bool:
        return now - self.built > MAX_AGE

    def find(self, query: str) -> Team:
        """The one team meant by `query`, or an error the model can act on."""
        wanted = normalize(query)
        wanted = normalize(NICKNAMES.get(wanted, wanted))
        if not wanted:
            raise FootballError("no team name was given.")

        names = {t: {normalize(t.name), normalize(t.short_name)} - {""} for t in self.teams}
        exact = [t for t in self.teams if wanted in names[t]]
        by_code = [t for t in self.teams if t.tla and wanted == t.tla.casefold()]
        words = set(wanted.split())
        partial = [t for t in self.teams if any(words <= set(n.split()) for n in names[t])]
        for found in (exact, by_code, partial):
            if len(found) == 1:
                return found[0]
            if found:
                options = "; ".join(f"{t.name} ({', '.join(t.competitions)})" for t in found[:8])
                raise FootballError(
                    f"'{query}' fits several teams: {options}. Ask the user which one."
                )

        known = {n: t.name for t in self.teams for n in names[t]}
        close = list(dict.fromkeys(known[n] for n in get_close_matches(wanted, known, 3, 0.75)))
        hint = f" Similar names: {', '.join(close)}." if close else ""
        raise FootballError(
            f"no team called '{query}' in the available competitions.{hint} "
            "Do not use another team without asking the user."
        )


def load_index(path: Path = INDEX_FILE) -> TeamIndex | None:
    try:
        raw = json.loads(path.read_text())
        teams = [Team(**{**t, "competitions": tuple(t["competitions"])}) for t in raw["teams"]]
        return TeamIndex(teams, datetime.fromisoformat(raw["built"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None  # missing or damaged: rebuild


async def build_index(
    client: FootballClient, path: Path = INDEX_FILE, report: Callable[[str], None] = lambda s: None
) -> TeamIndex:
    """Ask every competition for its teams: 12 requests, so about a minute."""
    found: dict[int, dict] = {}
    for n, code in enumerate(COMPETITIONS, 1):
        report(f"{n}/{len(COMPETITIONS)} {COMPETITIONS[code]}")
        try:
            fetched = await client.get(f"/competitions/{code}/teams", ttl=0, max_wait=65)
        except NotFound:
            continue  # no current season
        for t in fetched.data.get("teams") or []:
            if not t.get("id") or not t.get("name"):
                continue  # not decided yet
            team = found.setdefault(t["id"], {
                "id": t["id"], "name": t["name"], "short_name": t.get("shortName") or "",
                "tla": t.get("tla") or "", "competitions": [],
            })
            team["competitions"].append(code)

    index = TeamIndex(
        [Team(**{**t, "competitions": tuple(t["competitions"])}) for t in found.values()],
        datetime.now().astimezone(),
    )
    path.parent.mkdir(exist_ok=True)
    # Write aside, then swap, so stopping halfway never leaves a broken file.
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(
        {"built": index.built.isoformat(), "teams": [asdict(t) for t in index.teams]},
        ensure_ascii=False, indent=1,
    ))
    temp.replace(path)
    return index


if __name__ == "__main__":
    built = asyncio.run(build_index(FootballClient(load_config().football_key), report=print))
    print(f"{len(built.teams)} teams saved to {INDEX_FILE}")
