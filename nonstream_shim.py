#!/usr/bin/env python3
"""Tiny OpenAI-compatible shim that sits between LiteLLM and the Runpod Public Endpoint.

Why: Runpod's streaming path cuts long responses (a large tool call arrives truncated, with no
finish_reason) and is several times slower than a plain request. This shim takes a streaming
/chat/completions request, makes the upstream call WITHOUT streaming, then replays the finished
response as server-sent events. Keepalive comments go out while the model works so clients do not
time out. Other requests are passed through unchanged. Standard library only.

Usage: nonstream_shim.py <upstream_base_url> <port>
The Authorization header from the caller is forwarded; the key is never read from disk or logged.
"""
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = sys.argv[1].rstrip("/")
PORT = int(sys.argv[2])
KEEPALIVE_SECS = 10
UPSTREAM_TIMEOUT = 1800


def call_upstream(method, path, body, auth):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = auth
    req = urllib.request.Request(UPSTREAM + path, body, headers, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT)
        return r.status, r.headers.get("Content-Type", "application/json"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "application/json"), e.read()


def sse(obj):
    return b"data: " + json.dumps(obj).encode() + b"\n\n"


def replay(resp, want_usage):
    """Turn a finished chat.completion into a list of chat.completion.chunk SSE events."""
    ch = resp["choices"][0]
    msg = ch.get("message") or {}
    base = {"id": resp.get("id", "chatcmpl-shim"), "object": "chat.completion.chunk",
            "created": resp.get("created", int(time.time())), "model": resp.get("model", "")}
    out = []

    def chunk(delta, finish=None):
        out.append(sse({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}))

    chunk({"role": "assistant", "content": ""})
    reasoning = msg.get("reasoning_content") or msg.get("reasoning")
    if reasoning:
        chunk({"reasoning_content": reasoning})
    if msg.get("content"):
        chunk({"content": msg["content"]})
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        chunk({"tool_calls": [{"index": i, "id": tc.get("id"), "type": "function",
                               "function": {"name": fn.get("name"), "arguments": ""}}]})
        args = fn.get("arguments") or ""
        for j in range(0, len(args), 2000):
            chunk({"tool_calls": [{"index": i, "function": {"arguments": args[j:j + 2000]}}]})
    chunk({}, ch.get("finish_reason") or "stop")
    if want_usage and resp.get("usage"):
        out.append(sse({**base, "choices": [], "usage": resp["usage"]}))
    out.append(b"data: [DONE]\n\n")
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, status, ctype, data):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        status, ctype, data = call_upstream("GET", self.path.replace("/v1", "", 1) if self.path.startswith("/v1/") else self.path,
                                            None, self.headers.get("Authorization"))
        self._send(status, ctype, data)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        auth = self.headers.get("Authorization")
        path = self.path.replace("/v1", "", 1) if self.path.startswith("/v1/") else self.path
        try:
            req = json.loads(raw)
        except ValueError:
            req = None
        if not (path.endswith("/chat/completions") and isinstance(req, dict) and req.get("stream")):
            status, ctype, data = call_upstream("POST", path, raw, auth)
            return self._send(status, ctype, data)

        want_usage = bool((req.get("stream_options") or {}).get("include_usage"))
        req["stream"] = False
        req.pop("stream_options", None)
        body = json.dumps(req).encode()

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def write(b):
            self.wfile.write(b"%x\r\n" % len(b) + b + b"\r\n")
            self.wfile.flush()

        result = {}

        def work():
            result["r"] = call_upstream("POST", path, body, auth)

        t = threading.Thread(target=work, daemon=True)
        t.start()
        try:
            while t.is_alive():
                t.join(KEEPALIVE_SECS)
                if t.is_alive():
                    write(b": keepalive\n\n")
            status, _, data = result["r"]
            if status != 200:
                write(sse({"error": {"message": data.decode("utf-8", "replace")[:2000], "type": "upstream_error",
                                     "code": status}}))
            else:
                for ev in replay(json.loads(data), want_usage):
                    write(ev)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
