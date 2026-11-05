# runpod-code

Set up a coding agent against Kimi models on a [Runpod Public Endpoint](https://docs.runpod.io), for example as a backup when your usual coding assistant is down.

```
./runpod-code setup            # check your key, install OpenCode, write a config with cost tracking
./runpod-code models --live    # list models and prices, and diff against the live endpoint
./runpod-code claude           # start an Anthropic-to-OpenAI proxy and run the Claude Code CLI through it
```

## Requirements

- macOS or Linux with `bash`, `curl` and `python3`
- A Runpod API key in `RUNPOD_API_KEY` (or `setup` will prompt for it)
- OpenCode (`setup` can install it with Homebrew), and/or the Claude Code CLI plus [LiteLLM](https://docs.litellm.ai) (the `claude` command offers to install LiteLLM into a virtualenv)

Your key is never written into the generated config (it references `{env:RUNPOD_API_KEY}`). `setup` offers to append an `export` line to `~/.zshenv` if you typed the key at the prompt.

## Models and prices

Models, per-token prices and a `status` live in `models.json`. Only `kimi-k3.1-pro` is marked `verified`; the others are `untested` and have no cache prices (the tool warns about that). Prices are USD per 1M tokens from the Runpod catalog on 2026-11-04 and change, so check the Runpod console.

## Cost tracking

- OpenCode: the generated config includes a `cost` block, so `opencode run --format json "task"` reports a cost on each `step_finish` event.
- Claude Code: the proxy returns `x-litellm-response-cost-original` per request. Claude Code's own cost readout is not reliable for non-Anthropic models.
- The Runpod billing page is the source of truth.

## What was tested

- `setup`: bad key, dummy key, merge into an existing OpenCode config, real key
- `models --live`
- An OpenCode run with the generated config
- A Claude Code CLI 2.1.311 run through the proxy wrapper (5 turns, fixed a seeded bug, no Anthropic login)

Not tested: the LiteLLM install step, a clean machine, the interactive key prompt, Linux, and any model other than `kimi-k3.1-pro`.

## Known behavior

- The endpoint has no Anthropic `/v1/messages` route and no OpenAI `/responses` route, only `/chat/completions`. So Claude Code needs the proxy, and the proxy must use LiteLLM's `hosted_vllm/` provider prefix (the `openai/` prefix calls `/responses` and fails with a 502).
- Claude Code echoes back the `thinking` blocks the proxy returned (with an empty signature). Forwarded to Kimi they produce empty replies and Claude Code reports "stream was malformed". The proxy strips them with a small LiteLLM callback (`strip_thinking.py`, written by the `claude` command).
- Kimi reasons before answering, so the first visible token can take 20s or more, and throughput was about 8 tokens/s in our runs.
- OpenCode 2.x keeps a background service. In our tests a service started before the config existed made `opencode run` hang until `opencode service restart`, so `setup` restarts it.
- The Claude Code desktop app does not use `ANTHROPIC_BASE_URL`; use the CLI with this tool.

## Status

Experimental and community-maintained, not an official Runpod product.
