#!/usr/bin/env python3
"""Issue #289: physical launcher server lifecycle for the #280 campaign driver.

DEFECT BEING FIXED (issue #280 r3, retained evidence ~/is280r3-evidence on
the controller): the r3 physical driver's ``launch()`` executor never
stopped the previous launch — stop ran only in a post-campaign ``finally``
— and its readiness probe was a plain HTTP ``/health`` poll against a fixed
port. The R1 baseline server therefore answered the R2 readiness probe, R2
was declared "ready" while its own process had already exited on bind
failure (``couldn't bind HTTP server socket ... port 8791``), and the
R2-cold request was served by the still-running R1 baseline server. The
pure gate engine (``scripts/issue280_runner.run_campaign``) correctly
failed closed on the missing retained R2 observer bytes; the defect was
entirely in the untracked session-local physical executor.

This module extracts the minimal launcher/lifecycle component into a
tracked repository module with a deterministic production entry point
(:func:`campaign_executor`) that the next physical operator drives exactly
like the r3 driver: the unchanged gate engine over one
``launch(matrix_row) -> request(kind)`` executor per matrix row. Lifecycle
laws fixed here:

- **Ownership.** A launch owns exactly the child process (and its process
  group) that it spawned, identified by PID plus the non-inherited /proc
  start time (PID-reuse guard). Nothing is ever killed by port or by a
  generic process name.
- **Sequencing.** The previous owned launch is always stopped and reaped —
  graceful SIGTERM, bounded wait, SIGKILL escalation restricted to the
  owned process group — BEFORE the next launch begins, and the port is
  verified released. A prior launch that fails to stop cleanly is a hard
  pre-request STOP, never a reason to retry or dispatch to a stale server.
- **Port ownership.** Before spawning, the port must be free. If it is
  occupied by a foreign process the launch fails closed and the foreign
  listener is never sent an HTTP request.
- **Live identity.** Readiness requires (a) the owned child alive under
  the same process identity the launcher spawned, and (b) the server
  reporting THIS launch's identity token. A bare HTTP 200, an open port,
  or a cached health response is never readiness. The token is unique per
  launch (``<label>#<launcher-pid>#<monotonic-nonce>``), injected into the
  child environment as ``I280_LAUNCH_IDENTITY``, and echoed on ``/health``
  and in every completion response, so an HTTP request can never be
  routed to — or admitted from — a previous launch/arm, including across
  a bind collision, early exit, or PID reuse.
- **Traceability.** Every request record carries launch label, arm, server
  PID, and both identity tokens alongside the response bytes; a response
  whose server identity does not match the current launch is recorded as
  an identity-mismatch transport failure and never treated as an
  observation of this arm.
- **Fail-closed launch failures.** A launch that cannot start (foreign
  port, bind failure/early death, startup timeout, wrong-identity
  readiness) still consumes its request slots through the unchanged gate
  engine as transport-failed requests — no HTTP request is dispatched to
  any server that is not this launch's live, identity-verified child.
- **Cleanup.** Deterministic stop/reap of every owned child on success,
  gate-engine STOP, launch failure, and executor exception: no orphan
  process survives :func:`campaign_executor` returning.

CPU-only: no model loading, no GPU/Vulkan/device access, no physical
execution. The server command is supplied by the caller (the physical
``llama-server`` in production; a stdlib ``http.server`` stub in tests).
Observer-bracket slicing is the r3 driver's law, retained verbatim as
:func:`slice_request_bracket`; health sampling stays an injected callable.
The frozen admission/STOP law stays in ``scripts/issue280_runner.py``,
which this module does not modify.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

# Bounded lifecycle constants (seconds).
GRACEFUL_STOP_S = 10.0
ESCALATED_STOP_S = 5.0
STARTUP_TIMEOUT_S = 60.0
READY_POLL_INTERVAL_S = 0.25
STARTUP_PROBE_TIMEOUT_S = 1.0
LOG_FLUSH_WAIT_S = 5.0
LOG_FLUSH_POLL_S = 0.2
PORT_PROBE_TIMEOUT_S = 0.5

IDENTITY_ENV = "I280_LAUNCH_IDENTITY"
IDENTITY_HEADER = "X-I280-LAUNCH-IDENTITY"

# Events kept in the per-request observer bracket prefix (the r3 driver's
# slice law: recording + model-load inventory rows preceding the request).
BRACKET_PREFIX_EVENTS = ("recording", "weight_inventory", "kv_inventory",
                         "buffer_decl", "cpu_state", "unexplained_placement")


class LaunchError(RuntimeError):
    """Launch lifecycle failure. Always fail-closed: the executor turns
    this into a consumed request slot and a campaign STOP, never a retry."""


def utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def proc_start_time(pid: int) -> str | None:
    """Non-inherited process start time (field 22 of /proc/<pid>/stat).
    Together with the PID this identifies the exact process instance,
    defeating PID-reuse misattribution."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            stat = fh.read().decode("utf-8", "replace")
        fields = stat[stat.rindex(")") + 2:].split()
        return fields[19]
    except (OSError, ValueError, IndexError):
        return None


def pid_alive_same_instance(pid: int, start_time: str | None) -> bool:
    """The PID is alive AND is the same process instance the launcher
    spawned (same /proc start time). Strictly fail-closed (review
    5459338940 B3): a missing start-time identity NEVER authenticates a
    live PID — an unreadable /proc is an identity failure, not a
    permissive live-check."""
    if pid is None or pid <= 0 or start_time is None:
        return False
    observed = proc_start_time(pid)
    if observed is None:
        return False
    return observed == start_time


def port_occupied(host: str, port: int) -> bool:
    """True if some process is listening on host:port. Detection is a raw
    TCP connect that sends no bytes — an occupied port is NEVER probed
    with HTTP (the foreign listener is not contacted for service)."""
    try:
        with socket.create_connection((host, port),
                                      timeout=PORT_PROBE_TIMEOUT_S):
            return True
    except OSError:
        return False


def slice_request_bracket(log_text: str, ordinal: int) -> str | None:
    """Derive the per-request observer bracket from the append-only server
    log (r3 driver law, byte-identical semantics): the ``recording`` +
    model-load inventory rows preceding the request, plus the
    ``request_accept``..``request_end`` rows for this ordinal, with the
    ordinal rewritten to 1 and ``requests_planned`` rewritten to 1. The
    raw retained log itself is preserved separately; the bracket is a
    derived evidence view."""
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
    """One owned server launch: spawn, identity-checked readiness, requests
    through the owned child only, and bounded stop/reap.

    ``command_builder(arm, port, log_path, env_extra)`` returns the exact
    server argv (the launcher injects ``I280_LAUNCH_IDENTITY`` into the
    child environment itself). ``slice_observer`` defaults to
    :func:`slice_request_bracket`; ``retain(label, kind, record, bracket)``
    and ``health() -> (sample, stop_or_None)`` are optional injected
    callables matching the r3 driver's seams.
    """

    def __init__(self, row, *, command_builder, workdir, env=None,
                 host="127.0.0.1", port=8791, slice_observer=None,
                 retain=None, health=None, startup_timeout_s=STARTUP_TIMEOUT_S,
                 prompt_binding=None):
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
        # B4 (review 5459338940): the exact prompt bytes + request
        # settings the production caller must supply explicitly, keyed
        # by prompt id. There is NO default prompt text: a row without a
        # binding (or an explicit in-row synthetic prompt for CPU tests)
        # is rejected before any HTTP dispatch.
        self.prompt_binding = prompt_binding
        self.log_path = self.workdir / f"server-{self.label}.log"
        self.proc: subprocess.Popen | None = None
        self.log_file = None
        self._start_time: str | None = None
        self._identity: str | None = None
        self._t0: float | None = None
        self.startup_s: float | None = None
        self.ordinal = 0
        # traceable lifecycle record (request-to-server/arm binding)
        self.record: dict = {
            "label": self.label, "arm": self.arm, "pid": None,
            "identity": None, "host": host, "port": port,
            "started_utc": None, "ready_utc": None, "exit": None,
            "failure": None,
        }

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        """Spawn the owned child and block until THIS launch is ready.

        Raises :class:`LaunchError` on foreign port occupation, early
        child exit, startup timeout, or a readiness response carrying a
        foreign identity. On any post-spawn failure the child remains
        owned and must be :meth:`stop`ped by the caller (the production
        entry point does this deterministically)."""
        if port_occupied(self.host, self.port):
            raise LaunchError(
                f"PORT_OCCUPIED_BEFORE_START {self.host}:{self.port} by a "
                f"foreign process; launch {self.label} refuses to start "
                f"and will not contact the foreign listener")
        cmd = self.command_builder(self.arm, self.port, self.log_path,
                                   self.env_extra)
        env = dict(os.environ)
        # B2 (review 5459338940): the SAME dict the command_builder
        # received (and may have extended/updated — the documented r3
        # production pattern) is the child's environment base. The
        # builder's values are no longer silently discarded.
        env.update(self.env_extra)
        # Launch-identity injection authority: the launcher's generated
        # token always wins over caller- or builder-supplied values.
        self._identity = f"{self.label}#{os.getpid()}#{time.monotonic_ns():x}"
        env[IDENTITY_ENV] = self._identity
        self.record["identity"] = self._identity
        self.record["started_utc"] = utcnow()
        self.log_file = open(self.log_path, "wb")
        self._t0 = time.monotonic()
        try:
            self.proc = subprocess.Popen(cmd, stdout=self.log_file,
                                         stderr=self.log_file, env=env,
                                         start_new_session=True)
        except OSError as e:
            try:
                self.log_file.close()
            except OSError:
                pass
            self.log_file = None
            self.record["failure"] = f"SPAWN_FAILED {e}"
            raise LaunchError(
                f"SPAWN_FAILED launch={self.label} cmd={cmd[0]}: {e}")
        self.record["pid"] = self.proc.pid
        # B3 (review 5459338940): readiness/requests require a VALID
        # captured /proc start-time identity. A null capture is a hard
        # fail-closed launch failure (the child stays owned and is
        # stopped by the caller / executor).
        self._start_time = proc_start_time(self.proc.pid)
        if self._start_time is None:
            self.record["failure"] = (
                f"START_IDENTITY_CAPTURE_FAILED launch={self.label} "
                f"pid={self.proc.pid}: /proc start time unreadable; an "
                f"unverifiable process identity never becomes readiness")
            raise LaunchError(self.record["failure"])
        self._await_ready()
        self.record["ready_utc"] = utcnow()

    def _child_alive(self) -> tuple[bool, str | None]:
        """(alive, identity_error). B3: an unreadable /proc start time is
        an identity failure (IDENTITY_UNAVAILABLE), a changed start time
        is a mismatch (IDENTITY_MISMATCH) — both fail closed, never a
        permissive live-PID pass."""
        if self.proc is None or self.proc.poll() is not None:
            return False, None
        observed = proc_start_time(self.proc.pid)
        if observed is None:
            return False, "IDENTITY_UNAVAILABLE"
        if self._start_time is None or observed != self._start_time:
            return False, "IDENTITY_MISMATCH"
        return True, None

    def _await_ready(self):
        deadline = time.monotonic() + self.startup_timeout_s
        t0 = self._t0 or time.monotonic()
        last_observed = None
        while time.monotonic() < deadline:
            if not self._child_alive():
                code = self.proc.returncode if self.proc else None
                raise LaunchError(
                    f"CHILD_EXITED_BEFORE_READY launch={self.label} "
                    f"pid={self.record['pid']} code={code}")
            ident = self._probe_identity()
            if ident is not None:
                last_observed = ident
                if ident == self._identity:
                    self.startup_s = time.monotonic() - t0
                    return
                raise LaunchError(
                    f"FOREIGN_SERVER_IDENTITY launch={self.label} "
                    f"expected={self._identity} observed={ident}; a live "
                    f"listener answering for a different launch is never "
                    f"readiness for this one")
            time.sleep(READY_POLL_INTERVAL_S)
        raise LaunchError(
            f"STARTUP_TIMEOUT launch={self.label} pid={self.record['pid']} "
            f"last_observed_identity={last_observed}")

    def _probe_identity(self) -> str | None:
        """GET /health; return the identity token the serving process
        reports, or None. A 200 without this launch's identity is not
        readiness (and is never accepted silently)."""
        url = f"http://{self.host}:{self.port}/health"
        try:
            with urllib.request.urlopen(url,
                                        timeout=STARTUP_PROBE_TIMEOUT_S) as r:
                if r.status != 200:
                    return None
                token = r.headers.get(IDENTITY_HEADER)
                if token:
                    return token
                body = r.read(65536).decode("utf-8", "replace")
                try:
                    data = json.loads(body)
                except ValueError:
                    return None
                return data.get(IDENTITY_ENV) or data.get("identity")
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def stop(self):
        """Bounded graceful stop (SIGTERM to the owned process group),
        SIGKILL escalation restricted to the owned process group, always
        reap, verify exit. Returns the exit record (the FIRST stop's
        record is authoritative — later calls never rewrite it). Raises
        :class:`LaunchError` only if the owned child cannot be stopped."""
        if self.proc is None:
            return self.record["exit"]
        already = self.record["exit"]
        if already is not None and already.get("reaped"):
            return already
        try:
            if self.proc.poll() is None:
                self._signal_group(signal.SIGTERM)
                try:
                    self.proc.wait(GRACEFUL_STOP_S)
                except subprocess.TimeoutExpired:
                    self._signal_group(signal.SIGKILL)
                    try:
                        self.proc.wait(ESCALATED_STOP_S)
                    except subprocess.TimeoutExpired:
                        raise LaunchError(
                            f"UNSTOPPABLE_CHILD launch={self.label} "
                            f"pid={self.proc.pid}")
            self.record["exit"] = {"returncode": self.proc.returncode,
                                   "reaped": True,
                                   "stopped_utc": utcnow()}
            return self.record["exit"]
        finally:
            if self.log_file is not None:
                try:
                    self.log_file.close()
                except OSError:
                    pass
                self.log_file = None

    def _signal_group(self, sig):
        """Signal ONLY the owned child's process group (the launcher made
        it a session leader via start_new_session); fall back to the child
        PID itself if the group is already gone."""
        proc = self.proc
        if proc is None:
            return
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            if proc.poll() is None:
                try:
                    proc.send_signal(sig)
                except (ProcessLookupError, OSError):
                    pass

    # -- requests ----------------------------------------------------------

    def _resolve_prompt(self):
        """B4 (review 5459338940): resolve the EXACT prompt text and
        request settings for this launch's row, or return a rejection
        reason. No default text exists in production: the bytes come
        only from (in priority order) an explicit in-row synthetic test
        prompt (``prompt_text`` + ``prompt_sha256`` — CPU tests only) or
        the explicitly supplied frozen ``prompt_binding`` keyed by the
        row's prompt id. The resolved bytes are verified against their
        SHA-256 identity when one is supplied; a missing hash on a
        binding is a mismatch (ambiguity fails closed)."""
        prompt_id = self.row.get("prompt")
        if "prompt_text" in self.row:
            text = self.row["prompt_text"]
            expect = self.row.get("prompt_sha256")
            if not isinstance(text, str) or not text:
                return None, None, "PROMPT_BINDING_MISMATCH synthetic prompt_text empty"
            got = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if expect is not None and got != expect:
                return (None, None,
                        f"PROMPT_BINDING_MISMATCH prompt_sha256 {got[:12]}… "
                        f"!= bound {expect[:12]}…")
            settings = self.row.get("request_settings")
            return text, settings, None
        entry = (self.prompt_binding or {}).get(prompt_id)
        if entry is None:
            return (None, None,
                    f"PROMPT_BINDING_MISSING no prompt bytes bound for "
                    f"prompt id {prompt_id!r} (launch {self.label}); the "
                    f"production launcher refuses to substitute default "
                    f"prompt text")
        text = entry.get("text")
        expect = entry.get("utf8_sha256")
        if not isinstance(text, str) or not text:
            return (None, None,
                    f"PROMPT_BINDING_MISMATCH bound prompt {prompt_id!r} "
                    f"has empty/non-string text")
        if not isinstance(expect, str) or len(expect) != 64:
            return (None, None,
                    f"PROMPT_BINDING_MISMATCH bound prompt {prompt_id!r} "
                    f"lacks a valid utf8_sha256 identity; ambiguity fails "
                    f"closed")
        got = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if got != expect:
            return (None, None,
                    f"PROMPT_BINDING_MISMATCH prompt {prompt_id!r} bytes "
                    f"sha256 {got[:12]}… != frozen {expect[:12]}…")
        return text, entry.get("settings"), None

    def build_request(self, kind):
        """(url, body_bytes, headers, request_identity) for one
        completion request. B4: the prompt bytes and request settings
        are the explicitly supplied, hash-verified frozen values; a
        missing/mismatched binding raises LaunchError BEFORE any HTTP
        dispatch. The returned identity evidence (sha256 + byte count)
        never contains the prompt text itself."""
        text, settings, rejection = self._resolve_prompt()
        if rejection is not None:
            raise LaunchError(rejection)
        body_settings = {"n_predict": 128, "temperature": 0.0,
                         "top_k": 1, "seed": 42, "repeat_penalty": 1.0,
                         "cache_prompt": False, "samplers": ["top_k"],
                         "stream": True,
                         "timings_per_token": True}
        if settings:
            body_settings.update(settings)
        prompt_bytes = text.encode("utf-8")
        body = json.dumps({"prompt": text, **body_settings}).encode()
        identity = {
            "prompt_id": self.row.get("prompt"),
            "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "prompt_bytes": len(prompt_bytes),
            "request_settings": dict(body_settings),
        }
        return (f"http://{self.host}:{self.port}/completion", body,
                {"Content-Type": "application/json"}, identity)

    def request(self, kind):
        """One request, served by THIS launch only. The response must echo
        this launch's identity token (header or SSE field); anything else
        — stale server, foreign listener, PID-reused process — is recorded
        as an identity-mismatch transport failure and is never admitted as
        an observation of this arm."""
        alive, identity_error = self._child_alive()
        if not alive:
            code = self.proc.returncode if self.proc else None
            detail = (f"CHILD_IDENTITY_{identity_error} "
                      f"launch={self.label} pid={self.record['pid']} "
                      f"expected_start={self._start_time!r}"
                      if identity_error else
                      f"CHILD_NOT_LIVE_AT_REQUEST launch={self.label} "
                      f"pid={self.record['pid']} code={code}")
            return self._failed_request(kind, detail)
        try:
            url, data, headers, request_identity = self.build_request(kind)
        except LaunchError as e:
            # B4: prompt/request binding rejected BEFORE any HTTP
            # dispatch — the slot is consumed fail-closed, never sent.
            return self._failed_request(kind, str(e))
        self.ordinal += 1
        ordinal = self.ordinal
        t0 = time.monotonic()
        ttft = None
        chunks = []
        final = None
        transport_ok = True
        err = None
        server_identity = None
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                server_identity = r.headers.get(IDENTITY_HEADER)
                for line in r:
                    if not line.startswith(b"data: "):
                        continue
                    try:
                        c = json.loads(line[6:].decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if server_identity is None and c.get("identity"):
                        server_identity = c["identity"]
                    if c.get("content"):
                        if ttft is None:
                            ttft = time.monotonic() - t0
                        chunks.append(c["content"])
                    if c.get("stop") is True or (
                            isinstance(c.get("stop"), str) and c.get("stop")):
                        final = c
                        if not c.get("content"):
                            break
        except Exception as e:  # any transport failure
            transport_ok = False
            err = f"{type(e).__name__}: {e}"
        wall = time.monotonic() - t0
        mismatch = False
        if transport_ok and server_identity != self._identity:
            mismatch = True
            transport_ok = False
            err = (f"SERVER_IDENTITY_MISMATCH launch={self.label} "
                   f"expected={self._identity} observed={server_identity}; "
                   f"response not attributable to this launch/arm")
        record = {
            "launch": self.label, "arm": self.arm,
            "prompt": self.row.get("prompt"), "kind": kind,
            "ordinal": ordinal,
            "server_pid": self.record["pid"],
            "server_identity": server_identity,
            "launch_identity": self._identity,
            "identity_mismatch": mismatch,
            "request_identity": request_identity,
            "text": "".join(chunks), "transport_ok": transport_ok,
            "error": err, "ttft_s": ttft, "wall_s": wall,
            "startup_s": self.startup_s,
            "final": ({k: final.get(k) for k in
                       ("stop_type", "tokens_predicted", "tokens_evaluated",
                        "timings")} if final else None),
        }
        # bounded wait for the owned server log to flush request_end, then
        # derive the observer bracket through the r3 slice law
        bracket = None
        if transport_ok:
            deadline = time.monotonic() + LOG_FLUSH_WAIT_S
            while time.monotonic() < deadline:
                bracket = self.slice_observer(self._read_log(), ordinal)
                if bracket is not None:
                    break
                time.sleep(LOG_FLUSH_POLL_S)
        health_sample, health_stop = (None, None)
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

    def _failed_request(self, kind, error):
        """A request slot consumed without dispatching any HTTP bytes
        (launch not live / not ready). Fail-closed through the unchanged
        gate engine: transport failed -> slot consumed -> STOP."""
        record = {
            "launch": self.label, "arm": self.arm,
            "prompt": self.row.get("prompt"), "kind": kind,
            "server_pid": self.record["pid"],
            "server_identity": None, "launch_identity": self._identity,
            "identity_mismatch": False, "request_identity": None,
            "text": "", "transport_ok": False,
            "error": error, "ttft_s": None, "wall_s": 0.0,
            "startup_s": self.startup_s, "final": None, "health_stop": None,
        }
        if self.retain is not None:
            self.retain(self.label, kind, record, None)
        return record, {"observer_raw": None, "peak_rss_bytes": None}

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
                      startup_timeout_s=STARTUP_TIMEOUT_S,
                      prompt_binding=None):
    """Deterministic production entry point: run the whole matrix through
    the UNCHANGED pure gate engine (``issue280_runner.run_campaign``) with
    the corrected launch lifecycle. Returns ``(summary, launches)``.

    B4 (review 5459338940): ``prompt_binding`` maps prompt id -> frozen
    entry ``{"text", "utf8_sha256", "settings"}`` (e.g. the accepted
    ``docs/investigations/vulkan-same-request-280/workload.json`` prompts).
    It is REQUIRED for production matrices whose rows carry only a
    prompt id: a row without bound, hash-verified prompt bytes is
    rejected before any HTTP dispatch (no silent default text). CPU
    tests use explicit in-row ``prompt_text``/``prompt_sha256`` instead.

    Every owned child is stopped and reaped before control returns — on
    COMPLETE, on gate-engine STOP, on launch failure, and on exception.
    A launch lifecycle failure is carried into the engine as a
    transport-failed request (slot consumed, synchronous STOP); it never
    raises out of the engine loop and never dispatches HTTP to a server
    that is not the launch's own live, identity-verified child."""
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
    stopped = set()

    def stop_owned(ctx: Launch, *, phase: str):
        if ctx.label not in stopped:
            ctx.stop()
            stopped.add(ctx.label)
        if port_occupied(host, port):
            raise LaunchError(
                f"PORT_NOT_RELEASED_AFTER_STOP launch={ctx.label} "
                f"phase={phase} {host}:{port}; refusing to start the next "
                f"launch against an unverified port")

    def launch(row):
        # LAW: stop and reap every prior owned launch BEFORE the next one
        # begins, and verify the port is released.
        launch_failure = None
        for prior in launches:
            try:
                stop_owned(prior, phase="pre-launch")
            except LaunchError as e:
                launch_failure = f"prior launch failed to stop: {e}"
        ctx = Launch(row, command_builder=command_builder, workdir=workdir,
                     env=env, host=host, port=port,
                     slice_observer=slice_observer, retain=retain,
                     health=health, startup_timeout_s=startup_timeout_s,
                     prompt_binding=prompt_binding)
        if launch_failure is None:
            try:
                ctx.start()
            except LaunchError as e:
                ctx.record["failure"] = str(e)
                launch_failure = str(e)
                # deterministic cleanup of the failed-but-owned child
                try:
                    ctx.stop()
                    stopped.add(ctx.label)
                except LaunchError:
                    pass
        else:
            ctx.record["failure"] = launch_failure
        launches.append(ctx)
        if on_launch_record is not None:
            on_launch_record(dict(ctx.record))

        def request(kind):
            if launch_failure is not None or not ctx.record.get("ready_utc"):
                return ctx._failed_request(
                    kind, f"LAUNCH_FAILURE launch={ctx.label}: "
                          f"{launch_failure or ctx.record.get('failure')}")
            return ctx.request(kind)

        return request

    try:
        summary = runner.run_campaign(matrix, launch)
    finally:
        for ctx in launches:
            try:
                ctx.stop()
            except LaunchError:
                # already reported through the launch record; never mask
                # an in-flight exception with a cleanup error
                pass
    return summary, launches
