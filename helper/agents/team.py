"""The list of agents the main assistant can use.

To add an API: write its agent like football.py, then add one Specialist here.
"""
from collections.abc import Callable

from helper.agents.football import football_agent, football_registry
from helper.agents.general import general_agent
from helper.agents.weather import weather_agent
from helper.assistant import Assistant, Specialist
from helper.config import Config
from helper.football.client import FootballClient
from helper.football.teams import TeamIndex

FOOTBALL = ("anything about football (soccer): matches, results, fixtures, league tables, "
            "scorers, clubs, players, coaches, competitions, also past winners and awards. "
            "Not other sports such as Formula 1, basketball or tennis")
WEATHER = ("weather anywhere: current conditions, temperature, rain, snow, wind, forecasts, "
           "weather warnings, whether to take an umbrella or a coat")
GENERAL = ("everything else: greetings, thanks, time, date and time zones, writing, explanations, "
           "maths, other sports, general questions")


def main_assistant(
    llm, config: Config, client: FootballClient, teams: Callable[[], TeamIndex | None],
    time_tools: list | None = None, weather_tools: list | None = None,
) -> Assistant:
    """Each agent gets only its own tools. Without weather tools (the server did not
    start), there is no weather agent and the general agent says it can't look it up."""
    team = [Specialist("football", FOOTBALL,
                       football_agent(llm, config, football_registry(client, teams)))]
    if weather_tools is not None:
        team.append(Specialist("weather", WEATHER, weather_agent(llm, config, weather_tools)))
    team.append(Specialist("general", GENERAL, general_agent(llm, config, time_tools)))
    return Assistant(llm, team, fallback="general")
