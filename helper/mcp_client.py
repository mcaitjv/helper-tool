"""MCP client: start the servers in mcp.json and turn their tools into ours.

An MCP server is a separate program. We talk to it over stdin/stdout (stdio):
  1. initialize   - say hello, agree on a protocol version
  2. tools/list   - ask which tools it has (name, description, JSON schema)
  3. tools/call   - run one when the model asks for it

Only add servers you trust: they run with your user's permissions, and their
tool descriptions go straight into the model's prompt.
"""
import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import jsonschema
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from helper.config import ROOT
from helper.tools.registry import InvalidArguments, ToolError

log = logging.getLogger(__name__)

CONFIG_FILE = ROOT / "mcp.json"
LOG_DIR = ROOT / "data"
START_TIMEOUT = 20.0
CALL_TIMEOUT = 15.0


@dataclass(frozen=True)
class ServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()


def load_config(path: Path = CONFIG_FILE) -> list[ServerConfig]:
    """Read mcp.json (the same shape other MCP apps use). No file = no servers."""
    if not path.exists():
        return []
    try:
        servers = json.loads(path.read_text())["mcpServers"]
        configs = []
        for name, entry in servers.items():
            command = entry["command"]
            if not isinstance(command, str) or not command:
                raise ValueError(f"'{name}' needs a command")
            if "/" in command and not Path(command).is_absolute():
                command = str(ROOT / command)  # relative to the project
            args = tuple(str(a) for a in entry.get("args", []))
            env = tuple((str(k), str(v)) for k, v in entry.get("env", {}).items())
            configs.append(ServerConfig(name, command, args, env))
        return configs
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"mcp.json is not valid: {e}") from None


class McpServer:
    """One running server.

    The MCP library's connection must be opened and closed by the same task, but
    each CLI question is a separate run. So one long-lived task owns it, and
    tool calls from any question use the session it opened.
    """

    def __init__(self, config: ServerConfig):
        self.config = config
        self.session: ClientSession | None = None
        self._owner: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> list["McpTool"]:
        ready = asyncio.Event()
        self._owner = asyncio.create_task(self._own(ready))
        waiter = asyncio.create_task(ready.wait())
        done, _ = await asyncio.wait({self._owner, waiter}, timeout=START_TIMEOUT,
                                     return_when=asyncio.FIRST_COMPLETED)
        waiter.cancel()
        if not ready.is_set():
            error = self._owner.exception() if self._owner in done else None
            await self.stop()
            reason = f"{type(error).__name__}: {error}" if error else "it did not start in time"
            raise ToolError(f"MCP server '{self.config.name}' failed: {reason}")
        listed = await asyncio.wait_for(self.session.list_tools(), CALL_TIMEOUT)
        return [McpTool(self, t.name, t.description or "", t.input_schema or {})
                for t in listed.tools]

    async def _own(self, ready: asyncio.Event) -> None:
        params = StdioServerParameters(
            command=self.config.command, args=list(self.config.args),
            # Only what mcp.json gives. The library adds just HOME, PATH and a few
            # others, so our API key is not passed on.
            env=dict(self.config.env) or None,
        )
        LOG_DIR.mkdir(exist_ok=True)
        with open(LOG_DIR / f"mcp-{self.config.name}.log", "a") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.session = session
                    ready.set()
                    await self._stop.wait()
        self.session = None

    async def call(self, name: str, arguments: dict) -> str:
        if self.session is None or self._owner is None or self._owner.done():
            raise ToolError(f"the MCP server '{self.config.name}' is not running.")
        try:
            result = await asyncio.wait_for(self.session.call_tool(name, arguments), CALL_TIMEOUT)
        except TimeoutError:
            raise ToolError(f"the MCP server '{self.config.name}' took too long.") from None
        except Exception as e:  # protocol errors, a crashed server, ...
            log.debug("MCP call failed", exc_info=True)
            raise ToolError(f"the MCP server '{self.config.name}' refused: {e}") from None
        text = "\n".join(getattr(c, "text", "[non-text content]") for c in result.content or [])
        if getattr(result, "is_error", False):
            raise ToolError(text or "the MCP tool reported an error.")
        return text or "(empty result)"

    async def stop(self) -> None:
        self._stop.set()
        if self._owner:
            try:
                await asyncio.wait_for(self._owner, 10)
            except BaseException:  # a failed start already reported its error
                pass


@dataclass(frozen=True)
class McpTool:
    """An MCP tool that looks like one of ours to the registry."""
    server: McpServer
    name: str
    description: str
    input_schema: dict
    adapt: Callable[[str], str] | None = None  # optional rewrite of the result text

    @property
    def source(self) -> str:
        return f"MCP server '{self.server.config.name}'"

    def schema(self) -> dict:
        parameters = {k: v for k, v in self.input_schema.items() if k != "title"}
        parameters.setdefault("type", "object")
        parameters["properties"] = {
            k: {kk: vv for kk, vv in v.items() if kk != "title"}
            for k, v in parameters.get("properties", {}).items()
        }
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": parameters}}

    async def invoke(self, arguments: dict) -> str:
        # Check before sending, like our own tools: the model may send wrong arguments.
        problems = sorted(jsonschema.Draft202012Validator(self.input_schema).iter_errors(arguments),
                          key=str)
        if problems:
            where = lambda e: ".".join(map(str, e.absolute_path)) or "arguments"
            raise InvalidArguments("; ".join(f"{where(e)}: {e.message}" for e in problems))
        text = await self.server.call(self.name, arguments)
        return self.adapt(text) if self.adapt else text


class McpServers:
    """All servers from mcp.json."""

    def __init__(self, configs: list[ServerConfig]):
        self.servers = [McpServer(c) for c in configs]
        self.tools: list[McpTool] = []
        self.problems: list[str] = []

    async def start(self) -> None:
        for server in self.servers:
            try:
                self.tools += await server.start()
            except ToolError as e:
                self.problems.append(str(e))

    async def stop(self) -> None:
        for server in self.servers:
            await server.stop()
