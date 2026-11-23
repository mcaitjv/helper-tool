"""Question set for the router. Needs Ollama.

Run:  python -m evals.routing [repeats]
"""
import asyncio
import re
import sys

from evals.football import INDEX, FakeClient
from helper.agent import Agent, Text
from helper.agents.team import main_assistant
from helper.assistant import Specialist
from helper.config import load_config
from helper.conversation import Conversation
from helper.llm import LLM
from helper.tools.registry import Registry

# (earlier turns, message, expected agent)
FB = [("Who leads the Premier League?", "Burnley leads with 27 points.")]
TIME = [("What time is it in Tokyo?", "It is 21:49 in Tokyo.")]

TUNING = [
    ([], "Who leads La Liga?", "football"),
    ([], "Arsenal'in sıradaki maçı ne zaman?", "football"),
    ([], "Who won the 2022 World Cup?", "football"),
    ([], "What's the Süper Lig table?", "football"),
    ([], "Is Haaland injured?", "football"),
    ([], "When do Arsenal play?", "football"),
    ([], "hello", "general"),
    ([], "merhaba", "general"),
    ([], "What time is it in Tokyo?", "general"),
    ([], "Write a short poem about the sea", "general"),
    ([], "What is 17 * 23?", "general"),
    ([], "What's the weather in Istanbul?", "general"),
    ([], "Who won the NBA finals?", "general"),
    (FB, "and who is second?", "football"),
    (FB, "peki ikinci kim?", "football"),
    (FB, "thanks!", "general"),
    (FB, "What time is it in London?", "general"),
    (TIME, "and in London?", "general"),
    (TIME, "Who coaches Chelsea?", "football"),
    (FB + TIME, "who is second in that league?", "football"),
    ([], "Who leads La Liga and what is 17 * 23?", "football"),
    ([], "Say hi in French and tell me when Arsenal plays", "football"),
    ([], "What time is it in Tokyo and what is 2 + 2?", "general"),
    (FB, "Write a two line poem about the sea", "general"),
]
HELD_OUT = [
    ([], "Top scorers in Serie A?", "football"),
    ([], "Did Galatasaray win?", "football"),
    ([], "Bugün hangi maçlar var?", "football"),
    ([], "Who is the manager of Liverpool?", "football"),
    ([], "How many teams are in the Bundesliga?", "football"),
    ([], "Translate 'good morning' to Turkish", "general"),
    ([], "Explain what an API is", "general"),
    ([], "What day is it today?", "general"),
    ([], "Who won the Formula 1 race?", "general"),
    ([], "Tell me about Barcelona's beaches", "general"),
    (FB, "what about yesterday's results?", "football"),
    (FB, "now explain recursion", "general"),
    (TIME, "Is Real Madrid playing tonight?", "football"),
    (TIME, "and what's the date there?", "general"),
    ([], "Convert 10 miles to km, and who is top scorer in La Liga?", "football"),
    ([], "Tell me a joke and what day it is", "general"),
]
# A pretend third agent, to see whether adding an API later will work.
THIRD = [
    ([], "Do I need an umbrella in Istanbul?", "weather"),
    ([], "Yarın hava nasıl olacak?", "weather"),
    ([], "Who leads La Liga?", "football"),
    ([], "hello", "general"),
    ([("Will it rain in Paris?", "No, it stays dry.")], "and tomorrow?", "weather"),
    ([("Will it rain in Paris?", "No, it stays dry.")], "When does PSG play?", "football"),
]


def build(llm, config):
    return main_assistant(llm, config, FakeClient(), lambda: INDEX)


async def section(title, assistant, cases, repeats):
    good = 0
    print(title)
    for earlier, question, expected in cases:
        assistant.chat.clear()
        for q, a in earlier:
            assistant.chat.add_turn([{"role": "user", "content": q},
                                     {"role": "assistant", "content": a}])
        got = [await assistant.pick(question) for _ in range(repeats)]
        good += got.count(expected)
        if got.count(expected) < repeats:
            print(f"  {got.count(expected)}/{repeats}  {question}  (after {len(earlier)} turns) got {got}")
    print(f"  {good}/{len(cases) * repeats}")


# Whole chats through router and agents, with invented football data.
CHATS = [
    ("switch topic and come back",
     ["Who leads the Premier League?", "What time is it in Tokyo?",
      "Who is second in the Premier League?"], lambda t: "Luton" in t),
    ("short follow-up", ["Who leads the Premier League?", "and who is second?"],
     lambda t: "Luton" in t),
    ("general agent works after football", ["Who coaches Arsenal?", "What is 17 * 23?"],
     lambda t: "391" in t),
    ("time question after football goes to the time tools",
     ["Who coaches Arsenal?", "What time is it in Tokyo?"], lambda t: bool(re.search(r"\d{1,2}:\d\d", t))),
    ("no invented weather", ["What's the weather in Istanbul now?"], lambda t: "°" not in t),
    ("no football from memory", ["hello", "Who won the 2022 World Cup?"],
     lambda t: "Argentina" not in t),
]


async def chats(llm, config, repeats):
    good = 0
    print("Whole chats")
    for name, questions, check in CHATS:
        wrong = []
        for _ in range(repeats):
            assistant = build(llm, config)
            for q in questions:
                events = [e async for e in assistant.run(q)]
            text = "".join(e.text for e in events if isinstance(e, Text))
            if check(text):
                good += 1
            else:
                wrong.append(text[:200])
        if wrong:
            print(f"  {repeats - len(wrong)}/{repeats}  {name}\n        got {wrong[0]!r}")
    print(f"  {good}/{len(CHATS) * repeats}")


async def main(repeats):
    config = load_config()
    llm = LLM(config)
    assistant = build(llm, config)
    await section("Tuning questions", assistant, TUNING, repeats)
    await section("Held-out questions", assistant, HELD_OUT, repeats)
    extra = Agent(llm, Registry(), Conversation("", 1000))
    extra.chat.turns = assistant.chat.turns
    assistant.specialists["weather"] = Specialist(
        "weather", "weather: temperature, rain, wind, forecasts", extra)
    await section("With a pretend weather agent", assistant, THIRD, repeats)
    await chats(llm, config, repeats)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
