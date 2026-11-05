# runpod-code

**Keep coding when Claude is down.** `runpod-code` runs the [Claude Code](https://code.claude.com/docs) CLI on Kimi K3.1 Pro, an open coding model hosted on [Runpod](https://www.runpod.io). Same Claude Code you already know, different model behind it, and you pay only for what you use.

New to Runpod? It's a GPU cloud. This project uses its [Public Endpoints](https://docs.runpod.io/hub/public-endpoints): ready-made hosted models you call with an API key, with nothing to deploy or manage. Questions? Join the [Runpod Discord](https://discord.com/invite/cUpRmau42V).

## Before you start

- A Mac. This is tested on macOS; Linux is untested.
- `bash`, `curl` and `python3` (already on most Macs).
- [Homebrew](https://brew.sh), only if you don't have the Claude Code CLI yet. Setup uses it to install Claude Code. If `claude` is already on your PATH, setup skips that step.

## Quick start

**1. Get a Runpod API key.** [Create an account](https://www.runpod.io), add a few dollars of credit, then go to [Settings](https://console.runpod.io/user/settings) and create an API key. ([Runpod's guide to API keys](https://docs.runpod.io/get-started/api-keys).)

**2. Run setup.**

```bash
git clone https://github.com/Kilo-Loco/runpod-code.git
cd runpod-code
./runpod-code setup
```

Paste your key when asked (it stays hidden). Setup checks the key, offers to save it to `~/.zshenv`, and installs what's missing, asking first: the Claude Code CLI, and a small local translator called LiteLLM (see [how it works](#how-it-works)) in its own virtualenv. The LiteLLM download is large, so expect a minute or two.

**3. Start Claude Code on Kimi.** Go to the project you want to work on and run:

```bash
/path/to/runpod-code/runpod-code claude
```

No new terminal tab is needed; the saved key is found automatically. No Anthropic login is needed either. When you exit, everything it started shuts down. Anything after `claude` is passed to Claude Code, for example `runpod-code claude -p "fix the failing test"`.

**Tip: run it from any folder.** From inside the `runpod-code` folder, add a shortcut, then open a new terminal tab:

```bash
echo "alias runpod-code='$PWD/runpod-code'" >> ~/.zshrc
```

After that, `runpod-code claude` works anywhere.

## What it costs

You're billed from the credit on your Runpod account. Kimi K3.1 Pro is **$2 per 1M input tokens and $10 per 1M output tokens** (tokens are roughly word fragments; cached input costs less). In our tests a small bug fix cost a few cents, and building a small multi-file web app cost well under a dollar. Prices change, so check the [Runpod console](https://console.runpod.io).

Claude Code's own cost readout is not reliable for Kimi, so ignore it. The Runpod billing page is the source of truth.

## Troubleshooting

| What you see | What to do |
|---|---|
| `RUNPOD_API_KEY is not set` | Run `./runpod-code setup` and paste your key. |
| `proxy did not start` | The error lines are printed. The full log is `~/.local/share/runpod-code/proxy.log`. It doesn't contain your key, but skim it before sharing. |
| `something else is already listening on 127.0.0.1:4000` | Use another port: `RUNPOD_CODE_PORT=4100 runpod-code claude`. |
| Replies are slow, or arrive in bursts | Expected: the model thinks before answering and output arrives in chunks. For faster, cheaper replies on easy tasks, turn thinking off: `RUNPOD_CODE_THINKING=off runpod-code claude`. |
| Claude Code says the model "isn't recognized" | Harmless. It just doesn't know Kimi's context size. |
| You use the Claude Code desktop app | Not supported. Use the CLI. |

Still stuck? Ask in the [Runpod Discord](https://discord.com/invite/cUpRmau42V) or [open an issue](https://github.com/Kilo-Loco/runpod-code/issues).

## Other models

```bash
./runpod-code models --live                       # list models and prices, compare with the live endpoint
./runpod-code claude --model kimi-k3.1-pro-highspeed
```

Models and prices live in `models.json`. Only `kimi-k3.1-pro` has been tested; the others are marked `untested`.

## Advanced: use your own Runpod endpoint

If the public endpoint is slow or busy, you can point Claude Code at a model you host yourself on a [Runpod Serverless vLLM endpoint](https://docs.runpod.io/serverless/vllm/get-started):

```bash
./runpod-code endpoint add            # lists your endpoints, or pass an id: endpoint add <id>
./runpod-code claude --model <name>   # the name it prints
```

`endpoint add` wakes the endpoint (a cold start can take several minutes), reads the model it serves, and tests what Claude Code needs before saving anything:

- **Tool calling.** On the Runpod vLLM worker set `ENABLE_AUTO_TOOL_CHOICE=true` and `TOOL_CALL_PARSER` (for example `hermes` for Qwen). If the test fails, it tells you what to change.
- **A context window of at least 32k tokens.** Set `MAX_MODEL_LEN`. Claude Code's own instructions use about 16k.

Your endpoints are saved in `~/.config/runpod-code/models.json` and show up in `./runpod-code models`. `endpoint list` and `endpoint remove <name>` manage them (removing only forgets it here; the endpoint on Runpod is untouched). Serverless bills GPU-seconds on your account, so there is no per-token price. Tested on one small Qwen model; quality depends on the model you choose.

## How it works

<details>
<summary>The short version, for the curious</summary>

Claude Code speaks Anthropic's API; Runpod's endpoint speaks OpenAI's. `runpod-code` starts two small helpers on your machine and points Claude Code at them:

- **LiteLLM** (the local "translator") converts Claude Code's requests into OpenAI-style ones. It listens only on `127.0.0.1` and is protected by a random key generated on each start.
- **A tiny shim** (`nonstream_shim.py`) sits between LiteLLM and Runpod. Runpod's streaming path cuts off long responses (a big file write arrives truncated) and is much slower, so the shim asks for the full response and replays it. That's why output appears in bursts instead of token by token.

It also removes replayed `thinking` blocks from the conversation, which otherwise make Kimi return empty replies. Your API key is never written into any config; the proxy reads it from `RUNPOD_API_KEY`.

Tested on macOS (Apple silicon) with Claude Code CLI 2.1.311, including a fresh install on a second Mac. Two runs each built a complete multi-file web app (about 100KB of HTML, CSS and JS) in 22 to 38 minutes. Linux and the untested models are not verified.

</details>

## Uninstall

Remove the folder you cloned, then:

```bash
rm -rf ~/.local/share/runpod-code ~/.config/runpod-code
```

Also delete the `export RUNPOD_API_KEY=...` line from `~/.zshenv`, and the `alias runpod-code=...` line from `~/.zshrc` if you added it. To revoke the key itself, delete it in Runpod's Settings.

## Community and support

- Chat and ask questions in the [Runpod Discord](https://discord.com/invite/cUpRmau42V).
- Report bugs or suggest changes through [GitHub issues](https://github.com/Kilo-Loco/runpod-code/issues).

Experimental and community-maintained, not an official Runpod product.
