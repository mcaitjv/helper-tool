"""The only file that talks to Ollama."""
import json
from collections.abc import AsyncIterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx
import ollama

from helper.config import Config


class LLMError(Exception):
    """A problem we can explain to the user in one sentence."""


@dataclass
class ToolCall:
    """The model asking us to run something."""
    name: str
    arguments: dict


@dataclass
class Chunk:
    """A small piece of a streamed reply."""
    text: str = ""
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@contextmanager
def clear_errors(config: Config):
    """Turn technical errors into one sentence."""
    try:
        yield
    except ollama.ResponseError as e:
        if e.status_code == 404:
            raise LLMError(f"Model '{config.model}' not found. Check: ollama list") from e
        raise LLMError(f"Ollama returned an error: {e.error}") from e
    except httpx.TimeoutException as e:
        raise LLMError("The model took too long to answer.") from e
    except (ConnectionError, httpx.HTTPError) as e:
        raise LLMError(
            f"Can't reach Ollama at {config.ollama_url}. Is the Ollama app running?"
        ) from e


class LLM:
    def __init__(self, config: Config):
        self.config = config

    async def stream(
        self, messages: list[dict], think: bool = False, tools: list[dict] | None = None
    ) -> AsyncIterator[Chunk]:
        # A new client per call, because each CLI turn is a separate async run.
        client = ollama.AsyncClient(
            host=self.config.ollama_url, timeout=self.config.request_timeout
        )
        with clear_errors(self.config):
            reply = await client.chat(
                model=self.config.model,
                messages=messages,
                tools=tools or None,
                think=think,
                stream=True,
                options={
                    "temperature": self.config.temperature,
                    "presence_penalty": self.config.presence_penalty,
                    "num_predict": self.config.max_thinking_tokens if think
                    else self.config.max_answer_tokens,
                },
            )
            async for part in reply:
                yield Chunk(
                    text=part.message.content or "",
                    thinking=part.message.thinking or "",
                    tool_calls=[
                        ToolCall(c.function.name, dict(c.function.arguments))
                        for c in part.message.tool_calls or []
                    ],
                )
                if part.done_reason == "length":
                    yield Chunk(text="\n[answer cut: it was too long]")

    async def choose(self, messages: list[dict], options: list[str]) -> str:
        """Make the model pick one option. Returns "" if it gave something unusable."""
        client = ollama.AsyncClient(
            host=self.config.ollama_url, timeout=self.config.request_timeout
        )
        schema = {
            "type": "object",
            "properties": {"choice": {"type": "string", "enum": options}},
            "required": ["choice"],
        }
        with clear_errors(self.config):
            reply = await client.chat(
                model=self.config.model, messages=messages, think=False, format=schema,
                options={"temperature": 0, "num_predict": 50},
            )
        try:
            choice = json.loads(reply.message.content or "")["choice"]
        except (ValueError, KeyError, TypeError):
            return ""
        return choice if choice in options else ""
