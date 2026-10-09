#!/usr/bin/env python3
"""CPU-only loopback stub server for issue #289 launcher tests.

A real HTTP server subprocess (stdlib http.server) that mimics the
observable lifecycle surface of the physical #280 llama-server:

- binds 127.0.0.1:<port>; exits nonzero on bind failure (like the
  retained r3 server-R2.log ``couldn't bind HTTP server socket``);
- ``GET /health`` answers 200 ``{"ok": true}`` (the r3 readiness law)
  carrying the launch identity token from ``I280_LAUNCH_IDENTITY`` both
  as the ``X-I280-LAUNCH-IDENTITY`` header and as a JSON field;
- ``POST /completion`` answers a two-chunk SSE stream ending with a
  final ``stop`` row; the identity echoed on the completion response is
  the launch token unless ``--stale-completion-id`` is given (models a
  stale/foreign server answering the request after a correct-health
  race);
- appends ``I280 {json}`` observer rows to ``--log``: the caller stream's
  inventory prefix once at startup, then the caller-supplied per-request
  observer rows (default shape: a mechanically valid stream built by
  tests/test_issue280_admission's ``build_stream``), renumbered to the
  server's own request counter, so the r3 slice law derives admissible
  brackets;
- ``--refuse-stop`` ignores SIGTERM to exercise bounded escalation.

No model, no GPU, no Vulkan — pure stdlib CPU process.
"""
import argparse
import hashlib
import json
import os
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IDENTITY_ENV = "I280_LAUNCH_IDENTITY"
IDENTITY_HEADER = "X-I280-LAUNCH-IDENTITY"
GOOD_TEXT = '{"service":"payments","severity":"high","status":"resolved"}'

ARGS = argparse.Namespace(log=None, arm="?", stale_completion_id=None,
                          foreign_health_id=None, env_report=None,
                          env_keys=(), record_requests=None)
STARTED_NS = time.monotonic_ns()
REQUESTS_SERVED = 0
PREFIX_ROWS = []
REQUEST_ROWS = []


def log_line(line):
    if ARGS.log:
        with open(ARGS.log, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def load_stream_rows(path):
    """Split the caller observer stream into (prefix rows before the
    request_accept row, request rows from request_accept to the end)."""
    lines = [l for l in open(path, encoding="utf-8").read().splitlines()
             if l.startswith("I280 ")]
    for i, line in enumerate(lines):
        row = json.loads(line.split("I280 ", 1)[1])
        if row.get("event") == "request_accept":
            return lines[:i], lines[i:]
    return lines, []


def renumber(rows, n):
    out = []
    for line in rows:
        row = json.loads(line.split("I280 ", 1)[1])
        if "request" in row:
            row["request"] = n
        if row.get("event") == "request_accept":
            row["ordinal"] = n
        out.append("I280 " + json.dumps(row))
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def _identity(self):
        return os.environ.get(IDENTITY_ENV) or f"UNCONFIGURED#{os.getpid()}"

    def _health_identity(self):
        return ARGS.foreign_health_id or self._identity()

    def _send_json(self, code, obj, identity=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(IDENTITY_HEADER, identity or self._identity())
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True,
                                  IDENTITY_ENV: self._health_identity(),
                                  "arm": ARGS.arm, "pid": os.getpid()},
                            identity=self._health_identity())
            return
        if self.path == "/__test__/env":
            # Test-only loopback reporting of NONSECRET sentinel values
            # (names supplied by --env-keys) — proves which environment
            # values the spawned child actually received.
            report = {k: os.environ.get(k) for k in ARGS.env_keys}
            report[IDENTITY_ENV] = os.environ.get(IDENTITY_ENV)
            self._send_json(200, report)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        global REQUESTS_SERVED
        if self.path != "/completion":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        REQUESTS_SERVED += 1
        ordinal = REQUESTS_SERVED
        if ARGS.record_requests:
            # Test-only loopback recording: the EXACT request bytes this
            # server received, plus nonsecret env sentinels, appended to
            # the caller-named file (diag log; never the observer log).
            try:
                body_txt = raw.decode("utf-8", "replace")
                rec = {"ordinal": ordinal, "path": "/completion",
                       "body": body_txt,
                       "body_sha256": hashlib.sha256(raw).hexdigest(),
                       "prompt_bytes": len(raw)}
                for k in ARGS.env_keys:
                    rec[f"env::{k}"] = os.environ.get(k)
                rec[f"env::{IDENTITY_ENV}"] = (
                    "present" if os.environ.get(IDENTITY_ENV) else "absent")
                with open(ARGS.record_requests, "a",
                          encoding="utf-8") as fh:
                    fh.write(json.dumps(rec) + "\n")
            except OSError:
                pass
        ident = self._identity()
        completion_ident = ARGS.stale_completion_id or ident
        chunks = [
            {"content": GOOD_TEXT, "identity": completion_ident,
             "arm": ARGS.arm},
            {"stop": True, "stop_type": "eos", "identity": completion_ident,
             "arm": ARGS.arm, "tokens_predicted": 8, "tokens_evaluated": 8},
        ]
        body = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
        body = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(IDENTITY_HEADER, completion_ident)
        self.end_headers()
        # Finish the synthetic observer bracket before delivering the SSE
        # body. The client must never race a partially appended JSON row.
        for line in renumber(REQUEST_ROWS, ordinal):
            log_line(line)
        self.wfile.write(body)


def main():
    global ARGS, PREFIX_ROWS, REQUEST_ROWS
    p = argparse.ArgumentParser()
    p.add_argument("port", type=int)
    p.add_argument("--arm", default="?")
    p.add_argument("--log", default=None)
    p.add_argument("--stream", default=None)
    p.add_argument("--stale-completion-id", dest="stale_completion_id",
                   default=None)
    p.add_argument("--foreign-health-id", dest="foreign_health_id",
                   default=None)
    p.add_argument("--refuse-stop", action="store_true")
    p.add_argument("--env-keys", dest="env_keys", default="",
                   help="comma-separated NONSECRET env names reported by "
                        "/__test__/env and request recording (tests only)")
    p.add_argument("--record-requests", dest="record_requests", default=None,
                   help="append exact received /completion request bytes "
                        "to this file (tests only)")
    ARGS = p.parse_args()
    ARGS.env_keys = tuple(k for k in ARGS.env_keys.split(",") if k)
    if ARGS.stream:
        PREFIX_ROWS, REQUEST_ROWS = load_stream_rows(ARGS.stream)
    if ARGS.refuse_stop:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    server = ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler)
    server.daemon_threads = True
    for line in PREFIX_ROWS:
        log_line(line)
    server.serve_forever(poll_interval=0.05)


if __name__ == "__main__":
    main()
