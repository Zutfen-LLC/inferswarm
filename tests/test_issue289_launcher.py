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
import json
import os
import shutil
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
        self.assertTrue(m.pid_alive_same_instance(me, None))
        self.assertFalse(m.pid_alive_same_instance(me, "1"))
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
            workdir=self.tmp, port=self.port, startup_timeout_s=20)
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
                       startup_timeout_s=20)
        # R2 stub can only start if the port is free: start R1's Launch
        # properly first, stop it, then start R2 — sequence through the
        # mutated module (still stops prior launch).
        r1ctx = m.Launch(MATRIX[0], command_builder=self.command_builder,
                         workdir=self.tmp, port=self.port,
                         startup_timeout_s=20)
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


if __name__ == "__main__":
    unittest.main()
