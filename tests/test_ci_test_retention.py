"""Issue #246 CI test-retention audit and retired-lineage integrity tests.

The real repository must pass both checks, and each negative control
mutates a scratch copy to prove the check fails closed:

  * retired historical evidence cannot drift, gain undeclared files, lose
    rows, or be rewritten together with its manifest once the behavior
    suite that used to replay it is gone;
  * a new test module cannot enter discovery without a retention record,
    a retired module cannot silently re-enter discovery, and a current
    contract cannot be removed from CI.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_ci_test_retention as retention  # noqa: E402
import plan_ci  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RealRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = retention.load_audit(ROOT)

    def test_real_audit_and_retired_lineage_integrity_pass(self):
        self.assertEqual(retention.check(ROOT), [])

    def test_cli_passes(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_ci_test_retention.py")],
            capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ci-test-retention: OK", proc.stdout)

    def test_discovery_population_is_exactly_the_retained_records(self):
        active = {m for m, r in self.audit["modules"].items()
                  if r["disposition"] in retention.ACTIVE_DISPOSITIONS}
        self.assertEqual(retention.discovered_modules(ROOT), active)
        registered = {m for mods in plan_ci.GROUP_TEST_MODULES.values()
                      for m in mods}
        self.assertEqual(registered, active)

    def test_only_historical_or_obsolete_units_were_removed(self):
        # A unit never leaves CI for being slow: removal requires a
        # HISTORICAL_ONLY/OBSOLETE classification and a named replacement.
        for module, record in self.audit["modules"].items():
            if record["disposition"] in retention.REMOVED_DISPOSITIONS:
                self.assertIn(record["category"],
                              ("HISTORICAL_ONLY", "OBSOLETE"), module)
                self.assertTrue(record["replacement"], module)
                self.assertEqual(record["pinned_by_evidence"], [], module)
                self.assertEqual(record["imported_by_scripts"], [], module)

    def test_every_retired_producer_and_row_file_is_pinned(self):
        pins = retention.read_pins(ROOT)
        for replacement in self.audit["integrity_replacements"]:
            self.assertTrue(replacement["producers"], replacement["id"])
            for producer in replacement["producers"]:
                self.assertIn(producer, pins)
            for bundle in replacement["bundles"]:
                for row_file in bundle["row_files"]:
                    self.assertIn(row_file["path"], pins)

    def test_retired_evidence_selects_the_integrity_group(self):
        for replacement in self.audit["integrity_replacements"]:
            for path in replacement["producers"] + [
                    b["root"] + "x.json" for b in replacement["bundles"]]:
                plan = plan_ci.plan([path], mode="pr")
                self.assertFalse(plan["full_regression"], path)
                self.assertIn("repo-integrity", plan["groups"], path)


def write(root: Path, relative: str, data: bytes | str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path


class IntegrityMutationControls(unittest.TestCase):
    """Synthetic retired lineage: one manifest bundle, one pinned root."""

    AUDIT = {"integrity_replacements": [{
        "id": "lineage",
        "replaces": ["test_old"],
        "bundles": [
            {"root": "docs/ev/bundle/", "row_files": [
                {"path": "docs/ev/bundle/MANIFEST.sha256",
                 "format": "sha256sum", "base": "repo"}]},
            {"root": "docs/ev/data/", "row_files": [],
             "exempt_suffixes": [".md"]},
        ],
        "extra_pins": [],
        "producers": ["scripts/old_producer.py"],
    }]}

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        rows = ""
        for name, body in (("result.json", '{"terminal": "PASS"}\n'),
                           ("README.md", "# bundle\n")):
            data = write(self.root, f"docs/ev/bundle/{name}", body).read_bytes()
            rows += f"{sha256(data)}  docs/ev/bundle/{name}\n"
        write(self.root, "docs/ev/bundle/MANIFEST.sha256", rows)
        write(self.root, "docs/ev/data/placement.json", '{"slots": 3774}\n')
        write(self.root, "docs/ev/data/README.md", "# data\n")
        write(self.root, "scripts/old_producer.py", "print('frozen')\n")
        retention.write_pins(self.root, self.AUDIT)

    def errors(self):
        return retention.integrity_errors(self.root, self.AUDIT)

    def assert_caught(self, needle):
        errors = self.errors()
        self.assertTrue(any(needle in e for e in errors),
                        f"expected {needle!r} in {errors}")

    def test_clean_baseline_passes(self):
        self.assertEqual(self.errors(), [])

    def test_evidence_byte_mutation_is_caught(self):
        write(self.root, "docs/ev/bundle/result.json", '{"terminal": "FAIL"}\n')
        self.assert_caught("accepted evidence changed: docs/ev/bundle/result.json")

    def test_evidence_rewritten_with_its_manifest_is_caught(self):
        data = write(self.root, "docs/ev/bundle/result.json",
                     '{"terminal": "FAIL"}\n').read_bytes()
        manifest = self.root / "docs/ev/bundle/MANIFEST.sha256"
        lines = manifest.read_text().splitlines()
        lines[0] = f"{sha256(data)}  docs/ev/bundle/result.json"
        manifest.write_text("\n".join(lines) + "\n")
        errors = self.errors()
        self.assertNotIn("accepted evidence changed", "\n".join(errors))
        self.assert_caught("pinned file changed: docs/ev/bundle/MANIFEST.sha256")

    def test_undeclared_evidence_file_is_caught(self):
        write(self.root, "docs/ev/bundle/late-addition.json", "{}\n")
        self.assert_caught("undeclared evidence file: docs/ev/bundle/late-addition.json")

    def test_deleted_evidence_is_caught(self):
        (self.root / "docs/ev/bundle/result.json").unlink()
        self.assert_caught("accepted row missing: docs/ev/bundle/result.json")

    def test_retired_producer_mutation_is_caught(self):
        write(self.root, "scripts/old_producer.py", "print('edited')\n")
        self.assert_caught("pinned file changed: scripts/old_producer.py")

    def test_pinned_root_data_mutation_is_caught(self):
        write(self.root, "docs/ev/data/placement.json", '{"slots": 4240}\n')
        self.assert_caught("pinned file changed: docs/ev/data/placement.json")

    def test_new_file_in_pinned_root_is_caught(self):
        write(self.root, "docs/ev/data/new.json", "{}\n")
        self.assert_caught("required pin absent: docs/ev/data/new.json")
        self.assert_caught("undeclared evidence file: docs/ev/data/new.json")

    def test_stray_pin_is_caught(self):
        write(self.root, "docs/other.json", "{}\n")
        pins = self.root / retention.PINS
        pins.write_text(pins.read_text()
                        + f"{sha256(b'{}' + bytes([10]))}  docs/other.json\n")
        self.assert_caught("stray pin not required by the audit: docs/other.json")

    def test_prose_forward_note_in_pinned_root_is_allowed(self):
        write(self.root, "docs/ev/data/README.md", "# data\n\nSuperseded.\n")
        self.assertEqual(self.errors(), [])

    def test_real_retired_bundle_mutation_is_caught(self):
        # Real accepted R8-C evidence, real CI pins: the behavior suite
        # that used to replay it is gone, the bytes stay protected.
        audit = retention.load_audit(ROOT)
        replacement = copy.deepcopy(next(
            r for r in audit["integrity_replacements"]
            if r["id"] == "r8-qwen-retired-investigations"))
        replacement["bundles"] = [
            b for b in replacement["bundles"]
            if b["root"] == "docs/investigations/qwen38-flash-next-r8-c/"]
        replacement["producers"] = [p for p in replacement["producers"]
                                    if p.startswith("scripts/issue193_")]
        replacement["extra_pins"] = []
        sub = {"integrity_replacements": [replacement]}
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        bundle = replacement["bundles"][0]["root"]
        shutil.copytree(ROOT / bundle, root / bundle)
        for producer in replacement["producers"]:
            write(root, producer, (ROOT / producer).read_bytes())
        real_pins = retention.read_pins(ROOT)
        needed = retention.required_pins(root, sub)
        (root / retention.PINS).parent.mkdir(parents=True, exist_ok=True)
        (root / retention.PINS).write_text("".join(
            f"{real_pins[p]}  {p}\n" for p in sorted(needed)))
        self.assertEqual(retention.integrity_errors(root, sub), [])
        target = sorted(p for p in (root / bundle).rglob("*.json"))[0]
        target.write_bytes(target.read_bytes() + b" ")
        errors = retention.integrity_errors(root, sub)
        self.assertTrue(any("accepted evidence changed" in e for e in errors),
                        errors)


class AuditControls(unittest.TestCase):
    """Synthetic repository: tests/, registry, and audit records."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        write(self.root, "tests/test_current.py",
              "import unittest\n\n\nclass CurrentTests(unittest.TestCase):\n"
              "    def test_contract(self):\n        pass\n")
        write(self.root, "tests/test_pinned.py",
              "import unittest\n\n\nclass PinnedTests(unittest.TestCase):\n"
              "    def test_replay(self):\n        pass\n")
        self.registry = {"groups": {
            "current-group": {"test_modules": ["test_current"]},
            "pinned-group": {"test_modules": ["test_pinned"]}}}
        self.write_registry()
        self.audit = {
            "schema": retention.AUDIT_SCHEMA,
            "modules": {
                "test_current": {
                    "group": "current-group", "lineage": "current",
                    "category": "CURRENT_CONTRACT", "disposition": "retain",
                    "invariant": "the current contract holds",
                    "rationale": "current"},
                "test_pinned": {
                    "group": "pinned-group", "lineage": "history",
                    "category": "HISTORICAL_ONLY", "disposition": "retain",
                    "invariant": "frozen replay", "rationale": "history",
                    "retention_blocker": "pinned by an accepted manifest"},
                "test_retired": {
                    "group": None, "lineage": "history",
                    "category": "HISTORICAL_ONLY",
                    "disposition": "integrity-replacement",
                    "invariant": "(retired)", "rationale": "history",
                    "replacement": "manifest pins"},
            },
            "integrity_replacements": [{"id": "x", "replaces": ["test_retired"],
                                        "bundles": [], "producers": []}],
        }

    def write_registry(self):
        write(self.root, "scripts/ci_groups.json", json.dumps(self.registry))

    def errors(self):
        return retention.audit_errors(self.root, self.audit)

    def assert_caught(self, needle):
        errors = self.errors()
        self.assertTrue(any(needle in e for e in errors),
                        f"expected {needle!r} in {errors}")

    def test_clean_baseline_passes(self):
        self.assertEqual(self.errors(), [])

    def test_new_module_without_record_is_caught(self):
        write(self.root, "tests/test_new_campaign.py", "")
        self.assert_caught("test_new_campaign: discovered test module has no "
                           "retention audit record")

    def test_retired_module_reentering_discovery_is_caught(self):
        write(self.root, "tests/test_retired.py", "")
        self.assert_caught("test_retired: removed module re-entered canonical "
                           "discovery")

    def test_retired_module_still_registered_is_caught(self):
        self.registry["groups"]["pinned-group"]["test_modules"].append(
            "test_retired")
        self.write_registry()
        self.assert_caught("test_retired: removed module is still registered")

    def test_current_contract_cannot_be_removed(self):
        (self.root / "tests/test_current.py").unlink()
        del self.registry["groups"]["current-group"]
        self.write_registry()
        record = self.audit["modules"]["test_current"]
        record.update(disposition="delete", group=None, replacement="none")
        self.assert_caught("CURRENT_CONTRACT module cannot be removed")

    def test_retained_historical_module_needs_a_blocker(self):
        self.audit["modules"]["test_pinned"]["retention_blocker"] = None
        self.assert_caught("must name the retention_blocker")

    def test_missing_invariant_is_caught(self):
        self.audit["modules"]["test_current"]["invariant"] = " "
        self.assert_caught("test_current: missing invariant")

    def test_group_drift_from_planner_is_caught(self):
        self.audit["modules"]["test_current"]["group"] = "pinned-group"
        self.assert_caught("!= planner group 'current-group'")

    def test_override_of_unknown_unit_is_caught(self):
        self.audit["modules"]["test_pinned"]["overrides"] = {
            "PinnedTests.test_gone": {"category": "EVIDENCE_INTEGRITY",
                                      "disposition": "retain",
                                      "rationale": "r"}}
        self.assert_caught("override names unknown test unit")

    def test_removed_unit_still_defined_is_caught(self):
        self.audit["modules"]["test_pinned"]["overrides"] = {
            "PinnedTests.test_replay": {"category": "OBSOLETE",
                                        "disposition": "delete",
                                        "rationale": "r"}}
        self.assert_caught("removed test unit PinnedTests.test_replay is "
                           "still defined")

    def test_removed_module_needs_a_replacement_statement(self):
        self.audit["modules"]["test_retired"]["replacement"] = ""
        self.assert_caught("removed module must name what protects")


if __name__ == "__main__":
    unittest.main()
