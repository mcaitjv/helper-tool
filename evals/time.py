"""Question set for the MCP time tools. Needs Ollama and the time server.

Run:  python -m evals.time [repeats] [--builtin]
      --builtin uses our own clock instead of the MCP server
"""
import asyncio
import sys
from datetime import datetime

from helper.agents.general import general_prompt
from helper.config import load_config
from helper.llm import LLM
from helper.mcp_client import McpServers
from helper.mcp_client import load_config as load_mcp_config
from helper.tools.registry import Registry

# question, expected tool, expected arguments (subset)
QUESTIONS = [
    ("What time is it in Tokyo?", "get_current_time", {"timezone": "Asia/Tokyo"}),
    ("Saat kaç?", "get_current_time", {}),
    ("What time is it in New York right now?", "get_current_time",
     {"timezone": "America/New_York"}),
    ("If it's 15:00 in Istanbul, what time is it in London?", "convert_time",
     {"source_timezone": "Europe/Istanbul", "time": "15:00", "target_timezone": "Europe/London"}),
    ("A match starts at 20:45 in Madrid. What time is that in Istanbul?", "convert_time",
     {"source_timezone": "Europe/Madrid", "time": "20:45", "target_timezone": "Europe/Istanbul"}),
    ("What was the time 5 hours ago in UTC?", "get_time_ago", {"timezone": "UTC", "hours_ago": 5}),
    ("What time is it?", "get_current_time", {}),
    # Today's date is in the prompt, so answering without a tool is fine here.
    ("Bugün günlerden ne?", "ANY", {}),
    ("hello", None, {}),
]


async def main(repeats: int, builtin: bool) -> None:
    servers = McpServers([] if builtin else load_mcp_config())
    await servers.start()
    if servers.problems:
        sys.exit("; ".join(servers.problems))
    try:
        from helper.tools.clock import get_current_time
        llm = LLM(load_config())
        tools = Registry(get_current_time) if builtin else Registry(*servers.tools)
        questions = [q for q in QUESTIONS if not builtin or q[1] in (None, "ANY", "get_current_time")]
        prompt, good = general_prompt(datetime.now().astimezone()), 0
        for question, name, expected in questions:
            right, seen = 0, []
            for _ in range(repeats):
                messages = [{"role": "system", "content": prompt},
                            {"role": "user", "content": question}]
                calls = []
                async for chunk in llm.stream(messages, False, tools.schemas()):
                    calls += chunk.tool_calls
                ok = True if name == "ANY" else (not calls) if name is None else (
                    len(calls) == 1 and calls[0].name == name
                    and all(calls[0].arguments.get(k) == v for k, v in expected.items()))
                right += ok
                if not ok:
                    seen.append([f"{c.name}({c.arguments})" for c in calls] or "no tool")
            good += right
            print(f"  {right}/{repeats}  {question}" + (f"\n        got {seen[0]}" if seen else ""))
        print(f"Time tools {good}/{len(questions) * repeats}")
    finally:
        await servers.stop()


if __name__ == "__main__":
    numbers = [a for a in sys.argv[1:] if a.isdigit()]
    asyncio.run(main(int(numbers[0]) if numbers else 3, "--builtin" in sys.argv))
