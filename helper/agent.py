"""The agent loop. Generic: any system prompt + any tools. Prints nothing."""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from helper.conversation import Conversation
from helper.tools.registry import Registry


# The loop reports what happens as events; the CLI (or a web UI) displays them.
@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Thinking:
    text: str


@dataclass(frozen=True)
class ToolStarted:
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolFinished:
    name: str
    ok: bool
    content: str


Event = Text | Thinking | ToolStarted | ToolFinished


class Agent:
    def __init__(self, llm, registry: Registry, chat: Conversation, max_rounds: int = 6):
        self.llm = llm
        self.registry = registry
        self.chat = chat
        self.max_rounds = max_rounds

    async def run(self, question: str, think: bool = False) -> AsyncIterator[Event]:
        # This turn is kept separately and saved only once it completes,
        # so an error or Ctrl-C never leaves half a turn in the history.
        turn: list[dict] = [{"role": "user", "content": question}]
        tools = self.registry.schemas()

        for _ in range(self.max_rounds):
            text, thinking, calls = "", "", []
            async for chunk in self.llm.stream(self.chat.messages(turn), think, tools):
                if chunk.thinking:
                    thinking += chunk.thinking
                    yield Thinking(chunk.thinking)
                if chunk.text:
                    text += chunk.text
                    yield Text(chunk.text)
                calls += chunk.tool_calls

            message = {"role": "assistant", "content": text}
            if not calls:  # no tool wanted: this is the final answer
                if not text:
                    message["content"] = "I couldn't produce an answer. Please try again."
                    yield Text(message["content"])
                turn.append(message)
                self._save(turn)
                return

            # The model must see its own request, then one result per call.
            message["tool_calls"] = [
                {"function": {"name": c.name, "arguments": c.arguments}} for c in calls
            ]
            if thinking:
                message["thinking"] = thinking
            turn.append(message)
            for call in calls:
                yield ToolStarted(call.name, call.arguments)
                result = await self.registry.call(call.name, call.arguments)
                yield ToolFinished(call.name, result.ok, result.content)
                turn.append({"role": "tool", "tool_name": call.name, "content": result.content})

        stopped = f"I stopped after {self.max_rounds} tool rounds without finishing."
        yield Text(stopped)
        turn.append({"role": "assistant", "content": stopped})
        self._save(turn)

    def _save(self, turn: list[dict]) -> None:
        for message in turn:
            message.pop("thinking", None)  # useful within the turn, clutter afterwards
        self.chat.add_turn(turn)
