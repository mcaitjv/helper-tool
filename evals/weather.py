"""Question set for the weather agent. Needs Ollama, the weather server and internet.

Run:  python -m evals.weather [repeats]

Real weather changes, so we can't check exact answers. Instead: the right tool, the
right city, Celsius, and every temperature in the answer must appear in a tool result.
"""
import asyncio
import re
import sys

from helper.agent import Text, ToolFinished, ToolStarted
from helper.agents.weather import weather_agent
from helper.config import load_config
from helper.llm import LLM
from helper.mcp_client import McpServers
from helper.mcp_client import load_config as load_mcp_config
from helper.tools.weather_adapter import shape_weather_tools

# question, acceptable tools (None = no tool), a word the city argument must contain
QUESTIONS = [
    ("What's the weather in Istanbul right now?", {"get_current_conditions", "get_weather_summary"}, "istanbul"),
    ("Will it rain in London tomorrow?", {"get_forecast", "get_weather_summary"}, "london"),
    ("Yarın Ankara'da hava nasıl olacak?", {"get_forecast", "get_weather_summary"}, "ankara"),
    ("Do I need a coat in Berlin today?", {"get_current_conditions", "get_weather_summary", "get_forecast"}, "berlin"),
    ("How hot will it be in Madrid this weekend?", {"get_forecast", "get_weather_summary"}, "madrid"),
    ("Are there any weather warnings in Paris?", {"get_alerts", "get_weather_summary"}, "paris"),
    ("Is it windy in Izmir?", {"get_current_conditions", "get_weather_summary"}, "izmir"),
    ("What's the weather like?", None, ""),          # no place: should ask
    ("Who won the Champions League?", None, ""),      # not weather
]


def temperatures(text: str) -> set[str]:
    return set(re.findall(r"(-?\d+(?:\.\d+)?)\s*°", text))


async def main(repeats: int) -> None:
    servers = McpServers([c for c in load_mcp_config() if c.name == "weather"])
    await servers.start()
    if servers.problems:
        sys.exit("; ".join(servers.problems))
    llm, config = LLM(load_config()), load_config()
    tools = shape_weather_tools(servers.tools)
    good = total = 0
    try:
        for question, wanted, city in QUESTIONS:
            wrong = []
            for _ in range(repeats):
                agent = weather_agent(llm, config, tools)
                events = [e async for e in agent.run(question)]
                calls = [e for e in events if isinstance(e, ToolStarted)]
                results = "\n".join(e.content for e in events if isinstance(e, ToolFinished) and e.ok)
                answer = "".join(e.text for e in events if isinstance(e, Text))
                if wanted is None:
                    ok, why = not calls, "used a tool"
                else:
                    first = calls[0] if calls else None
                    invented = temperatures(answer) - temperatures(results)
                    checks = [
                        (first is not None and first.name in wanted, "wrong or no tool"),
                        (first is not None and city in str(first.arguments).lower()
                         .replace("i̇", "i").replace("ı", "i"), "wrong city"),
                        ("°F" not in answer and "mph" not in answer, "not metric"),
                        (not invented, f"temperatures not in tool result: {invented}"),
                    ]
                    ok = all(c for c, _ in checks)
                    why = "; ".join(w for c, w in checks if not c)
                good += ok
                total += 1
                if not ok:
                    wrong.append(f"{why} | {[f'{c.name}({c.arguments})' for c in calls]} | {answer[:160]!r}")
            print(f"  {repeats - len(wrong)}/{repeats}  {question}" + (f"\n        {wrong[0]}" if wrong else ""), flush=True)
    finally:
        await servers.stop()
    print(f"Weather {good}/{total}")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 2))
