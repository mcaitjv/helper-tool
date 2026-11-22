"""The list of agents the main assistant can use.

To add an API: write its agent like football.py, then add one Specialist here.
"""
from collections.abc import Callable

from helper.agents.football import football_agent, football_registry
from helper.agents.general import general_agent
from helper.assistant import Assistant, Specialist
from helper.config import Config
from helper.football.client import FootballClient
from helper.football.teams import TeamIndex

FOOTBALL = ("anything about football (soccer): matches, results, fixtures, league tables, "
            "scorers, clubs, players, coaches, competitions, also past winners and awards")
GENERAL = ("everything else: greetings, thanks, time and date, writing, explanations, maths, "
           "other sports, weather, general questions")


def main_assistant(
    llm, config: Config, client: FootballClient, teams: Callable[[], TeamIndex | None]
) -> Assistant:
    return Assistant(
        llm,
        [
            Specialist("football", FOOTBALL,
                       football_agent(llm, config, football_registry(client, teams))),
            Specialist("general", GENERAL, general_agent(llm, config)),
        ],
        fallback="general",
    )
