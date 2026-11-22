"""Terminal chat.

Run:  python -m helper.cli            the football agent
      python -m helper.cli general    the plain helper
"""
import argparse
import asyncio
from datetime import datetime

from rich.console import Console

from helper.agent import Agent, Sources, Text, Thinking, ToolFinished, ToolStarted
from helper.agents.football import football_agent, football_registry
from helper.agents.general import general_agent
from helper.config import load_config
from helper.football.client import FootballClient, FootballError
from helper.football.teams import TeamIndex, build_index, load_index
from helper.llm import LLM, LLMError

HELP = "/think switch thinking on or off · /clear forget this chat · /quit leave"


async def show(agent: Agent, question: str, think: bool, out: Console) -> None:
    """Run the agent and draw its events."""
    previous = None
    async for event in agent.run(question, think):
        # Start a new line when switching between thinking, tools and text.
        if previous in (Text, Thinking) and type(event) is not previous:
            out.print()
        previous = type(event)
        match event:
            case Thinking(text):
                out.print(text, end="", style="dim", markup=False, highlight=False)
            case Text(text):
                out.print(text, end="", markup=False, highlight=False)
            case ToolStarted(name, arguments):
                args = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
                out.print(f"→ {name}({args})", style="yellow", markup=False, highlight=False)
            case ToolFinished(_, ok, content):
                short = content if len(content) <= 200 else content[:200] + "…"
                out.print(f"← {short}", style="dim" if ok else "red",
                          markup=False, highlight=False)
            case Sources(lines):
                for line in lines:
                    out.print(line, style="dim", markup=False, highlight=False)
    if previous in (Text, Thinking):
        out.print()


def prepare_teams(client: FootballClient, runner: asyncio.Runner, out: Console) -> TeamIndex | None:
    """Load the team list, rebuilding it when missing or a week old."""
    index = load_index()
    if index and not index.is_old(datetime.now().astimezone()):
        return index
    out.print("[dim]Updating the team list, about a minute (Ctrl-C to skip)[/]")
    try:
        return runner.run(build_index(client, report=lambda s: out.print(f"[dim]  {s}[/]")))
    except FootballError as e:
        out.print(str(e), style="red", markup=False)
    except KeyboardInterrupt:
        out.print("[dim]skipped[/]")
    return index  # an old list is better than none


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m helper.cli")
    parser.add_argument("agent", nargs="?", choices=["football", "general"], default="football")
    which = parser.parse_args().agent

    config = load_config()
    out = Console()
    llm = LLM(config)
    think = False
    out.print(f"[bold]Helper[/] · {which} · {config.model}\n[dim]{HELP}[/]")

    # Input stays outside the async part so Ctrl-C works at the prompt.
    with asyncio.Runner() as runner:
        if which == "football":
            client = FootballClient(config.football_key)
            teams = prepare_teams(client, runner, out)
            agent = football_agent(llm, config, football_registry(client, lambda: teams))
        else:
            agent = general_agent(llm, config)
        while True:
            try:
                line = out.input("\n[bold cyan]you>[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line in ("/quit", "/exit"):
                break
            if line == "/think":
                think = not think
                out.print(f"[dim]thinking {'on' if think else 'off'}[/]")
                continue
            if line == "/clear":
                agent.chat.clear()
                out.print("[dim]forgotten[/]")
                continue
            if line.startswith("/"):
                out.print(f"[dim]{HELP}[/]")
                continue

            try:
                runner.run(show(agent, line, think, out))
            except LLMError as e:
                out.print(str(e), style="red", markup=False)
            except KeyboardInterrupt:
                out.print("\n[dim]stopped[/]")
    out.print("[dim]bye[/]")


if __name__ == "__main__":
    main()
