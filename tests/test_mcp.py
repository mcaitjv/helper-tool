import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from helper.mcp_client import McpServer, McpServers, McpTool, ServerConfig, load_config
from helper.tools.registry import Registry

@pytest.fixture(autouse=True)
def logs_elsewhere(tmp_path, monkeypatch):
    """Server logs go to a temporary folder, not the project's data/."""
    monkeypatch.setattr("helper.mcp_client.LOG_DIR", tmp_path / "logs")


SCHEMA = {"type": "object", "title": "x", "required": ["time"],
          "properties": {"time": {"type": "string", "title": "Time"},
                         "hours": {"type": "integer", "minimum": 0}}}


class FakeServer:
    config = ServerConfig("fake", "x")

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        if self.error:
            raise self.error
        return self.reply


def tool(server):
    return McpTool(server, "convert_time", "Convert time", SCHEMA)


def test_schema_looks_like_ours():
    fn = tool(FakeServer()).schema()["function"]
    assert fn["name"] == "convert_time" and "title" not in fn["parameters"]
    assert fn["parameters"]["properties"]["time"] == {"type": "string"}


async def test_valid_call_reaches_the_server():
    server = FakeServer(reply="ok")
    result = await Registry(tool(server)).call("convert_time", {"time": "10:00"})
    assert result.ok and result.content == "ok" and server.calls == [
        ("convert_time", {"time": "10:00"})]


@pytest.mark.parametrize("arguments, word", [
    ({}, "time"), ({"time": 5}, "time"), ({"time": "1", "hours": -1}, "hours"),
])
async def test_bad_arguments_never_reach_the_server(arguments, word):
    server = FakeServer(reply="ok")
    result = await Registry(tool(server)).call("convert_time", arguments)
    assert not result.ok and "invalid arguments" in result.content and word in result.content
    assert server.calls == []


async def test_adapter_rewrites_the_result():
    from dataclasses import replace
    adapted = replace(tool(FakeServer(reply="raw")), adapt=str.upper)
    assert (await Registry(adapted).call("convert_time", {"time": "1"})).content == "RAW"


WIDE = {"type": "object", "required": [], "properties": {
    "city_name": {"type": "string"}, "days": {"type": "number", "minimum": 1, "maximum": 16},
    "units": {"type": "string", "enum": ["imperial", "metric"]}, "latitude": {"type": "number"}}}


def shaped(server):
    return McpTool(server, "get_forecast", "Forecast", WIDE, keep=("city_name", "days"),
                   require=("city_name",), fixed=(("units", "metric"),), source_line="Source: w")


def test_shaped_schema_shows_only_what_is_kept():
    params = shaped(FakeServer()).schema()["function"]["parameters"]
    assert set(params["properties"]) == {"city_name", "days"}
    assert params["required"] == ["city_name"]


async def test_shaped_call_adds_fixed_values_and_a_source():
    server = FakeServer(reply="ok")
    result = await Registry(shaped(server)).call("get_forecast", {"city_name": "Rome", "days": 2})
    assert server.calls == [("get_forecast", {"city_name": "Rome", "days": 2, "units": "metric"})]
    assert result.ok and result.source == "Source: w"


@pytest.mark.parametrize("arguments, word", [
    ({"days": 2}, "missing: city_name"), ({"city_name": "", "days": 2}, "missing"),
    ({"city_name": "Rome", "units": "imperial"}, "unknown arguments: units"),
    ({"city_name": "Rome", "latitude": 1}, "unknown"), ({"city_name": "Rome", "days": 40}, "days"),
])
async def test_shaped_call_rejects(arguments, word):
    server = FakeServer(reply="ok")
    result = await Registry(shaped(server)).call("get_forecast", arguments)
    assert not result.ok and word in result.content and server.calls == []


async def test_server_errors_become_results():
    from helper.tools.registry import ToolError
    result = await Registry(tool(FakeServer(error=ToolError("bad time")))).call(
        "convert_time", {"time": "x"})
    assert not result.ok and "bad time" in result.content


def write(tmp_path, data):
    path = tmp_path / "mcp.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


def test_config(tmp_path):
    path = write(tmp_path, {"mcpServers": {
        "time": {"command": ".venv/bin/srv", "args": ["--x", 1]},
        "other": {"command": "uvx", "env": {"A": "b"}}}})
    time, other = load_config(path)
    assert time.command.endswith("helper-tool/.venv/bin/srv") and time.args == ("--x", "1")
    assert other.command == "uvx" and other.env == (("A", "b"),)


def test_server_folder(tmp_path):
    path = write(tmp_path, {"mcpServers": {"w": {"command": "x", "cwd": "mcp_servers/w"}}})
    assert load_config(path)[0].cwd.endswith("helper-tool/mcp_servers/w")


@pytest.mark.parametrize("cwd", [".", "", "mcp_servers/.."])
def test_server_may_not_run_in_the_project_folder(tmp_path, cwd):
    path = write(tmp_path, {"mcpServers": {"w": {"command": "x", "cwd": cwd}}})
    with pytest.raises(ValueError, match="project folder"):
        load_config(path)


def test_no_config_file_means_no_servers(tmp_path):
    assert load_config(tmp_path / "missing.json") == []


@pytest.mark.parametrize("data", ["{", "[]", {"servers": {}}, {"mcpServers": {"x": {}}},
                                  {"mcpServers": {"x": {"command": ""}}}])
def test_bad_config_is_explained(tmp_path, data):
    with pytest.raises(ValueError, match="mcp.json is not valid"):
        load_config(write(tmp_path, data))


async def test_missing_program_is_reported_not_fatal():
    servers = McpServers([ServerConfig("ghost", "/nonexistent/server")])
    await servers.start()
    assert servers.tools == [] and "ghost" in servers.problems[0]
    await servers.stop()


async def test_real_servers_start_in_their_own_folder():
    """Every server in mcp.json either has its own folder or reads no .env."""
    for config in load_config():
        assert config.cwd is None or "mcp_servers" in config.cwd


async def test_real_time_server():
    """Starts the real time server from the venv (local, about a second)."""
    servers = McpServers(load_config())
    await servers.start()
    try:
        assert servers.problems == []
        tools = Registry(*servers.tools)
        assert {t.name for t in tools} >= {"get_current_time", "convert_time"}
        ok = await tools.call("get_current_time", {"timezone": "Asia/Tokyo"})
        assert ok.ok and '"timezone": "Asia/Tokyo"' in ok.content
        bad = await tools.call("convert_time", {"source_timezone": "Europe/Istanbul",
                                                 "time": "25:00", "target_timezone": "UTC"})
        assert not bad.ok and "HH:MM" in bad.content
        nope = await tools.call("get_current_time", {"timezone": "Mars/Base"})
        assert not nope.ok and "Invalid timezone" in nope.content
    finally:
        await servers.stop()
    assert all(s.session is None for s in servers.servers)


async def test_server_gets_no_secrets(monkeypatch, tmp_path):
    """Our key is in os.environ after load_dotenv: the server must not see it."""
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "secret123")
    out = tmp_path / "env.txt"
    script = tmp_path / "srv.py"
    script.write_text(f"import os, pathlib\npathlib.Path({str(out)!r}).write_text(repr(dict(os.environ)))\n")
    servers = McpServers([ServerConfig("spy", sys.executable, (str(script),))])
    await servers.start()   # it exits at once, so the start fails; that's fine
    await servers.stop()
    seen = out.read_text()
    assert "PATH" in seen and "secret123" not in seen
