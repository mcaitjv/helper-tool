"""Adapt the MCP time server's convert_time result.

convert_time takes only a clock time and always answers with TODAY's date. Asked about a
match tomorrow, the model copied that date, even when told not to. So we remove the dates
and say which day the result falls on, relative to the input.
"""
import json
from dataclasses import replace
from datetime import datetime


def simplify_conversion(text: str) -> str:
    try:
        data = json.loads(text)
        source = datetime.fromisoformat(data["source"]["datetime"])
        target = datetime.fromisoformat(data["target"]["datetime"])
    except (ValueError, KeyError, TypeError):
        return text  # not the shape we know: pass it on unchanged
    shift = (target.date() - source.date()).days
    day = {0: "the same day", 1: "the next day", -1: "the previous day"}.get(
        shift, f"{shift:+d} days")
    return (f"{source:%H:%M} in {data['source']['timezone']} is {target:%H:%M} in "
            f"{data['target']['timezone']}, on {day} ({data.get('time_difference', '?')}). "
            "Dates are not included: use the date from the conversation. Offsets are today's.")


def adapt_time_tools(tools: list) -> list:
    return [replace(t, adapt=simplify_conversion) if t.name == "convert_time" else t
            for t in tools]
