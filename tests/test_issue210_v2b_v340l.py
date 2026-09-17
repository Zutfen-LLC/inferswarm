"""Issue #210 V2-B focused negative-control tests (real retained evidence).

Every control mutates ONE aspect of the REAL committed V2-B evidence in
an isolated sandbox copy and asserts the fail-closed contract rejects
exactly that mutation END TO END: the mutation is applied to copied
bytes, the real terminal reducer runs against the sandbox through its
env seam, and the derived terminal must fall off
V2B_V340L_DUAL_DIE_QUALIFICATION_PASS. Controls run on CPU against
committed bytes; no physical execution, and canonical committed
evidence is never mutated in place.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v2a_authority_v3 as authority_v3  # noqa: E402
import v2a_harness as harness  # noqa: E402
import v1a_runner as runner  # noqa: E402

AREA = ROOT / "docs/investigations/vulkan-v2-b-v340l"
ACCT_KEYS = ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
             "unplanned_state_movements")
PASS_TERMINAL = "V2B_V340L_DUAL_DIE_QUALIFICATION_PASS"


def load(path):
    return json.loads((AREA / path).read_text())


def load_authority(die):
    return authority_v3.load_authority_file(
        AREA / f"AUTHORITY-V340L-{die}.json", reference_root=ROOT,
        discovery_root=ROOT, raw_root=ROOT,
        frozen_at="2026-09-17T14:30:00+00:00")


class Sandbox:
    """Isolated copy of everything the terminal reducer reads.

    Copies the V2-B evidence area plus the retained accepted V2-A
    terminal artifact the predecessor predicate binds to, so mutating
    either stays out of the committed tree. The reducer runs as a
    SUBPROCESS with INFERSWARM_ISSUE210_ROOT pointed at the sandbox —
    it never imports against mutated bytes in this process.
    """

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="issue210-sandbox-")
        root = Path(self.tmp)
        (root / "docs/investigations").mkdir(parents=True)
        shutil.copytree(AREA, root / "docs/investigations/vulkan-v2-b-v340l")
        v2a_dir = root / "docs/investigations/vulkan-v2-a"
        v2a_dir.mkdir()
        shutil.copy(ROOT / "docs/investigations/vulkan-v2-a/FINAL-TERMINAL.json", v2a_dir)
        self.root = root

    def path(self, rel: str) -> Path:
        return self.root / rel

    def edit_json(self, rel: str, mutate) -> None:
        path = self.path(rel)
        doc = json.loads(path.read_text())
        mutate(doc)
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")

    def derive(self) -> dict:
        env = dict(os.environ, INFERSWARM_ISSUE210_ROOT=str(self.root))
        script = ROOT / "scripts/issue210_terminal.py"
        # The reducer writes TERMINAL.json inside the sandbox and prints
        # the derivation line; run it as a module-agnostic subprocess.
        proc = subprocess.run(
            [sys.executable, str(script)],
            env=env, capture_output=True, text=True, check=True)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TerminalMutationControls(unittest.TestCase):
    """Mutate copied retained evidence -> run the real reducer -> the
    campaign must be unable to satisfy the dual-die PASS contract."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.close)

    def _assert_pass_baseline(self, outcome: dict):
        # Every mutation control must start from a green synthetic
        # baseline: the unmutated sandbox derives the PASS terminal.
        self.assertEqual(outcome["terminal"], PASS_TERMINAL, outcome)

    def test_baseline_sandbox_derives_pass(self):
        outcome = self.sandbox.derive()
        self._assert_pass_baseline(outcome)

    # -- required control 1: wrong V2-A predecessor identity --

    def test_control_1a_wrong_predecessor_merge_rejects_pass(self):
        self._assert_pass_baseline(self.sandbox.derive())
        for wrong in ("0" * 40,  # forged identity
                      "c26746c719e4f60fc6c5f85482e40483de5aa9ec"):  # superseded/foreign commit
            self.sandbox.edit_json(
                "docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-A.json",
                lambda d: d["predecessors"].__setitem__("v2a_merge", wrong))
            outcome = self.sandbox.derive()
            self.assertNotEqual(outcome["terminal"], PASS_TERMINAL, wrong)
            # restore for the next iteration
            self.sandbox.edit_json(
                "docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-A.json",
                lambda d: d["predecessors"].__setitem__(
                    "v2a_merge", "e38ebe91a0604fb666397ddae675248e9f819f60"))

    def test_control_1b_wrong_predecessor_terminal_rejects_pass(self):
        self._assert_pass_baseline(self.sandbox.derive())
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-B.json",
            lambda d: d["predecessors"].__setitem__(
                "v2a_terminal", "V2A_ATTEMPT01_SUPERSEDED"))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_1c_superseded_retained_terminal_artifact_rejects_pass(self):
        # The retained accepted V2-A terminal artifact no longer carries
        # the accepted terminal (e.g. swapped for a superseded variant)
        # -> the predecessor predicate must fail closed.
        self._assert_pass_baseline(self.sandbox.derive())
        terminal_path = self.sandbox.path(
            "docs/investigations/vulkan-v2-a/FINAL-TERMINAL.json")
        doc = json.loads(terminal_path.read_text())
        doc["terminal"] = "V2A_REUSABLE_DEVICE_QUALIFICATION_HARNESS_FAIL"
        terminal_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    # -- required controls 2-6: Phase-1 topology evidence --

    def test_control_2_missing_root_port_topology_evidence_rejects_pass(self):
        self._assert_pass_baseline(self.sandbox.derive())
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/phase1/pci-topology.json",
            lambda d: d.pop("0000:00:1d.0"))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_2b_missing_upstream_topology_evidence_rejects_pass(self):
        self._assert_pass_baseline(self.sandbox.derive())
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/phase1/pci-topology.json",
            lambda d: d.pop("0000:02:00.0"))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_3_root_port_gen1_rejects_pass(self):
        self._assert_pass_baseline(self.sandbox.derive())
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/phase1/pci-topology.json",
            lambda d: d["0000:00:1d.0"].__setitem__(
                "current_link_speed", "2.5 GT/s PCIe"))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_4_root_port_wrong_width_rejects_pass(self):
        self._assert_pass_baseline(self.sandbox.derive())
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/phase1/pci-topology.json",
            lambda d: d["0000:00:1d.0"].__setitem__("current_link_width", "2"))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_5_upstream_gen1_or_gen2_rejects_pass(self):
        self._assert_pass_baseline(self.sandbox.derive())
        for wrong in ("2.5 GT/s PCIe", "5.0 GT/s PCIe"):
            self.sandbox.edit_json(
                "docs/investigations/vulkan-v2-b-v340l/raw/phase1/pci-topology.json",
                lambda d, w=wrong: d["0000:02:00.0"].__setitem__(
                    "current_link_speed", w))
            outcome = self.sandbox.derive()
            self.assertNotEqual(outcome["terminal"], PASS_TERMINAL, wrong)

    def test_control_6_upstream_wrong_width_rejects_pass(self):
        self._assert_pass_baseline(self.sandbox.derive())
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/phase1/pci-topology.json",
            lambda d: d["0000:02:00.0"].__setitem__("current_link_width", "16"))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_6b_null_topology_fields_rejects_pass(self):
        # Present entries with erased speed/width are not "missing
        # evidence" the terminal can ignore — completeness fails closed.
        self._assert_pass_baseline(self.sandbox.derive())
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/phase1/pci-topology.json",
            lambda d: d["0000:00:1d.0"].__setitem__("current_link_speed", None))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    # -- required controls 7-9: accounting, end to end through the terminal --

    def test_control_12_nonzero_unexplained_persistent_host_mirror(self):
        # Mutate the recorded accounting on the canonical record to a
        # nonzero value; the retained raw stderr still proves zero, so
        # the honest end-to-end path is: nonzero accounting -> die fails
        # -> terminal off PASS. (Re-laundering through the raw parser is
        # covered by control 12b.)
        self._assert_pass_baseline(self.sandbox.derive())
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/v2b-v340l-a-canonical-01/"
            "canonical-execution.json",
            lambda d: d["accounting"].__setitem__(
                "unexplained_persistent_host_mirror_bytes", 1024))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_12b_unexplained_mirror_derived_from_mutated_raw_bytes(self):
        # Mutate the RAW retained stderr so the accepted accounting
        # reducer itself derives a nonzero unexplained host-mirror figure
        # from the bytes (device-resident 243 MiB model claimed host
        # CPU_Mapped only 100 MiB -> 143 MiB unexplained): the recorded
        # zero no longer agrees with raw bytes.
        self._assert_pass_baseline(self.sandbox.derive())
        stderr_path = self.sandbox.path(
            "docs/investigations/vulkan-v2-b-v340l/raw/v2b-v340l-a-canonical-01/stderr.txt")
        text = stderr_path.read_text()
        # First post-ready Host row total is 283 = 243 + 0 + 40; shrink the
        # CPU_Mapped model row so host model exceeds the mapped bytes.
        mutated = text.replace(
            "load_tensors:   CPU_Mapped model buffer size =   243.43 MiB",
            "load_tensors:   CPU_Mapped model buffer size =   100.00 MiB", 1)
        self.assertNotEqual(mutated, text)
        stderr_path.write_text(mutated)
        import v1c_accounting as acc
        parsed = acc.parse_accounting(mutated, selector="Vulkan1")
        self.assertGreater(parsed["unexplained_persistent_host_mirror_bytes"], 0)
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_13_nonzero_source_fetches_after_ready(self):
        self._assert_pass_baseline(self.sandbox.derive())
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/v2b-v340l-a-canonical-01/"
            "canonical-execution.json",
            lambda d: d["accounting"].__setitem__("source_fetches_after_ready", 1))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_13b_source_fetch_derived_from_mutated_raw_bytes(self):
        # Append a post-ready fetch line to the RAW transcript: the
        # accepted reducer counts it -> nonzero -> die fails.
        self._assert_pass_baseline(self.sandbox.derive())
        stderr_path = self.sandbox.path(
            "docs/investigations/vulkan-v2-b-v340l/raw/v2b-v340l-a-canonical-01/stderr.txt")
        text = stderr_path.read_text()
        stderr_path.write_text(text + "0.06.000.000 I load_tensors: remote source fetch for layer 5\n")
        import v1c_accounting as acc
        parsed = acc.parse_accounting(stderr_path.read_text(), selector="Vulkan1")
        self.assertEqual(parsed["source_fetches_after_ready"], 1)
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_13c_nonzero_unplanned_state_movements(self):
        self._assert_pass_baseline(self.sandbox.derive())
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/v2b-v340l-a-canonical-01/"
            "canonical-execution.json",
            lambda d: d["accounting"].__setitem__("unplanned_state_movements", 2))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_13d_movement_derived_from_mutated_raw_bytes(self):
        self._assert_pass_baseline(self.sandbox.derive())
        stderr_path = self.sandbox.path(
            "docs/investigations/vulkan-v2-b-v340l/raw/v2b-v340l-a-canonical-01/stderr.txt")
        text = stderr_path.read_text()
        stderr_path.write_text(text + "0.06.000.000 I ggml-vulkan: copying state for rematerialization\n")
        import v1c_accounting as acc
        parsed = acc.parse_accounting(stderr_path.read_text(), selector="Vulkan1")
        self.assertEqual(parsed["unplanned_state_movements"], 1)
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_12_canonical_stdout_digest_mutation_rejects_pass(self):
        # Flip one byte of a retained raw stdout: the re-hash no longer
        # agrees with the recorded digest -> die fails -> no PASS.
        self._assert_pass_baseline(self.sandbox.derive())
        stdout_path = self.sandbox.path(
            "docs/investigations/vulkan-v2-b-v340l/raw/v2b-v340l-a-canonical-01/stdout.txt")
        data = bytearray(stdout_path.read_bytes())
        data[-1] = data[-1] ^ 0x01
        stdout_path.write_bytes(bytes(data))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_12b_canonical_stderr_digest_mutation_rejects_pass(self):
        self._assert_pass_baseline(self.sandbox.derive())
        stderr_path = self.sandbox.path(
            "docs/investigations/vulkan-v2-b-v340l/raw/v2b-v340l-a-canonical-01/stderr.txt")
        data = bytearray(stderr_path.read_bytes())
        data[-1] = data[-1] ^ 0x01
        stderr_path.write_bytes(bytes(data))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_10_selector_bdf_swap_rejects_pass(self):
        # Swap the selector->BDF mapping in the retained R3 bindings so
        # each authority's selector resolves to the twin die's BDF.
        self._assert_pass_baseline(self.sandbox.derive())

        def swap(doc):
            for x in doc["bindings"]:
                if x["selector"] == "Vulkan1":
                    x["pci_bdf"] = "09:00.0"
                elif x["selector"] == "Vulkan2":
                    x["pci_bdf"] = "06:00.0"
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/DISCOVERY-BINDINGS-R3.json", swap)
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_11_one_die_pass_only_is_never_promoted(self):
        # Die B canonical FAIL in the sandbox -> PARTIAL, never dual-die
        # board PASS (authoritative terminal path, not a helper subset).
        self._assert_pass_baseline(self.sandbox.derive())
        self.sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/v2b-v340l-b-canonical-01/"
            "canonical-execution.json",
            lambda d: d.__setitem__("result", "FAIL"))
        outcome = self.sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)
        self.assertEqual(outcome["terminal"], "V2B_V340L_PARTIAL_DIE_QUALIFICATION")


class TerminalTests(unittest.TestCase):
    """TERMINAL.json derives only from retained bytes; mutations flip it."""

    def test_real_terminal_is_dual_die_pass(self):
        record = json.loads((AREA / "TERMINAL.json").read_text())
        self.assertEqual(record["terminal"], PASS_TERMINAL)
        self.assertTrue(all(record["terminal_derivation"].values()))

    def test_committed_terminal_matches_live_derivation(self):
        # The committed TERMINAL.json is exactly what the reducer
        # derives from the committed bytes (no forged stored terminal).
        import issue210_terminal as term
        self.assertEqual(term.derive_record(), record := json.loads(
            (AREA / "TERMINAL.json").read_text()), record)


class AuthorityNegativeControls(unittest.TestCase):
    """Selector/BDF/stale-authority fail-closed at authority load (2-8)."""

    def setUp(self):
        self.doc_a = json.loads((AREA / "AUTHORITY-V340L-A.json").read_text())

    def _load(self, doc):
        return authority_v3.load_authority(
            doc, reference_root=ROOT, discovery_root=ROOT, raw_root=ROOT,
            frozen_at="2026-09-17T14:30:00+00:00")

    def test_control_3_wrong_selector_for_valid_bdf_fails(self):
        doc = copy.deepcopy(self.doc_a)
        doc["frozen"]["selector"] = "Vulkan2"  # die B's selector, A's BDF
        doc["discovery_binding"]["selector"] = "Vulkan2"
        with self.assertRaises(Exception):
            self._load(doc)

    def test_control_4_wrong_bdf_for_valid_selector_fails(self):
        doc = copy.deepcopy(self.doc_a)
        doc["frozen"]["physical_device_bdf"] = "09:00.0"
        with self.assertRaises(Exception):
            self._load(doc)

    def test_control_5_selector_bdf_swap_between_identical_dies_fails(self):
        doc = copy.deepcopy(self.doc_a)
        # Swap ONLY the BDF to the twin die's endpoint, keeping die A's
        # selector and its retained identity-probe proof: the probe bytes
        # for Vulkan1 mechanically prove 06:00.0, so the swapped pair fails.
        doc["frozen"]["physical_device_bdf"] = "09:00.0"
        doc["discovery_binding"]["pci_bdf"] = "09:00.0"
        with self.assertRaises(Exception):
            self._load(doc)

    def test_control_6_stale_authority_fails(self):
        doc = copy.deepcopy(self.doc_a)
        # Anchor the freeze 100h after the physical inventory measurement:
        # the corrected loader ages the INVENTORY itself (72h limit).
        import datetime
        measured = datetime.datetime.fromisoformat(
            doc["discovery_binding"]["inventory_measured_utc"])
        stale_anchor = (measured + datetime.timedelta(hours=100)).isoformat()
        with self.assertRaises(Exception):
            authority_v3.load_authority(
                doc, reference_root=ROOT, discovery_root=ROOT, raw_root=ROOT,
                frozen_at=stale_anchor)

    def test_control_7_mutated_accepted_evidence_fails(self):
        doc = copy.deepcopy(self.doc_a)
        doc["frozen"]["executable_sha256"] = "0" * 64
        with self.assertRaises(Exception):
            self._load(doc)

    def test_control_2_missing_gen3_x1_topology_evidence(self):
        # Missing required topology evidence must make the campaign
        # UNABLE to satisfy the PASS contract: deleting the root-port
        # entry from the retained Phase-1 probe output (sandboxed) ends
        # with a non-PASS terminal. (The loader-level variant is the
        # TerminalMutationControls battery above.)
        sandbox = Sandbox()
        self.addCleanup(sandbox.close)
        self.assertEqual(sandbox.derive()["terminal"], PASS_TERMINAL)
        sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/phase1/pci-topology.json",
            lambda d: d.pop("0000:00:1d.0"))
        outcome = sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)


class CanonicalNegativeControls(unittest.TestCase):
    """Replay-level controls against the retained canonical transcripts (9-15)."""

    def setUp(self):
        self.stderr_a = (AREA / "raw/v2b-v340l-a-canonical-01/stderr.txt").read_text()
        self.stdout_a = (AREA / "raw/v2b-v340l-a-canonical-01/stdout.txt").read_bytes()
        self.auth = load_authority("A")
        self.reference = (ROOT / "docs/investigations/vulkan-v1-a" /
                          "reference-visible-output.txt").read_bytes()

    def test_control_9_partial_offload_or_cpu_fallback_fails(self):
        bad = self.stderr_a.replace("offloaded 37/37 layers to GPU", "offloaded 12/37 layers to GPU")
        self.assertNotEqual(bad, self.stderr_a)
        with self.assertRaises(Exception):
            harness.adapter.parse_backend_observation(
                stderr=bad, selector="Vulkan1", expected_bdf="06:00.0",
                node_id="node-inferswarm02", compute_unit_id="cu-v340l-die-a",
                memory_resource_id="mr-v340l-die-a-vram", execution_unit_id="unit-q4km-whole-model",
                execution_contract_id="contract-s2-opaque-v1",
                implementation_id="impl-portable-v340l-die-a",
                evidence_id="v2b-v340l-a-canonical-01",
                runtime_identity=self.auth["frozen"]["runtime_identity"])

    def test_control_10_canonical_output_attributed_to_wrong_die_fails(self):
        # die A's transcript parsed with die B's expected BDF fails
        with self.assertRaises(Exception):
            harness.adapter.parse_backend_observation(
                stderr=self.stderr_a, selector="Vulkan1", expected_bdf="09:00.0",
                node_id="node-inferswarm02", compute_unit_id="cu-v340l-die-b",
                memory_resource_id="mr-v340l-die-b-vram", execution_unit_id="unit-q4km-whole-model",
                execution_contract_id="contract-s2-opaque-v1",
                implementation_id="impl-portable-v340l-die-b",
                evidence_id="v2b-v340l-b-canonical-01",
                runtime_identity=self.auth["frozen"]["runtime_identity"])

    def test_control_11_accounting_rows_substituted_between_dies(self):
        # accounting parsed under the WRONG (die B) selector fails or is
        # attributable: parse die A stderr under Vulkan2 -> no selector rows
        with self.assertRaises(Exception):
            accounting = harness.accepted_accounting.parse_accounting(
                self.stderr_a, selector="Vulkan2")
            for key in ACCT_KEYS:
                if accounting[key] != 0:
                    raise ValueError(key)

    def test_control_14_authored_pass_contradicting_raw_evidence(self):
        # tamper the canonical record's accounting to nonzero while the raw
        # transcript proves zero -> the retained record disagrees with raw bytes
        record = load("raw/v2b-v340l-a-canonical-01/canonical-execution.json")
        raw_accounting = harness.accepted_accounting.parse_accounting(
            self.stderr_a, selector="Vulkan1")
        for key in ACCT_KEYS:
            self.assertEqual(record["accounting"][key], raw_accounting[key])
        tampered = copy.deepcopy(record)
        tampered["accounting"]["unexplained_persistent_host_mirror_bytes"] = 5
        self.assertNotEqual(
            tampered["accounting"]["unexplained_persistent_host_mirror_bytes"],
            raw_accounting["unexplained_persistent_host_mirror_bytes"])
        # and the honest terminal path already rejects the tampered record
        # end to end (TerminalMutationControls.test_control_12_...).

    def test_control_15_upstream_link_not_gen3_x1(self):
        # TRUE negative control: mutate the retained topology to a
        # non-Gen3-x1 condition (upstream at Gen1) in the sandbox and
        # prove the authoritative terminal rejects PASS. The good
        # committed bytes asserting Gen3 x1 is pinned by the direct
        # TERMINAL.json derivation test above.
        sandbox = Sandbox()
        self.addCleanup(sandbox.close)
        self.assertEqual(sandbox.derive()["terminal"], PASS_TERMINAL)
        sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/raw/phase1/pci-topology.json",
            lambda d: d["0000:02:00.0"].__setitem__(
                "current_link_speed", "2.5 GT/s PCIe"))
        outcome = sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)

    def test_control_2_wrong_predecessor_identity(self):
        # Mutate predecessors.v2a_merge in a SANDBOX copy of the
        # authority and prove the authoritative terminal path rejects
        # PASS (binding is at the terminal reducer, not just the pins).
        sandbox = Sandbox()
        self.addCleanup(sandbox.close)
        self.assertEqual(sandbox.derive()["terminal"], PASS_TERMINAL)
        sandbox.edit_json(
            "docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-A.json",
            lambda d: d["predecessors"].__setitem__("v2a_merge", "0" * 40))
        outcome = sandbox.derive()
        self.assertNotEqual(outcome["terminal"], PASS_TERMINAL)
        # the accepted source pins still verify byte-exact on the real tree:
        doc = json.loads((AREA / "AUTHORITY-V340L-A.json").read_text())
        import hashlib
        for path, sha in doc["accepted_source_pins"].items():
            actual = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            self.assertEqual(actual, sha)


class CrossDieControls(unittest.TestCase):

    def test_identical_visible_output_across_dies_and_repeats(self):
        import v0c_correctness as v0c
        prompt = load_authority("A")["frozen"]["prompt"].encode()
        reference = (ROOT / "docs/investigations/vulkan-v1-a" /
                     "reference-visible-output.txt").read_bytes()
        vis = {}
        for die in ("a", "b"):
            for suffix in ("", "-r2", "-r3"):
                out = (AREA / f"raw/v2b-v340l-{die}-canonical-01{suffix}/stdout.txt").read_bytes()
                vis[f"{die}{suffix}"] = v0c.reduce(out, prompt, reference)["visible_response_bytes"]
        self.assertEqual(len(set(vis.values())), 1)

    def test_portability_audit_pass_and_data_only(self):
        audit = load("PORTABILITY-AUDIT.json")
        self.assertEqual(audit["result"], "PASS")
        self.assertFalse(audit["subject_specific_code_required"])
        self.assertFalse(audit["foundational_invariant_falsified"])

    def test_no_vendor_or_device_literals_in_harness_sources(self):
        for src in harness.HARNESS_SOURCES:
            text = (ROOT / src).read_text()
            for token in ("6864", "V340", "v340", "MI25", "VEGA10", "vega"):
                self.assertNotIn(token, text, f"{src} contains {token}")


if __name__ == "__main__":
    unittest.main()
