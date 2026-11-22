"""All settings in one place. Secrets come from .env, never from code."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    model: str = "qwen3.5:9b"
    ollama_url: str = "http://localhost:11434"
    # repr=False keeps the key out of print(config) and tracebacks.
    football_key: str = field(default="", repr=False)

    # Low temperature = predictable. The model's own default is 1.
    temperature: float = 0.2
    presence_penalty: float = 0.0

    # Ollama's MLX runner loads this model with a 32K window and ignores
    # num_ctx, so we trim the history ourselves and leave room for the answer.
    max_history_tokens: int = 24_000
    request_timeout: float = 120.0


def load_config() -> Config:
    load_dotenv(ROOT / ".env")
    return Config(
        model=os.getenv("HELPER_MODEL", Config.model),
        ollama_url=os.getenv("OLLAMA_URL", Config.ollama_url),
        football_key=os.getenv("FOOTBALL_DATA_API_KEY", ""),
    )
