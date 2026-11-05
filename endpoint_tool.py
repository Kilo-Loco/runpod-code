#!/usr/bin/env python3
"""Helpers for runpod-code: merge the built-in model list with the user's own endpoints, and manage
those endpoints (add / list / remove) with a preflight check. Standard library only.

  endpoint_tool.py merge BUILTIN_JSON USER_JSON OUT_JSON ROUTES_JSON
  endpoint_tool.py add [ENDPOINT_ID_OR_URL] [--name ALIAS] [--model SERVED_NAME] [--force] [--skip-check]
  endpoint_tool.py list
  endpoint_tool.py remove ALIAS

`add`, `list` and `remove` read RUNPOD_API_KEY (add only), USER_MODELS and BUILTIN_JSON from the
environment. The API key is only ever sent as an Authorization header; it is never printed or saved.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

ALIAS_RE = re.compile(r"^[A-Za-z0-9._-]+$")
MIN_CONTEXT = 20000      # Claude Code's own prompt plus tool definitions is about 16k tokens
COMFY_CONTEXT = 32768


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def read_user(path):
    if not path or not os.path.exists(path):
        return {"models": []}
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError('expected {"models": [...]}')
    return data


# ---------------------------------------------------------------- merge
def merge(builtin_path, user_path, out_path, routes_path):
    with open(builtin_path) as f:
        data = json.load(f)
    public = data["base_url"].rstrip("/")
    models = []
    for m in data["models"]:
        m = dict(m)
        m.setdefault("base_url", public)
        m.setdefault("upstream_model", m["id"])
        m["source"] = "public"
        models.append(m)
    try:
        user = read_user(user_path)
    except (ValueError, OSError) as e:
        print(f"warning: ignoring {user_path}: {e}", file=sys.stderr)
        user = {"models": []}
    for u in user["models"]:
        uid = u.get("id") if isinstance(u, dict) else None
        url = (u.get("base_url") or "") if isinstance(u, dict) else ""
        if not (isinstance(uid, str) and ALIAS_RE.match(uid) and url.startswith(("http://", "https://"))):
            print(f"warning: skipping invalid custom model entry: {str(u)[:80]}", file=sys.stderr)
            continue
        m = {"id": uid, "name": u.get("name", uid), "status": "custom", "source": "custom",
             "base_url": url.rstrip("/"), "upstream_model": u.get("upstream_model", uid),
             "billing": u.get("billing", "gpu-seconds"),
             "cost": u.get("cost") or {"input": 0.0, "output": 0.0, "cache_read": None, "cache_write": None}}
        models = [x for x in models if x["id"] != uid] + [m]
    data["models"] = models
    write_json(out_path, data)
    write_json(routes_path, {m["id"]: m["base_url"] for m in models})


# ---------------------------------------------------------------- http
def http(method, url, key, body=None, timeout=60):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None, headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # timeouts, DNS, refused
        return 0, str(e).encode()


class Ticker:
    """Prints a progress line every few seconds while a slow call (a cold start) is running."""

    def __init__(self, msg, every=15):
        self.msg, self.every, self.stop, self.t0 = msg, every, threading.Event(), time.time()

    def __enter__(self):
        def run():
            while not self.stop.wait(self.every):
                print(f"  {self.msg} ({int(time.time() - self.t0)}s)", flush=True)
        self.th = threading.Thread(target=run, daemon=True)
        self.th.start()
        return self

    def __exit__(self, *a):
        self.stop.set()


def wake(base, key, deadline=1200):
    """GET /models, riding out a Serverless cold start. The gateway drops a connection that waits
    about 5 minutes, so keep retrying until `deadline` seconds. While waiting, show worker and queue
    state, and say so if no worker has started (usually no GPU capacity for the chosen GPU types)."""
    t0, stop = time.time(), threading.Event()
    m = re.match(r"^https://api\.runpod\.ai/v2/([A-Za-z0-9]+)/openai/v1$", base)
    health = f"https://api.runpod.ai/v2/{m.group(1)}/health" if m else None

    def watch():
        warned = False
        while not stop.wait(15):
            line = f"waking the endpoint ({int(time.time() - t0)}s)"
            if health:
                st, raw = http("GET", health, key, timeout=15)
                try:
                    h = json.loads(raw)
                    w, j = h["workers"], h["jobs"]
                    up = w.get("ready", 0) + w.get("idle", 0) + w.get("running", 0)
                    line += f": workers starting={w.get('initializing', 0)} up={up}, queued requests={j.get('inQueue', 0)}"
                    if not (w.get("initializing", 0) or up) and time.time() - t0 > 120 and not warned:
                        warned = True
                        line += ("\n  No worker has started after 2 minutes. This usually means no GPU capacity for the GPU types"
                                 "\n  or CUDA version selected. In the endpoint's settings allow more GPU types or a lower CUDA minimum.")
                except (ValueError, KeyError):
                    pass
            print("  " + line, flush=True)

    threading.Thread(target=watch, daemon=True).start()
    try:
        while True:
            left = deadline - (time.time() - t0)
            if left <= 0:
                return 0, f"gave up after {deadline // 60} minutes without the endpoint becoming ready".encode()
            st, raw = http("GET", base + "/models", key, timeout=min(290, left))
            if st not in (0, 500, 502, 503, 504, 524):
                return st, raw
            time.sleep(2)
    finally:
        stop.set()


def ask(prompt, default=""):
    if not sys.stdin.isatty():
        return default
    try:
        a = input(prompt).strip()
    except EOFError:
        return default
    return a or default


# ---------------------------------------------------------------- add
TOOL_FIX = (
    "  Your vLLM worker needs tool calling switched on. In the endpoint's environment variables set:\n"
    "      ENABLE_AUTO_TOOL_CHOICE=true\n"
    "      TOOL_CALL_PARSER=<the parser for your model>\n"
    "  Parsers the Runpod vLLM worker offers: hermes (Qwen and Hermes models), mistral, llama3_json\n"
    "  (Llama 3.1+), pythonic, internlm. Pick the one your model's docs recommend, then save the\n"
    "  endpoint so its workers restart, and run this command again."
)


def preflight(base, key, model, max_len, skip):
    """Returns a list of (level, message) where level is 'ok', 'warn' or 'fail'."""
    out = []
    if max_len:
        if max_len < MIN_CONTEXT:
            out.append(("fail", f"context window is only {max_len} tokens; Claude Code needs about {MIN_CONTEXT} "
                                f"just for its own instructions. Raise the MAX_MODEL_LEN environment variable (aim for {COMFY_CONTEXT}+)."))
        elif max_len < COMFY_CONTEXT:
            out.append(("warn", f"context window is {max_len} tokens; long sessions will hit the limit. "
                                f"Consider MAX_MODEL_LEN of {COMFY_CONTEXT} or more."))
        else:
            out.append(("ok", f"context window {max_len} tokens"))
    else:
        out.append(("warn", "the endpoint did not report its context window; make sure it is at least 32k tokens"))
    if skip:
        out.append(("warn", "tool-calling check skipped"))
        return out
    body = {"model": model, "temperature": 0, "max_tokens": 300, "tool_choice": "auto",
            "messages": [{"role": "user", "content": "What is the weather in Paris right now? Use the get_weather tool."}],
            "tools": [{"type": "function", "function": {
                "name": "get_weather", "description": "Get the current weather for a city",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]}
    print("Testing tool calling (Claude Code cannot work without it)...", flush=True)
    with Ticker("still waiting for the model"):
        status, raw = http("POST", base + "/chat/completions", key, body, timeout=290)
        if status in (0, 502, 503, 504, 524):  # gateway hiccup right after a cold start: one more try
            status, raw = http("POST", base + "/chat/completions", key, body, timeout=290)
    text = raw.decode("utf-8", "replace")
    if status == 200:
        try:
            msg = json.loads(text)["choices"][0]["message"]
        except (ValueError, KeyError, IndexError):
            out.append(("fail", "the endpoint returned a response that is not OpenAI chat-completions JSON"))
            return out
        calls = msg.get("tool_calls") or []
        if calls:
            try:
                json.loads(calls[0]["function"]["arguments"])
                out.append(("ok", f"tool calling works ({calls[0]['function']['name']})"))
            except (ValueError, KeyError, TypeError):
                out.append(("fail", "the model produced a tool call with malformed arguments.\n" + TOOL_FIX))
        else:
            out.append(("fail", "the model answered in plain text instead of calling the tool. Either the tool-call "
                                "parser is not configured or this model does not support tool calling.\n" + TOOL_FIX))
    elif status == 400 and re.search(r"tool", text, re.I):
        out.append(("fail", "the endpoint rejected a request that uses tools.\n" + TOOL_FIX))
    elif status in (401, 403):
        out.append(("fail", f"HTTP {status}: the API key was not accepted by this endpoint"))
    else:
        # The Runpod gateway can turn vLLM's 400 into a bare 502, so the status alone is not enough.
        # Control probe: the same call without tools. If that works, the tools are what failed.
        control = {"model": model, "max_tokens": 5, "messages": [{"role": "user", "content": "Say ok"}]}
        cs, _ = http("POST", base + "/chat/completions", key, control, timeout=290)
        if cs == 200:
            out.append(("fail", f"plain chat works, but a request that uses tools was rejected (HTTP {status}).\n" + TOOL_FIX))
        else:
            out.append(("fail", f"tool test failed with HTTP {status} and plain chat failed with HTTP {cs}: {text[:200]}"))
    return out


def cmd_add(args):
    key = os.environ.get("RUNPOD_API_KEY", "")
    if not key:
        die("RUNPOD_API_KEY is not set (run: ./runpod-code setup)")
    name = model = None
    force = skip = False
    pos = []
    it = iter(args)
    for a in it:
        if a == "--name":
            name = next(it, None)
        elif a == "--model":
            model = next(it, None)
        elif a == "--force":
            force = True
        elif a == "--skip-check":
            skip = True
        elif a.startswith("-"):
            die(f"unknown option: {a}")
        else:
            pos.append(a)
    target = pos[0] if pos else None

    if not target:
        status, raw = http("GET", "https://rest.runpod.io/v1/endpoints", key, timeout=30)
        items = []
        if status == 200:
            try:
                data = json.loads(raw)
                data = data if isinstance(data, list) else data.get("endpoints", [])
                items = [e for e in data if isinstance(e, dict) and e.get("id")]
            except ValueError:
                pass
        if not items:
            die("could not list your endpoints; pass one: ./runpod-code endpoint add <endpoint-id>")
        print("Your Runpod endpoints:")
        for i, e in enumerate(items, 1):
            print(f"  {i}. {e.get('name') or '(unnamed)'}  [{e['id']}]")
        pick = ask("Which one? (number) ", "")
        if not pick.isdigit() or not 1 <= int(pick) <= len(items):
            die("no endpoint chosen")
        target = items[int(pick) - 1]["id"]

    if target.startswith(("http://", "https://")):
        base = target.rstrip("/")
        base = base if base.endswith("/v1") else base + "/v1"
    else:
        if not re.match(r"^[A-Za-z0-9]+$", target):
            die("that does not look like an endpoint id (letters and digits only) or a URL")
        base = f"https://api.runpod.ai/v2/{target}/openai/v1"

    print(f"Contacting {base}\n  (a Serverless endpoint with no warm worker can take several minutes to start)", flush=True)
    status, raw = wake(base, key)
    if status != 200:
        hint = {401: "the key was not accepted", 403: "the key was not accepted",
                404: "no OpenAI-compatible route here; the endpoint must run a vLLM worker (expected .../openai/v1)"}.get(status, "")
        die(f"could not read {base}/models (HTTP {status}). {hint or raw.decode('utf-8', 'replace')[:200]}")
    try:
        listed = json.loads(raw)["data"]
    except (ValueError, KeyError):
        die("the endpoint's /models response was not OpenAI-style JSON")
    ids = [x["id"] for x in listed if isinstance(x, dict) and x.get("id")]
    if not ids:
        die("the endpoint reports no models")
    if model:
        if model not in ids:
            die(f"model '{model}' is not served here; it serves: {', '.join(ids)}")
    elif len(ids) == 1:
        model = ids[0]
    else:
        for i, m in enumerate(ids, 1):
            print(f"  {i}. {m}")
        pick = ask("Which model? (number) ", "1")
        model = ids[int(pick) - 1] if pick.isdigit() and 1 <= int(pick) <= len(ids) else ids[0]
    info = next(x for x in listed if x.get("id") == model)
    max_len = info.get("max_model_len")
    print(f"Serving model: {model}")

    alias = name or re.sub(r"[^A-Za-z0-9._-]+", "-", model.split("/")[-1]).strip("-").lower()
    if not ALIAS_RE.match(alias or ""):
        die("the name may only contain letters, digits, dot, dash and underscore")
    builtin_ids = set()
    try:
        with open(os.environ.get("BUILTIN_JSON", "")) as f:
            builtin_ids = {m["id"] for m in json.load(f)["models"]}
    except (OSError, ValueError, KeyError):
        pass
    if alias in builtin_ids:
        die(f"'{alias}' is a built-in model name; choose another with --name")

    results = preflight(base, key, model, max_len if isinstance(max_len, int) else None, skip)
    failed = False
    for level, msg in results:
        print({"ok": "  ok:   ", "warn": "  warn: ", "fail": "  FAIL: "}[level] + msg)
        failed = failed or level == "fail"
    if failed and not force:
        if ask("Save it anyway? [y/N] ", "n").lower() != "y":
            die("not saved. Fix the endpoint and run the command again (or use --force).")

    path = os.environ.get("USER_MODELS") or die("USER_MODELS is not set")
    user = read_user(path)
    user["models"] = [m for m in user["models"] if m.get("id") != alias] + [{
        "id": alias, "name": alias, "base_url": base, "upstream_model": model, "billing": "gpu-seconds",
        **({"max_model_len": max_len} if isinstance(max_len, int) else {})}]
    write_json(path, user)
    print(f"\nSaved '{alias}' to {path}")
    print(f"Use it with:  ./runpod-code claude --model {alias}")
    print("Cost: Serverless bills GPU-seconds on your Runpod account, not tokens, so Claude Code's cost\n"
          "readout is not meaningful here. Check the Runpod billing page.")


def cmd_list():
    path = os.environ.get("USER_MODELS", "")
    try:
        user = read_user(path)
    except (ValueError, OSError) as e:
        die(f"cannot read {path}: {e}")
    if not user["models"]:
        print(f"No custom endpoints yet ({path}). Add one: ./runpod-code endpoint add")
        return
    for m in user["models"]:
        print(f"{m.get('id'):28} {m.get('base_url')}  ->  {m.get('upstream_model', m.get('id'))}")


def cmd_remove(args):
    if not args:
        die("usage: endpoint remove <name>")
    path = os.environ.get("USER_MODELS") or die("USER_MODELS is not set")
    user = read_user(path)
    keep = [m for m in user["models"] if m.get("id") != args[0]]
    if len(keep) == len(user["models"]):
        die(f"no custom endpoint named '{args[0]}'")
    user["models"] = keep
    write_json(path, user)
    print(f"Removed '{args[0]}'. (This only forgets it here; the endpoint on Runpod is untouched.)")


if __name__ == "__main__":
    cmd, rest = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "merge" and len(rest) == 4:
        merge(*rest)
    elif cmd == "add":
        cmd_add(rest)
    elif cmd == "list":
        cmd_list()
    elif cmd in ("remove", "rm"):
        cmd_remove(rest)
    else:
        die("usage: endpoint_tool.py merge|add|list|remove ...")
