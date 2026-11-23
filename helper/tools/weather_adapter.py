"""Shape the weather MCP server's tools for a small model.

The server's tools have 14 to 21 options each and default to Fahrenheit and mph. We show
the model only what it needs and fix the units in code.
"""
from dataclasses import replace

CITY = ("city_name",)
METRIC = (("units", "metric"), ("time_format", "24h"))

SHAPES = {
    "get_weather_summary": {"keep": CITY + ("days",), "fixed": METRIC},
    "get_forecast": {"keep": CITY + ("days", "granularity"), "fixed": METRIC},
    "get_current_conditions": {"keep": CITY, "fixed": METRIC},
    "get_alerts": {"keep": CITY, "fixed": ()},
}
SOURCE = "Source: weather MCP server (Open-Meteo and national weather services)."
# The model added Fahrenheit in brackets even when the prompt said not to; a note at the
# end of the result, where it looks last, works better (as with get_winner).
NOTE = "\n\nGive temperatures only in °C and wind in km/h, exactly as above. Do not add °F."


def add_note(text: str) -> str:
    return text + NOTE


def shape_weather_tools(tools: list) -> list:
    """Only the tools we know how to shape; anything else the server adds is left out."""
    return [replace(t, keep=SHAPES[t.name]["keep"], require=CITY, adapt=add_note,
                    fixed=SHAPES[t.name]["fixed"], source_line=SOURCE)
            for t in tools if t.name in SHAPES]
