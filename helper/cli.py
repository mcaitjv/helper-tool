"""Terminal chat.  Run: python -m helper.cli"""
import asyncio
from datetime import datetime

from rich.console import Console

from helper.config import load_config
from helper.conversation import Conversation
from helper.llm import LLM, LLMError

HELP = "/think switch thinking on or off · /clear forget this chat · /quit leave"


def system_prompt() -> str:
    today = datetime.now().astimezone().strftime("%A, %d %B %Y")
    return (
        "You are a personal helper. Be brief and clear. "
        "Reply in the language the user writes in. "
        "If you don't know something, say so. "
        f"Today is {today}."
    )


async def answer(llm: LLM, chat: Conversation, think: bool, out: Console) -> str:
    """Stream one reply to the screen and return its full text."""
    text = ""
    async for chunk in llm.stream(chat.messages(), think=think):
        if chunk.thinking:
            out.print(chunk.thinking, end="", style="dim", markup=False, highlight=False)
        if chunk.text:
            if not text and think:
                out.print("\n")
            text += chunk.text
            out.print(chunk.text, end="", markup=False, highlight=False)
    out.print()
    return text


def main() -> None:
    config = load_config()
    llm, out = LLM(config), Console()
    chat = Conversation(system_prompt(), config.max_history_tokens)
    think = False
    out.print(f"[bold]Helper[/] · {config.model}\n[dim]{HELP}[/]")

    # Input stays outside the async part so Ctrl-C works at the prompt.
    with asyncio.Runner() as runner:
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
                chat.clear()
                out.print("[dim]forgotten[/]")
                continue
            if line.startswith("/"):
                out.print(f"[dim]{HELP}[/]")
                continue

            chat.add("user", line)
            try:
                chat.add("assistant", runner.run(answer(llm, chat, think, out)))
            except LLMError as e:
                chat.drop_last_turn()
                out.print(str(e), style="red", markup=False)
            except KeyboardInterrupt:
                chat.drop_last_turn()
                out.print("\n[dim]stopped[/]")
    out.print("[dim]bye[/]")


if __name__ == "__main__":
    main()
