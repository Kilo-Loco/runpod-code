# runpod-code

Get a coding agent running on Kimi K3.1 Pro through a [Runpod Public Endpoint](https://docs.runpod.io). Handy as a backup when your usual coding assistant is down.

## Quick start

**1. Get a Runpod API key.** Create an account at [runpod.io](https://www.runpod.io), add a few dollars of credit, then create a key under Settings → API Keys.

**2. Run setup.**

```bash
git clone https://github.com/Kilo-Loco/runpod-code.git
cd runpod-code
./runpod-code setup
```

Paste your key when asked. Setup checks the key, installs [OpenCode](https://opencode.ai) with Homebrew if you don't have it, and writes the config.

**3. Start coding.** Open a new terminal tab (so the saved key loads), go to your project, and run:

```bash
opencode
```

That's it. You're talking to Kimi K3.1 Pro on Runpod.

You need `bash`, `curl` and `python3`. Setup uses Homebrew to install OpenCode; without Homebrew, install OpenCode yourself first.

## Use Claude Code instead

```bash
./runpod-code claude
```

This starts a small local proxy (LiteLLM) and runs the Claude Code CLI through it. The first run offers to install LiteLLM into a virtualenv. You need the [Claude Code CLI](https://code.claude.com/docs) installed; no Anthropic login is needed. The Claude Code desktop app is not supported.

## What it costs

Kimi K3.1 Pro is $2 per 1M input tokens and $10 per 1M output tokens (cached input is cheaper). A small bug-fix task cost a few cents in our tests. Prices change, so check the Runpod console.

- **OpenCode:** `opencode run --format json "your task"` reports a cost on each `step_finish` event.
- **Claude Code:** the proxy returns a per-request cost header. Claude Code's own cost readout is not reliable for Kimi.
- The Runpod billing page is the source of truth.

## Other models

```bash
./runpod-code models --live    # list models, prices, and compare with the live endpoint
./runpod-code setup --model kimi-k3.1-pro-highspeed
```

Models and prices live in `models.json`. Only `kimi-k3.1-pro` has been tested; the others are marked `untested`.

## Good to know

- Kimi thinks before it answers, so the first token can take 20 seconds or more, and output runs at roughly 8 tokens per second.
- Your key is never written into the config. It is read from `RUNPOD_API_KEY`.
- If `opencode run` hangs after setup, run `opencode service restart`.
- Tested on macOS only. The LiteLLM install step and a clean-machine run are untested.

Experimental and community-maintained, not an official Runpod product.
