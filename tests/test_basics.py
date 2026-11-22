import pytest

from helper.config import Config
from helper.conversation import Conversation
from helper.llm import LLM, LLMError


def user(text):
    return {"role": "user", "content": text}


def assistant(text):
    return {"role": "assistant", "content": text}


def test_key_is_hidden_when_config_is_printed():
    assert "secret123" not in repr(Config(football_key="secret123"))


def test_messages_are_system_then_history_then_current():
    chat = Conversation("sys", 1000)
    chat.add_turn([user("a"), assistant("b")])
    assert [m["content"] for m in chat.messages([user("c")])] == ["sys", "a", "b", "c"]


def test_trim_drops_oldest_whole_turns():
    chat = Conversation("sys", 150)
    for i in range(5):
        chat.add_turn([user(f"q{i} " + "x" * 60), assistant(f"a{i} " + "y" * 60)])
    kept = chat.messages([user("now")])
    assert kept[0]["role"] == "system"
    assert kept[1]["role"] == "user"      # never starts mid-turn
    assert kept[-2]["content"].startswith("a4")
    assert not any(m["content"].startswith("q0") for m in kept)


def test_current_turn_is_kept_even_if_too_big():
    chat = Conversation("sys", 10)
    chat.add_turn([user("old"), assistant("old")])
    assert [m["content"][:3] for m in chat.messages([user("x" * 500)])] == ["sys", "xxx"]


async def test_ollama_not_running_gives_clear_error():
    llm = LLM(Config(ollama_url="http://127.0.0.1:9"))
    with pytest.raises(LLMError, match="Can't reach Ollama"):
        async for _ in llm.stream([user("hi")]):
            pass
