# Helper tool

A personal helper AI on a local Qwen model (through Ollama). A learning project.

## Run

```
source .venv/bin/activate
python lessons/01_raw_chat.py "your question"   # step 1
python -m helper.cli                            # the main assistant
python -m helper.cli football                   # only the football agent
python -m helper.cli general                    # only the plain helper
python -m evals.football                        # football question set (needs Ollama)
python -m evals.routing                         # router question set (needs Ollama)
python -m helper.football.teams                 # rebuild the team list
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

### Step 5: a real API (`football/`)
- `client.py` does everything about HTTP; `tools.py` only turns data into short text.
- **API key:** sent in the `X-Auth-Token` header over https. Never in the URL, where logs
  would keep it. Redirects are off, so it can't be forwarded to another address.
- **Rate limit:** 10 requests a minute. The response headers say how many are left. We wait
  up to 15 seconds, otherwise we tell the user how long to wait.
- **Cache:** the same question within 10 minutes reuses the answer.
- **Test the real API, don't only read the docs:** a wrong key returns 400 (not 401),
  World Cup standings returned 404, and the Champions League has one table of 36 teams.
- **Short results:** raw JSON is 5-10 KB; the Premier League table we send is about 1.3 KB.
- **The description is part of the program:** asked about the Turkish Super Lig, the model
  first fetched Italy's table. One sentence in the tool description stopped that.

### Step 6: five tools and the team list
- `get_standings`, `get_top_scorers`, `get_matches`, `get_team_matches`, `get_team_info`.
- **Names to ids:** the API only knows ids. `teams.py` saves all 246 teams in
  `data/teams.json` (12 requests, about a minute, refreshed weekly by the chat).
- **Never guess a team:** "Manchester" returns both options and the model asks you.
- **Code does the date arithmetic:** the model says `yesterday`, Python makes the dates.
- **Traps found by testing the real API:**
  - `dateTo` leaves out the end day. A first test suggested the opposite because of one
    match at 00:00 UTC. We ask for an extra day and filter by the local day.
  - A team's `limit` returns the *last* matches: "next 2" gave May of next year.
  - `fullTime` includes shoot-out goals: 1-1 (3-4 on penalties) is sent as 4-5.
  - National team pages are not in the free plan (403).
- **Right data can still mislead:** Galatasaray's Champions League match is not necessarily
  its next match, because its league isn't covered. The tool result now says so.

### Step 7: the football agent (`agents/football.py`)
- **An agent = prompt + tools + the generic loop.** The loop did not change per agent.
- **Unit tests vs evals:** unit tests check our code and always give the same result.
  Evals ask the real model, so each question is repeated. The football data in evals is
  invented, so a correct answer proves the model read the tool, not its memory.
- **Held-out questions** are never used for tuning, to see if a fix really generalizes.
- **More rules made it worse.** A strict ten-rule prompt dropped tool choice from 54/54 to
  39/54 and the model invented facts. A short "call the tool first" prompt fixed it.
- **Fix the tool before adding prompt text:**
  - A league we don't have made the model pick a wrong one. An `OTHER` choice fixed most cases.
  - It drifted to the wrong language. "Same language as the question" failed twice; code that
    detects the language and says "Answer the user in English." passed 20 of 20.
- **Must-haves belong in code:** the source and fetch time are added by code, not the model.
- **Reply length is capped**, since a timeout never fires while text keeps coming.
- **Known limits:** "Bundesliga 2" in Turkish is read as the first Bundesliga. Language
  detection covers only Turkish and English. Evals are not a guarantee.
- **Note:** a sleeping Mac pauses evals; some runs looked stuck for minutes because of that.

### Step 8 (first part): the main assistant (`assistant.py`)
- **Router:** one quick model call picks an agent from a fixed list, then that agent answers.
  The answer is not rewritten, so warnings and sources survive.
- **Structured output:** Ollama's `format` takes a JSON schema, and the model can only reply
  in that shape. We still check the result (`LLM.choose`).
- **Shared history:** all agents use one list of turns, so "and who is second?" works after a
  topic change. The router itself sees only the last two turns.
- **Adding an API:** write the agent like `agents/football.py`, then add one `Specialist` in
  `agents/team.py`. The router reads its `handles` text.
- **Known limits:** one agent per message. A question needing two live-data agents will need
  more work once there is a second API. After `/clear`, "and who is third?" makes the model
  assume the Premier League instead of asking.
