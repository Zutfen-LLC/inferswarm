#!/usr/bin/env python3
"""Issue #289 RED baseline: the r3 physical driver lifecycle, tracked.

This is a faithful tracked port of the issue #280 r3 physical driver's
launch lifecycle (``inferswarm05:~/is280r3-physical/driver.py``, sha256
2cc001b521cbefd56a5fedb29c7ff2e774e5154851fdb1dd2fdce633237f8e39) reduced
to its minimal lifecycle component, with the SAME interface the corrected
module will keep (``campaign_executor``, ``Launch``). It preserves the
defect this issue exists to fix, so the committed RED tests reproduce it
on CPU with loopback stub servers:

- ``launch()`` never stops the previous launch: stop runs only in a
  post-campaign ``finally`` (the r3 driver's finally loop after
  ``run_campaign``), so the R1 baseline server is still alive when the R2
  candidate server starts;
- readiness is a plain HTTP ``/health`` poll returning 200 with ``"ok"``:
  the still-running R1 server answers the R2 readiness probe, so R2 is
  declared "ready" while its own process already exited on bind failure
  (retained server-R2.log: ``couldn't bind HTTP server socket ... port
  8791``, exit in 39 ms);
- requests are dispatched to whichever process answers the fixed port:
  the R2-cold request was served by the R1 baseline server (three
  request_accept rows in server-R1.log), and only the missing retained R2
  observer bytes made the pure gate engine fail closed.

The frozen admission/STOP law stays in ``scripts/issue280_runner.py``,
unchanged. CPU-only: no model loading, no GPU/Vulkan, no physical
execution; the server command is caller-supplied (stub servers in tests).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

STARTUP_TIMEOUT_S = 60.0
READY_POLL_INTERVAL_S = 0.25
LOG_FLUSH_WAIT_S = 5.0
LOG_FLUSH_POLL_S = 0.2

BRACKET_PREFIX_EVENTS = ("recording", "weight_inventory", "kv_inventory",
                         "buffer_decl", "cpu_state", "unexplained_placement")


class LaunchError(RuntimeError):
    """Launch lifecycle failure (interface parity with the corrected
    module; the r3 law raises it only for early exit / startup timeout)."""


def utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def slice_request_bracket(log_text: str, ordinal: int) -> str | None:
    """Per-request observer bracket sliced from the append-only server log
    (r3 driver law, byte-identical semantics)."""
    lines = log_text.splitlines()
    accept_idx = end_idx = None
    rid = None
    for i, line in enumerate(lines):
        if "I280 " not in line:
            continue
        row = json.loads(line.split("I280 ", 1)[1])
        if row.get("event") == "request_accept" and row.get("ordinal") == ordinal:
            accept_idx = i
            rid = row.get("request")
            for j in range(i + 1, len(lines)):
                if "I280 " not in lines[j]:
                    continue
                r2 = json.loads(lines[j].split("I280 ", 1)[1])
                if (r2.get("event") == "request_end"
                        and r2.get("request") == rid):
                    end_idx = j
                    break
            break
    if accept_idx is None or end_idx is None:
        return None
    out = []
    for line in lines[:accept_idx]:
        if "I280 " not in line:
            continue
        row = json.loads(line.split("I280 ", 1)[1])
        if row.get("event") in BRACKET_PREFIX_EVENTS:
            if row["event"] == "recording":
                row["requests_planned"] = 1
                line = "I280 " + json.dumps(row)
            out.append(line)
    for line in lines[accept_idx:end_idx + 1]:
        if "I280 " in line:
            row = json.loads(line.split("I280 ", 1)[1])
            if row.get("event") == "request_accept":
                row["ordinal"] = 1
                line = "I280 " + json.dumps(row)
        out.append(line)
    return "\n".join(out) + "\n"


class Launch:
    """One server launch under the r3 lifecycle law (THE DEFECT).

    Same constructor surface as the corrected module so one test suite
    drives both: ``command_builder(arm, port, log_path, env_extra)``.
    """

    def __init__(self, row, *, command_builder, workdir, env=None,
                 host="127.0.0.1", port=8791, slice_observer=None,
                 retain=None, health=None, startup_timeout_s=STARTUP_TIMEOUT_S):
        self.row = row
        self.arm = row["arm"]
        self.label = row["label"]
        self.command_builder = command_builder
        self.workdir = Path(workdir)
        self.env_extra = dict(env or {})
        self.host = host
        self.port = port
        self.slice_observer = slice_observer or slice_request_bracket
        self.retain = retain
        self.health = health
        self.startup_timeout_s = startup_timeout_s
        self.log_path = self.workdir / f"server-{self.label}.log"
        self.proc = None
        self.log_file = None
        self.startup_s = None
        self.ordinal = 0
        self.record = {
            "label": self.label, "arm": self.arm, "pid": None,
            "identity": None, "host": host, "port": port,
            "started_utc": None, "ready_utc": None, "exit": None,
            "failure": None,
        }

    def start(self):
        """r3 law: no port preflight, no owned-process identity; readiness
        is ANY 200 with "ok" on the fixed port — including the previous
        launch's still-running server."""
        cmd = self.command_builder(self.arm, self.port, self.log_path,
                                   dict(self.env_extra))
        env = dict(os.environ)
        env.update(self.env_extra)
        self.record["started_utc"] = utcnow()
        self.log_file = open(self.log_path, "wb")
        t0 = time.monotonic()
        self.proc = subprocess.Popen(cmd, stdout=self.log_file,
                                     stderr=self.log_file, env=env)
        self.record["pid"] = self.proc.pid
        while time.monotonic() - t0 < self.startup_timeout_s:
            if self.proc.poll() is not None:
                raise LaunchError(
                    f"PROCESS_EXIT launch={self.label} "
                    f"code={self.proc.returncode}")
            try:
                r = urllib.request.urlopen(
                    f"http://{self.host}:{self.port}/health", timeout=1)
                if b'"ok"' in r.read():
                    self.startup_s = time.monotonic() - t0
                    self.record["ready_utc"] = utcnow()
                    return
            except Exception:
                time.sleep(READY_POLL_INTERVAL_S)
        raise LaunchError(f"STARTUP_TIMEOUT launch={self.label}")

    def stop(self):
        """r3 law: terminate/kill the child only; called from the
        post-campaign finally, NEVER between launches."""
        if self.proc is None:
            return self.record["exit"]
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(10)
                except Exception:
                    self.proc.kill()
                    self.proc.wait()
            self.record["exit"] = {"returncode": self.proc.returncode,
                                   "reaped": True, "stopped_utc": utcnow()}
            return self.record["exit"]
        finally:
            if self.log_file is not None:
                try:
                    self.log_file.close()
                except OSError:
                    pass
                self.log_file = None

    def build_request(self, kind):
        body = json.dumps({
            "prompt": self.row.get("prompt_text", "stub"),
            "n_predict": 128, "temperature": 0.0, "top_k": 1, "seed": 42,
            "repeat_penalty": 1.0, "cache_prompt": False,
            "samplers": ["top_k"], "stream": True,
            "timings_per_token": True,
        }).encode()
        return (f"http://{self.host}:{self.port}/completion", body,
                {"Content-Type": "application/json"})

    def request(self, kind):
        """r3 law: dispatch to whichever process answers the port; no
        server-identity verification of any kind."""
        self.ordinal += 1
        ordinal = self.ordinal
        url, data, headers = self.build_request(kind)
        t0 = time.monotonic()
        ttft = None
        chunks = []
        final = None
        transport_ok = True
        err = None
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                for line in r:
                    if not line.startswith(b"data: "):
                        continue
                    try:
                        c = json.loads(line[6:].decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if c.get("content"):
                        if ttft is None:
                            ttft = time.monotonic() - t0
                        chunks.append(c["content"])
                    if c.get("stop") is True or (
                            isinstance(c.get("stop"), str) and c.get("stop")):
                        final = c
                        if not c.get("content"):
                            break
        except Exception as e:
            transport_ok = False
            err = f"{type(e).__name__}: {e}"
        wall = time.monotonic() - t0
        record = {
            "launch": self.label, "arm": self.arm,
            "prompt": self.row.get("prompt"), "kind": kind,
            "ordinal": ordinal, "server_pid": self.record["pid"],
            "server_identity": None, "launch_identity": None,
            "identity_mismatch": False,
            "text": "".join(chunks), "transport_ok": transport_ok,
            "error": err, "ttft_s": ttft, "wall_s": wall,
            "startup_s": self.startup_s,
            "final": ({k: final.get(k) for k in
                       ("stop_type", "tokens_predicted", "tokens_evaluated",
                        "timings")} if final else None),
        }
        bracket = None
        if transport_ok:
            deadline = time.monotonic() + LOG_FLUSH_WAIT_S
            while time.monotonic() < deadline:
                bracket = self.slice_observer(self._read_log(), ordinal)
                if bracket is not None:
                    break
                time.sleep(LOG_FLUSH_POLL_S)
        health_sample, health_stop = None, None
        if self.health is not None:
            health_sample, health_stop = self.health()
        record["health_stop"] = health_stop
        state = {"observer_raw": bracket,
                 "peak_rss_bytes": self._peak_rss(),
                 "health_sample": health_sample,
                 "startup_s": self.startup_s}
        if self.retain is not None:
            self.retain(self.label, kind, record, bracket)
        return record, state

    def _read_log(self) -> str:
        try:
            return self.log_path.read_text(errors="replace")
        except OSError:
            return ""

    def _peak_rss(self):
        try:
            with open(f"/proc/{self.record['pid']}/status") as fh:
                for line in fh:
                    if line.startswith("VmHWM"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass
        return None


def campaign_executor(matrix, *, command_builder, workdir, env=None,
                      host="127.0.0.1", port=8791, slice_observer=None,
                      retain=None, health=None, on_launch_record=None,
                      startup_timeout_s=STARTUP_TIMEOUT_S):
    """r3 law (THE DEFECT): launches accumulate; the previous launch is
    never stopped before the next one; every owned child is stopped only
    after the whole campaign, in the finally."""
    import importlib.util

    runner_path = Path(__file__).resolve().parent / "issue280_runner.py"
    spec = importlib.util.spec_from_file_location("issue280_runner",
                                                  runner_path)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    launches: list[Launch] = []

    def launch(row):
        # r3 defect: the previous launch is NOT stopped here
        ctx = Launch(row, command_builder=command_builder, workdir=workdir,
                     env=env, host=host, port=port,
                     slice_observer=slice_observer, retain=retain,
                     health=health, startup_timeout_s=startup_timeout_s)
        ctx.start()
        launches.append(ctx)
        if on_launch_record is not None:
            on_launch_record(dict(ctx.record))
        return ctx.request

    try:
        summary = runner.run_campaign(matrix, launch)
    finally:
        for ctx in launches:
            try:
                ctx.stop()
            except Exception:
                pass
    return summary, launches
