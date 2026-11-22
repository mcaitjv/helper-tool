"""The only file that talks to Ollama."""
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import ollama

from helper.config import Config


class LLMError(Exception):
    """A problem we can explain to the user in one sentence."""


@dataclass
class Chunk:
    """A small piece of a streamed reply."""
    text: str = ""
    thinking: str = ""


class LLM:
    def __init__(self, config: Config):
        self.config = config

    async def stream(self, messages: list[dict], think: bool = False) -> AsyncIterator[Chunk]:
        # A new client per call, because each CLI turn is a separate async run.
        client = ollama.AsyncClient(
            host=self.config.ollama_url, timeout=self.config.request_timeout
        )
        try:
            reply = await client.chat(
                model=self.config.model,
                messages=messages,
                think=think,
                stream=True,
                options={
                    "temperature": self.config.temperature,
                    "presence_penalty": self.config.presence_penalty,
                },
            )
            async for part in reply:
                yield Chunk(text=part.message.content or "",
                            thinking=part.message.thinking or "")
        except ollama.ResponseError as e:
            if e.status_code == 404:
                raise LLMError(f"Model '{self.config.model}' not found. Check: ollama list") from e
            raise LLMError(f"Ollama returned an error: {e.error}") from e
        except httpx.TimeoutException as e:
            raise LLMError("The model took too long to answer.") from e
        except (ConnectionError, httpx.HTTPError) as e:
            raise LLMError(
                f"Can't reach Ollama at {self.config.ollama_url}. Is the Ollama app running?"
            ) from e
