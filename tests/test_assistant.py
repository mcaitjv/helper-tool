"""The router, tested with a fake model."""
import httpx
import ollama
import pytest

from helper.agent import Agent, Text
from helper.assistant import Assistant, Routed, Specialist
from helper.config import Config
from helper.conversation import Conversation
from helper.llm import LLM, Chunk, LLMError
from helper.tools.registry import Registry


class FakeLLM:
    def __init__(self, *choices):
        self.choices, self.asked, self.prompts = list(choices), [], []

    async def choose(self, messages, options):
        self.asked.append((messages, options))
        choice = self.choices.pop(0)
        if isinstance(choice, Exception):
            raise choice
        return choice

    async def stream(self, messages, think=False, tools=None):
        self.prompts.append([m["content"] for m in messages])
        if "fail" in messages[-1]["content"]:
            raise LLMError("down")
        yield Chunk(text=f"answer from {messages[0]['content']}")


def make(*choices):
    llm = FakeLLM(*choices)
    team = [Specialist(n, f"about {n}", Agent(llm, Registry(), Conversation(n, 10_000)))
            for n in ("football", "general")]
    return Assistant(llm, team, fallback="general"), llm


async def ask(assistant, question):
    return [e async for e in assistant.run(question)]


async def test_the_chosen_agent_answers():
    assistant, llm = make("football")
    assert await ask(assistant, "q") == [Routed("football"), Text("answer from football")]
    messages, options = llm.asked[0]
    assert options == ["football", "general"]
    assert "- football: about football" in messages[0]["content"]
    assert messages[1]["content"] == "Latest message: q"


async def test_history_is_shared_between_agents():
    assistant, llm = make("football", "general")
    await ask(assistant, "q1")
    await ask(assistant, "q2")
    assert llm.prompts[1] == ["general", "q1", "answer from football", "q2"]
    assert "User: q1\nAssistant: answer from football" in llm.asked[1][0][1]["content"]


async def test_clear_forgets_everywhere():
    assistant, llm = make("football", "general")
    await ask(assistant, "q1")
    assistant.chat.clear()
    await ask(assistant, "q2")
    assert llm.prompts[1] == ["general", "q2"]
    assert llm.asked[1][0][1]["content"] == "Latest message: q2"


async def test_router_sees_only_recent_short_text():
    assistant, llm = make(*["football"] * 4)
    for i in range(3):
        await ask(assistant, f"q{i} " + "x" * 1000)
    await ask(assistant, "now")
    context = llm.asked[3][0][1]["content"]
    assert "q0" not in context and "q1" in context and len(context) < 1_500


@pytest.mark.parametrize("bad", ["", "weather"])
async def test_unusable_choice_stays_with_the_last_agent(bad):
    assistant, _ = make(bad, "football", bad)
    assert (await ask(assistant, "a"))[0] == Routed("general")   # nothing yet: fallback
    assert (await ask(assistant, "b"))[0] == Routed("football")
    assert (await ask(assistant, "c"))[0] == Routed("football")


async def test_errors_leave_no_half_turn():
    assistant, _ = make(LLMError("down"), "football", "general")
    with pytest.raises(LLMError):
        await ask(assistant, "q")
    with pytest.raises(LLMError):
        await ask(assistant, "fail")
    assert assistant.chat.turns == [] and assistant.last is None


async def test_one_agent_needs_no_router():
    llm = FakeLLM()
    only = Specialist("general", "x", Agent(llm, Registry(), Conversation("general", 100)))
    assert (await ask(Assistant(llm, [only], "general"), "q"))[0] == Routed("general")
    assert llm.asked == []


def test_setup_mistakes_are_caught():
    a = Specialist("a", "x", Agent(None, Registry(), Conversation("s", 10)))
    with pytest.raises(ValueError, match="same name"):
        Assistant(None, [a, a], "a")
    with pytest.raises(ValueError, match="fallback"):
        Assistant(None, [a], "b")


@pytest.mark.parametrize("content, expected", [
    ('{"choice": "a"}', "a"), ('{"choice": "z"}', ""), ('{"x": 1}', ""),
    ("not json", ""), ("[]", ""), ("", ""), ('{"choice": ["a"]}', ""),
])
async def test_choose_never_returns_something_else(monkeypatch, content, expected):
    async def chat(self, **kw):
        return ollama.ChatResponse(message=ollama.Message(role="assistant", content=content))

    monkeypatch.setattr(ollama.AsyncClient, "chat", chat)
    assert await LLM(Config()).choose([], ["a", "b"]) == expected


async def test_choose_gives_clear_errors(monkeypatch):
    async def chat(self, **kw):
        raise httpx.ReadTimeout("t")

    monkeypatch.setattr(ollama.AsyncClient, "chat", chat)
    with pytest.raises(LLMError, match="too long"):
        await LLM(Config()).choose([], ["a"])
