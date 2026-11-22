# Helper tool

A personal helper AI on a local Qwen model (through Ollama). A learning project.

## Run

```
source .venv/bin/activate
python lessons/01_raw_chat.py "your question"   # step 1
python -m helper.cli                            # step 2
python -m pytest                                # tests
```

First time on another machine: `python3 -m venv .venv`, activate it,
`pip install -e ".[dev]"`, and copy `.env.example` to `.env`.

## Learning notes

### Step 1: one raw request
- Ollama is a local web server. Chatting is one POST to `/api/chat`.
- `messages` is a list with roles: `system` (our rules), `user`, `assistant`.
- Models read and write **tokens**, pieces of words.

### Step 2: a real chat
- **The model has no memory.** `conversation.py` resends the history each time.
  `/clear` empties that list, and the model "forgets".
- **Streaming** shows text as it is produced instead of waiting for the end.
- **The context window is limited.** Ollama's MLX runner uses 32K tokens here and
  ignores `num_ctx` (tested with 2048 and 16384), so we drop the oldest turns ourselves.
- **Thinking** is text the model writes before answering. We show it but do not
  store it in the history.
- **Only `llm.py` knows about Ollama**, so the model server can be swapped later.
