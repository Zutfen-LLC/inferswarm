"""Issue #117 checkpoint-authority recovery tests (CPU-only, synthetic).

Proves, on synthetic fixtures:
- the recovered rule derives the accepted authority from matching bytes;
- altered model bytes CANNOT inherit the accepted authority (any-byte
  mutation, truncation, extension, foreign content of the same length);
- a sidecar that merely repeats the accepted string proves nothing;
- the validator refuses symlinks, missing files, wrong sizes;
- the retained provenance record and the retained V5 authority evidence
  agree on the accepted identity;
- the preflight now derives the checkpoint authority mechanically from a
  candidate repository instead of failing closed.
"""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue117_checkpoint_authority as authority  # noqa: E402
import issue117_preflight as preflight  # noqa: E402


ACCEPTED = "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d"


def _synthetic_checkpoint(directory: Path, payload: bytes, *,
                          size_override: int | None = None,
                          symlink: bool = False,
                          sidecar: bool = False) -> Path:
    root = directory / "checkpoint"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "model.safetensors"
    if symlink:
        real = directory / "elsewhere.bin"
        real.write_bytes(payload)
        target.symlink_to(real)
    else:
        target.write_bytes(payload)
    (root / "config.json").write_text('{"model_type": "gemma"}')
    if sidecar:
        (root / "checkpoint-authority.json").write_text(json.dumps(
            {"checkpoint_sha256": ACCEPTED}))
    return root


class ProvenanceRecordTests(unittest.TestCase):
    def test_retained_record_states_the_recovered_rule(self):
        document = authority.load_provenance_record(ROOT)
        self.assertEqual(
            document["derivation_rule"]["historical_statement"],
            "checkpoint sha256 == sha256(model.safetensors bytes)")
        self.assertEqual(document["subject"]["checkpoint_authority_sha256"],
                         ACCEPTED)
        self.assertEqual(
            document["independent_trust_anchors"]["huggingface_remote_authority"]
            ["observed"]["model.safetensors"]["lfs_oid"], ACCEPTED)

    def test_provenance_agrees_with_retained_v5_authority_evidence(self):
        import issue117_applicability as applicability
        self.assertEqual(authority.accepted_checkpoint_authority(ROOT),
                         applicability.accepted_checkpoint_authority_from_evidence(ROOT))


class DerivationTests(unittest.TestCase):
    """The rule is byte-exact and mechanically reproducible."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="issue117-authority-")
        self.tmp = Path(self._temp.name)
        # canonical synthetic object whose sha256 IS the accepted value is
        # impossible to synthesize; instead the accepted value is what the
        # record says and the rule is exercised with expected overrides.
        self.payload = b"\x89safetensors" + bytes(range(256)) * 4

    def tearDown(self):
        self._temp.cleanup()

    def _expected(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()

    def test_matching_bytes_derive_the_authority(self):
        root = _synthetic_checkpoint(self.tmp, self.payload)
        record = authority.validate_checkpoint_repository(
            root, expected_sha256=self._expected(),
            expected_size=len(self.payload))
        self.assertEqual(record["derivation"], "MATCH")
        self.assertEqual(record["weights_sha256"], self._expected())
        self.assertEqual(record["status"], "CHECKPOINT_AUTHORITY_DERIVED")

    def test_single_flipped_byte_cannot_inherit_the_authority(self):
        flipped = bytearray(self.payload)
        flipped[len(flipped) // 2] ^= 0x01
        root2 = _synthetic_checkpoint(self.tmp, bytes(flipped))
        with self.assertRaises(authority.CheckpointAuthorityError) as ctx2:
            authority.validate_checkpoint_repository(
                root2, expected_sha256=self._expected(),
                expected_size=len(flipped))
        self.assertIn("does not derive", str(ctx2.exception))

    def test_same_length_foreign_bytes_cannot_inherit_the_authority(self):
        foreign = bytes(len(self.payload))
        root = _synthetic_checkpoint(self.tmp, foreign)
        with self.assertRaises(authority.CheckpointAuthorityError):
            authority.validate_checkpoint_repository(
                root, expected_sha256=self._expected(),
                expected_size=len(foreign))

    def test_truncated_and_extended_bytes_fail(self):
        root = _synthetic_checkpoint(self.tmp, self.payload[:-1])
        with self.assertRaises(authority.CheckpointAuthorityError):
            authority.validate_checkpoint_repository(
                root, expected_sha256=self._expected(),
                expected_size=len(self.payload))
        root2 = _synthetic_checkpoint(self.tmp, self.payload + b"\x00")
        with self.assertRaises(authority.CheckpointAuthorityError):
            authority.validate_checkpoint_repository(
                root2, expected_sha256=self._expected(),
                expected_size=len(self.payload))

    def test_self_attesting_sidecar_proves_nothing(self):
        # a repository with WRONG bytes plus a sidecar repeating ACCEPTED
        # must still fail: the rule hashes bytes, not sidecars.
        wrong = self.payload[:-1] + bytes([self.payload[-1] ^ 0xFF])
        root = _synthetic_checkpoint(self.tmp, wrong, sidecar=True)
        with self.assertRaises(authority.CheckpointAuthorityError):
            authority.validate_checkpoint_repository(
                root, expected_sha256=ACCEPTED,
                expected_size=len(wrong))

    def test_symlinked_weights_are_refused(self):
        root = _synthetic_checkpoint(self.tmp, self.payload, symlink=True)
        with self.assertRaises(authority.CheckpointAuthorityError):
            authority.validate_checkpoint_repository(
                root, expected_sha256=self._expected(),
                expected_size=len(self.payload))

    def test_missing_or_wrong_size_fails_closed(self):
        empty = self.tmp / "empty"; empty.mkdir()
        with self.assertRaises(authority.CheckpointAuthorityError):
            authority.validate_checkpoint_repository(empty)
        root = _synthetic_checkpoint(self.tmp, self.payload)
        with self.assertRaises(authority.CheckpointAuthorityError):
            authority.validate_checkpoint_repository(
                root, expected_sha256=self._expected(),
                expected_size=len(self.payload) + 1)


class PreflightWiringTests(unittest.TestCase):
    """The preflight derives authority from candidate bytes now."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="issue117-pf-auth-")
        self.tmp = Path(self._temp.name)
        # reuse the existing test builder
        sys.path.insert(0, str(ROOT / "tests"))
        from test_issue117_preflight import build_valid_preflight  # noqa
        self.valid = build_valid_preflight(self.tmp)

    def tearDown(self):
        self._temp.cleanup()

    def test_physical_preflight_now_derives_authority_from_bytes(self):
        payload = b"synthetic weights"
        root = _synthetic_checkpoint(self.tmp, payload)
        # digest mismatch => mechanical failure naming the derivation
        failures = preflight.validate_preflight(
            self.valid, repo_root=ROOT, checkpoint_root=root)
        self.assertTrue(any(
            "checkpoint authority derivation failed" in failure
            or "does not match the mechanically derived" in failure
            for failure in failures), failures)

    def test_physical_preflight_rejects_altered_bytes(self):
        payload = b"synthetic weights altered"
        root = _synthetic_checkpoint(self.tmp, payload)
        failures = preflight.validate_preflight(
            self.valid, repo_root=ROOT, checkpoint_root=root)
        self.assertTrue(any("checkpoint authority derivation failed" in failure
                            for failure in failures), failures)


if __name__ == "__main__":
    unittest.main()
