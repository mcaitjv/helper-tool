"""The chat history. The model has no memory: we resend this every time."""
import json


def estimate_tokens(message: dict) -> int:
    # English is about 4.5 characters per token here; 3 is deliberately cautious.
    size = len(message["content"]) + len(message.get("thinking", ""))
    if "tool_calls" in message:
        size += len(json.dumps(message["tool_calls"]))
    return size // 3 + 4


class Conversation:
    def __init__(self, system_prompt: str, max_tokens: int):
        self.system = {"role": "system", "content": system_prompt}
        self.max_tokens = max_tokens
        # One turn = a question, any tool calls and results, and the answer.
        self.turns: list[list[dict]] = []

    def add_turn(self, turn: list[dict]) -> None:
        self.turns.append(turn)

    def clear(self) -> None:
        self.turns.clear()

    def messages(self, current: list[dict]) -> list[dict]:
        """System prompt + as many past turns as fit + the turn in progress."""
        used = sum(estimate_tokens(m) for m in [self.system, *current])
        kept: list[dict] = []
        for turn in reversed(self.turns):  # newest first
            used += sum(estimate_tokens(m) for m in turn)
            if used > self.max_tokens:
                break
            kept = turn + kept
        return [self.system, *kept, *current]
