"""Consumed-holdout non-reuse boundary (CPU-only, Issue #246).

Current doctrine: consumed holdout observations are permanently
diagnostic-only and can never become successor calibration, stress, or
holdout inputs.

* ``h109-*`` (V5, #110): ``docs/qualification/gemma4-12b-it-v5-campaign-110/
  README.md`` -- "can never become successor calibration, stress, or
  holdout inputs".
* ``h86-*`` (V3, #88): ``ROADMAP.md`` -- "the ``h86-*`` observations remain
  permanently diagnostic-only".

The retired #168/#172/#182 campaign suites each asserted that their own
campaign tooling never named the consumed ``h109-`` namespace, and the
retired V3 suites carried the same rule for ``h86-``.  That per-campaign
replay is gone: the campaign tooling is byte-frozen by
``docs/ci/retired-lineage-pins.sha256`` and the accepted row files it
pins.  The still-current invariant is repository-wide and is extracted
here: a script may name a consumed holdout namespace only when it is
byte-frozen historical tooling or the consuming qualification line's own
accepted tooling listed in ``OWNERS``.  Current and future tooling --
including the active R8-I line -- cannot admit consumed observations as
inputs without a reviewed change to this contract.

The active R8-I sealed-holdout custody boundary itself is protected by
``tests/test_issue237_r8i_methodology.py`` (``HoldoutControlTests``,
``GitPurityTests``, ``CustodyReceiptTests``); this module never reads
holdout plaintext.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_ci_test_retention as retention  # noqa: E402

#: consumed namespace -> (doctrine document, doctrine sentence fragment)
CONSUMED = {
    "h109-": ("docs/qualification/gemma4-12b-it-v5-campaign-110/README.md",
              "can never become successor calibration"),
    "h86-": ("ROADMAP.md", "remain permanently diagnostic-only"),
}

#: current (not byte-frozen) tooling of the line that created and consumed
#: a namespace, with the namespaces it may name and why
OWNERS = {
    "scripts/build_issue109_disjointness.py": (
        {"h109-", "h86-"},
        "V5 #109 freeze: proves the fresh c109/h109 corpora are disjoint "
        "from every earlier namespace (reads identifiers, never rows)."),
    "scripts/build_issue109_schemas.py": (
        {"h109-"}, "V5 #109 schema authority for the h109 case-id grammar."),
    "scripts/commit_issue109_holdout.py": (
        {"h109-"}, "V5 #109 sealed-holdout commitment producer."),
    "scripts/generate_issue109_corpora.py": (
        {"h109-"}, "V5 #109 corpus generator that minted the h109 namespace."),
}

ACTIVE_LINE_PREFIXES = ("scripts/issue237_", "scripts/issue244_")


def frozen_paths(root: Path) -> set[str]:
    """Byte-frozen paths: retired-lineage pins plus rows of pinned row files."""
    pins = retention.read_pins(root)
    frozen = set(pins)
    audit = retention.load_audit(root)
    for replacement in audit.get("integrity_replacements", []):
        for bundle in replacement.get("bundles", []):
            for row_file in bundle.get("row_files", []):
                if row_file["path"] in pins:
                    frozen.update(retention.row_file_rows(
                        root, row_file, bundle["root"]))
    return frozen


def namespace_references(root: Path) -> dict[str, set[str]]:
    """Script path -> consumed namespaces its source names."""
    found: dict[str, set[str]] = {}
    for path in sorted((root / "scripts").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        named = {ns for ns in CONSUMED if ns in source}
        if named:
            found[path.relative_to(root).as_posix()] = named
    return found


def boundary_errors(root: Path, owners: dict | None = None) -> list[str]:
    owners = OWNERS if owners is None else owners
    frozen = frozen_paths(root)
    references = namespace_references(root)
    errors = []
    for script, named in sorted(references.items()):
        if script in frozen:
            continue
        allowed = owners.get(script, (set(), ""))[0]
        for namespace in sorted(named - allowed):
            errors.append(f"{script} names consumed holdout namespace "
                          f"{namespace!r} (not frozen, not an owner)")
    for script, (allowed, reason) in sorted(owners.items()):
        if not reason.strip():
            errors.append(f"{script}: owner entry has no reason")
        if not (root / script).is_file():
            errors.append(f"{script}: owner entry names a missing script")
        elif script in frozen:
            errors.append(f"{script}: owner entry is byte-frozen (redundant)")
        elif not references.get(script, set()) & allowed:
            errors.append(f"{script}: stale owner entry (names no consumed "
                          "namespace)")
        if script.startswith(ACTIVE_LINE_PREFIXES):
            errors.append(f"{script}: active R8-I tooling cannot own a "
                          "consumed holdout namespace")
    return errors


class ConsumedHoldoutDoctrineTests(unittest.TestCase):
    def test_doctrine_is_stated_by_its_authority(self):
        for namespace, (document, sentence) in CONSUMED.items():
            text = " ".join((ROOT / document).read_text(
                encoding="utf-8").split())
            self.assertIn(sentence, text, namespace)
            self.assertIn(namespace.rstrip("-"), text, namespace)


class ConsumedHoldoutBoundaryTests(unittest.TestCase):
    def test_only_frozen_or_owner_tooling_names_a_consumed_namespace(self):
        self.assertEqual(boundary_errors(ROOT), [])

    def test_active_r8i_tooling_names_no_consumed_namespace(self):
        references = namespace_references(ROOT)
        active = [s for s in references if s.startswith(ACTIVE_LINE_PREFIXES)]
        self.assertEqual(active, [])

    def test_retired_campaign_tooling_is_byte_frozen(self):
        # the retired #168/#172/#182 campaign pins modules that stated the
        # prohibition are frozen evidence, not live tooling
        frozen = frozen_paths(ROOT)
        for script in ("scripts/issue170_corpus_methodology.py",
                       "scripts/issue172_campaign_pins.py",
                       "scripts/issue175_campaign_pins.py",
                       "scripts/issue182_campaign_pins.py"):
            self.assertIn(script, frozen)


class ConsumedHoldoutNegativeControls(unittest.TestCase):
    """Mutations of a scratch tree must break the boundary."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        shutil.copytree(ROOT / "scripts", self.root / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / "docs/ci").mkdir(parents=True)
        for name in (retention.AUDIT, retention.PINS):
            shutil.copy2(ROOT / name, self.root / name)
        for replacement in retention.load_audit(ROOT)["integrity_replacements"]:
            for bundle in replacement["bundles"]:
                for row_file in bundle["row_files"]:
                    target = self.root / row_file["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / row_file["path"], target)

    def assert_caught(self, needle, owners=None):
        errors = boundary_errors(self.root, owners)
        self.assertTrue(any(needle in e for e in errors),
                        f"expected {needle!r} in {errors}")

    def test_scratch_baseline_passes(self):
        self.assertEqual(boundary_errors(self.root), [])

    def test_new_tooling_naming_h109_is_caught(self):
        (self.root / "scripts/successor_calibration.py").write_text(
            'CASES = ["h109-01-01-01"]\n')
        self.assert_caught("scripts/successor_calibration.py names consumed "
                           "holdout namespace 'h109-'")

    def test_active_r8i_tooling_naming_h86_is_caught(self):
        (self.root / "scripts/issue237_stress_pool.py").write_text(
            'POOL = "h86-03-05-01"\n')
        self.assert_caught("scripts/issue237_stress_pool.py names consumed "
                           "holdout namespace 'h86-'")

    def test_owner_naming_an_undeclared_namespace_is_caught(self):
        path = self.root / "scripts/generate_issue109_corpora.py"
        path.write_text(path.read_text() + '\nREUSE = "h86-"\n')
        self.assert_caught("generate_issue109_corpora.py names consumed "
                           "holdout namespace 'h86-'")

    def test_stale_owner_entry_is_caught(self):
        owners = dict(OWNERS)
        owners["scripts/plan_ci.py"] = ({"h109-"}, "not an owner")
        self.assert_caught("scripts/plan_ci.py: stale owner entry", owners)

    def test_active_line_owner_is_caught(self):
        (self.root / "scripts/issue237_reuse.py").write_text('X = "h109-"\n')
        owners = dict(OWNERS)
        owners["scripts/issue237_reuse.py"] = ({"h109-"}, "reuse")
        self.assert_caught("active R8-I tooling cannot own", owners)

    def test_unfreezing_retired_tooling_is_caught(self):
        # a retired campaign's pins module stops being byte-frozen (its pin
        # is dropped): its consumed-namespace reference is then live
        pins = self.root / retention.PINS
        pins.write_text("".join(
            line for line in pins.read_text().splitlines(keepends=True)
            if not line.endswith("  scripts/issue182_campaign_pins.py\n")))
        self.assert_caught("scripts/issue182_campaign_pins.py names consumed "
                           "holdout namespace 'h109-'")


if __name__ == "__main__":
    unittest.main()
