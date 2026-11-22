from typing import Literal

import pytest
from pydantic import Field

from helper.tools.clock import get_current_time
from helper.tools.registry import MAX_RESULT_CHARS, Registry, Tool, ToolArgs, ToolError


class Args(ToolArgs):
    league: Literal["PL", "SA"] = Field(description="League code")
    limit: int = Field(default=5, ge=1, le=20, description="1 to 20")


async def run(args):
    if args.limit == 13:
        raise ToolError("bad luck")
    if args.limit == 14:
        raise RuntimeError("token=secret123")
    if args.limit == 15:
        return "x" * (MAX_RESULT_CHARS + 1)
    return f"{args.league} {args.limit}"


tool = Tool("demo", "A demo.", Args, run)


def test_schema_is_generated_from_pydantic():
    fn = tool.schema()["function"]
    assert fn["name"] == "demo"
    assert fn["parameters"]["required"] == ["league"]
    assert fn["parameters"]["properties"]["league"] == {
        "type": "string", "enum": ["PL", "SA"], "description": "League code"}


async def test_valid_call():
    result = await Registry(tool).call("demo", {"league": "PL", "limit": 3})
    assert result.ok and result.content == "PL 3"


@pytest.mark.parametrize("arguments, word", [
    ({"league": "TSL"}, "league"),              # not in the list
    ({}, "league"),                             # missing
    ({"league": "PL", "limit": 99}, "limit"),   # out of range
    ({"league": "PL", "extra": 1}, "extra"),    # unknown
])
async def test_invalid_arguments(arguments, word):
    result = await Registry(tool).call("demo", arguments)
    assert not result.ok and word in result.content


async def test_unknown_tool_lists_the_real_ones():
    result = await Registry(tool).call("nope", {})
    assert not result.ok and "demo" in result.content


async def test_expected_error_is_explained():
    result = await Registry(tool).call("demo", {"league": "PL", "limit": 13})
    assert not result.ok and "bad luck" in result.content


async def test_unexpected_error_does_not_leak_details():
    result = await Registry(tool).call("demo", {"league": "PL", "limit": 14})
    assert not result.ok and "secret123" not in result.content


async def test_long_result_is_cut():
    result = await Registry(tool).call("demo", {"league": "PL", "limit": 15})
    assert result.ok and result.content.endswith("[result cut: too long]")


def test_duplicate_tool_is_rejected():
    with pytest.raises(ValueError):
        Registry(tool, tool)


@pytest.mark.parametrize("zone, ok", [
    ("", True), ("Asia/Tokyo", True),
    ("Mars/Base", False), ("../../etc/passwd", False), ("/etc/passwd", False), ("Asia", False),
])
async def test_clock(zone, ok):
    result = await Registry(get_current_time).call("get_current_time", {"timezone": zone})
    assert result.ok is ok
    if not ok:
        assert "unknown timezone" in result.content
