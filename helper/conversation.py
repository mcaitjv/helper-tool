"""The chat history. The model has no memory: we resend this every time."""


def estimate_tokens(message: dict) -> int:
    # English is about 4.5 characters per token here; 3 is deliberately cautious.
    return len(message["content"]) // 3 + 4


class Conversation:
    def __init__(self, system_prompt: str, max_tokens: int):
        self.system = {"role": "system", "content": system_prompt}
        self.max_tokens = max_tokens
        self.history: list[dict] = []

    def add(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def drop_last_turn(self) -> None:
        """Forget the latest question, e.g. after an error or Ctrl-C."""
        while self.history and self.history.pop()["role"] != "user":
            pass

    def clear(self) -> None:
        self.history.clear()

    def messages(self) -> list[dict]:
        """System prompt + as much recent history as fits. Trims old turns."""
        while self._size() > self.max_tokens:
            next_turn = next(
                (i for i, m in enumerate(self.history) if i > 0 and m["role"] == "user"), None
            )
            if next_turn is None:  # always keep the latest turn
                break
            del self.history[:next_turn]
        return [self.system, *self.history]

    def _size(self) -> int:
        return sum(estimate_tokens(m) for m in [self.system, *self.history])
