"""Competitions in the free plan (checked with a live key, 22 November 2026)."""
from typing import Literal

COMPETITIONS = {
    "PL": "Premier League (England)",
    "ELC": "Championship (England, second tier)",
    "PD": "La Liga (Spain)",
    "SA": "Serie A (Italy)",
    "BL1": "Bundesliga (Germany, first tier)",
    "FL1": "Ligue 1 (France)",
    "DED": "Eredivisie (Netherlands)",
    "PPL": "Primeira Liga (Portugal)",
    "BSA": "Serie A (Brazil)",
    "CL": "UEFA Champions League",
    "EC": "European Championship",
    "WC": "FIFA World Cup",
}

# The model must pick from a fixed list. Without OTHER it sometimes picked a wrong
# competition for a league we don't have; OTHER is an honest way out.
CompetitionCode = Literal[
    "PL", "ELC", "PD", "SA", "BL1", "FL1", "DED", "PPL", "BSA", "CL", "EC", "WC", "OTHER"
]

CompetitionOrAll = Literal[
    "ALL", "PL", "ELC", "PD", "SA", "BL1", "FL1", "DED", "PPL", "BSA", "CL", "EC", "WC", "OTHER"
]

COMPETITION_HELP = "Competition code: " + ", ".join(f"{c}={n}" for c, n in COMPETITIONS.items())
COMPETITION_HELP += ", OTHER=any league or cup not in this list"

# Teams in one of these have their league matches covered.
LEAGUES = {"PL", "ELC", "PD", "SA", "BL1", "FL1", "DED", "PPL", "BSA"}

# Teams found only here are national teams.
TOURNAMENTS = {"EC", "WC"}
