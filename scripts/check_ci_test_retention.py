#!/usr/bin/env python3
"""CI test-retention audit and retired-lineage integrity check (Issue #246).

Two repository-integrity checks, both CPU-only and pure standard library:

1. **Retention audit.** ``docs/ci/test-retention-audit.json`` classifies
   every canonical test module (``tests/test_*.py``) with exactly one
   retention category and disposition.  Every discovered module must carry
   a record, and a retained module must declare the current invariant it
   protects and match its registered CI group in ``scripts/plan_ci.py``.
   A module may only be removed when it is ``HISTORICAL_ONLY`` or
   ``OBSOLETE``; a retained ``HISTORICAL_ONLY``/``OBSOLETE`` module must
   name the stop condition that blocks its retirement.  A newly added test
   module without a record fails this check, so no future group can grow
   into an unowned catch-all.

2. **Retired-lineage integrity.** When a historical behavior suite is
   retired, the accepted evidence it guarded stays protected by cheap
   byte checks instead of reducer replay.  For every integrity replacement
   the audit declares evidence bundles (a root directory plus the accepted
   row files -- ``MANIFEST.sha256``, ``CLOSURE.sha256``, JSON ``rows`` --
   that hash it) and the retired producer scripts.  The check requires:

   * every row in every row file matches the bytes on disk;
   * every file under a bundle root is covered by a row, a row file, a
     pin, or a declared exempt suffix (no undeclared evidence);
   * the row files themselves, the retired producers, the ``extra_pins``
     (root files the accepted rows do not cover), and -- for a bundle with
     no row files -- every non-exempt file under its root are pinned by
     ``docs/ci/retired-lineage-pins.sha256``, so evidence and its manifest
     cannot be rewritten together and retired producers stay frozen;
   * the pin file names exactly the required set (no stray pins).

Usage::

    python3 scripts/check_ci_test_retention.py            # check (default)
    python3 scripts/check_ci_test_retention.py --write-pins

``--write-pins`` re-pins current bytes.  Only use it with maintainer
authority for a deliberate change to retired evidence; it is how accepted
evidence would be rewritten, so a pin change fails the planner closed to
full regression and needs review.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = Path("docs/ci/test-retention-audit.json")
PINS = Path("docs/ci/retired-lineage-pins.sha256")
AUDIT_SCHEMA = "inferswarm.ci.test-retention-audit/1"

CATEGORIES = frozenset({
    "CURRENT_CONTRACT",
    "CURRENT_REGRESSION",
    "EVIDENCE_INTEGRITY",
    "HISTORICAL_ONLY",
    "OBSOLETE",
})
CURRENT_CATEGORIES = frozenset({
    "CURRENT_CONTRACT", "CURRENT_REGRESSION", "EVIDENCE_INTEGRITY"})
REMOVABLE_CATEGORIES = CATEGORIES - CURRENT_CATEGORIES
ACTIVE_DISPOSITIONS = frozenset({"retain", "narrow"})
REMOVED_DISPOSITIONS = frozenset({
    "integrity-replacement", "historical-retire", "delete"})
DISPOSITIONS = ACTIVE_DISPOSITIONS | REMOVED_DISPOSITIONS
ROW_FORMATS = frozenset({"sha256sum", "json-rows"})
ROW_BASES = frozenset({"repo", "bundle"})


class RetentionError(Exception):
    """A fail-closed audit or integrity violation."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_audit(root: Path = ROOT) -> dict:
    return json.loads((root / AUDIT).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Retired-lineage integrity
# ---------------------------------------------------------------------------

def parse_sha256sum(text: str, base: str) -> dict[str, str]:
    """Parse ``<sha256>  <path>`` rows; ``#`` comments and blanks skip."""
    rows: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        digest, separator, relative = line.partition("  ")
        if (separator != "  " or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or not relative):
            raise RetentionError(f"malformed row {number}: {line!r}")
        path = base + relative
        if path in rows:
            raise RetentionError(f"duplicate row {number}: {path}")
        rows[path] = digest
    return rows


def parse_json_rows(text: str) -> dict[str, str]:
    rows = json.loads(text).get("rows")
    if not isinstance(rows, dict) or not rows:
        raise RetentionError("json-rows file has no rows object")
    for relative, digest in rows.items():
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)):
            raise RetentionError(f"malformed json row: {relative}")
    return dict(rows)


def read_pins(root: Path) -> dict[str, str]:
    path = root / PINS
    if not path.is_file():
        raise RetentionError(f"missing pin file: {PINS}")
    return parse_sha256sum(path.read_text(encoding="utf-8"), "")


def bundle_rows(root: Path, bundle: dict) -> dict[str, str]:
    """All accepted rows declared by a bundle's row files."""
    rows: dict[str, str] = {}
    for row_file in bundle.get("row_files", []):
        if row_file["format"] not in ROW_FORMATS:
            raise RetentionError(f"unknown row format: {row_file}")
        if row_file.get("base", "repo") not in ROW_BASES:
            raise RetentionError(f"unknown row base: {row_file}")
        path = root / row_file["path"]
        if not path.is_file():
            raise RetentionError(f"missing row file: {row_file['path']}")
        text = path.read_text(encoding="utf-8")
        if row_file["format"] == "json-rows":
            parsed = parse_json_rows(text)
        else:
            base = bundle["root"] if row_file.get("base") == "bundle" else ""
            parsed = parse_sha256sum(text, base)
        for relative, digest in parsed.items():
            if rows.get(relative, digest) != digest:
                raise RetentionError(f"conflicting rows for {relative}")
            rows[relative] = digest
    return rows


def files_under(root: Path, prefix: str) -> list[str]:
    base = root / prefix
    if not base.is_dir():
        raise RetentionError(f"missing bundle root: {prefix}")
    found = []
    for directory, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in filenames:
            found.append((Path(directory) / name).relative_to(root).as_posix())
    return sorted(found)


def required_pins(root: Path, audit: dict) -> set[str]:
    """The exact set of paths the pin file must name."""
    required: set[str] = set()
    for replacement in audit.get("integrity_replacements", []):
        required.update(replacement.get("producers", []))
        required.update(replacement.get("extra_pins", []))
        for bundle in replacement.get("bundles", []):
            required.update(r["path"] for r in bundle.get("row_files", []))
            if not bundle.get("row_files"):
                exempt = tuple(bundle.get("exempt_suffixes", []))
                required.update(
                    p for p in files_under(root, bundle["root"])
                    if not p.endswith(exempt))
    return required


def integrity_errors(root: Path = ROOT, audit: dict | None = None) -> list[str]:
    audit = audit if audit is not None else load_audit(root)
    errors: list[str] = []
    try:
        pins = read_pins(root)
    except RetentionError as error:
        return [str(error)]
    for relative, digest in sorted(pins.items()):
        path = root / relative
        if not path.is_file():
            errors.append(f"pinned file missing: {relative}")
        elif sha256(path) != digest:
            errors.append(f"pinned file changed: {relative}")
    try:
        required = required_pins(root, audit)
    except RetentionError as error:
        return errors + [str(error)]
    for relative in sorted(required - set(pins)):
        errors.append(f"required pin absent: {relative}")
    for relative in sorted(set(pins) - required):
        errors.append(f"stray pin not required by the audit: {relative}")
    for replacement in audit.get("integrity_replacements", []):
        for bundle in replacement.get("bundles", []):
            prefix = bundle["root"]
            try:
                rows = bundle_rows(root, bundle)
                present = files_under(root, prefix)
            except (RetentionError, ValueError) as error:
                errors.append(f"{prefix}: {error}")
                continue
            for relative, digest in sorted(rows.items()):
                path = root / relative
                if not path.is_file():
                    errors.append(f"{prefix}: accepted row missing: {relative}")
                elif sha256(path) != digest:
                    errors.append(f"{prefix}: accepted evidence changed: {relative}")
            covered = set(rows) | set(pins)
            covered.update(r["path"] for r in bundle.get("row_files", []))
            exempt = tuple(bundle.get("exempt_suffixes", []))
            for relative in present:
                if relative not in covered and not relative.endswith(exempt):
                    errors.append(f"{prefix}: undeclared evidence file: {relative}")
    return errors


def write_pins(root: Path = ROOT, audit: dict | None = None) -> None:
    audit = audit if audit is not None else load_audit(root)
    lines = [f"{sha256(root / p)}  {p}\n"
             for p in sorted(required_pins(root, audit))]
    (root / PINS).parent.mkdir(parents=True, exist_ok=True)
    (root / PINS).write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Retention audit
# ---------------------------------------------------------------------------

def discovered_modules(root: Path = ROOT) -> set[str]:
    """Module names canonical discovery (``tests/test_*.py``) will import."""
    return {p.stem for p in (root / "tests").glob("test_*.py")}


FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
CI_REGISTRATION_SCRIPTS = frozenset({"plan_ci.py", "ci_workflow_parity.py"})


def defined_names(path: Path) -> set[str]:
    """``Class``, ``Class.method``, and module-level function names."""
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, FUNCTIONS):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
            names.update(f"{node.name}.{item.name}" for item in node.body
                         if isinstance(item, FUNCTIONS))
    return names


def manifest_rows_naming_tests(root: Path) -> dict[str, set[str]]:
    """Test module -> accepted MANIFEST.sha256 files listing its path.

    The evidence-manifest lifecycle check requires every row target to
    exist, so a listed test file cannot be removed without rewriting
    accepted evidence.
    """
    found: dict[str, set[str]] = {}
    docs = root / "docs"
    if not docs.is_dir():
        return found
    for manifest in docs.rglob("MANIFEST.sha256"):
        for line in manifest.read_text(encoding="utf-8").splitlines():
            relative = line.partition("  ")[2]
            if relative.startswith("tests/test_") and relative.endswith(".py"):
                found.setdefault(relative[len("tests/"):-3], set()).add(
                    manifest.relative_to(root).as_posix())
    return found


def scripts_consuming_tests(root: Path) -> dict[str, set[str]]:
    """Test module -> scripts that import it or name its file path.

    Manifest builders and authority audits that name a test file consume
    its bytes; the CI planner's own registration lists are not consumers.
    """
    found: dict[str, set[str]] = {}
    scripts = root / "scripts"
    if not scripts.is_dir():
        return found
    for path in scripts.glob("*.py"):
        if path.name in CI_REGISTRATION_SCRIPTS:
            continue
        source = path.read_text(encoding="utf-8")
        consumed = set(re.findall(r"tests/(test_\w+)\.py", source))
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                consumed.update(a.name for a in node.names
                                if a.name.startswith("test_"))
            elif (isinstance(node, ast.ImportFrom) and node.module
                  and node.module.startswith("test_")):
                consumed.add(node.module)
        for module in consumed:
            found.setdefault(module, set()).add(
                path.relative_to(root).as_posix())
    return found


def planner_module_groups(root: Path = ROOT) -> dict[str, str]:
    registry = json.loads(
        (root / "scripts/ci_groups.json").read_text(encoding="utf-8"))
    owners: dict[str, str] = {}
    for group, info in registry["groups"].items():
        for module in info["test_modules"]:
            owners[module] = group
    return owners


def _record_errors(module: str, record: dict) -> list[str]:
    errors = []
    category = record.get("category")
    disposition = record.get("disposition")
    if category not in CATEGORIES:
        errors.append(f"{module}: unknown category {category!r}")
    if disposition not in DISPOSITIONS:
        errors.append(f"{module}: unknown disposition {disposition!r}")
    for field in ("lineage", "invariant", "rationale"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            errors.append(f"{module}: missing {field}")
    if disposition in ACTIVE_DISPOSITIONS and category not in CURRENT_CATEGORIES:
        if not str(record.get("retention_blocker") or "").strip():
            errors.append(f"{module}: retained {category} module must name "
                          "the retention_blocker stop condition")
    if disposition in REMOVED_DISPOSITIONS:
        if category not in REMOVABLE_CATEGORIES:
            errors.append(f"{module}: {category} module cannot be removed; "
                          "only HISTORICAL_ONLY/OBSOLETE units may leave CI")
        if not str(record.get("replacement") or "").strip():
            errors.append(f"{module}: removed module must name what protects "
                          "its evidence or why nothing needs to")
    for key, override in record.get("overrides", {}).items():
        if (override.get("disposition") in REMOVED_DISPOSITIONS
                and override.get("category") not in REMOVABLE_CATEGORIES):
            errors.append(f"{module}.{key}: only HISTORICAL_ONLY/OBSOLETE "
                          "units may be removed")
        if override.get("category") not in CATEGORIES:
            errors.append(f"{module}.{key}: unknown override category")
        if override.get("disposition") not in DISPOSITIONS:
            errors.append(f"{module}.{key}: unknown override disposition")
        if not str(override.get("rationale") or "").strip():
            errors.append(f"{module}.{key}: override missing rationale")
    return errors


def audit_errors(root: Path = ROOT, audit: dict | None = None) -> list[str]:
    audit = audit if audit is not None else load_audit(root)
    errors: list[str] = []
    if audit.get("schema") != AUDIT_SCHEMA:
        errors.append(f"unexpected audit schema: {audit.get('schema')!r}")
    records = audit.get("modules", {})
    discovered = discovered_modules(root)
    owners = planner_module_groups(root)
    manifest_rows = manifest_rows_naming_tests(root)
    consumers = scripts_consuming_tests(root)
    for module in sorted(discovered - set(records)):
        errors.append(f"{module}: discovered test module has no retention "
                      "audit record (declare its category and invariant)")
    for module, record in sorted(records.items()):
        errors.extend(_record_errors(module, record))
        disposition = record.get("disposition")
        # The declared pins/consumers are cross-checked against the tree:
        # an accepted manifest row or a consuming script is a stop
        # condition, so the audit may not omit one.
        for manifest in sorted(manifest_rows.get(module, set())
                               - set(record.get("pinned_by_evidence", []))):
            errors.append(f"{module}: accepted manifest {manifest} lists the "
                          "test file but pinned_by_evidence omits it")
        for script in sorted(consumers.get(module, set())
                             - set(record.get("referenced_by_scripts", []))):
            errors.append(f"{module}: {script} consumes the test module but "
                          "referenced_by_scripts omits it")
        if disposition in ACTIVE_DISPOSITIONS:
            if module not in discovered:
                errors.append(f"{module}: retained module is not discovered")
                continue
            if owners.get(module) != record.get("group"):
                errors.append(f"{module}: audit group {record.get('group')!r} "
                              f"!= planner group {owners.get(module)!r}")
            names = defined_names(root / "tests" / f"{module}.py")
            for key, override in record.get("overrides", {}).items():
                removed = override.get("disposition") in REMOVED_DISPOSITIONS
                if removed and key in names:
                    errors.append(f"{module}: removed test unit {key} is "
                                  "still defined")
                elif not removed and key not in names:
                    errors.append(f"{module}: override names unknown test "
                                  f"unit {key}")
        elif disposition in REMOVED_DISPOSITIONS:
            if module in discovered:
                errors.append(f"{module}: removed module re-entered "
                              "canonical discovery")
            if module in owners:
                errors.append(f"{module}: removed module is still "
                              "registered to a CI group")
            if record.get("group") is not None:
                errors.append(f"{module}: removed module must have group null")
    replaced = {module for replacement in audit.get("integrity_replacements", [])
                for module in replacement.get("replaces", [])}
    for module, record in sorted(records.items()):
        if (record.get("disposition") == "integrity-replacement"
                and module not in replaced):
            errors.append(f"{module}: no integrity replacement lists it")
    for module in sorted(replaced):
        if records.get(module, {}).get("disposition") != "integrity-replacement":
            errors.append(f"{module}: listed by an integrity replacement but "
                          "not dispositioned integrity-replacement")
    return errors


def check(root: Path = ROOT) -> list[str]:
    try:
        audit = load_audit(root)
    except (OSError, ValueError) as error:
        return [f"cannot load {AUDIT}: {error}"]
    return audit_errors(root, audit) + integrity_errors(root, audit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write-pins", action="store_true",
                        help="re-pin current bytes (maintainer authority only)")
    args = parser.parse_args(argv)
    if args.write_pins:
        write_pins()
        print(f"wrote {PINS}")
        return 0
    errors = check()
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(f"ci-test-retention: FAILED ({len(errors)} errors)")
        return 1
    print("ci-test-retention: OK (retention audit complete; retired-lineage "
          "evidence, manifests, and producers verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
