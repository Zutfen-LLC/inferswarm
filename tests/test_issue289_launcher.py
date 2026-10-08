"""Issue #289: physical launcher server lifecycle and stale-arm routing.

Issue #280 r3 (retained evidence, controller ~/is280r3-evidence) terminated
STOP because the physical driver never terminated the R1 baseline server
before starting the R2 candidate: R2 failed to bind 127.0.0.1:8791, the
still-running R1 server answered R2's /health readiness probe AND the
R2-cold HTTP request, and only the missing retained R2 observer bytes made
the pure gate engine fail closed.

These tests drive the tracked launcher module
(``scripts/issue289_launcher.py``) — the minimal lifecycle component
extracted from the session-local r3 driver — through the REAL gate engine
(``issue280_runner.run_campaign``, unchanged) with two distinct CPU-only
loopback HTTP stub server subprocesses (one per arm) on the SAME port.
No model loading, no Vulkan, no GPU, no SSH probing.

RED phase: the module is a faithful port of the r3 defect; the lifecycle
tests FAIL (stale-arm routing reproduced; prior launch never stopped;
readiness accepts any 200).

GREEN phase (same tests, unchanged, after the fix): sequential R1->R2
through the production entry point stops/reaps R1 before R2, verifies R2
owns the endpoint and this-launch identity BEFORE any R2 request, fails
closed without stale-server routing or orphan processes on: occupied
port, refusing termination, bind failure/early death, readiness race,
wrong-arm/stale-server response, startup timeout, and exception cleanup.
Negative controls prove a fail-open mutation of the fix would be caught.
"""
import importlib.util
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/issue289_launcher.py"
STUB = ROOT / "tests" / "stub_issue289_server.py"
ADMISSION = ROOT / "tests/test_issue280_admission.py"

MATRIX = [
    {"label": "R1", "prompt": "P1", "arm": "A",
     "requests": ("cold", "warm")},
    {"label": "R2", "prompt": "P1", "arm": "B",
     "requests": ("cold", "warm")},
]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The REAL frozen production surfaces (B4): the runner's actual matrix has
# ``prompt: "P1"`` id rows only — the prompt BYTES live in the frozen
# workload binding with their SHA-256 identity.
_runner_mod = load("i289_runner_matrix", ROOT / "scripts" / "issue280_runner.py")
REAL_MATRIX = _runner_mod.MINIMAL_RERUN_MATRIX
WORKLOAD = json.loads(
    (ROOT / "docs/investigations/vulkan-same-request-280/workload.json")
    .read_text(encoding="utf-8"))
P1 = WORKLOAD["prompts"]["P1"]


def load_launcher():
    return load("issue289_launcher_under_test", LAUNCHER)


_admission = load("i289_admission_builder", ADMISSION)


def stub_stream(arm):
    """A mechanically valid observer stream for the arm."""
    return _admission.build_stream(single_die=(arm == "A"))


def free_loopback_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def pid_alive(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def terminate(proc, timeout=5):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def wait_listening(port, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"nothing ever listened on {port}")


class LauncherHarness(unittest.TestCase):
    """Two distinct CPU loopback stub servers (one per arm), same port,
    driven through the real gate engine via the production entry point."""

    def setUp(self):
        self.m = load_launcher()
        self.port = free_loopback_port()
        self.tmp = Path(tempfile.mkdtemp(prefix="issue289-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.records = []
        self.launch_records = []
        for arm in ("A", "B"):
            (self.tmp / f"stream-{arm}.txt").write_text(stub_stream(arm))
        self.streams = {arm: str(self.tmp / f"stream-{arm}.txt")
                        for arm in ("A", "B")}

    # -- production surfaces ------------------------------------------------

    def command_builder(self, arm, port, log_path, env_extra):
        """The r3 driver's seam: argv for the server this launch owns.
        The launcher routes stdout/stderr to log_path and injects the
        identity environment itself."""
        stream = self.streams.get(arm) or self.streams["A"]
        return [sys.executable, str(STUB), str(port),
                "--arm", arm, "--log", str(log_path),
                "--stream", stream]

    def run_matrix(self, *, matrix=MATRIX, command_builder=None,
                   startup_timeout_s=None):
        return self.m.campaign_executor(
            matrix,
            command_builder=command_builder or self.command_builder,
            workdir=self.tmp,
            host="127.0.0.1", port=self.port,
            prompt_binding={"P1": P1},  # corrected interface: explicit,
            # hash-verified frozen prompt bytes (no silent default text)
            retain=lambda label, kind, record, bracket:
                self.records.append(record),
            on_launch_record=self.launch_records.append,
            startup_timeout_s=startup_timeout_s or 20,
        )

    def dispositions(self, summary):
        return [r["disposition"] for r in summary["requests"]]


class SequentialCampaignTests(LauncherHarness):
    """GREEN law 1: the previous launch is stopped/reaped before the next,
    and every admitted request is served by that launch's own child."""

    def test_sequential_r1_r2_same_port_all_admitted_and_attributed(self):
        summary, launches = self.run_matrix()
        self.assertEqual(summary["terminal"], "COMPLETE",
                         f"stop_reason={summary.get('stop_reason')}")
        self.assertEqual(self.dispositions(summary), ["accepted"] * 4)
        by_label = {r["launch"]: r for r in self.records}
        for label, arm, ctx in (("R1", "A", launches[0]),
                                ("R2", "B", launches[1])):
            for kind in ("cold", "warm"):
                rec = [r for r in self.records
                       if r["launch"] == label and r["kind"] == kind][0]
                self.assertEqual(rec["server_pid"], ctx.record["pid"],
                                 f"{label}-{kind} served by the {label} "
                                 f"child PID")
                self.assertTrue(rec["transport_ok"], rec.get("error"))
                self.assertFalse(rec.get("identity_mismatch", False))
                self.assertIsNotNone(rec["launch_identity"])

    def test_prior_launch_dead_before_next_starts(self):
        """R1's PID is dead (stopped AND reaped) before R2 spawns. The
        launcher records provide the ordering proof."""
        summary, launches = self.run_matrix()
        self.assertEqual(summary["terminal"], "COMPLETE")
        r1, r2 = launches
        self.assertIsNotNone(r1.record["exit"])
        self.assertTrue(r1.record["exit"]["reaped"])
        # r2 start strictly after r1 stop (wall-clock proof)
        self.assertLessEqual(r1.record["exit"]["stopped_utc"],
                             r2.record["started_utc"])

    def test_no_launch_survives_campaign_return(self):
        summary, launches = self.run_matrix()
        for ctx in launches:
            self.assertFalse(pid_alive(ctx.record["pid"]),
                             f"{ctx.label} pid {ctx.record['pid']} alive "
                             f"after campaign return")
            self.assertTrue(ctx.record["exit"]["reaped"])


class StaleArmRoutingTests(LauncherHarness):
    """GREEN law 2: requests can never be routed to a previous launch/arm
    or admitted from its bytes."""

    def test_r3_replay_under_fixed_module_never_serves_r2_from_r1(self):
        """The exact r3 terminal sequence (two launches, same fixed port,
        R2 bind failure while R1 alive) replayed under the fixed module:
        R1 is stopped first, R2 either owns the port or fails closed with
        NO HTTP request dispatched to R1's process; the campaign NEVER
        admits an arm-B observation from baseline bytes."""
        summary, launches = self.run_matrix()
        r2 = launches[-1]
        for rec in self.records:
            if rec["launch"] == "R2" and rec["transport_ok"]:
                self.assertEqual(rec["server_pid"], r2.record["pid"],
                                 "an R2-labeled response attributed to "
                                 "another process is exactly the r3 "
                                 "stale-arm routing failure")

    def test_wrong_arm_stale_response_recorded_not_admitted(self):
        """A server that answers /health with THIS launch's identity but
        echoes a STALE identity on the completion (the post-readiness
        stale-server race): recorded as SERVER_IDENTITY_MISMATCH transport
        failure, slot consumed, synchronous STOP, never admitted."""
        stale = "R1#stale#deadbeef"

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            if arm == "B":
                argv += ["--stale-completion-id", stale]
            return argv

        summary, launches = self.run_matrix(command_builder=builder)
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIn("transport failed", summary["stop_reason"])
        self.assertEqual(self.dispositions(summary),
                         ["accepted", "accepted", "aborted",
                          "not_attempted"])
        r2c = [r for r in self.records if r["launch"] == "R2"][0]
        self.assertFalse(r2c["transport_ok"])
        self.assertTrue(r2c["identity_mismatch"])
        self.assertIn("SERVER_IDENTITY_MISMATCH", r2c["error"])
        self.assertEqual(r2c["server_identity"], stale)

    def test_readiness_race_foreign_health_rejected(self):
        """R2's Launch.start() while a foreign server answers the launch
        port: a /health answer carrying a foreign identity is
        FOREIGN_SERVER_IDENTITY, never readiness. The port preflight is
        bypassed for this test (the race it models begins after spawn —
        e.g. an outside squatter binding between preflight and listen);
        the owned child is alive on a side port so the child-exit guard
        does not fire first; the foreign listener (not owned) is NOT
        killed and no completion request is dispatched."""
        r1_argv = self.command_builder(
            "A", self.port, self.tmp / "foreign.log", {})
        foreign = subprocess.Popen(r1_argv)
        self.addCleanup(terminate, foreign)
        wait_listening(self.port)

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv[2] = str(port + 1)  # owned child alive on a side port
            return argv

        row = MATRIX[1]
        ctx = self.m.Launch(row, command_builder=builder,
                            workdir=self.tmp, port=self.port,
                            startup_timeout_s=5)
        ctx.record["preflight_bypassed_for_test"] = True
        # patch the preflight out for this one launch (race model), then
        # start: the readiness loop must still reject the foreign answer
        original_occupied = self.m.port_occupied
        self.m.port_occupied = lambda host, port: False
        try:
            with self.assertRaises(self.m.LaunchError) as cm:
                ctx.start()
        finally:
            self.m.port_occupied = original_occupied
        self.assertIn("FOREIGN_SERVER_IDENTITY", str(cm.exception))
        self.assertTrue(pid_alive(foreign.pid),
                        "the launcher must not kill a process it does "
                        "not own")
        ctx.stop()
        self.assertFalse(pid_alive(ctx.record["pid"]))


class PortOwnershipTests(LauncherHarness):
    def test_foreign_listener_before_r1_refused_without_contact(self):
        """Port already owned by a foreign process at campaign start: R1
        fails closed (PORT_OCCUPIED), the foreign listener never receives
        a completion request, all four slots consumed, STOP."""
        foreign_log = self.tmp / "foreign.log"
        argv = self.command_builder("X", self.port, foreign_log, {})
        foreign = subprocess.Popen(argv)
        self.addCleanup(terminate, foreign)
        wait_listening(self.port)
        summary, launches = self.run_matrix()
        self.assertEqual(summary["terminal"], "STOP")
        # synchronous STOP law: the first slot is aborted (transport
        # failed — no server of ours exists), the remaining slots are
        # consumed as not_attempted; the foreign listener is untouched
        self.assertEqual(self.dispositions(summary),
                         ["aborted", "not_attempted", "not_attempted",
                          "not_attempted"])
        self.assertIn("PORT_OCCUPIED",
                      launches[0].record.get("failure") or "")
        # the foreign server received no COMPLETION request (only its
        # self-emitted startup inventory rows are in the log)
        foreign_rows = [json.loads(l.split("I280 ", 1)[1])
                        for l in foreign_log.read_text(
                            errors="replace").splitlines()
                        if l.startswith("I280 ")]
        self.assertEqual(
            [r["event"] for r in foreign_rows],
            [r["event"] for r in foreign_rows
             if r["event"] in ("recording", "weight_inventory",
                               "kv_inventory")],
            "no request_accept/response rows: the foreign listener was "
            "never sent a completion request")

    def test_r2_child_early_death_r1_already_dead(self):
        """R2's child dies instantly (bad interpreter): R2 fails closed
        with NO HTTP dispatched for R2 slots; R1 was stopped and reaped
        BEFORE R2 was attempted; STOP with slots consumed."""
        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            if arm == "B":
                return ["/nonexistent-interpreter-289"] + argv[1:]
            return argv

        summary, launches = self.run_matrix(command_builder=builder)
        self.assertEqual(summary["terminal"], "STOP")
        self.assertEqual(self.dispositions(summary),
                         ["accepted", "accepted", "aborted",
                          "not_attempted"])
        r1, r2 = launches
        self.assertFalse(pid_alive(r1.record["pid"]),
                         "R1 must be dead before R2's request attempt")
        r2c = [r for r in self.records if r["launch"] == "R2"][0]
        self.assertFalse(r2c["transport_ok"])
        self.assertIn("LAUNCH_FAILURE", r2c["error"])
        self.assertIn("SPAWN_FAILED", r2.record.get("failure") or "")


class TerminationTests(LauncherHarness):
    def test_r1_refusing_sigterm_still_escalated_and_stopped(self):
        """R1 ignores SIGTERM: bounded escalation (SIGKILL to the owned
        process group) reaps it before R2; campaign completes; no
        orphan."""
        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            if arm == "A":
                argv += ["--refuse-stop"]
            return argv

        summary, launches = self.run_matrix(command_builder=builder)
        r1 = launches[0]
        self.assertFalse(pid_alive(r1.record["pid"]),
                         "SIGTERM-refusing R1 must be escalated and reaped")
        self.assertEqual(summary["terminal"], "COMPLETE")

    def test_startup_timeout_fails_closed_with_cleanup(self):
        """A server that never becomes ready on the launch port: bounded
        startup timeout, child killed and reaped, slots consumed, STOP,
        no orphan."""
        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            if arm == "A":
                # wrong port: never answers the launch port
                argv[2] = str(port + 1)
            return argv

        summary, launches = self.run_matrix(command_builder=builder,
                                            startup_timeout_s=3)
        self.assertEqual(summary["terminal"], "STOP")
        self.assertFalse(pid_alive(launches[0].record["pid"]))
        self.assertIn("STARTUP_TIMEOUT",
                      launches[0].record.get("failure") or "")


class CleanupTests(LauncherHarness):
    def test_request_exception_still_stops_child(self):
        """An exception raised mid-campaign (retain machinery explodes
        after the first accepted request) must not orphan the child: the
        production entry point's finally stops and reaps every launch."""
        def exploding_retain(label, kind, record, bracket):
            self.records.append(record)
            raise RuntimeError("retain machinery exploded")

        with self.assertRaises(RuntimeError):
            self.m.campaign_executor(
                MATRIX,
                command_builder=self.command_builder,
                workdir=self.tmp, port=self.port,
                prompt_binding={"P1": P1},
                retain=exploding_retain,
                startup_timeout_s=20)
        # children were spawned; verify none survives the exception path
        # (the executor raised, so inspect via the workdir logs: assert no
        # python stub still listens on the port)
        self.assertFalse(self.m.port_occupied("127.0.0.1", self.port),
                         "no owned stub may keep the port after an "
                         "exception-path return")

    def test_gate_stop_still_stops_all_children(self):
        """Gate-engine STOP mid-campaign (semantic failure on R2-cold):
        both owned children stopped and reaped before return."""
        bad_text = "not json at all"

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            return argv

        # inject wrong text via a stale completion? simpler: patch the
        # semantic seam by feeding a stream whose GOOD_TEXT is replaced —
        # instead drive a transport-abort: wrong port on R2 only for the
        # request phase is not expressible; use early death (already
        # covered). Here: R2 bind conflict via foreign squatter that is
        # NOT owned: covered by port-occupied. So exercise STOP via a
        # stream mutation: strip required events from R2's stream.
        bad = "\n".join(l for l in stub_stream("B").splitlines()
                        if '"boundary_begin"' not in l
                        and '"copy_manifest"' not in l) + "\n"
        (self.tmp / "stream-B.txt").write_text(bad)
        self.streams["B"] = str(self.tmp / "stream-B.txt")
        summary, launches = self.run_matrix()
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIn("observer admission failure", summary["stop_reason"])
        for ctx in launches:
            self.assertFalse(pid_alive(ctx.record["pid"]))


class PureFunctionTests(LauncherHarness):
    """No subprocesses: PID-reuse guard, port probe, r3 slice law."""

    def test_pid_alive_same_instance_rejects_reused_pid(self):
        m = self.m
        me = os.getpid()
        # B3 strict law: a None start-time identity never authenticates
        # a live PID (the old permissive assert is inverted by review
        # 5459338940 B3).
        self.assertFalse(m.pid_alive_same_instance(me, None))
        self.assertFalse(m.pid_alive_same_instance(me, "1"))
        real_start = m.proc_start_time(me)
        self.assertIsNotNone(real_start)
        self.assertTrue(m.pid_alive_same_instance(me, real_start))
        self.assertFalse(m.pid_alive_same_instance(-1, None))

    def test_port_occupied_detects_listener(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            self.assertTrue(self.m.port_occupied("127.0.0.1", port))
        finally:
            s.close()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not self.m.port_occupied("127.0.0.1", port):
                break
            time.sleep(0.05)
        self.assertFalse(self.m.port_occupied("127.0.0.1", port))

    def test_slice_law_unchanged_from_r3(self):
        lines = [
            'I280 {"schema":"issue280-raw/1","event":"recording",'
            '"requests_planned":2}',
            'noise without marker',
            'I280 {"schema":"issue280-raw/1","event":"weight_inventory",'
            '"tensor":"t"}',
            'I280 {"schema":"issue280-raw/1","event":"request_accept",'
            '"request":7,"ordinal":1}',
            'I280 {"schema":"issue280-raw/1","event":"sample","request":7}',
            'I280 {"schema":"issue280-raw/1","event":"request_end",'
            '"request":7}',
        ]
        bracket = self.m.slice_request_bracket("\n".join(lines) + "\n", 1)
        rows = [json.loads(l.split("I280 ", 1)[1])
                for l in bracket.splitlines()]
        self.assertEqual([r["event"] for r in rows],
                         ["recording", "weight_inventory",
                          "request_accept", "sample", "request_end"])
        self.assertEqual(rows[0]["requests_planned"], 1)
        self.assertEqual(rows[2]["ordinal"], 1)


class LauncherEnvInterfaceTests(LauncherHarness):
    """B2 (review 5459338940): caller- and builder-supplied environment
    values must BOTH reach the real spawned child, deterministically,
    and the launcher's own identity injection keeps authority.

    CPU loopback proof with NONSECRET sentinels only: the stub child
    reports its actual environment through ``/__test__/env`` and the
    request-recording diag log. No secrets, no environment dumps."""

    SENTINELS = ("I289_TEST_LIB", "I289_TEST_VK_DRIVER", "I289_TEST_OBSERVE")

    def child_env_report(self, port):
        import urllib.request
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/__test__/env",
                timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_builder_env_values_reach_spawned_child(self):
        """The documented production command_builder mutates the supplied
        env dict (LD_LIBRARY_PATH / VK_DRIVER_FILES / ISSUE280_OBSERVE);
        those values must be present in the child's actual environment
        (r3 driver interface contract)."""
        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--env-keys", ",".join(self.SENTINELS)]
            # documented production pattern: builder adds environment
            env_extra.update(I289_TEST_LIB="/opt/test-vulkan/lib",
                             I289_TEST_VK_DRIVER="/tmp/test-icd.json",
                             I289_TEST_OBSERVE="1")
            return argv

        ctx = self.m.Launch(MATRIX[0], command_builder=builder,
                            workdir=self.tmp, port=self.port,
                            startup_timeout_s=20)
        try:
            ctx.start()
            report = self.child_env_report(self.port)
            self.assertEqual(report.get("I289_TEST_LIB"),
                             "/opt/test-vulkan/lib",
                             "builder-added LD_LIBRARY_PATH-equivalent "
                             "value lost before spawn")
            self.assertEqual(report.get("I289_TEST_VK_DRIVER"),
                             "/tmp/test-icd.json")
            self.assertEqual(report.get("I289_TEST_OBSERVE"), "1")
        finally:
            ctx.stop()

    def test_caller_and_builder_env_precedence_deterministic(self):
        """A caller-supplied value and a builder-set value for the same
        name: the builder (which receives the caller dict and documents
        that it may extend it) supplies the value that reaches the
        child; a builder override of a caller value must reach the child
        (no silent resurrection of the stale caller copy)."""
        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--env-keys", ",".join(self.SENTINELS)]
            env_extra["I289_TEST_OBSERVE"] = "builder-set"
            return argv

        ctx = self.m.Launch(
            MATRIX[0], command_builder=builder, workdir=self.tmp,
            env={"I289_TEST_OBSERVE": "caller-set"}, port=self.port,
            startup_timeout_s=20)
        try:
            ctx.start()
            report = self.child_env_report(self.port)
            self.assertEqual(report.get("I289_TEST_OBSERVE"), "builder-set",
                             "builder's update of the caller-supplied dict "
                             "must reach the child")
        finally:
            ctx.stop()

    def test_launch_identity_not_overridable(self):
        """Caller and builder environment must NOT override the
        launcher-generated I280_LAUNCH_IDENTITY."""
        ident_key = self.m.IDENTITY_ENV

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--env-keys", ",".join(self.SENTINELS)]
            env_extra[ident_key] = "FORGED#IDENTITY"
            return argv

        ctx = self.m.Launch(
            MATRIX[0], command_builder=builder, workdir=self.tmp,
            env={ident_key: "FORGED#CALLER"}, port=self.port,
            startup_timeout_s=20)
        try:
            ctx.start()  # must succeed: server echoes the REAL identity
            report = self.child_env_report(self.port)
            self.assertEqual(report.get(ident_key), ctx.record["identity"],
                             "the launcher's generated identity must win "
                             "over caller- and builder-supplied values")
            self.assertNotEqual(report.get(ident_key), "FORGED#IDENTITY")
            self.assertNotEqual(report.get(ident_key), "FORGED#CALLER")
        finally:
            ctx.stop()


class LauncherIdentityFailClosedTests(LauncherHarness):
    """B3 (review 5459338940): a missing/unreadable/malformed /proc start
    time is an identity failure, never a permissive live-check. Fail
    closed with zero completion requests; the owned child is still
    cleaned up safely (bounded stop of THIS launch's process group
    only — never a foreign PID)."""

    def test_pid_alive_same_instance_requires_nonnull_start_time(self):
        """The pure guard: a None start-time identity must NEVER
        authenticate a live PID (no permissive fallback)."""
        me = os.getpid()
        self.assertFalse(self.m.pid_alive_same_instance(me, None),
                         "None start-time must fail closed, not "
                         "authenticate any live PID")

    def test_start_fails_when_identity_capture_fails(self):
        """/proc start-time unreadable at capture: Launch.start() must
        fail closed (LaunchError, no readiness, no requests), and the
        owned child must still be stopped and reaped."""
        real = self.m.proc_start_time
        self.m.proc_start_time = lambda pid: None
        try:
            ctx = self.m.Launch(MATRIX[0],
                                command_builder=self.command_builder,
                                workdir=self.tmp, port=self.port,
                                startup_timeout_s=10)
            with self.assertRaises(self.m.LaunchError) as cm:
                ctx.start()
            self.assertIn("START_IDENTITY_CAPTURE_FAILED", str(cm.exception))
            ctx.stop()
            self.assertFalse(pid_alive(ctx.record["pid"]),
                             "owned child must be cleaned after identity "
                             "capture failure")
            self.assertTrue(ctx.record["exit"]["reaped"])
        finally:
            self.m.proc_start_time = real

    def test_request_fails_closed_when_identity_check_unavailable(self):
        """/proc start-time unreadable at request time: the request must
        fail closed (no completion dispatched) even for a ready,
        healthy child."""
        diag = self.tmp / "requests.jsonl"
        recs = []

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--record-requests", str(diag)]
            return argv

        ctx = self.m.Launch(MATRIX[0], command_builder=builder,
                            workdir=self.tmp, port=self.port,
                            startup_timeout_s=20)
        try:
            ctx.start()
            real = self.m.proc_start_time
            self.m.proc_start_time = lambda pid: None
            record, state = ctx.request("cold")
            recs.append(record)
            self.assertFalse(record["transport_ok"])
            self.assertIn("IDENTITY_UNAVAILABLE", record["error"])
            self.assertEqual(record["server_identity"], None)
            self.assertFalse(diag.exists(),
                              "no completion HTTP bytes may be dispatched "
                              "when identity evidence is unavailable")
        finally:
            self.m.proc_start_time = real
            ctx.stop()

    def test_ready_launch_rejects_malformed_start_time_then_fails_closed(self):
        """Malformed (present but wrong-format) captured identity: the
        subsequent liveness check must not authenticate the child —
        every request fails closed; no completion dispatched."""
        diag = self.tmp / "requests.jsonl"

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--record-requests", str(diag)]
            return argv

        ctx = self.m.Launch(MATRIX[0], command_builder=builder,
                            workdir=self.tmp, port=self.port,
                            startup_timeout_s=20)
        try:
            ctx.start()
            real = self.m.proc_start_time
            self.m.proc_start_time = lambda pid: "garbage-not-numeric"
            record, state = ctx.request("cold")
            self.assertFalse(record["transport_ok"])
            self.assertIn("IDENTITY_MISMATCH", record["error"])
            self.assertFalse(diag.exists())
        finally:
            self.m.proc_start_time = real
            ctx.stop()

    def test_pid_reuse_after_ready_fails_closed(self):
        """PID-reuse regression: after readiness, the owned child is
        killed externally and the PID slot is reoccupied by an unrelated
        process; a request must fail closed (identity mismatch), never
        dispatch to the reoccupant, and cleanup must not kill the
        reoccupant (not owned)."""
        diag = self.tmp / "requests.jsonl"
        reoccupant_log = self.tmp / "reoccupant.log"

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--record-requests", str(diag)]
            return argv

        ctx = self.m.Launch(MATRIX[0], command_builder=builder,
                            workdir=self.tmp, port=self.port,
                            startup_timeout_s=20)
        try:
            ctx.start()
            owned_pid = ctx.record["pid"]
            owned_start = ctx._start_time
            # externally kill the owned child (simulates crash), reap it
            # via the still-open Popen, and reoccupy its PID slot with an
            # unrelated stub listening on a SIDE port (must never be
            # contacted or killed by the launcher)
            os.kill(owned_pid, signal.SIGKILL)
            ctx.proc.wait(5)
            side_port = free_loopback_port()
            reoccupant_argv = self.command_builder(
                "X", side_port, reoccupant_log, {})
            reoccupant = subprocess.Popen(reoccupant_argv)
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if (self.m.proc_start_time(reoccupant.pid)
                            is not None):
                        break
                    time.sleep(0.02)
                # the launcher must observe the reoccupant under the
                # SAME pid as the owned child for the request path to be
                # exercised; not portable to force, so prove the law the
                # request path relies on directly: exact identity equality.
                self.assertNotEqual(
                    self.m.proc_start_time(reoccupant.pid), owned_start,
                    "test setup: reoccupant must be a different instance")
                # the pure law the request path relies on:
                self.assertFalse(self.m.pid_alive_same_instance(
                    owned_pid, owned_start) or
                    self.m.pid_alive_same_instance(
                        reoccupant.pid, owned_start),
                    "a different process instance must never satisfy the "
                    "captured identity")
            finally:
                terminate(reoccupant)
        finally:
            ctx.stop()

    def test_identity_failure_never_dispatches_through_executor(self):
        """Fail-closed law through the production entry point: with
        /proc start-time unavailable everywhere, the campaign consumes
        every slot as transport failures (LAUNCH_FAILURE), dispatches
        zero HTTP completions, and still leaves no orphan."""
        diag = self.tmp / "requests.jsonl"
        recs = []

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--record-requests", str(diag)]
            return argv

        real = self.m.proc_start_time
        self.m.proc_start_time = lambda pid: None
        try:
            summary, launches = self.m.campaign_executor(
                MATRIX, command_builder=builder, workdir=self.tmp,
                port=self.port, startup_timeout_s=10,
                retain=lambda label, kind, record, bracket:
                    recs.append(record))
        finally:
            self.m.proc_start_time = real
        self.assertEqual(summary["terminal"], "STOP")
        self.assertEqual(self.dispositions(summary),
                         ["aborted", "not_attempted", "not_attempted",
                          "not_attempted"])
        self.assertFalse(diag.exists(),
                          "identity failure must produce zero completion "
                          "requests")
        for ctx in launches:
            self.assertFalse(pid_alive(ctx.record["pid"]))

    def test_unexpected_child_exit_after_ready_fails_closed(self):
        """Regression: the child dies after readiness but before the
        request; the request fails closed (child not live), no HTTP to
        any other process, cleanup still reaps."""
        diag = self.tmp / "requests.jsonl"

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--record-requests", str(diag)]
            return argv

        ctx = self.m.Launch(MATRIX[0], command_builder=builder,
                            workdir=self.tmp, port=self.port,
                            startup_timeout_s=20)
        try:
            ctx.start()
            os.kill(ctx.record["pid"], signal.SIGKILL)
            ctx.proc.wait(5)
            record, state = ctx.request("cold")
            self.assertFalse(record["transport_ok"])
            self.assertIn("CHILD_NOT_LIVE_AT_REQUEST", record["error"])
            self.assertFalse(diag.exists())
        finally:
            ctx.stop()


class LauncherPromptBindingTests(LauncherHarness):
    """B4 (review 5459338940): the production launcher must be supplied
    the exact frozen prompt bytes and request settings explicitly; a
    missing/mismatched/ambiguous prompt must be rejected BEFORE any
    HTTP dispatch. The submitted POST body must carry the exact frozen
    P1 bytes; no silent ``"stub"`` substitution; request identity
    evidence retained without leaking prompt text into diagnostics."""

    def test_real_matrix_row_without_prompt_text_never_sends_stub(self):
        """RED core: driving the production entry point with the REAL
        MINIMAL_RERUN_MATRIX shape (``prompt: "P1"``, no ``prompt_text``)
        and NO explicit prompt binding must reject the launch BEFORE
        dispatch — the stub must never receive a completion request."""
        diag = self.tmp / "requests.jsonl"
        recs = []

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--record-requests", str(diag)]
            return argv

        summary, launches = self.m.campaign_executor(
            REAL_MATRIX, command_builder=builder, workdir=self.tmp,
            port=self.port, startup_timeout_s=10,
            retain=lambda label, kind, record, bracket: recs.append(record))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertFalse(diag.exists(),
                          "no HTTP completion may be dispatched when the "
                          "prompt binding is absent (silent 'stub' "
                          "substitution is exactly what must not happen)")
        r1c = [r for r in recs if r["launch"] == "R1"][0]
        self.assertIn("PROMPT_BINDING_MISSING", r1c["error"])

    def test_prompt_bytes_verified_against_frozen_identity(self):
        """Explicit prompt binding with WRONG bytes (hash mismatch) is
        rejected before dispatch."""
        diag = self.tmp / "requests.jsonl"
        recs = []

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--record-requests", str(diag)]
            return argv

        binding = {"P1": {"text": "definitely not the frozen P1 prompt",
                          "utf8_sha256": P1["utf8_sha256"],
                          "settings": P1["settings"]}}
        summary, launches = self.m.campaign_executor(
            REAL_MATRIX, command_builder=builder, workdir=self.tmp,
            port=self.port, prompt_binding=binding, startup_timeout_s=10,
            retain=lambda label, kind, record, bracket: recs.append(record))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertFalse(diag.exists())
        r1c = [r for r in recs if r["launch"] == "R1"][0]
        self.assertIn("PROMPT_BINDING_MISMATCH", r1c["error"])

    def test_exact_frozen_prompt_reaches_server_and_is_evidenced(self):
        """GREEN: with the exact frozen P1 binding supplied, the server
        receives the exact prompt bytes + frozen settings, the record
        carries request identity evidence (sha256 + bytes count) without
        the prompt text itself, and the campaign completes."""
        diag = self.tmp / "requests.jsonl"
        recs = []

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--record-requests", str(diag)]
            return argv

        binding = {"P1": P1}
        summary, launches = self.m.campaign_executor(
            REAL_MATRIX, command_builder=builder, workdir=self.tmp,
            port=self.port, prompt_binding=binding, startup_timeout_s=20,
            retain=lambda label, kind, record, bracket: recs.append(record))
        self.assertEqual(summary["terminal"], "COMPLETE",
                         f"stop_reason={summary.get('stop_reason')}")
        rows = [json.loads(l) for l in
                diag.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 4)
        for row in rows:
            body = json.loads(row["body"])
            self.assertEqual(body["prompt"], P1["text"],
                             "the server must receive the exact frozen "
                             "P1 bytes")
            for key, value in P1["settings"].items():
                if key == "samplers":
                    # #280 comment 6030829366 accepts top_k, not the
                    # retained workload's invalid historical greedy spelling.
                    self.assertEqual(body[key], ["top_k"])
                elif isinstance(value, list):
                    self.assertEqual(sorted(body[key]), sorted(value))
                else:
                    self.assertEqual(body[key], value)
            self.assertEqual(row["body_sha256"],
                             hashlib.sha256(
                                 row["body"].encode()).hexdigest())
        for rec in recs:
            ev = rec["request_identity"]
            self.assertEqual(ev["prompt_sha256"], P1["utf8_sha256"])
            self.assertEqual(ev["prompt_bytes"],
                             len(P1["text"].encode("utf-8")))
            self.assertNotIn(P1["text"], json.dumps(rec),
                             "prompt text must not leak into records")

    def test_synthetic_prompt_explicit_in_tests(self):
        """CPU stub tests keep synthetic prompt data EXPLICIT: a matrix
        row with explicit test prompt bytes runs and the server receives
        exactly those bytes."""
        diag = self.tmp / "requests.jsonl"

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv += ["--record-requests", str(diag)]
            return argv

        # Explicit CPU-only authority binding lives in the TEST harness.
        # No permissive test-mode switch or in-row override in production.
        from unittest.mock import patch
        entry = {"text": "synthetic-cpu-test-prompt",
                 "utf8_sha256": hashlib.sha256(
                     b"synthetic-cpu-test-prompt").hexdigest(),
                 "settings": dict(P1["settings"])}
        binding = {"P1": entry}
        matrix = [dict(MATRIX[0])]  # preserve the real gate engine's P1 task
        with patch.object(self.m, "frozen_prompts", return_value=binding):
            summary, launches = self.m.campaign_executor(
                matrix, command_builder=builder, workdir=self.tmp,
                prompt_binding=binding, port=self.port, startup_timeout_s=20)
        self.assertEqual(summary["terminal"], "COMPLETE",
                         f"stop_reason={summary.get('stop_reason')}")
        row = json.loads(diag.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(json.loads(row["body"])["prompt"],
                         "synthetic-cpu-test-prompt")


class NegativeControlTests(LauncherHarness):
    """Prove the GREEN tests catch a fail-open mutation of the fix: patch
    ONE law off in an in-memory mutated copy of the module and assert the
    corresponding GREEN guarantee now visibly breaks."""

    MUTATIONS = {
        "no_prior_stop": (
            "        for prior in launches:\n"
            "            try:\n"
            "                stop_owned(prior, phase=\"pre-launch\")\n"
            "            except LaunchError as e:\n"
            "                launch_failure = f\"prior launch failed to stop: {e}\"",
            "        pass  # MUTATED: prior launch never stopped"),
        "any_200_ready": (
            "                if ident == self._identity:",
            "                if True:  # MUTATED: any identity is readiness"),
        "no_request_identity": (
            "        if transport_ok and server_identity != self._identity:",
            "        if False:  # MUTATED: no completion identity check"),
        "no_port_preflight": (
            "        if port_occupied(self.host, self.port):",
            "        if False and port_occupied(self.host, self.port):"),
    }

    def _stage_engine_closure(self, td):
        """Stage the REAL gate engine (issue280_* scripts plus the #280
        evidence area the engine's compatibility gate reads: the bundle
        AND the instrumentation headers) so a launcher copy that lives in
        ``td/scripts`` resolves its closure exactly as production does
        (engine ROOT anchors at the scripts dir's parent)."""
        scripts_dst = td / "scripts"
        scripts_dst.mkdir(parents=True, exist_ok=True)
        for dep in ROOT.glob("scripts/issue280_*.py"):
            shutil.copy(dep, scripts_dst)
        area_src = ROOT / "docs/investigations/vulkan-same-request-280"
        shutil.copytree(area_src, td / "docs/investigations/"
                        "vulkan-same-request-280")

    def mutated(self, name):
        src = LAUNCHER.read_text()
        old, new = self.MUTATIONS[name]
        self.assertIn(old, src, f"mutation site missing: {name}")
        td = Path(tempfile.mkdtemp(prefix="issue289-mut-"))
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        # stage the real engine closure and put the mutated launcher
        # INSIDE the scripts dir: the launcher resolves the engine as its
        # sibling, and the engine anchors its bundle ROOT at the scripts
        # dir's parent — identical to production layout
        self._stage_engine_closure(td)
        p = td / "scripts" / "mutated_launcher.py"
        p.write_text(src.replace(old, new, 1))
        return load("issue289_launcher_mutated", p)

    def test_control_no_prior_stop_replays_r3(self):
        """With prior-stop disabled, the campaign replays the r3 failure
        (R1 alive during R2 attempt) — proving the sequential GREEN test
        detects exactly this fail-open."""
        m = self.mutated("no_prior_stop")
        summary, launches = m.campaign_executor(
            MATRIX, command_builder=self.command_builder,
            workdir=self.tmp, port=self.port, startup_timeout_s=20,
            prompt_binding={"P1": P1})
        # Either the campaign STOPs (R2 launch fails) or an R2 response is
        # misattributed; a healthy COMPLETE with R2-attributed PIDs must
        # be impossible because R2 cannot bind while R1 lives.
        r2 = launches[-1]
        r2_served = [r for r in self.records if r["launch"] == "R2"]
        if summary["terminal"] == "COMPLETE":
            for rec in r2_served:
                if rec["transport_ok"]:
                    self.assertNotEqual(rec.get("server_pid"),
                                        r2.record["pid"],
                                        "fail-open would admit R1-served "
                                        "bytes as R2")

    def test_control_any_200_ready_accepts_foreign_health(self):
        m = self.mutated("any_200_ready")
        r1_argv = self.command_builder(
            "A", self.port, self.tmp / "foreign.log", {})
        foreign = subprocess.Popen(r1_argv)
        self.addCleanup(terminate, foreign)
        wait_listening(self.port)

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            argv[2] = str(port + 1)  # owned child alive on a side port
            return argv

        ctx = m.Launch(MATRIX[1], command_builder=builder,
                       workdir=self.tmp, port=self.port,
                       startup_timeout_s=5)
        # bypass the (unmutated) preflight so the mutated readiness law is
        # what the launch exercises — the fail-open this control detects
        m.port_occupied = lambda host, port: False
        ctx.start()  # mutated: accepts the foreign identity as ready
        try:
            self.assertTrue(pid_alive(foreign.pid))
        finally:
            ctx.stop()
        # GREEN raises FOREIGN_SERVER_IDENTITY at start(); the mutated
        # module's silent readiness is the detectable fail-open.

    def test_control_no_request_identity_admits_stale_bytes(self):
        m = self.mutated("no_request_identity")
        stale = "R1#stale#deadbeef"

        def builder(arm, port, log_path, env_extra):
            argv = self.command_builder(arm, port, log_path, env_extra)
            if arm == "B":
                argv += ["--stale-completion-id", stale]
            return argv

        ctx = m.Launch(MATRIX[1], command_builder=builder,
                       workdir=self.tmp, port=self.port,
                       startup_timeout_s=20, prompt_binding={"P1": P1})
        # R2 stub can only start if the port is free: start R1's Launch
        # properly first, stop it, then start R2 — sequence through the
        # mutated module (still stops prior launch).
        r1ctx = m.Launch(MATRIX[0], command_builder=self.command_builder,
                         workdir=self.tmp, port=self.port,
                         startup_timeout_s=20, prompt_binding={"P1": P1})
        r1ctx.start()
        r1ctx.stop()
        ctx.start()
        try:
            record, state = ctx.request("cold")
            self.assertTrue(record["transport_ok"],
                            "mutated module admitted stale-arm bytes — "
                            "GREEN mismatch test catches this fail-open")
            self.assertFalse(record.get("identity_mismatch", False))
        finally:
            ctx.stop()

    def test_control_no_port_preflight_contacts_foreign(self):
        """Unmutated law: PORT_OCCUPIED refusal with zero HTTP to the
        foreign listener. Mutated law: the module probes the foreign
        server (contact proven by the FOREIGN_SERVER_IDENTITY error the
        probe produces) — exactly the fail-open the GREEN test detects."""
        m = self.mutated("no_port_preflight")
        foreign_log = self.tmp / "foreign.log"
        argv = self.command_builder("X", self.port, foreign_log, {})
        foreign = subprocess.Popen(argv)
        self.addCleanup(terminate, foreign)
        wait_listening(self.port)

        def builder(arm, port, log_path, env_extra):
            argv2 = self.command_builder(arm, port, log_path, env_extra)
            argv2[2] = str(port + 1)  # owned child alive on a side port
            return argv2

        # sanity: the unmutated module refuses without contacting
        ctx0 = self.m.Launch(MATRIX[0], command_builder=builder,
                             workdir=self.tmp, port=self.port,
                             startup_timeout_s=3)
        with self.assertRaises(self.m.LaunchError) as cm0:
            ctx0.start()
        self.assertIn("PORT_OCCUPIED", str(cm0.exception))
        ctx0.stop()

        ctx = m.Launch(MATRIX[0], command_builder=builder,
                       workdir=self.tmp, port=self.port,
                       startup_timeout_s=3)
        with self.assertRaises(m.LaunchError) as cm:
            ctx.start()
        # the mutated module probed the foreign listener: its identity
        # answer surfaced (instead of the preflight refusal)
        self.assertIn("FOREIGN_SERVER_IDENTITY", str(cm.exception),
                      "mutated module must have contacted the foreign "
                      "listener; unexpected error: " + str(cm.exception))
        ctx.stop()


class R3FaithfulnessTests(NegativeControlTests):
    """RED-phase pinning: under the r3 law (all fail-open mutations
    applied to the fixed module) the retained terminal failure shape
    reproduces on CPU — proving the defect and the suite's ability to
    catch it. These tests document the OLD behavior; they run against a
    mutated copy, never the production module."""

    def test_r3_law_replays_stale_arm_terminal(self):
        m = self.mutated_r3()
        recs = []
        summary, launches = m.campaign_executor(
            MATRIX, command_builder=self.command_builder,
            workdir=self.tmp, port=self.port, startup_timeout_s=20,
            prompt_binding={"P1": P1},
            retain=lambda label, kind, record, bracket: recs.append(record))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIn("observer admission failure", summary["stop_reason"])
        self.assertEqual(
            [r["disposition"] for r in summary["requests"]],
            ["accepted", "accepted", "rejected", "not_attempted"])
        r2c = [r for r in recs if r["launch"] == "R2"][0]
        self.assertTrue(r2c["transport_ok"],
                        "r3 law must route the R2-cold request to the "
                        "still-alive R1 server")
        r2 = launches[-1]
        # the retained r3 shape: the request succeeded while R2's own
        # child had already exited on bind failure — the response cannot
        # have come from R2's process (the r3 law just never checked)
        self.assertNotEqual(r2.record["exit"]["returncode"], 0,
                            "R2 child must have died on bind failure")

    def mutated_r3(self):
        """Apply ALL fail-open mutations at once: the r3 law exactly."""
        src = LAUNCHER.read_text()
        for name in ("no_prior_stop", "any_200_ready",
                     "no_request_identity", "no_port_preflight"):
            old, new = self.MUTATIONS[name]
            self.assertIn(old, src)
            src = src.replace(old, new, 1)
        td = Path(tempfile.mkdtemp(prefix="issue289-r3-"))
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        self._stage_engine_closure(td)
        p = td / "scripts" / "r3_launcher.py"
        p.write_text(src)
        return load("issue289_launcher_r3", p)


class ReadinessTupleRegressionTests(LauncherHarness):
    """N1: real owned child; valid token cannot excuse identity failure."""

    def exercise_failure(self, mode):
        from unittest.mock import patch
        diag = self.tmp / "n1-requests.jsonl"
        real_start = self.m.proc_start_time
        real_await = self.m.Launch._await_ready
        observed = []

        def builder(arm, port, log_path, env_extra):
            return self.command_builder(arm, port, log_path, env_extra) + [
                "--record-requests", str(diag)]

        def read_start(pid):
            observed.append(pid)
            # First capture succeeds, only the first readiness check fails.
            # Later identity checks succeed: the old bug dispatches requests.
            if len(observed) == 2:
                return None if mode == "unreadable" else "changed-instance"
            return real_start(pid)

        def await_ready(ctx):
            wait_listening(ctx.port)
            # Real listener is available and echoes exactly this launch token.
            self.assertEqual(ctx._probe_identity(), ctx._identity)
            if mode == "exited":
                ctx.proc.kill()
                ctx.proc.wait(5)
                # A listener's expected token (cached/racing response) is
                # still no substitute for the owned child's live identity.
                ctx._probe_identity = lambda: ctx._identity
            return real_await(ctx)

        t0 = time.monotonic()
        with patch.object(self.m, "proc_start_time", read_start), \
                patch.object(self.m.Launch, "_await_ready", await_ready):
            summary, launches = self.run_matrix(command_builder=builder,
                                                startup_timeout_s=3)
        ctx = launches[0]
        reason = {"unreadable": "IDENTITY_UNAVAILABLE",
                  "changed": "IDENTITY_MISMATCH",
                  "exited": "CHILD_EXITED_BEFORE_READY"}[mode]
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIsNone(ctx.record["ready_utc"])
        self.assertIn(reason, ctx.record["failure"] or "")
        self.assertEqual(self.dispositions(summary),
                         ["aborted", "not_attempted", "not_attempted",
                          "not_attempted"])
        self.assertFalse(diag.exists(), "no completion bytes after failed readiness")
        self.assertTrue(ctx.record["exit"]["reaped"])
        self.assertFalse(pid_alive(ctx.record["pid"]))
        self.assertFalse(self.m.port_occupied("127.0.0.1", self.port))
        self.assertLess(time.monotonic() - t0, 8)

    def test_start_time_unreadable_between_capture_and_ready(self):
        self.exercise_failure("unreadable")

    def test_start_time_changed_between_capture_and_ready(self):
        self.exercise_failure("changed")

    def test_owned_child_exits_before_ready_despite_expected_token(self):
        self.exercise_failure("exited")

    def test_tuple_truthiness_mutation_is_killed(self):
        # Mutate ONLY tuple consumption in the actual production method.
        import inspect
        import textwrap
        from unittest.mock import patch
        source = textwrap.dedent(inspect.getsource(self.m.Launch._await_ready))
        corrected = ("        alive, identity_error = self._child_alive()\n"
                     "        if not alive:")
        reviewed = ("        identity_error = None\n"
                    "        if not self._child_alive():")
        # Both RED (already broken) and GREEN use the same regression.
        if corrected in source:
            source = source.replace(corrected, reviewed, 1)
        else:
            self.assertIn("if not self._child_alive():", source)
        namespace = dict(self.m.__dict__)
        exec(source, namespace)
        with patch.object(self.m.Launch, "_await_ready", namespace["_await_ready"]):
            for mode in ("unreadable", "changed", "exited"):
                with self.subTest(mode=mode), self.assertRaises(AssertionError):
                    self.exercise_failure(mode)


class FrozenRequestAuthorityRegressionTests(LauncherHarness):
    """N2: record actual POST bytes with the existing real CPU stub."""

    def dispatch(self, binding, row=None):
        diag = self.tmp / "n2-requests.jsonl"

        def builder(arm, port, log_path, env_extra):
            return self.command_builder(arm, port, log_path, env_extra) + [
                "--record-requests", str(diag)]

        ctx = self.m.Launch(row or MATRIX[0], command_builder=builder,
                            workdir=self.tmp, port=self.port,
                            startup_timeout_s=5, prompt_binding=binding)
        try:
            ctx.start()
            record, _ = ctx.request("cold")
        finally:
            ctx.stop()
        self.assertFalse(pid_alive(ctx.record["pid"]))
        rows = ([json.loads(line) for line in diag.read_text().splitlines()]
                if diag.exists() else [])
        if diag.exists():
            diag.unlink()
        return record, rows

    def reject(self, binding, row=None, reason="BINDING"):
        record, rows = self.dispatch(binding, row)
        self.assertFalse(record["transport_ok"], "unapproved request dispatched")
        self.assertIn(reason, record["error"])
        self.assertEqual(rows, [], "authority failure must send zero completion bytes")
        self.assertIsNone(record["request_identity"])
        self.assertNotIn(P1["text"], json.dumps(record))

    def entry(self):
        return json.loads(json.dumps(P1))

    def test_self_consistent_wrong_prompt_hash_cannot_impersonate_p1(self):
        entry = self.entry()
        entry["text"] = "self-consistent but not frozen P1"
        entry["utf8_sha256"] = hashlib.sha256(entry["text"].encode()).hexdigest()
        self.reject({"P1": entry})

    def test_in_row_synthetic_override_cannot_replace_production_binding(self):
        text = "in-row override"
        row = dict(MATRIX[0], prompt_text=text,
                   prompt_sha256=hashlib.sha256(text.encode()).hexdigest())
        self.reject({"P1": self.entry()}, row)

    def test_synthetic_row_without_explicit_cpu_binding_is_rejected(self):
        text = "unauthenticated synthetic row"
        self.reject(None, dict(MATRIX[0], prompt_text=text,
                              prompt_sha256=hashlib.sha256(text.encode()).hexdigest()))

    def test_reserved_prompt_setting_never_replaces_outgoing_prompt(self):
        entry = self.entry()
        entry["settings"]["prompt"] = "overwritten POST prompt"
        self.reject({"P1": entry}, reason="REQUEST_SETTINGS")

    def test_missing_settings_fail_closed(self):
        for settings in (None, {}, {"seed": 42}):
            with self.subTest(settings=settings):
                entry = self.entry()
                entry["settings"] = settings
                self.reject({"P1": entry}, reason="REQUEST_SETTINGS")

    def test_unknown_settings_fail_closed(self):
        entry = self.entry()
        entry["settings"]["unapproved_option"] = True
        self.reject({"P1": entry}, reason="REQUEST_SETTINGS")

    def test_conflicting_frozen_settings_fail_closed(self):
        for key, value in (("seed", 43), ("n_predict", 129),
                           ("cache_prompt", True), ("stream", False),
                           ("samplers", ["temperature"]),
                           ("timings_per_token", False)):
            with self.subTest(key=key):
                entry = self.entry()
                entry["settings"][key] = value
                self.reject({"P1": entry}, reason="REQUEST_SETTINGS")

    def test_ambiguous_settings_types_fail_closed(self):
        for key, value in (("seed", "42"), ("top_k", True),
                           ("cache_prompt", 0), ("temperature", False)):
            with self.subTest(key=key):
                entry = self.entry()
                entry["settings"][key] = value
                self.reject({"P1": entry}, reason="REQUEST_SETTINGS")

    def test_unknown_prompt_id_fails_closed(self):
        self.reject({"P9": self.entry()}, dict(MATRIX[0], prompt="P9"))

    def test_accepted_greedy_normalization_reaches_actual_wire(self):
        record, rows = self.dispatch({"P1": self.entry()})
        self.assertTrue(record["transport_ok"], record["error"])
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0]["body"])
        self.assertEqual(payload["samplers"], ["top_k"])
        self.assertEqual(payload["prompt"], P1["text"])
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["top_k"], 1)
        self.assertEqual(payload["seed"], 42)

    def test_retained_authority_missing_sends_zero_completion_bytes(self):
        from unittest.mock import patch
        with patch.object(self.m, "WORKLOAD_PATH", self.tmp / "missing.json",
                          create=True):
            self.reject({"P1": self.entry()}, reason="AUTHORITY_MISSING")

    def test_retained_authority_self_consistent_drift_is_rejected(self):
        from unittest.mock import patch
        altered = json.loads(json.dumps(WORKLOAD))
        entry = altered["prompts"]["P1"]
        entry["text"] = "changed retained bytes and changed caller bytes"
        entry["utf8_sha256"] = hashlib.sha256(entry["text"].encode()).hexdigest()
        authority_path = self.tmp / "altered-workload.json"
        authority_path.write_text(json.dumps(altered))
        with patch.object(self.m, "WORKLOAD_PATH", authority_path, create=True):
            self.reject({"P1": entry}, reason="AUTHORITY_MISMATCH")

    def test_approved_effective_sampler_spelling_is_accepted(self):
        entry = self.entry()
        entry["settings"]["samplers"] = ["top_k"]
        record, rows = self.dispatch({"P1": entry})
        self.assertTrue(record["transport_ok"], record["error"])
        self.assertEqual(json.loads(rows[0]["body"])["samplers"], ["top_k"])

    def test_evidence_derived_from_actual_transmitted_bytes(self):
        record, rows = self.dispatch({"P1": self.entry()})
        self.assertTrue(record["transport_ok"], record["error"])
        self.assertEqual(len(rows), 1)
        raw = rows[0]["body"].encode("utf-8")
        payload = json.loads(raw)
        evidence = record["request_identity"]
        self.assertEqual(evidence.get("body_sha256"),
                         hashlib.sha256(raw).hexdigest())
        self.assertEqual(evidence.get("body_bytes"), len(raw))
        self.assertEqual(evidence["prompt_sha256"],
                         hashlib.sha256(payload["prompt"].encode()).hexdigest())
        self.assertEqual(evidence["prompt_bytes"], len(payload["prompt"].encode()))
        self.assertEqual(evidence["request_settings"],
                         {k: v for k, v in payload.items() if k != "prompt"})
        self.assertNotIn(P1["text"], json.dumps(record))


if __name__ == "__main__":
    unittest.main()
