# MCS examples

Two end-to-end demos. Both default to **mock mode** (no API key, no
network); switch to **real mode** by setting environment variables —
either inline or via a `.env` file at the project root.

## Quick start

### Option A — `.env` at project root (recommended for repeated runs)

Copy the template and fill in your DeepSeek key:

```bash
cp .env.example .env
# edit .env to set:
#   DEEPSEEK_API_KEY=sk-...
#   DEEPSEEK_MODEL=deepseek-chat  (or another model id)
#   MCS_LLM_MODE=real
```

Then just:

```bash
python examples/basic_usage.py
python examples/wiki_example.py
```

`.env` is `.gitignore`'d so the key never reaches git.

### Option B — inline env vars (one-off)

```bash
MCS_LLM_MODE=real DEEPSEEK_API_KEY=sk-... python examples/basic_usage.py
```

Inline env vars override `.env` values, so you can keep `.env` set to
mock mode and only override for ad-hoc runs.

## basic_usage.py

Three `ingest()` calls + one `query()`. Demonstrates that `query()`
returns `List[Node]` (memory) by default.

## wiki_example.py

Three document chunks ingested with `doc_id` / `chunk_id` metadata, then
a two-turn query showing how to pass the first turn's result back as
`existing_context` to continue the thread on the second turn.

## Mode / variable summary

| Variable | Default | Effect |
|----------|---------|--------|
| `MCS_LLM_MODE` | `mock` | `mock` = scripted MockLLM, no network. `real` = DeepSeekLLMPlugin. |
| `DEEPSEEK_API_KEY` | _(unset)_ | Required when `MCS_LLM_MODE=real`. |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek model id used in real mode. |

## What you should see

In **mock mode** the demos verify that the framework wiring (plugin
chains, pipeline orchestration, `WriteContext` flow, `QueryContext`
flow) is intact. The "intelligence" is scripted, so don't read too much
into the specific names returned.

In **real mode** the LLM does the actual concept extraction / relation
judgment / direction selection. Output quality depends on the prompts
in `mcs/prompts/` and the model behind `DeepSeekLLMPlugin`.
