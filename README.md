# Helper tool

A personal helper AI on a local Qwen model (through Ollama). A learning project.

## Run

```
source .venv/bin/activate
python lessons/01_raw_chat.py "your question"   # step 1
python -m helper.cli                            # the chat
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

### Step 3: the tool registry (`tools/registry.py`)
- A tool = name + description + arguments + a Python function.
- Arguments are a Pydantic class. It produces the **schema** the model reads *and*
  **validates** what the model sends back, since models can send wrong arguments.
- The Ollama client drops `minimum`, `maximum` and `default` from schemas, so limits
  also go in the description text.
- Expected errors (`ToolError`) are explained to the model. Unexpected ones are logged
  and hidden, so secrets can't leak into the chat.

### Step 4: the agent loop (`agent.py`)
1. Send messages + tool schemas to the model.
2. No tool calls in the reply? That is the answer, stop.
3. Otherwise run each tool, add its result with the role `tool`, and go back to 1.
- At most 6 rounds, so it can't loop forever.
- The loop prints nothing. It yields **events** and the CLI draws them.
- A turn is saved only when it finishes, so errors and Ctrl-C leave no half turns.
- Tests use a fake, scripted model, so they are fast and repeatable.
