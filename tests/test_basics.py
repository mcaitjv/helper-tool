import pytest

from helper.config import Config
from helper.conversation import Conversation
from helper.llm import LLM, LLMError


def test_key_is_hidden_when_config_is_printed():
    assert "secret123" not in repr(Config(football_key="secret123"))


def test_messages_start_with_system_and_keep_order():
    chat = Conversation("sys", 1000)
    chat.add("user", "a")
    chat.add("assistant", "b")
    assert [m["content"] for m in chat.messages()] == ["sys", "a", "b"]


def test_trim_drops_oldest_whole_turns():
    chat = Conversation("sys", 100)
    for i in range(5):
        chat.add("user", f"q{i} " + "x" * 60)
        chat.add("assistant", f"a{i} " + "y" * 60)
    kept = chat.messages()
    assert kept[0]["role"] == "system"
    assert kept[1]["role"] == "user"      # never starts mid-turn
    assert kept[-1]["content"].startswith("a4")
    assert chat._size() <= 100


def test_trim_keeps_latest_turn_even_if_too_big():
    chat = Conversation("sys", 10)
    chat.add("user", "x" * 500)
    assert len(chat.messages()) == 2


def test_drop_last_turn():
    chat = Conversation("sys", 1000)
    chat.add("user", "a")
    chat.add("assistant", "b")
    chat.add("user", "c")
    chat.drop_last_turn()
    assert [m["content"] for m in chat.history] == ["a", "b"]


async def test_ollama_not_running_gives_clear_error():
    llm = LLM(Config(ollama_url="http://127.0.0.1:9"))
    with pytest.raises(LLMError, match="Can't reach Ollama"):
        async for _ in llm.stream([{"role": "user", "content": "hi"}]):
            pass
