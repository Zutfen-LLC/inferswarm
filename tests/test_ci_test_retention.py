"""Issue #246 CI test-retention audit and retired-lineage integrity tests.

The real repository must pass every check, and each negative control
mutates a scratch copy to prove the check fails closed:

  * retired historical evidence cannot drift, gain undeclared files, lose
    rows, or be rewritten together with its manifest once the behavior
    suite that used to replay it is gone;
  * an accepted manifest row naming a deleted test file passes only
    behind one exact retired-row tombstone (manifest path + manifest
    digest + target path + stored target digest), and every other
    missing, changed, duplicated, wildcard, or stale case fails;
  * only CURRENT_CONTRACT / CURRENT_REGRESSION / EVIDENCE_INTEGRITY
    modules may be discovered or registered, a new test module cannot
    enter discovery without a retention record, a retired module cannot
    silently re-enter discovery, a current contract cannot be removed from
    CI, and no current script may consume a retired test module.
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
        retired, errors = retention.load_retired_rows(ROOT, self.audit)
        self.assertEqual(errors, [])
        pins = retention.read_pins(ROOT)
        for module, record in self.audit["modules"].items():
            if record["disposition"] in retention.REMOVED_DISPOSITIONS:
                self.assertIn(record["category"],
                              retention.REMOVABLE_CATEGORIES, module)
                self.assertTrue(record["replacement"], module)
                self.assertEqual(
                    set(record["pinned_by_evidence"]),
                    retired.manifests_for(f"tests/{module}.py"), module)
                for script in record["referenced_by_scripts"]:
                    self.assertIn(script, pins, f"{module}: {script}")

    def test_zero_historical_or_obsolete_modules_are_canonical(self):
        discovered = retention.discovered_modules(ROOT)
        registered = {m for mods in plan_ci.GROUP_TEST_MODULES.values()
                      for m in mods}
        for module in discovered | registered:
            self.assertIn(self.audit["modules"][module]["category"],
                          retention.CURRENT_CATEGORIES, module)
        removable = {m for m, r in self.audit["modules"].items()
                     if r["category"] in retention.REMOVABLE_CATEGORIES}
        self.assertFalse(removable & (discovered | registered))

    def test_real_retired_rows_are_exact_and_absent(self):
        retired, errors = retention.load_retired_rows(ROOT, self.audit)
        self.assertEqual(errors, [])
        document = json.loads((ROOT / retention.RETIRED_ROWS).read_text())
        self.assertEqual(len(retired.entries), len(document["retirements"]))
        for entry in retired.entries:
            self.assertFalse((ROOT / entry["target"]).exists(), entry)
            module = entry["target"][len("tests/"):-len(".py")]
            self.assertIn(self.audit["modules"][module]["disposition"],
                          retention.REMOVED_DISPOSITIONS, module)

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
    """Synthetic repository: tests/, registry, audit records, tombstones."""

    RETIRED_ROW = "tests/test_retired.py"

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        write(self.root, "tests/test_current.py",
              "import unittest\n\n\nclass CurrentTests(unittest.TestCase):\n"
              "    def test_contract(self):\n        pass\n")
        write(self.root, "tests/test_evidence.py",
              "import unittest\n\n\nclass EvidenceTests(unittest.TestCase):\n"
              "    def test_bytes(self):\n        pass\n")
        # the retired module's accepted manifest row, tombstoned exactly
        write(self.root, "docs/ev/MANIFEST.sha256",
              f"{'a' * 64}  {self.RETIRED_ROW}\n")
        self.write_tombstones([self.tombstone()])
        write(self.root, retention.PINS, "")
        self.registry = {"groups": {
            "current-group": {"test_modules": ["test_current"]},
            "evidence-group": {"test_modules": ["test_evidence"]}}}
        self.write_registry()
        self.audit = {
            "schema": retention.AUDIT_SCHEMA,
            "modules": {
                "test_current": {
                    "group": "current-group", "lineage": "current",
                    "category": "CURRENT_CONTRACT", "disposition": "retain",
                    "invariant": "the current contract holds",
                    "rationale": "current"},
                "test_evidence": {
                    "group": "evidence-group", "lineage": "evidence",
                    "category": "EVIDENCE_INTEGRITY", "disposition": "retain",
                    "invariant": "accepted bytes stay exact",
                    "rationale": "evidence"},
                "test_retired": {
                    "group": None, "lineage": "history",
                    "category": "HISTORICAL_ONLY",
                    "disposition": "integrity-replacement",
                    "invariant": "(retired)", "rationale": "history",
                    "replacement": "manifest pins",
                    "pinned_by_evidence": ["docs/ev/MANIFEST.sha256"]},
            },
            "integrity_replacements": [{"id": "x", "replaces": ["test_retired"],
                                        "bundles": [], "producers": []}],
        }

    def tombstone(self, **changes):
        manifest = self.root / "docs/ev/MANIFEST.sha256"
        entry = {"manifest": "docs/ev/MANIFEST.sha256",
                 "manifest_sha256": sha256(manifest.read_bytes()),
                 "target": self.RETIRED_ROW, "target_sha256": "a" * 64,
                 "reason": "retired replay suite",
                 "authority": retention.RETIREMENT_AUTHORITY}
        entry.update(changes)
        return entry

    def write_tombstones(self, entries):
        write(self.root, retention.RETIRED_ROWS, json.dumps({
            "schema": retention.RETIRED_ROWS_SCHEMA, "retirements": entries}))

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
        self.assert_caught("test_retired: discovered HISTORICAL_ONLY module")

    def test_retired_module_still_registered_is_caught(self):
        self.registry["groups"]["evidence-group"]["test_modules"].append(
            "test_retired")
        self.write_registry()
        self.assert_caught("test_retired: removed module is still registered")
        self.assert_caught("test_retired: registered HISTORICAL_ONLY module")

    def test_current_contract_cannot_be_removed(self):
        (self.root / "tests/test_current.py").unlink()
        del self.registry["groups"]["current-group"]
        self.write_registry()
        record = self.audit["modules"]["test_current"]
        record.update(disposition="delete", group=None, replacement="none")
        self.assert_caught("CURRENT_CONTRACT module cannot be removed")

    def test_discovered_historical_only_module_is_caught(self):
        self.audit["modules"]["test_evidence"]["category"] = "HISTORICAL_ONLY"
        self.assert_caught("test_evidence: discovered HISTORICAL_ONLY module")
        self.assert_caught("test_evidence: HISTORICAL_ONLY module cannot stay "
                           "in canonical discovery")

    def test_discovered_obsolete_module_is_caught(self):
        self.audit["modules"]["test_evidence"]["category"] = "OBSOLETE"
        self.assert_caught("test_evidence: discovered OBSOLETE module")

    def test_registered_historical_only_module_is_caught(self):
        # registered (e.g. by a workflow/registry edit) but not discovered
        self.registry["groups"]["legacy"] = {"test_modules": ["test_legacy"]}
        self.write_registry()
        self.audit["modules"]["test_legacy"] = {
            "group": "legacy", "lineage": "history",
            "category": "HISTORICAL_ONLY", "disposition": "retain",
            "invariant": "frozen replay", "rationale": "history"}
        self.assert_caught("test_legacy: registered HISTORICAL_ONLY module")

    def test_registered_obsolete_module_is_caught(self):
        self.registry["groups"]["legacy"] = {"test_modules": ["test_legacy"]}
        self.write_registry()
        self.audit["modules"]["test_legacy"] = {
            "group": "legacy", "lineage": "history",
            "category": "OBSOLETE", "disposition": "retain",
            "invariant": "stale bookkeeping", "rationale": "history"}
        self.assert_caught("test_legacy: registered OBSOLETE module")

    def test_retention_blocker_no_longer_keeps_a_historical_module(self):
        # provenance (a manifest pin, a consuming script) is not a reason
        record = self.audit["modules"]["test_evidence"]
        record.update(category="HISTORICAL_ONLY",
                      retention_blocker="pinned by an accepted manifest")
        self.assert_caught("cannot stay in canonical discovery or CI")

    def test_retained_historical_override_is_caught(self):
        self.audit["modules"]["test_evidence"]["overrides"] = {
            "EvidenceTests.test_bytes": {"category": "HISTORICAL_ONLY",
                                         "disposition": "retain",
                                         "rationale": "r"}}
        self.assert_caught("test_evidence.EvidenceTests.test_bytes: retained "
                           "unit must be CURRENT_CONTRACT")

    def test_missing_invariant_is_caught(self):
        self.audit["modules"]["test_current"]["invariant"] = " "
        self.assert_caught("test_current: missing invariant")

    def test_group_drift_from_planner_is_caught(self):
        self.audit["modules"]["test_current"]["group"] = "evidence-group"
        self.assert_caught("!= planner group 'current-group'")

    def test_override_of_unknown_unit_is_caught(self):
        self.audit["modules"]["test_evidence"]["overrides"] = {
            "EvidenceTests.test_gone": {"category": "EVIDENCE_INTEGRITY",
                                        "disposition": "retain",
                                        "rationale": "r"}}
        self.assert_caught("override names unknown test unit")

    def test_removed_unit_still_defined_is_caught(self):
        self.audit["modules"]["test_evidence"]["overrides"] = {
            "EvidenceTests.test_bytes": {"category": "OBSOLETE",
                                         "disposition": "delete",
                                         "rationale": "r"}}
        self.assert_caught("removed test unit EvidenceTests.test_bytes is "
                           "still defined")

    def test_undeclared_manifest_pin_is_caught(self):
        write(self.root, "docs/other/MANIFEST.sha256",
              f"{'0' * 64}  tests/test_current.py\n")
        self.assert_caught("test_current: accepted manifest "
                           "docs/other/MANIFEST.sha256 lists the test file "
                           "but pinned_by_evidence omits it")

    def test_removed_module_row_without_tombstone_is_caught(self):
        write(self.root, "docs/other/MANIFEST.sha256",
              f"{'0' * 64}  {self.RETIRED_ROW}\n")
        self.assert_caught("test_retired: accepted manifest "
                           "docs/other/MANIFEST.sha256 lists the removed test "
                           "file without a retired-row tombstone")

    def test_removed_module_pins_must_equal_its_tombstones(self):
        self.audit["modules"]["test_retired"]["pinned_by_evidence"] = []
        self.assert_caught("test_retired: pinned_by_evidence must equal the "
                           "manifests carrying its retired-row tombstones")

    def test_tombstone_for_a_non_removed_module_is_caught(self):
        self.audit["modules"]["test_retired"].update(
            category="CURRENT_CONTRACT", disposition="retain",
            group="current-group")
        self.assert_caught("test_retired: retired-row tombstone names a "
                           "module that is not a removed audit record")

    def test_undeclared_consuming_script_is_caught(self):
        write(self.root, "scripts/builder.py",
              "from test_evidence import CONSTANT\n")
        write(self.root, "scripts/audit.py",
              "INPUTS = ['tests/test_current.py']\n")
        self.assert_caught("test_evidence: scripts/builder.py consumes the "
                           "test module but referenced_by_scripts omits it")
        self.assert_caught("test_current: scripts/audit.py consumes the test "
                           "module but referenced_by_scripts omits it")

    def test_current_script_importing_a_retired_test_is_caught(self):
        write(self.root, "scripts/authority.py",
              "from test_retired import ACCEPTED_HASHES\n")
        self.audit["modules"]["test_retired"]["referenced_by_scripts"] = [
            "scripts/authority.py"]
        self.assert_caught("test_retired: scripts/authority.py imports a "
                           "retired test module")
        self.assert_caught("test_retired: current script scripts/authority.py "
                           "consumes a retired test module")

    def test_frozen_script_importing_a_retired_test_is_still_caught(self):
        write(self.root, "scripts/authority.py",
              "import test_retired\n")
        write(self.root, retention.PINS, f"{'1' * 64}  scripts/authority.py\n")
        self.audit["modules"]["test_retired"]["referenced_by_scripts"] = [
            "scripts/authority.py"]
        self.assert_caught("scripts/authority.py imports a retired test module")

    def test_current_script_naming_a_retired_test_path_is_caught(self):
        write(self.root, "scripts/audit.py",
              "ALLOW = ['tests/test_retired.py']\n")
        self.audit["modules"]["test_retired"]["referenced_by_scripts"] = [
            "scripts/audit.py"]
        self.assert_caught("current script scripts/audit.py consumes a "
                           "retired test module")

    def test_frozen_retired_producer_naming_the_path_is_historical_bytes(self):
        write(self.root, "scripts/audit.py",
              "ALLOW = ['tests/test_retired.py']\n")
        write(self.root, retention.PINS, f"{'1' * 64}  scripts/audit.py\n")
        self.audit["modules"]["test_retired"]["referenced_by_scripts"] = [
            "scripts/audit.py"]
        self.assertEqual(self.errors(), [])

    def test_planner_registration_is_not_consumption(self):
        write(self.root, "scripts/plan_ci.py",
              "MODULES = ['tests/test_current.py']\n")
        self.assertEqual(self.errors(), [])

    def test_removed_module_needs_a_replacement_statement(self):
        self.audit["modules"]["test_retired"]["replacement"] = ""
        self.assert_caught("removed module must name what protects")


class RetiredRowControls(unittest.TestCase):
    """Tombstone mutation matrix over a synthetic accepted bundle.

    ``docs/ev/`` carries an accepted ``MANIFEST.sha256`` and a JSON
    producer-hash ledger that both name ``tests/test_old.py``, deleted by
    retirement.  ``docs/ci/retired-test-rows.json`` tombstones exactly
    those two rows.
    """

    TARGET = "tests/test_old.py"
    MANIFEST = "docs/ev/MANIFEST.sha256"
    LEDGER = "docs/ev/producer-hashes.json"

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.old_bytes = b"import unittest\n# retired replay suite\n"
        self.old_digest = sha256(self.old_bytes)
        result = write(self.root, "docs/ev/result.json",
                       '{"terminal": "PASS"}\n').read_bytes()
        write(self.root, "scripts/producer.py", "print('frozen')\n")
        write(self.root, self.MANIFEST,
              f"{sha256(result)}  docs/ev/result.json\n"
              f"{self.old_digest}  {self.TARGET}\n")
        write(self.root, self.LEDGER, json.dumps({
            "scripts/producer.py": sha256(b"print('frozen')\n"),
            self.TARGET: self.old_digest}, indent=1) + "\n")
        self.audit = {"integrity_replacements": [{
            "id": "lineage", "replaces": ["test_old"], "extra_pins": [],
            "producers": ["scripts/producer.py"],
            "bundles": [{"root": "docs/ev/", "row_files": [
                {"path": self.MANIFEST, "format": "sha256sum", "base": "repo"},
                {"path": self.LEDGER, "format": "json-map", "base": "repo"}]}],
        }]}
        self.entries = [self.entry(self.MANIFEST), self.entry(self.LEDGER)]
        self.write_rows()
        retention.write_pins(self.root, self.audit)

    def entry(self, manifest, **changes):
        entry = {"manifest": manifest,
                 "manifest_sha256": sha256((self.root / manifest).read_bytes()),
                 "target": self.TARGET, "target_sha256": self.old_digest,
                 "reason": "test_old retired (Issue #246)",
                 "authority": retention.RETIREMENT_AUTHORITY}
        entry.update(changes)
        return entry

    def write_rows(self, entries=None):
        write(self.root, retention.RETIRED_ROWS, json.dumps({
            "schema": retention.RETIRED_ROWS_SCHEMA,
            "retirements": self.entries if entries is None else entries}))

    def load(self):
        return retention.load_retired_rows(self.root, self.audit)

    def all_errors(self):
        retired, errors = self.load()
        return errors + retention.integrity_errors(self.root, self.audit, retired)

    def assert_caught(self, *needles):
        errors = self.all_errors()
        for needle in needles:
            self.assertTrue(any(needle in e for e in errors),
                            f"expected {needle!r} in {errors}")

    def manifest_row_missing(self):
        return f"{self.MANIFEST}: accepted row missing: {self.TARGET}"

    # -- exact tombstone ---------------------------------------------------

    def test_exact_retirement_tuple_passes(self):
        retired, errors = self.load()
        self.assertEqual(errors, [])
        self.assertTrue(retired.permits(
            self.MANIFEST, sha256((self.root / self.MANIFEST).read_bytes()),
            self.TARGET, self.old_digest))
        self.assertEqual(self.all_errors(), [])

    def test_permits_requires_all_four_identities(self):
        retired, _ = self.load()
        digest = sha256((self.root / self.MANIFEST).read_bytes())
        for args in ((self.LEDGER, digest, self.TARGET, self.old_digest),
                     (self.MANIFEST, "0" * 64, self.TARGET, self.old_digest),
                     (self.MANIFEST, digest, "tests/test_other.py",
                      self.old_digest),
                     (self.MANIFEST, digest, self.TARGET, "0" * 64)):
            self.assertFalse(retired.permits(*args), args)

    # -- manifest / digest tampering ---------------------------------------

    def test_altered_accepted_manifest_invalidates_the_retirement(self):
        manifest = self.root / self.MANIFEST
        manifest.write_text(manifest.read_text() + "# appended note\n")
        self.assert_caught("do not match manifest_sha256",
                           self.manifest_row_missing(),
                           f"pinned file changed: {self.MANIFEST}")

    def test_wrong_manifest_digest_in_the_tombstone_fails(self):
        self.entries[0] = self.entry(self.MANIFEST, manifest_sha256="0" * 64)
        self.write_rows()
        self.assert_caught("do not match manifest_sha256",
                           self.manifest_row_missing())

    def test_altered_historical_target_digest_invalidates_the_retirement(self):
        self.entries[0] = self.entry(self.MANIFEST, target_sha256="0" * 64)
        self.write_rows()
        self.assert_caught(f"does not store target_sha256 for {self.TARGET}",
                           self.manifest_row_missing())

    def test_manifest_row_digest_rewritten_invalidates_the_retirement(self):
        # the accepted row itself is edited to a new digest: manifest
        # bytes change, so the tombstone (and the pin) no longer match
        manifest = self.root / self.MANIFEST
        manifest.write_text(manifest.read_text().replace(
            self.old_digest, "f" * 64))
        # (the rewritten row now also conflicts with the ledger row, which
        # fails the whole bundle closed)
        self.assert_caught("do not match manifest_sha256",
                           f"pinned file changed: {self.MANIFEST}",
                           f"conflicting rows for {self.TARGET}")

    # -- exactness ---------------------------------------------------------

    def test_wildcard_and_prefix_retirements_are_prohibited(self):
        for target in ("tests/test_*.py", "tests/", "tests/test_old",
                       "tests/test_ol?.py", "tests/sub/test_old.py",
                       "scripts/producer.py"):
            self.write_rows([dict(self.entry(self.MANIFEST), target=target)])
            _, errors = self.load()
            self.assertTrue(any("must be one exact tests/test_*.py path" in e
                                for e in errors), (target, errors))
        for manifest in ("docs/ev/*.sha256", "docs/ev/", "../docs/ev/MANIFEST.sha256"):
            self.write_rows([dict(self.entry(self.MANIFEST), manifest=manifest)])
            _, errors = self.load()
            self.assertTrue(any("manifest must be an exact path" in e
                                for e in errors), (manifest, errors))

    def test_missing_retirement_entry_fails(self):
        self.write_rows([self.entries[1]])
        self.assert_caught(self.manifest_row_missing())

    def test_duplicate_retirement_fails_and_excuses_nothing(self):
        self.write_rows([self.entries[0], dict(self.entries[0]),
                         self.entries[1]])
        self.assert_caught("duplicate or conflicting retirement",
                           self.manifest_row_missing())

    def test_conflicting_retirement_fails_and_excuses_nothing(self):
        conflicting = self.entry(self.MANIFEST, target_sha256="0" * 64)
        self.write_rows([self.entries[0], conflicting, self.entries[1]])
        self.assert_caught("duplicate or conflicting retirement",
                           self.manifest_row_missing())

    def test_malformed_entries_are_rejected(self):
        extra = dict(self.entries[0], pattern="tests/*")
        missing = {k: v for k, v in self.entries[0].items() if k != "reason"}
        for bad, needle in (
                (extra, "must carry exactly the fields"),
                (missing, "must carry exactly the fields"),
                (self.entry(self.MANIFEST, authority="Issue #1"),
                 "authority must be"),
                (self.entry(self.MANIFEST, reason=" "), "reason is empty"),
                (self.entry(self.MANIFEST, target_sha256="XYZ"),
                 "target_sha256 is not a sha256 digest")):
            self.write_rows([bad, self.entries[1]])
            _, errors = self.load()
            self.assertTrue(any(needle in e for e in errors), (needle, errors))
            self.assertTrue(any(self.manifest_row_missing() in e
                                for e in self.all_errors()), needle)

    def test_tombstone_for_an_unverified_row_file_is_rejected(self):
        write(self.root, "docs/ev/notes.json",
              json.dumps({self.TARGET: self.old_digest}))
        self.write_rows(self.entries + [self.entry("docs/ev/notes.json")])
        _, errors = self.load()
        self.assertTrue(any("is not a verified row file" in e for e in errors),
                        errors)

    # -- present targets and unrelated rows --------------------------------

    def test_retirement_cannot_hide_a_present_changed_target(self):
        write(self.root, self.TARGET, "import unittest\n# edited\n")
        self.assert_caught(f"retired target {self.TARGET} exists",
                           f"{self.MANIFEST}: accepted evidence changed: "
                           f"{self.TARGET}")

    def test_reintroduced_identical_target_still_fails_the_tombstone(self):
        write(self.root, self.TARGET, self.old_bytes)
        self.assert_caught(f"retired target {self.TARGET} exists")

    def test_unrelated_missing_manifest_row_still_fails(self):
        (self.root / "docs/ev/result.json").unlink()
        self.assert_caught(f"{self.MANIFEST}: accepted row missing: "
                           "docs/ev/result.json")

    def test_current_manifest_target_mutation_fails(self):
        write(self.root, "docs/ev/result.json", '{"terminal": "FAIL"}\n')
        self.assert_caught(f"{self.MANIFEST}: accepted evidence changed: "
                           "docs/ev/result.json")

    def test_json_ledger_row_needs_its_own_tombstone(self):
        self.write_rows([self.entries[0]])
        self.assert_caught(f"{self.LEDGER}: accepted row missing: "
                           f"{self.TARGET}")

    def test_altered_json_ledger_invalidates_its_tombstone(self):
        ledger = self.root / self.LEDGER
        ledger.write_text(ledger.read_text().replace(
            "\n}", ',\n "scripts/new.py": "' + "1" * 64 + '"\n}'))
        self.assert_caught(f"{self.LEDGER} bytes do not match manifest_sha256")


class RealTreeRetirementControls(unittest.TestCase):
    """Real audit + tombstones against a scratch copy of the real tree."""

    @classmethod
    def setUpClass(cls):
        cls.scratch = Path(tempfile.mkdtemp())
        root = cls.scratch
        audit = retention.load_audit(ROOT)
        paths = {str(retention.AUDIT), str(retention.PINS),
                 str(retention.RETIRED_ROWS), "scripts/ci_groups.json"}
        paths |= {p.relative_to(ROOT).as_posix()
                  for p in (ROOT / "docs").rglob("MANIFEST.sha256")}
        for replacement in audit["integrity_replacements"]:
            for bundle in replacement["bundles"]:
                paths |= {r["path"] for r in bundle["row_files"]}
        paths |= set(retention.read_pins(ROOT))
        for relative in paths:
            if (ROOT / relative).is_file():
                write(root, relative, (ROOT / relative).read_bytes())
        shutil.copytree(ROOT / "tests", root / "tests", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        for script in (ROOT / "scripts").glob("*.py"):
            write(root, f"scripts/{script.name}", script.read_bytes())
        cls.audit = audit

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch)

    def errors(self):
        retired, errors = retention.load_retired_rows(self.scratch, self.audit)
        return errors + retention.audit_errors(self.scratch, self.audit, retired)

    def test_scratch_copy_passes(self):
        self.assertEqual(self.errors(), [])

    def test_dead_module_reintroduced_under_tests_fails(self):
        target = self.scratch / "tests/test_v0b_reduction.py"
        target.write_text("import unittest\n")
        try:
            errors = self.errors()
        finally:
            target.unlink()
        for needle in ("test_v0b_reduction: removed module re-entered "
                       "canonical discovery",
                       "test_v0b_reduction: discovered HISTORICAL_ONLY module",
                       "retired target tests/test_v0b_reduction.py exists"):
            self.assertTrue(any(needle in e for e in errors), (needle, errors))

    def test_current_script_consuming_a_retired_test_fails(self):
        target = self.scratch / "scripts/new_authority_record.py"
        target.write_text(
            "from test_issue166_swa_remediation_record import HASHES\n")
        try:
            errors = self.errors()
        finally:
            target.unlink()
        self.assertTrue(any(
            "scripts/new_authority_record.py imports a retired test module"
            in e for e in errors), errors)

    def test_retired_module_registered_again_fails(self):
        registry = self.scratch / "scripts/ci_groups.json"
        original = registry.read_text()
        document = json.loads(original)
        document["groups"]["r8i-qwen-qualification"]["test_modules"].append(
            "test_issue195_r8d")
        registry.write_text(json.dumps(document))
        try:
            errors = self.errors()
        finally:
            registry.write_text(original)
        self.assertTrue(any("test_issue195_r8d: registered HISTORICAL_ONLY"
                            in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
