"""The main assistant: a router picks one agent, and that agent answers.

It has the same run() as Agent, so the CLI can't tell the difference.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from helper.agent import Agent, Event

# How much of the chat the router sees, to understand "and who is second?"
RECENT_TURNS = 2
MAX_CHARS = 300

ROUTER_PROMPT = """\
Choose which agent should handle the user's latest message.

Agents:
{agents}

If the latest message is a follow-up, such as "and yesterday?", use the conversation to see what \
it is about. A message that changes the subject goes to the agent for the new subject.
If the message asks two separate things, choose the agent for the part that needs looked-up data, \
not general."""


@dataclass(frozen=True)
class Specialist:
    """An agent plus the description the router reads. Adding an API = adding one."""
    name: str
    handles: str
    agent: Agent


@dataclass(frozen=True)
class Routed:
    """Event: which agent was picked."""
    name: str


class Assistant:
    def __init__(self, llm, specialists: list[Specialist], fallback: str):
        self.llm = llm
        self.specialists = {s.name: s for s in specialists}
        if len(self.specialists) != len(specialists):
            raise ValueError("two agents have the same name")
        if fallback not in self.specialists:
            raise ValueError(f"unknown fallback agent '{fallback}'")
        self.fallback = fallback
        self.last: str | None = None

        # One shared history, so a follow-up works whichever agent answers it.
        self.chat = specialists[0].agent.chat
        for s in specialists:
            s.agent.chat.turns = self.chat.turns

    async def run(self, question: str, think: bool = False) -> AsyncIterator[Event | Routed]:
        name = await self.pick(question)
        yield Routed(name)
        async for event in self.specialists[name].agent.run(question, think):
            yield event
        self.last = name

    async def pick(self, question: str) -> str:
        names = list(self.specialists)
        if len(names) == 1:
            return names[0]
        agents = "\n".join(f"- {s.name}: {s.handles}" for s in self.specialists.values())
        chosen = await self.llm.choose(
            [{"role": "system", "content": ROUTER_PROMPT.format(agents=agents)},
             {"role": "user", "content": self._context(question)}],
            names,
        )
        # The schema should make this impossible, but never trust model output.
        if chosen not in self.specialists:
            return self.last or self.fallback
        return chosen

    def _context(self, question: str) -> str:
        lines = []
        for turn in self.chat.turns[-RECENT_TURNS:]:
            lines.append(f"User: {turn[0]['content'][:MAX_CHARS]}")
            lines.append(f"Assistant: {turn[-1]['content'][:MAX_CHARS]}")
        earlier = "Conversation so far:\n" + "\n".join(lines) + "\n\n" if lines else ""
        return f"{earlier}Latest message: {question}"
