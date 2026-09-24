#!/usr/bin/env python3
"""CI test-retention audit and retired-lineage integrity check (Issue #246).

Three repository-integrity checks, all CPU-only and pure standard library:

1. **Retention audit.** ``docs/ci/test-retention-audit.json`` classifies
   every canonical test module (``tests/test_*.py``) with exactly one
   retention category and disposition.  Every discovered module must carry
   a record whose category is ``CURRENT_CONTRACT``, ``CURRENT_REGRESSION``,
   or ``EVIDENCE_INTEGRITY``, declare the current invariant it protects,
   and match its registered CI group in ``scripts/plan_ci.py``.
   ``HISTORICAL_ONLY`` and ``OBSOLETE`` records exist only for REMOVED
   units: such a module may be neither discovered nor registered, and no
   current script may consume it.  Historical provenance is not a
   retention criterion; Git history is the archive.  A newly added test
   module without a record fails this check, so no future group can grow
   into an unowned catch-all.

2. **Retired test rows.** An accepted manifest (``MANIFEST.sha256``,
   ``CLOSURE.sha256``, or a JSON producer-hash ledger) may name a test
   file that was deliberately deleted.  The accepted manifest bytes stay
   untouched; ``docs/ci/retired-test-rows.json`` instead records one exact
   tombstone per retired row, binding the manifest path, the SHA-256 of
   the accepted manifest bytes, the retired target path, the SHA-256 the
   manifest stores for it, the reason, and the Issue #246 authority.
   Row verification then treats a missing target as PASS only when one
   exact tombstone matches all four identities; a changed manifest, a
   changed stored digest, a wildcard, a duplicate, an unlisted missing
   row, or a tombstone for a target that still exists all fail.

3. **Retired-lineage integrity.** When a historical behavior suite is
   retired, the accepted evidence it guarded stays protected by cheap
   byte checks instead of reducer replay.  For every integrity replacement
   the audit declares evidence bundles (a root directory plus the accepted
   row files that hash it) and the retired producer scripts.  The check
   requires:

   * every row in every row file matches the bytes on disk, or is an
     exactly tombstoned retired test row;
   * every file under a bundle root (outside ``excluded_subtrees``, which
     carry their own authority) is covered by a row, a row file, a pin,
     or a declared exempt suffix (no undeclared evidence);
   * the row files themselves, the retired producers, the ``extra_pins``,
     and -- for a bundle with no row files or with ``pin_uncovered`` --
     every non-exempt file its rows do not cover are pinned by
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
RETIRED_ROWS = Path("docs/ci/retired-test-rows.json")
AUDIT_SCHEMA = "inferswarm.ci.test-retention-audit/1"
RETIRED_ROWS_SCHEMA = "inferswarm.ci.retired-test-rows/1"
RETIREMENT_AUTHORITY = "Issue #246"
RETIREMENT_FIELDS = frozenset({
    "manifest", "manifest_sha256", "target", "target_sha256", "reason",
    "authority"})
# A retired row names exactly one deleted canonical test file: no
# wildcard, prefix, directory, or non-test target can be tombstoned.
RETIRED_TARGET = re.compile(r"tests/test_[A-Za-z0-9_]+\.py")
EXACT_PATH = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*")

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
ROW_FORMATS = frozenset({"sha256sum", "json-rows", "json-map"})
ROW_BASES = frozenset({"repo", "bundle"})


class RetentionError(Exception):
    """A fail-closed audit or integrity violation."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_audit(root: Path = ROOT) -> dict:
    return json.loads((root / AUDIT).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Accepted row files
# ---------------------------------------------------------------------------

def _is_digest(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def parse_sha256sum(text: str, base: str) -> dict[str, str]:
    """Parse ``<sha256>  <path>`` rows; ``#`` comments and blanks skip."""
    rows: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        digest, separator, relative = line.partition("  ")
        if separator != "  " or not _is_digest(digest) or not relative:
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
        if not _is_digest(digest):
            raise RetentionError(f"malformed json row: {relative}")
    return dict(rows)


def parse_json_map(text: str, key: str | None) -> dict[str, str]:
    """A JSON producer-hash ledger: ``{path: sha256}``, optionally nested.

    With ``key`` the ledger is the object under that key (for example
    ``producers``); every value must be a digest.
    """
    document = json.loads(text)
    rows = document.get(key) if key else document
    if not isinstance(rows, dict) or not rows:
        raise RetentionError(f"json-map file has no row object (key {key!r})")
    for relative, digest in rows.items():
        if not _is_digest(digest):
            raise RetentionError(f"malformed json-map row: {relative}")
    return dict(rows)


def row_file_rows(root: Path, row_file: dict, bundle_root: str = "") -> dict[str, str]:
    """Parse one declared row file into ``{repo path: accepted sha256}``."""
    if row_file["format"] not in ROW_FORMATS:
        raise RetentionError(f"unknown row format: {row_file}")
    if row_file.get("base", "repo") not in ROW_BASES:
        raise RetentionError(f"unknown row base: {row_file}")
    path = root / row_file["path"]
    if not path.is_file():
        raise RetentionError(f"missing row file: {row_file['path']}")
    text = path.read_text(encoding="utf-8")
    if row_file["format"] == "json-rows":
        return parse_json_rows(text)
    if row_file["format"] == "json-map":
        return parse_json_map(text, row_file.get("key"))
    base = bundle_root if row_file.get("base") == "bundle" else ""
    return parse_sha256sum(text, base)


# ---------------------------------------------------------------------------
# Retired test rows (tombstones for deliberately deleted test files)
# ---------------------------------------------------------------------------

class RetiredRows:
    """The validated, exact tombstone index of retired accepted test rows.

    ``permits`` answers only for an exact four-part identity: accepted
    manifest path, the SHA-256 of its current bytes, the retired target
    path, and the SHA-256 the manifest stores for that target.  Nothing
    is matched by prefix or pattern.
    """

    def __init__(self, entries: list[dict] | None = None):
        self.entries = list(entries or [])
        self._index = {
            (e["manifest"], e["manifest_sha256"], e["target"],
             e["target_sha256"]): e
            for e in self.entries}

    def permits(self, manifest: str, manifest_sha256: str, target: str,
                target_sha256: str) -> bool:
        return (manifest, manifest_sha256, target, target_sha256) in self._index

    def targets(self) -> set[str]:
        return {e["target"] for e in self.entries}

    def manifests_for(self, target: str) -> set[str]:
        return {e["manifest"] for e in self.entries if e["target"] == target}


def _declared_row_files(root: Path, audit: dict | None) -> dict[str, dict]:
    """Every row file the repository verifies, keyed by path.

    ``docs/**/MANIFEST.sha256`` (the evidence-manifest lifecycle) plus the
    row files an integrity replacement declares (with their formats).
    """
    declared: dict[str, dict] = {}
    docs = root / "docs"
    if docs.is_dir():
        for manifest in docs.rglob("MANIFEST.sha256"):
            relative = manifest.relative_to(root).as_posix()
            declared[relative] = {"path": relative, "format": "sha256sum",
                                  "base": "repo", "bundle_root": ""}
    for replacement in (audit or {}).get("integrity_replacements", []):
        for bundle in replacement.get("bundles", []):
            for row_file in bundle.get("row_files", []):
                declared[row_file["path"]] = dict(
                    row_file, bundle_root=bundle["root"])
    return declared


def load_retired_rows(root: Path = ROOT, audit: dict | None = None
                      ) -> tuple[RetiredRows, list[str]]:
    """Validate ``docs/ci/retired-test-rows.json``; return (index, errors).

    Every entry must be exact and still describe the accepted bytes: the
    manifest digest must equal the current manifest bytes, the manifest
    must store exactly ``target_sha256`` for ``target``, and the target
    must be absent (a tombstone never excuses an existing, changed file).
    Invalid entries are reported and excluded from the index, so a
    missing target they would have covered also fails row verification.
    """
    path = root / RETIRED_ROWS
    if not path.is_file():
        return RetiredRows(), []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        return RetiredRows(), [f"{RETIRED_ROWS}: {error}"]
    errors: list[str] = []
    if document.get("schema") != RETIRED_ROWS_SCHEMA:
        errors.append(f"{RETIRED_ROWS}: unexpected schema "
                      f"{document.get('schema')!r}")
    entries = document.get("retirements")
    if not isinstance(entries, list):
        return RetiredRows(), errors + [f"{RETIRED_ROWS}: retirements must "
                                        "be a list"]
    declared = _declared_row_files(root, audit)
    seen: dict[tuple[str, str], int] = {}
    valid: list[dict] = []
    for number, entry in enumerate(entries):
        where = f"{RETIRED_ROWS} entry {number}"
        if not isinstance(entry, dict) or set(entry) != RETIREMENT_FIELDS:
            errors.append(f"{where}: must carry exactly the fields "
                          f"{sorted(RETIREMENT_FIELDS)}")
            continue
        manifest, target = entry["manifest"], entry["target"]
        problems = []
        if (not isinstance(manifest, str) or not EXACT_PATH.fullmatch(manifest)
                or ".." in manifest.split("/")):
            problems.append(f"manifest must be an exact path: {manifest!r}")
        if not isinstance(target, str) or not RETIRED_TARGET.fullmatch(target):
            problems.append("target must be one exact tests/test_*.py path "
                            f"(no wildcard or prefix): {target!r}")
        for field in ("manifest_sha256", "target_sha256"):
            if not _is_digest(entry[field]):
                problems.append(f"{field} is not a sha256 digest")
        if not isinstance(entry["reason"], str) or not entry["reason"].strip():
            problems.append("reason is empty")
        if entry["authority"] != RETIREMENT_AUTHORITY:
            problems.append(f"authority must be {RETIREMENT_AUTHORITY!r}")
        if problems:
            errors.extend(f"{where}: {p}" for p in problems)
            continue
        key = (manifest, target)
        if key in seen:
            errors.append(f"{where}: duplicate or conflicting retirement of "
                          f"{target} in {manifest} (also entry {seen[key]})")
            # neither conflicting entry may excuse the row
            valid = [e for e in valid
                     if (e["manifest"], e["target"]) != key]
            continue
        seen[key] = number
        manifest_path = root / manifest
        if not manifest_path.is_file():
            errors.append(f"{where}: accepted manifest missing: {manifest}")
            continue
        if sha256(manifest_path) != entry["manifest_sha256"]:
            errors.append(f"{where}: accepted manifest {manifest} bytes do "
                          "not match manifest_sha256 (the manifest changed; "
                          "the retirement is void)")
            continue
        row_file = declared.get(manifest)
        if row_file is None:
            errors.append(f"{where}: {manifest} is not a verified row file")
            continue
        try:
            rows = row_file_rows(root, row_file, row_file["bundle_root"])
        except (RetentionError, ValueError) as error:
            errors.append(f"{where}: {manifest}: {error}")
            continue
        if rows.get(target) != entry["target_sha256"]:
            errors.append(f"{where}: {manifest} does not store "
                          f"target_sha256 for {target}")
            continue
        if (root / target).exists():
            errors.append(f"{where}: retired target {target} exists; a "
                          "tombstone cannot excuse a present (possibly "
                          "changed) file -- verify it or delete it")
            continue
        valid.append(entry)
    return RetiredRows(valid), errors


def verify_rows(root: Path, row_file: str, rows: dict[str, str],
                retired: RetiredRows) -> list[str]:
    """Verify accepted rows against disk, honoring exact tombstones only."""
    errors: list[str] = []
    manifest_digest = sha256(root / row_file)
    for relative, digest in sorted(rows.items()):
        path = root / relative
        if path.is_file():
            if sha256(path) != digest:
                errors.append(f"{row_file}: accepted evidence changed: "
                              f"{relative}")
        elif not retired.permits(row_file, manifest_digest, relative, digest):
            errors.append(f"{row_file}: accepted row missing: {relative}")
    return errors


# ---------------------------------------------------------------------------
# Retired-lineage integrity
# ---------------------------------------------------------------------------

def read_pins(root: Path) -> dict[str, str]:
    path = root / PINS
    if not path.is_file():
        raise RetentionError(f"missing pin file: {PINS}")
    return parse_sha256sum(path.read_text(encoding="utf-8"), "")


def bundle_rows(root: Path, bundle: dict) -> dict[str, dict[str, str]]:
    """Accepted rows declared by a bundle, grouped by row file."""
    grouped: dict[str, dict[str, str]] = {}
    merged: dict[str, str] = {}
    for row_file in bundle.get("row_files", []):
        parsed = row_file_rows(root, row_file, bundle["root"])
        for relative, digest in parsed.items():
            if merged.get(relative, digest) != digest:
                raise RetentionError(f"conflicting rows for {relative}")
            merged[relative] = digest
        grouped[row_file["path"]] = parsed
    return grouped


def files_under(root: Path, prefix: str,
                excluded: tuple[str, ...] = ()) -> list[str]:
    base = root / prefix
    if not base.is_dir():
        raise RetentionError(f"missing bundle root: {prefix}")
    found = []
    for directory, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in filenames:
            relative = (Path(directory) / name).relative_to(root).as_posix()
            if not relative.startswith(excluded):
                found.append(relative)
    return sorted(found)


def _bundle_excluded(bundle: dict) -> tuple[str, ...]:
    excluded = tuple(bundle.get("excluded_subtrees", []))
    for subtree in excluded:
        if not (subtree.startswith(bundle["root"]) and subtree.endswith("/")
                and subtree != bundle["root"]):
            raise RetentionError(f"{bundle['root']}: excluded subtree must be "
                                 f"a strict sub-directory: {subtree!r}")
    return excluded


def _bundle_uncovered(root: Path, bundle: dict) -> list[str]:
    """Non-exempt files under a bundle root its accepted rows do not cover."""
    grouped = bundle_rows(root, bundle)
    covered = {path for rows in grouped.values() for path in rows}
    covered.update(r["path"] for r in bundle.get("row_files", []))
    exempt = tuple(bundle.get("exempt_suffixes", []))
    return [p for p in files_under(root, bundle["root"], _bundle_excluded(bundle))
            if p not in covered and not p.endswith(exempt)]


def required_pins(root: Path, audit: dict) -> set[str]:
    """The exact set of paths the pin file must name."""
    required: set[str] = set()
    for replacement in audit.get("integrity_replacements", []):
        required.update(replacement.get("producers", []))
        required.update(replacement.get("extra_pins", []))
        for bundle in replacement.get("bundles", []):
            required.update(r["path"] for r in bundle.get("row_files", []))
            if not bundle.get("row_files") or bundle.get("pin_uncovered"):
                required.update(_bundle_uncovered(root, bundle))
    return required


def integrity_errors(root: Path = ROOT, audit: dict | None = None,
                     retired: RetiredRows | None = None) -> list[str]:
    audit = audit if audit is not None else load_audit(root)
    if retired is None:
        retired, _ = load_retired_rows(root, audit)
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
    except (RetentionError, ValueError) as error:
        return errors + [str(error)]
    for relative in sorted(required - set(pins)):
        errors.append(f"required pin absent: {relative}")
    for relative in sorted(set(pins) - required):
        errors.append(f"stray pin not required by the audit: {relative}")
    for replacement in audit.get("integrity_replacements", []):
        for bundle in replacement.get("bundles", []):
            errors.extend(bundle_errors(root, bundle, retired, pins))
    return errors


def bundle_errors(root: Path, bundle: dict, retired: RetiredRows,
                  pinned=frozenset()) -> list[str]:
    """One accepted bundle: rows verified (exact tombstones only) + closure."""
    prefix = bundle["root"]
    try:
        grouped = bundle_rows(root, bundle)
        present = files_under(root, prefix, _bundle_excluded(bundle))
    except (RetentionError, ValueError) as error:
        return [f"{prefix}: {error}"]
    errors = []
    for row_file, rows in grouped.items():
        errors.extend(f"{prefix}: {e}"
                      for e in verify_rows(root, row_file, rows, retired))
    covered = {path for rows in grouped.values() for path in rows}
    covered |= set(pinned)
    covered.update(r["path"] for r in bundle.get("row_files", []))
    exempt = tuple(bundle.get("exempt_suffixes", []))
    for relative in present:
        if relative not in covered and not relative.endswith(exempt):
            errors.append(f"{prefix}: undeclared evidence file: {relative}")
    return errors


def replacement_bundle(audit: dict, bundle_root: str) -> dict:
    """The declared integrity bundle rooted exactly at ``bundle_root``."""
    for replacement in audit.get("integrity_replacements", []):
        for bundle in replacement.get("bundles", []):
            if bundle["root"] == bundle_root:
                return bundle
    raise RetentionError(f"no integrity bundle is rooted at {bundle_root}")


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

    The evidence-manifest lifecycle check verifies every row target, so a
    listed test file can only be removed behind an exact retired-row
    tombstone (``docs/ci/retired-test-rows.json``).
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


def scripts_consuming_tests(root: Path, *, imports_only: bool = False
                            ) -> dict[str, set[str]]:
    """Test module -> scripts that import it or name its file path.

    Manifest builders and authority audits that name a test file consume
    its bytes; the CI planner's own registration lists are not consumers.
    With ``imports_only`` only Python imports of the test module count.
    """
    found: dict[str, set[str]] = {}
    scripts = root / "scripts"
    if not scripts.is_dir():
        return found
    for path in scripts.rglob("*.py"):
        if path.name in CI_REGISTRATION_SCRIPTS:
            continue
        source = path.read_text(encoding="utf-8")
        consumed = (set() if imports_only
                    else set(re.findall(r"tests/(test_\w+)\.py", source)))
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                consumed.update(a.name.rpartition(".")[2] for a in node.names
                                if a.name.rpartition(".")[2].startswith("test_"))
            elif (isinstance(node, ast.ImportFrom) and node.module
                  and node.module.rpartition(".")[2].startswith("test_")):
                consumed.add(node.module.rpartition(".")[2])
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
        errors.append(f"{module}: {category} module cannot stay in canonical "
                      "discovery or CI; only CURRENT_CONTRACT, "
                      "CURRENT_REGRESSION, and EVIDENCE_INTEGRITY modules are "
                      "retained (historical provenance is not a retention "
                      "criterion)")
    if disposition in REMOVED_DISPOSITIONS:
        if category not in REMOVABLE_CATEGORIES:
            errors.append(f"{module}: {category} module cannot be removed; "
                          "only HISTORICAL_ONLY/OBSOLETE units may leave CI")
        if not str(record.get("replacement") or "").strip():
            errors.append(f"{module}: removed module must name what protects "
                          "its evidence or why nothing needs to")
    for key, override in record.get("overrides", {}).items():
        removed = override.get("disposition") in REMOVED_DISPOSITIONS
        if removed and override.get("category") not in REMOVABLE_CATEGORIES:
            errors.append(f"{module}.{key}: only HISTORICAL_ONLY/OBSOLETE "
                          "units may be removed")
        if (not removed and disposition in ACTIVE_DISPOSITIONS
                and override.get("category") not in CURRENT_CATEGORIES):
            errors.append(f"{module}.{key}: retained unit must be "
                          "CURRENT_CONTRACT, CURRENT_REGRESSION, or "
                          "EVIDENCE_INTEGRITY")
        if override.get("category") not in CATEGORIES:
            errors.append(f"{module}.{key}: unknown override category")
        if override.get("disposition") not in DISPOSITIONS:
            errors.append(f"{module}.{key}: unknown override disposition")
        if not str(override.get("rationale") or "").strip():
            errors.append(f"{module}.{key}: override missing rationale")
    return errors


def audit_errors(root: Path = ROOT, audit: dict | None = None,
                 retired: RetiredRows | None = None) -> list[str]:
    audit = audit if audit is not None else load_audit(root)
    if retired is None:
        retired, _ = load_retired_rows(root, audit)
    errors: list[str] = []
    if audit.get("schema") != AUDIT_SCHEMA:
        errors.append(f"unexpected audit schema: {audit.get('schema')!r}")
    records = audit.get("modules", {})
    discovered = discovered_modules(root)
    owners = planner_module_groups(root)
    manifest_rows = manifest_rows_naming_tests(root)
    consumers = scripts_consuming_tests(root)
    importers = scripts_consuming_tests(root, imports_only=True)
    try:
        frozen = set(read_pins(root))
    except RetentionError:
        frozen = set()
    removed = {m for m, r in records.items()
               if r.get("disposition") in REMOVED_DISPOSITIONS}
    for module in sorted(discovered - set(records)):
        errors.append(f"{module}: discovered test module has no retention "
                      "audit record (declare its category and invariant)")
    for module in sorted(set(owners) - set(records)):
        errors.append(f"{module}: registered test module has no retention "
                      "audit record")
    for module in sorted(discovered | set(owners)):
        category = records.get(module, {}).get("category")
        if category in REMOVABLE_CATEGORIES:
            where = "discovered" if module in discovered else "registered"
            errors.append(f"{module}: {where} {category} module (only "
                          "current contracts, regressions, and evidence "
                          "integrity may be canonical or CI-registered)")
    for module, record in sorted(records.items()):
        errors.extend(_record_errors(module, record))
        disposition = record.get("disposition")
        declared_scripts = set(record.get("referenced_by_scripts", []))
        for script in sorted(consumers.get(module, set()) - declared_scripts):
            errors.append(f"{module}: {script} consumes the test module but "
                          "referenced_by_scripts omits it")
        if disposition in ACTIVE_DISPOSITIONS:
            # The declared pins are cross-checked against the tree: an
            # accepted manifest row binds the retained file's bytes.
            for manifest in sorted(manifest_rows.get(module, set())
                                   - set(record.get("pinned_by_evidence", []))):
                errors.append(f"{module}: accepted manifest {manifest} lists "
                              "the test file but pinned_by_evidence omits it")
            if module not in discovered:
                errors.append(f"{module}: retained module is not discovered")
                continue
            if owners.get(module) != record.get("group"):
                errors.append(f"{module}: audit group {record.get('group')!r} "
                              f"!= planner group {owners.get(module)!r}")
            names = defined_names(root / "tests" / f"{module}.py")
            for key, override in record.get("overrides", {}).items():
                unit_removed = (override.get("disposition")
                                in REMOVED_DISPOSITIONS)
                if unit_removed and key in names:
                    errors.append(f"{module}: removed test unit {key} is "
                                  "still defined")
                elif not unit_removed and key not in names:
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
            # Accepted rows naming a removed test are exactly its
            # tombstones: the audit may neither omit nor invent one.
            tombstoned = retired.manifests_for(f"tests/{module}.py")
            if set(record.get("pinned_by_evidence", [])) != tombstoned:
                errors.append(f"{module}: pinned_by_evidence must equal the "
                              "manifests carrying its retired-row tombstones "
                              f"{sorted(tombstoned)}")
            for manifest in sorted(manifest_rows.get(module, set())
                                   - tombstoned):
                errors.append(f"{module}: accepted manifest {manifest} lists "
                              "the removed test file without a retired-row "
                              "tombstone")
            # No current script may consume a retired test module.  Only a
            # byte-frozen (pinned) retired producer may still name its
            # path, as historical bytes; nothing may import it.
            for script in sorted(importers.get(module, set())):
                errors.append(f"{module}: {script} imports a retired test "
                              "module")
            for script in sorted(consumers.get(module, set()) - frozen):
                errors.append(f"{module}: current script {script} consumes "
                              "a retired test module (move the authority "
                              "into a non-test module, or retire and pin "
                              "the script)")
    for target in sorted(retired.targets()):
        module = target[len("tests/"):-len(".py")]
        if module not in removed:
            errors.append(f"{module}: retired-row tombstone names a module "
                          "that is not a removed audit record")
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
    retired, retired_errors = load_retired_rows(root, audit)
    return (retired_errors + audit_errors(root, audit, retired)
            + integrity_errors(root, audit, retired))


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
    print("ci-test-retention: OK (every canonical test module is current; "
          "retired test rows exactly tombstoned; retired-lineage evidence, "
          "manifests, and producers verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
