"""The loop, tested with a scripted fake model: no Ollama needed."""
import pytest

from helper.agent import Agent, Text, ToolFinished, ToolStarted
from helper.conversation import Conversation
from helper.llm import Chunk, LLMError, ToolCall
from helper.tools.registry import Registry, Tool, ToolArgs, ToolError


class Args(ToolArgs):
    city: str


async def weather(args):
    if args.city == "Nowhere":
        raise ToolError("unknown city")
    return f"{args.city}: 20C"


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    async def stream(self, messages, think=False, tools=None):
        self.seen.append([dict(m) for m in messages])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        for chunk in reply:
            yield chunk


def call(city):
    return ToolCall("weather", {"city": city})


def say(text):
    return [Chunk(text=text)]


def use(*cities, **extra):
    return [Chunk(tool_calls=[call(c) for c in cities], **extra)]


def make(*replies, **kw):
    llm = FakeLLM(*replies)
    chat = Conversation("sys", 10_000)
    return Agent(llm, Registry(Tool("weather", "w", Args, weather)), chat, **kw), llm, chat


async def collect(agent, question="q"):
    return [e async for e in agent.run(question)]


async def test_no_tool():
    agent, _, chat = make(say("hello"))
    assert await collect(agent) == [Text("hello")]
    assert [m["role"] for m in chat.turns[0]] == ["user", "assistant"]


async def test_one_tool_result_goes_back_to_the_model():
    agent, llm, chat = make(use("Rome", thinking="hmm"), say("20C"))
    events = await collect(agent)
    assert ToolStarted("weather", {"city": "Rome"}) in events
    assert ToolFinished("weather", True, "Rome: 20C") in events
    sent = llm.seen[1]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "tool"]
    assert sent[2]["thinking"] == "hmm"          # kept within the turn...
    assert "thinking" not in chat.turns[0][1]    # ...dropped from the history
    assert sent[3]["content"] == "Rome: 20C"


async def test_two_calls_in_one_reply():
    agent, llm, _ = make(use("Rome", "Oslo"), say("done"))
    await collect(agent)
    assert [m["content"] for m in llm.seen[1] if m["role"] == "tool"] == ["Rome: 20C", "Oslo: 20C"]


async def test_tool_error_lets_the_model_retry():
    agent, _, _ = make(use("Nowhere"), use("Rome"), say("20C"))
    results = [e.ok for e in await collect(agent) if isinstance(e, ToolFinished)]
    assert results == [False, True]


async def test_step_limit():
    agent, llm, chat = make(*[use("Rome")] * 10, max_rounds=3)
    events = await collect(agent)
    assert len(llm.seen) == 3
    assert "stopped after 3" in events[-1].text
    assert chat.turns[0][-1]["role"] == "assistant"


async def test_empty_reply_is_reported():
    agent, _, _ = make(say(""))
    assert "couldn't produce" in (await collect(agent))[0].text


async def test_failed_turn_is_not_saved():
    agent, _, chat = make(use("Rome"), LLMError("down"), say("ok"))
    with pytest.raises(LLMError):
        await collect(agent)
    assert chat.turns == []
    assert await collect(agent, "again") == [Text("ok")]
