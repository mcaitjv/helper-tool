"""Lesson 1: talk to the model with nothing but an HTTP request.

Run:
    source .venv/bin/activate
    python lessons/01_raw_chat.py "your question"
"""
import json
import sys

import httpx

question = sys.argv[1] if len(sys.argv) > 1 else "Explain what an API is in one sentence."

request = {
    "model": "qwen3.5:9b",
    "messages": [
        # "system" = instructions from us, "user" = the human.
        # The model's replies come back with the role "assistant".
        {"role": "system", "content": "You are a brief, friendly helper. Use only api for football related questions."},
        {"role": "user", "content": question},
    ],
    "stream": False,  # wait for the whole answer
    "think": False,   # skip the model's private reasoning text
}

print("--- REQUEST\n" + json.dumps(request, indent=2, ensure_ascii=False))

response = httpx.post("http://localhost:11434/api/chat", json=request, timeout=120)
response.raise_for_status()
data = response.json()

print("\n--- RESPONSE\n" + json.dumps(data, indent=2, ensure_ascii=False))

# Ollama reports times in nanoseconds.
seconds = data["eval_duration"] / 1e9
print("\n--- ANSWER\n" + data["message"]["content"])
print(f"\ntokens read: {data['prompt_eval_count']}, tokens written: {data['eval_count']}, "
      f"speed: {data['eval_count'] / seconds:.0f} tokens/s")
