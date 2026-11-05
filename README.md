# runpod-code

Run the Claude Code CLI on Kimi K3.1 Pro through a [Runpod Public Endpoint](https://docs.runpod.io). Handy as a backup when Claude is down.

## Quick start

**1. Get a Runpod API key.** Create an account at [runpod.io](https://www.runpod.io), add a few dollars of credit, then create a key under Settings → API Keys.

**2. Run setup.**

```bash
git clone https://github.com/Kilo-Loco/runpod-code.git
cd runpod-code
./runpod-code setup
```

Paste your key when asked. Setup checks the key and installs anything missing, after asking: the [Claude Code CLI](https://code.claude.com/docs) (via Homebrew) and a small local proxy (LiteLLM, in its own virtualenv).

**3. Start Claude Code on Kimi.** Open a new terminal tab (so the saved key loads), go to your project, and run:

```bash
/path/to/runpod-code/runpod-code claude
```

That starts the proxy, runs `claude` against it, and stops the proxy when you exit. Anything you pass after `claude` goes to the Claude Code CLI, for example `./runpod-code claude -p "fix the failing test"`. No Anthropic login is needed.

You need `bash`, `curl` and `python3`. The Claude Code desktop app is not supported; use the CLI.

## What it costs

Kimi K3.1 Pro is $2 per 1M input tokens and $10 per 1M output tokens (cached input is cheaper). A small bug-fix task cost a few cents in our tests. Prices change, so check the Runpod console.

Claude Code's own cost readout is not reliable for Kimi. The proxy returns a per-request cost in the `x-litellm-response-cost-original` response header, and the Runpod billing page is the source of truth.

## Other models

```bash
./runpod-code models --live                       # list models and prices, compare with the live endpoint
./runpod-code claude --model kimi-k3.1-pro-highspeed
```

Models and prices live in `models.json`. Only `kimi-k3.1-pro` has been tested; the others are marked `untested`.

## Good to know

- Thinking is off by default. With it on, long reasoning streams were unreliable through the proxy. Turn it on with `RUNPOD_CODE_THINKING=on ./runpod-code claude`.
- Runpod's streaming path cuts off long responses (a large file write arrives truncated) and is much slower. So a small shim (`nonstream_shim.py`, started automatically) calls the endpoint without streaming and replays the result to Claude Code. Output appears in bursts rather than token by token.
- Your key is never written into any config. The proxy reads it from `RUNPOD_API_KEY`.
- The endpoint only serves OpenAI-style `/chat/completions`, so the proxy translates Claude Code's requests. It also strips replayed `thinking` blocks, which otherwise make Kimi return empty replies.
- Tested on macOS with Claude Code CLI 2.1.311. One run built a complete multi-file web app (about 95KB of HTML, CSS and JS) in about 22 minutes. The LiteLLM install step and a clean-machine run are untested.

Experimental and community-maintained, not an official Runpod product.
