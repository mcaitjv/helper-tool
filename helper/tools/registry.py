"""Tool registry: describes tools to the model, validates and runs its calls."""
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

log = logging.getLogger(__name__)

MAX_RESULT_CHARS = 8_000  # protects the context window from huge results


class ToolArgs(BaseModel):
    """Base for every tool's arguments. Unknown arguments are rejected.

    The Ollama client drops min/max/default from the schema, so also write
    limits in the field description. Pydantic still enforces them here.
    """
    model_config = ConfigDict(extra="forbid")


class ToolError(Exception):
    """An expected failure. Its text is shown to the model, so no secrets."""


class InvalidArguments(ToolError):
    """The model sent arguments that don't fit the schema."""


@dataclass(frozen=True)
class ToolOutput:
    """What a tool returns: text for the model, and a source line for the user."""
    content: str
    source: str = ""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[ToolArgs]
    run: Callable[[ToolArgs], Awaitable[str | ToolOutput]]
    source = "built in"

    async def invoke(self, arguments: dict) -> str | ToolOutput:
        try:
            args = self.args.model_validate(arguments)
        except ValidationError as e:
            raise InvalidArguments("; ".join(
                f"{'.'.join(map(str, p['loc'])) or 'arguments'}: {p['msg']}" for p in e.errors()
            )) from None
        return await self.run(args)

    def schema(self) -> dict:
        """The JSON the model sees."""
        parameters = self.args.model_json_schema()
        parameters.pop("title", None)
        parameters.pop("description", None)
        for prop in parameters.get("properties", {}).values():
            prop.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    content: str
    source: str = ""


class Registry:
    """Our own tools and MCP tools, behind one interface: schema() and invoke()."""

    def __init__(self, *tools):
        self._tools = {}
        for tool in tools:
            self.add(tool)

    def __iter__(self):
        return iter(self._tools.values())

    def add(self, tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self._tools.values()]

    async def call(self, name: str, arguments: dict) -> ToolResult:
        """Run a tool. Never raises: errors become results the model can read."""
        tool = self._tools.get(name)
        if tool is None:
            known = ", ".join(self._tools) or "none"
            return ToolResult(False, f"Error: no tool named '{name}'. Available: {known}")
        try:
            output = await tool.invoke(arguments)
        except InvalidArguments as e:
            return ToolResult(False, f"Error: invalid arguments. {e}")
        except ToolError as e:
            return ToolResult(False, f"Error: {e}")
        except Exception:
            # Unexpected: details go to the log, not to the model.
            log.exception("tool %s failed", name)
            return ToolResult(False, "Error: the tool failed unexpectedly.")
        if isinstance(output, str):
            output = ToolOutput(output)
        content = output.content
        if len(content) > MAX_RESULT_CHARS:
            content = content[:MAX_RESULT_CHARS] + "\n[result cut: too long]"
        return ToolResult(True, content, output.source)
