"""Round-7 RED/GREEN regressions: producer/receipt identity-shape defect
(exposed physically by round-6 A3 unit 001, issue #254).

Physical defect class (third A3 attempt, dispatched head d0df403): the real
production identity path was internally inconsistent. The real default
identity observer returns the accepted RAW #248 observation
(``{schema, arm, raw}``), which passes ``_identity_problems`` (that law
flattens internally before comparing HOST_FACTS) — but ``execute_unit``
retained the raw-shaped dict verbatim, ``run_unit`` passed it verbatim into
``P252.build_unit_receipt``, and ``validate_unit_receipt`` compares the
HOST_FACTS keys DIRECTLY against the raw shape. Every genuine production
observation therefore reached receipt validation in a shape it can never
accept, and the first physically real unit died AFTER successful inference
and collection with ``ValueError: receipt identity_pre identity missing or
drifted``. Offline suites missed it because every test seam injected an
already-flat ``dict(C252.HOST_FACTS)`` identity — encoding the validator's
own shape and hiding the divergence.

Round-7 correction (this module's GREEN law): ONE canonical producer-side
normalization boundary — ``normalize_retained_identity`` — converts the
authenticated #248 raw observation into the receipt-compatible frozen flat
identity + retained raw custody (exactly ``_flat_identity``'s existing
representation: every HOST_FACTS key equal, plus the authenticated raw
block), and that ONE object is bound identically into the receipt
(identity_pre/identity_post), the producer attestation, and the retained
identity-pre.json / identity-post.json artifacts.

The census-shaped raw block below is provenance-bound to the accepted #241
replacement census (same authority as tests/test_issue248_diagnostic.CENSUS_RAW_B).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from tests.test_issue254_producer import (
    ProducerFixtureMixin, MECH_A3_LOG, NL)
from tests.test_issue248_diagnostic import CENSUS_RAW_B
import issue248_identity as I248
import issue252_arms as A
import issue252_constants as C252
import issue252_mechanism as M
import issue252_physical as P252
import issue252_terminal as T252
import issue254_producer as PR
import issue250_diagnostic as D


def real_shaped_observation(**raw_overrides) -> dict:
    """A #248-shaped identity observation matching the EXACT return
    contract of ``_default_identity_observer``:
    ``{"schema": I248.IDENTITY_SCHEMA, "arm": "B", "raw": ...}`` built
    from the accepted census-provenance raw block (never an already-flat
    substitute)."""
    raw = json.loads(json.dumps(CENSUS_RAW_B))
    raw.update(raw_overrides)
    return {"schema": I248.IDENTITY_SCHEMA, "arm": "B", "raw": raw}


class NormalizationBoundaryTests(ProducerFixtureMixin,
                                 unittest.TestCase):
    """RED-1/RED-2/RED-3 at d0df4033; the GREEN canonical-boundary law."""

    def setUp(self):
        self.fixture()

    def test_red1_real_shaped_identity_passes_producer_but_fails_receipt(self):
        # RED-1: the genuine #248 raw observation passes the producer's
        # identity law, then FAILS receipt construction with exactly the
        # physical round-6 error.
        obs = real_shaped_observation()
        self.assertEqual(I248.identity_problems("B", obs), [])
        self.assertEqual(PR._identity_problems(obs), [])
        with self.assertRaises(ValueError) as ctx:
            P252.build_unit_receipt(
                authority=self.live_capture("A3"), unit_index=1,
                binary=Path("/nonexistent/llama-server"),
                model_member=PR.MODEL_DIR / next(iter(C252.MODEL_MEMBERS)),
                observer_dir=self.evidence, identity_pre=obs,
                identity_post=obs,
                placement={"output_projection": "Vulkan",
                           "embedding": "CPU", "ngl": 1,
                           "gpu_uuid": C252.HOST_FACTS["gpu_uuid"]},
                raw_response=json.dumps(
                    {"tokens": [1] * D.DECISIONS}).encode(),
                rows=[bytes(D.ROW_BYTES) for _ in range(D.DECISIONS)],
                observer_meta=b"m", server_log=MECH_A3_LOG.encode(),
                server_pid=4242,
                model_stat_witness={m: {"bytes": 1, "device": 1,
                                        "inode": 1, "mtime_ns": 1,
                                        "ctime_ns": 1}
                                    for m in C252.MODEL_MEMBERS},
                request=D.REQUEST_CONTRACT)
        self.assertIn("receipt identity_pre identity missing or drifted",
                      str(ctx.exception))

    def test_red2_already_flat_fixture_still_passes(self):
        # RED-2: the already-flat offline fixture passes receipt
        # construction — why the defect escaped every prior suite.
        flat = dict(C252.HOST_FACTS)
        rec = P252.build_unit_receipt(
            authority=self.live_capture("A3"), unit_index=1,
            binary=Path("/nonexistent/llama-server"),
            model_member=PR.MODEL_DIR / next(iter(C252.MODEL_MEMBERS)),
            observer_dir=self.evidence, identity_pre=flat,
            identity_post=flat,
            placement={"output_projection": "Vulkan",
                       "embedding": "CPU", "ngl": 1,
                       "gpu_uuid": C252.HOST_FACTS["gpu_uuid"]},
            raw_response=json.dumps(
                {"tokens": [1] * D.DECISIONS}).encode(),
            rows=[bytes(D.ROW_BYTES) for _ in range(D.DECISIONS)],
            observer_meta=b"m", server_log=MECH_A3_LOG.encode(),
            server_pid=4242,
            model_stat_witness={m: {"bytes": 1, "device": 1, "inode": 1,
                                    "mtime_ns": 1, "ctime_ns": 1}
                                for m in C252.MODEL_MEMBERS},
            request=D.REQUEST_CONTRACT)
        P252.validate_unit_receipt(rec)  # passes: the seam-encoded shape

    def test_normalize_is_mechanically_derived_from_raw(self):
        # RED-3/GREEN: the normalization is derived mechanically through
        # the accepted #248 derivation path (no second parser), equals
        # HOST_FACTS on every frozen key, and retains the raw block.
        obs = real_shaped_observation()
        normalized = PR.normalize_retained_identity(obs)
        for key, value in C252.HOST_FACTS.items():
            self.assertEqual(normalized[key], value)
        self.assertEqual(normalized["raw"], obs["raw"])
        # derivation provenance: the flat fields are exactly the existing
        # _flat_identity output (ONE derivation path, not a second parser)
        self.assertEqual(
            {k: v for k, v in normalized.items() if k != "raw"},
            {k: v for k, v in PR._flat_identity(obs).items()
             if k != "raw"})
        # normalization is idempotent: an already-normalized identity
        # passes through unchanged (same canonical representation).
        self.assertEqual(PR.normalize_retained_identity(normalized),
                         normalized)
        # an already-flat identity still requires EVERY HOST_FACTS field
        partial = {k: v for k, v in dict(C252.HOST_FACTS).items()
                   if k != "driver"}
        with self.assertRaises(PR.ProducerError):
            PR.normalize_retained_identity(partial)
        # caller-supplied "raw" material cannot override derived values
        forged = {**PR.normalize_retained_identity(obs),
                  "raw": dict(obs["raw"], host="attacker-host")}
        with self.assertRaises(PR.ProducerError):
            PR.normalize_retained_identity(forged)
        # the schema-shaped FAKE (correct schema token, raw that cannot
        # pass the accepted #248 validation) blocks
        fake = {"schema": I248.IDENTITY_SCHEMA, "arm": "B",
                "raw": json.loads(json.dumps(CENSUS_RAW_B))}
        fake["raw"]["nvidia-smi"] = "some other gpu"
        with self.assertRaises(PR.ProducerError):
            PR.normalize_retained_identity(fake)
        # malformed raw observation blocks
        with self.assertRaises(PR.ProducerError):
            PR.normalize_retained_identity(
                {"schema": I248.IDENTITY_SCHEMA, "arm": "B",
                 "raw": {"host": "inferswarm01"}})
        with self.assertRaises(PR.ProducerError):
            PR.normalize_retained_identity(
                {"schema": "not.a.schema", "arm": "B", "raw": {}})

    def test_altered_raw_identity_fields_block(self):
        # altered GPU UUID in the raw #248 observation blocks
        obs = real_shaped_observation()
        obs["raw"]["nvidia-smi"] = obs["raw"]["nvidia-smi"].replace(
            "GPU-d5c05739", "GPU-deadbeef")
        with self.assertRaises(PR.ProducerError):
            PR.normalize_retained_identity(obs)
        # altered BDF blocks (sysfs address and the nvidia-smi channel
        # must stay cross-bound: a consistent move is still drift)
        obs = real_shaped_observation(bdf="00000000:04:00.0")
        obs["raw"]["nvidia-smi"] = obs["raw"]["nvidia-smi"].replace(
            "00000000:03:00.0", "00000000:04:00.0")
        with self.assertRaises(PR.ProducerError):
            PR.normalize_retained_identity(obs)
        # altered driver blocks
        obs = real_shaped_observation()
        obs["raw"]["nvidia-smi"] = obs["raw"]["nvidia-smi"].replace(
            "610.57.04", "999.99.99")
        with self.assertRaises(PR.ProducerError):
            PR.normalize_retained_identity(obs)
        # altered ICD identity blocks (radeon substituted for the frozen
        # NVIDIA ICD)
        raw = json.loads(json.dumps(CENSUS_RAW_B))
        del raw["icd_inventory"]["nvidia_icd.json"]
        with self.assertRaises(PR.ProducerError):
            PR.normalize_retained_identity(
                {"schema": I248.IDENTITY_SCHEMA, "arm": "B", "raw": raw})
        # altered Vulkan identity blocks (deviceUUID no longer
        # cross-binds to the NVIDIA GPU UUID)
        raw = json.loads(json.dumps(CENSUS_RAW_B))
        raw["vulkaninfo"]["stdout"] = raw["vulkaninfo"]["stdout"].replace(
            "d5c05739-96c1-7e49-89b6-bf54c2121c55",
            "00000000-0000-0000-0000-000000000000")
        with self.assertRaises(PR.ProducerError):
            PR.normalize_retained_identity(
                {"schema": I248.IDENTITY_SCHEMA, "arm": "B", "raw": raw})

    def test_execute_unit_normalizes_at_the_boundary(self):
        # GREEN: execute_unit retains the NORMALIZED representation for
        # identity_pre/identity_post — the raw #248 observation from the
        # production observer never reaches the unit dict raw-shaped.
        obs = real_shaped_observation()
        with mock.patch.object(PR, "_default_identity_observer",
                               lambda: obs):
            unit = self.fake_execute_unit()(
                dispatch={"comment_id": 1, "body_sha256": "0" * 64,
                          "head_sha": "1" * 40},
                arm="A3", unit_index=1, binary=Path("/x"),
                unit_dir=Path("/x"), prompt="p", timeout_s=1)
        for phase in ("identity_pre", "identity_post"):
            normalized = PR.normalize_retained_identity(obs)
            self.assertEqual(unit[phase], normalized)
            for key, value in C252.HOST_FACTS.items():
                self.assertEqual(unit[phase][key], value)
            self.assertEqual(unit[phase]["raw"], obs["raw"])

    def test_identity_pre_post_drift_still_blocks(self):
        # pre/post drift (same raw shape, different values) still blocks:
        # the drifted post observation fails closed at the normalization
        # boundary and at the producer identity law.
        pre = real_shaped_observation()
        post = real_shaped_observation()
        post["raw"]["nvidia-smi"] = post["raw"]["nvidia-smi"].replace(
            "610.57.04", "999.99.99")
        with self.assertRaises(PR.ProducerError):
            PR.normalize_retained_identity(post)
        self.assertTrue(PR._identity_problems(post))
        # and the authentic pre observation is unaffected
        self.assertEqual(PR._identity_problems(pre), [])

    def test_receipt_attestation_retained_json_representations_consistent(self):
        # GREEN: receipt, producer attestation, and retained identity
        # JSONs all carry the SAME canonical normalized object; mutating
        # the identity in either the receipt or the attestation blocks.
        obs = real_shaped_observation()
        normalized = PR.normalize_retained_identity(obs)
        cap = self.live_capture("A3")
        unit_dir = self.write_unit_tree("A3", 1, cap, identity=normalized)
        receipt = json.loads((unit_dir / "unit.json").read_bytes())
        att = json.loads(
            (unit_dir / "producer-attestation.json").read_bytes())
        retained_pre = json.loads(
            (unit_dir / "identity-pre.json").read_bytes())
        retained_post = json.loads(
            (unit_dir / "identity-post.json").read_bytes())
        for doc in (receipt["identity_pre"], receipt["identity_post"],
                    att["identity_pre"], att["identity_post"],
                    retained_pre, retained_post):
            self.assertEqual(doc, normalized)
        # receipt identity mutation blocks
        mutated = json.loads(json.dumps(receipt))
        mutated["identity_pre"] = {
            **normalized, "driver": "999.99.99"}
        with self.assertRaises(ValueError):
            P252.validate_unit_receipt(mutated)
        # attestation identity mutation is a binding failure
        att_bad = json.loads(json.dumps(att))
        att_bad["identity_pre"] = {**normalized, "driver": "999.99.99"}
        (unit_dir / "producer-attestation.json").write_text(
            json.dumps(att_bad, sort_keys=True))
        self.assertFalse(PR.is_producer_attested(
            unit_dir, receipt, receipt["head_sha"]))


class RealShapeEndToEndTests(ProducerFixtureMixin, unittest.TestCase):
    """Required real-shape end-to-end CPU regression through the PRODUCTION
    run_unit orchestration: the internal identity observer returns the
    EXACT raw-shaped #248 contract; execution is test-doubled; run_unit
    reaches receipt construction, publishes atomically, retains the
    canonical representation, validates the producer attestation, and the
    reducer admits the resulting unit without identity-shape failure.

    RED at d0df4033: the same run died at receipt construction with the
    exact physical round-6 error. The regression does NOT inject a
    pre-flattened identity anywhere.
    """

    def setUp(self):
        self.fixture()
        self.arm = "A3"
        self.ns = A.ARMS[self.arm]["namespace"]

    COMPARATOR_SCRIPT = (
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "OUT = os.environ['LLAMA_OBSERVE_OUT']\n"
        f"ROW_BYTES = {D.ROW_BYTES}\n"
        "ENUM = (" + repr(
            "ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | uma: 0 | "
            "fp16: 1 | bf16: 0 | fp4: 0 | warp size: 32 | shared memory: "
            "49152 | int dot: 1 | matrix cores: NV_coopmat2") + ")\n"
        "ASYNC = (" + repr(
            "ggml_vulkan: WARNING: Async execution disabled on certain "
            "Intel devices.") + ")\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def log_message(self, *a):\n"
        "        pass\n"
        "    def do_GET(self):\n"
        "        if self.path == '/health':\n"
        "            self.send_response(200)\n"
        "            self.end_headers()\n"
        "            self.wfile.write(b'ok')\n"
        "        else:\n"
        "            self.send_response(404)\n"
        "            self.end_headers()\n"
        "    def do_POST(self):\n"
        "        n = int(self.headers.get('Content-Length', 0))\n"
        "        self.rfile.read(n)\n"
        "        with open(OUT + '.meta.json', 'w') as f:\n"
        "            f.write(''.join(json.dumps(\n"
        "                {'pos': i, 'pid': os.getpid()}) + chr(10)\n"
        "                for i in range(8)))\n"
        "        for i in range(8):\n"
        "            with open(OUT + '.row%d.f32' % i, 'wb') as f:\n"
        "                f.write(bytes([i]) + bytes(ROW_BYTES - 1))\n"
        "        body = json.dumps({'tokens': [1, 2, 3, 4, 5, 6, 7, 8],\n"
        "                           'content': 'x' * 8,\n"
        "                           'timings': {'prompt_n': 3072}}\n"
        "                          ).encode()\n"
        "        self.send_response(200)\n"
        "        self.send_header('Content-Type', 'application/json')\n"
        "        self.send_header('Content-Length', str(len(body)))\n"
        "        self.end_headers()\n"
        "        self.wfile.write(body)\n"
        "print(ASYNC, flush=True)\n"
        "print(ENUM, flush=True)\n"
        f"HTTPServer(('127.0.0.1', {PR.PORT}), H).serve_forever()\n")

    def test_real_shaped_observer_publishes_and_validates(self):
        # RED at d0df4033: this exact run died at receipt construction
        # with the physical round-6 error (ValueError: receipt
        # identity_pre identity missing or drifted). GREEN: the
        # production normalization boundary converts the authenticated
        # raw #248 observation into the one canonical representation and
        # the unit publishes and validates end to end.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "llama-server"
            binary.write_text(self.COMPARATOR_SCRIPT)
            binary.chmod(0o755)
            witness = {m: {"bytes": 1, "device": 1, "inode": 1,
                           "mtime_ns": 1, "ctime_ns": 1}
                       for m in C252.MODEL_MEMBERS}
            obs = real_shaped_observation()
            expected_argv = P252.launch_geometry(
                "A3", binary,
                PR.MODEL_DIR / next(iter(C252.MODEL_MEMBERS)),
                self.evidence / self.ns /
                ".exec-case-3072-B-a3-001.tmp" / "obs")["argv"]
            with mock.patch.object(PR, "_default_identity_observer",
                                   lambda: obs), \
                    self.patched_orchestration(self.arm,
                                               execute=PR.execute_unit), \
                    mock.patch.object(PR, "verify_comparator",
                                      lambda b: C252.COMPARATOR_SHA256), \
                    mock.patch.object(PR, "observe_model_stats",
                                      lambda md: witness), \
                    mock.patch.object(PR, "_default_health_runner",
                                      lambda: {"rc": 0,
                                               "nvidia_smi_raw": ""}), \
                    mock.patch.object(
                        PR, "_proc_readback",
                        lambda pid: {"argv": list(expected_argv),
                                     "env_raw_sha256": "0" * 64}):
                outcome = PR.run_unit(
                    repo_root=self.repo, evidence_root=self.evidence,
                    arm=self.arm, binary=binary, timeout_s=60)
        unit_dir = Path(outcome["unit_dir"])
        normalized = PR.normalize_retained_identity(obs)
        # receipt validated at publication and retained canonical
        receipt = json.loads((unit_dir / "unit.json").read_bytes())
        P252.validate_unit_receipt(receipt)
        self.assertEqual(receipt["identity_pre"], normalized)
        self.assertEqual(receipt["identity_post"], normalized)
        # retained identity JSONs carry the canonical representation
        for phase in ("identity-pre.json", "identity-post.json"):
            self.assertEqual(
                json.loads((unit_dir / phase).read_bytes()), normalized)
        # producer attestation validates and binds the same identity
        att = json.loads(
            (unit_dir / "producer-attestation.json").read_bytes())
        PR.validate_producer_attestation(att)
        self.assertTrue(PR.is_producer_attested(
            unit_dir, receipt, receipt["head_sha"]))
        # A3 mechanism retained-identity validation stays green with the
        # corrected authentic representation
        status = M.mechanism_status(self.evidence, self.arm, self.ns)
        self.assertTrue(status["capable"])
        # reducer admission of the resulting unit does not fail on
        # identity shape (full A3 population -> terminal path)
        cap = self.live_capture(self.arm)
        e2e_rows = [bytes([n]) + bytes(D.ROW_BYTES - 1)
                    for n in range(D.DECISIONS)]
        for i in range(2, 6):
            self.write_unit_tree(self.arm, i, cap,
                                 identity=normalized, rows=e2e_rows)
        (self.evidence / "authority.json").write_text(json.dumps({
            "repo_root": str(self.repo),
            "dispatch_capture": cap}, sort_keys=True))
        with mock.patch.object(P252, "fetch_dispatch_comment",
                               self.offline_comment_refetch()):
            self.assertEqual(T252.derive_terminal(self.evidence, {}),
                             C252.NOT_VALIDATED_TERMINAL)


if __name__ == "__main__":
    unittest.main()
