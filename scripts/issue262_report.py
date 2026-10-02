#!/usr/bin/env python3
"""Fail-closed CPU-only reducer for retained Issue #262 pilot units.

This consumes already retained evidence; it never launches a producer or
manufactures observations. Authentication here means checking every retained
artifact against its unit.json digest before applying the accepted #260/#262
parsers. Custody of the containing directory is external and must be supplied
by the parent forensic lane.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue260_instrumentation as I260
import issue262_h5 as H5
import issue262_pilot as P

ARMS = ("BASE", "A1", "A5", "A4", "H5_CANDIDATE")
ROWS = 8


class ReportError(ValueError):
    """Retained evidence is missing, malformed, unauthenticated, or ambiguous."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_screen_units(units: list[dict]) -> str:
    """Validate complete 2/3-unit screening sequence and return immutable class."""
    if not isinstance(units, list) or len(units) not in (2, 3):
        raise ReportError("screening requires exactly two or three completed units")
    indices = [u.get("unit_index") for u in units]
    if indices != list(range(1, len(units) + 1)):
        raise ReportError("screening unit identity/order must be 1..N")
    digests = [u.get("row_digest") for u in units]
    if any(not isinstance(d, str) or not d for d in digests):
        raise ReportError("screening row digest missing")
    if digests[0] != digests[1]:
        if len(units) != 2:
            raise ReportError("screening-variable arm must stop after two differing units")
    elif len(units) != 3:
        raise ReportError("matching first two screening units require a third")
    return P.screen_class(units)


def classify_units(units: list[dict]) -> str:
    return validate_screen_units(units)


def compare_memory_choices(base: dict, intervention: dict) -> bool:
    """Demand observed target branch/type/flags and apply accepted contrast law."""
    try:
        left, right = base["target"], intervention["target"]
        for item in (left, right):
            if (not isinstance(item.get("branch"), str)
                    or type(item.get("type")) is not int
                    or type(item.get("flags")) is not int):
                raise KeyError("target branch/type/flags")
    except (KeyError, TypeError) as exc:
        raise ReportError("H3 target lacks branch/type/flags") from exc
    return I260.memory_choice_changed(base, intervention)


def compare_arm_pairs(baseline: list[dict], intervention: list[dict], arm: str) -> list[dict]:
    """Contrast every BASE/intervention unit; unequal legal arm counts are valid."""
    for name, units in (("BASE", baseline), (arm, intervention)):
        if [u.get("unit_index") for u in units] != list(range(1, len(units) + 1)) or len(units) not in (2, 3):
            raise ReportError(f"{name} comparison has invalid unit identities/count")
    pairs = []
    for left in baseline:
        for right in intervention:
            bt = left.get("markers", {}).get("h2h3", {}).get("target")
            it = right.get("markers", {}).get("h2h3", {}).get("target")
            if bt is None or it is None:
                raise ReportError(f"H3 {arm} comparison lacks target choice")
            changed = compare_memory_choices({"target": bt}, {"target": it})
            record = {"baseline_unit": left["unit_index"], "intervention_arm": arm,
                      "intervention_unit": right["unit_index"],
                      "baseline_row_digest": left.get("row_digest"),
                      "intervention_row_digest": right.get("row_digest"),
                      "baseline_target": bt, "intervention_target": it,
                      "choice_changed": changed}
            record["comparison_sha256"] = _sha(json.dumps(record, sort_keys=True, separators=(",", ":")).encode())
            pairs.append(record)
    return pairs


def a4_required(a5_contrast: bool) -> bool:
    if type(a5_contrast) is not bool:
        raise ReportError("A5 contrast must be a proven boolean")
    return not a5_contrast


def h5_candidate_eligibility(observation: dict) -> tuple[bool, str]:
    """Delegate eligibility to the accepted route/shape/family law."""
    try:
        return H5.coopmat2_candidate_eligible(observation)
    except (AttributeError, TypeError) as exc:
        raise ReportError("invalid retained BASE H5 observation") from exc


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot read valid JSON {path}") from exc
    if not isinstance(data, dict):
        raise ReportError(f"expected JSON object in {path}")
    return data


def _inventory(root: Path) -> dict[str, dict]:
    """Verify the complete retained copy against its authenticated sibling manifest."""
    manifest = root.parent / "remote-inventory.tsv"
    if not manifest.is_file():
        raise ReportError("authenticated remote-inventory.tsv sibling missing")
    expected = {}
    try:
        for raw in manifest.read_text(encoding="utf-8").splitlines():
            name, size, digest = raw.split("\t")
            if name in expected or Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("duplicate/unsafe inventory path")
            expected[name] = {"size": int(size), "sha256": digest}
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReportError("malformed retained inventory") from exc
    actual = {}
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            blob = path.read_bytes()
            actual[rel] = {"size": len(blob), "sha256": _sha(blob)}
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(k for k in set(actual) & set(expected)
                         if actual[k] != expected[k])
        raise ReportError(f"retained inventory mismatch missing={missing[:3]} extra={extra[:3]} changed={changed[:3]}")
    return expected


def _source_lines(log: bytes, tokens: tuple[str, ...]) -> list[dict]:
    lines=[]
    text=log.decode("utf-8", errors="strict")
    for number, line in enumerate(text.splitlines(), 1):
        if any(token in line for token in tokens):
            lines.append({"line": number, "text": line})
    return lines


def _unit_dir(path: Path, arm: str) -> dict:
    meta = _read_json(path / "unit.json")
    if meta.get("arm") != arm or type(meta.get("unit_index")) is not int:
        raise ReportError(f"unit identity mismatch: {path}")
    log = (path / "server.log").read_bytes()
    log_hash = _sha(log)
    if meta.get("server_log_sha256") != log_hash:
        raise ReportError(f"server.log digest mismatch: {path}")
    if meta.get("response_raw_sha256") != _sha((path / "response.json.raw").read_bytes()):
        raise ReportError(f"response.json.raw digest mismatch: {path}")
    for key in ("binary_sha256", "request_sha256"):
        value = meta.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ReportError(f"invalid {key} in retained unit metadata: {path}")
    rows = []
    for i in range(ROWS):
        row = (path / f"obs.row{i}.f32").read_bytes()
        expected = meta.get("observer_rows_sha256", [])
        if expected and (len(expected) != ROWS or expected[i] != _sha(row)):
            raise ReportError(f"observer row {i} digest mismatch: {path}")
        rows.append(row)
    digest = _sha(b"".join(rows))
    if meta.get("row_digest") != digest:
        raise ReportError(f"combined row digest mismatch: {path}")
    try:
        markers = P.parse_unit_markers(log, arm)
    except Exception as exc:
        raise ReportError(f"retained marker parse failed: {path}: {exc}") from exc
    h2h3 = markers["h2h3"]
    text = log.decode("utf-8", errors="strict")
    target = h2h3.get("target")
    selected = []
    if target:
        allocation = []
        binding = []
        for number, line in enumerate(text.splitlines(), 1):
            memory = I260.MEMORY.search(line)
            tensor = I260.TENSOR.search(line)
            if memory and memory.end() == len(line):
                buffer, branch, memory_type, flags = memory.groups()
                if (int(buffer), branch, int(memory_type), int(flags, 16)) == (
                        target["buffer"], target["branch"], target["type"], target["flags"]):
                    allocation.append({"line": number, "text": line, "kind": "allocation"})
            if tensor and tensor.end() == len(line):
                buffer, offset, size, allocation_size = map(int, tensor.groups())
                if (buffer, offset, size, allocation_size) == (
                        target["buffer"], target["offset"], target["bytes"], target["allocation_size"]):
                    binding.append({"line": number, "text": line, "kind": "tensor-binding"})
        if len(allocation) != 1 or len(binding) != 1 or allocation[0]["line"] >= binding[0]["line"]:
            raise ReportError(f"parsed H3 target lacks exact allocation/tensor provenance: {path}")
        unit_hash = _sha((path / "unit.json").read_bytes())
        selected = [{**entry, "server_log_sha256": log_hash, "unit_json_sha256": unit_hash}
                    for entry in allocation + binding]
        target["provenance"] = selected
    h2h3["source_lines"] = selected
    h2h3["graphs"] = len(h2h3.get("graphs", []))
    h5_lines = _source_lines(log, ("ggml_vk_i262:v1|route|",))
    markers["h5"]["source_lines"] = h5_lines
    if arm != "A1" and not h2h3.get("target"):
        raise ReportError(f"missing parsed output.weight target: {path}")
    return {"unit_index": meta["unit_index"], "row_digest": digest,
            "tag": meta.get("tag", path.name),
            "binary_sha256": meta.get("binary_sha256"),
            "request_sha256": meta.get("request_sha256"),
            "response_raw_sha256": meta.get("response_raw_sha256"),
            "server_log_sha256": log_hash, "log": log, "markers": markers,
            "accepted_comparison": {"identity": "sha256(concat obs.row0.f32..obs.row7.f32)",
                                    "digest": digest},
            "source": {"unit_dir": path.name,
                       "unit_json_sha256": _sha((path / "unit.json").read_bytes()),
                       "server_log_sha256": log_hash}}


def _unanimous_contrast(pairs: list[dict], arm: str) -> bool:
    outcomes = {p["choice_changed"] for p in pairs}
    if len(outcomes) != 1:
        raise ReportError(f"{arm} target choice contrasts disagree across completed pairs")
    return outcomes.pop()


def reduce_evidence(root: Path, context: dict | None = None,
                    *, require_complete: bool = False) -> dict:
    root = Path(root)
    if not root.is_dir():
        raise ReportError(f"retained evidence directory missing: {root}")
    inventory = _inventory(root)
    arms: dict[str, list[dict]] = {}
    for arm in ARMS:
        matches = sorted(root.glob(f"d262-{arm.lower().replace('_','-')}/*"))
        units = []
        for p in matches:
            if not p.is_dir() or p.name.startswith("."):
                continue
            units.append(_unit_dir(p, arm))
        if arm in ("BASE", "A1", "A5") and len(units) < 2:
            raise ReportError(f"insufficient retained units for {arm}")
        if units:
            arms[arm] = units
    if "BASE" not in arms:
        raise ReportError("BASE evidence absent")
    a5_pairs = compare_arm_pairs(arms["BASE"], arms["A5"], "A5")
    a5_contrast = _unanimous_contrast(a5_pairs, "A5")
    a4_needed = a4_required(a5_contrast)
    a4_executed = "A4" in arms
    if a4_needed and not a4_executed and require_complete:
        raise ReportError("A4 required but not executed; refusing final report")
    h3_status = ("contrast-observed" if a5_contrast else
                 "awaiting-required-A4" if a4_needed and not a4_executed else
                 "no-memory-choice-contrast")
    a4_contrast = None
    if a4_executed:
        if not a4_needed:
            raise ReportError("A4 executed despite an existing A5 contrast")
        for unit in arms["A4"]:
            target = unit["markers"]["h2h3"].get("target")
            if target is None:
                raise ReportError("A4 unit lacks target allocation fields")
        a4_pairs = compare_arm_pairs(arms["BASE"], arms["A4"], "A4")
        a4_contrast = _unanimous_contrast(a4_pairs, "A4")
        h3_status = "contrast-observed" if a4_contrast else "no-memory-choice-contrast"
    h5_observations = [u["markers"]["h5"] for u in arms["BASE"]]
    eligibility = [h5_candidate_eligibility(obs) for obs in h5_observations]
    if len({eligible for eligible, _reason in eligibility}) != 1:
        raise ReportError("BASE units disagree on H5 candidate eligibility")
    candidate_eligible, eligibility_reason = eligibility[0]
    if "H5_CANDIDATE" in arms and not candidate_eligible:
        raise ReportError(f"retained H5_CANDIDATE ran without live BASE contrast: {eligibility_reason}")
    routes = h5_observations[0].get("routes", {})
    output_route = routes

    for arm, units in arms.items():
        expected_submission = "serialized" if arm == "A1" else "normal"
        if any(u["markers"]["h2h3"].get("submission") != expected_submission for u in units):
            raise ReportError(f"H2 {arm} submission observation disagrees with accepted law")
    quarantine_dirs = sorted(p for p in (root / "producer-defect-quarantine").iterdir()
                             if p.is_dir()) if (root / "producer-defect-quarantine").is_dir() else []
    quarantine = {}
    for directory in quarantine_dirs:
        prefix = f"producer-defect-quarantine/{directory.name}/"
        files = {key[len(prefix):]: value for key, value in inventory.items() if key.startswith(prefix)}
        if "obs.meta.json" not in files or "server.log" not in files:
            raise ReportError(f"quarantine provenance incomplete: {directory.name}")
        quarantine[directory.name] = {
            "defect": "known producer/parser defect; excluded from accepted screening",
            "obs_meta_json_sha256": files["obs.meta.json"]["sha256"],
            "server_log_sha256": files["server.log"]["sha256"],
            "inventory": {"file": "remote-inventory.tsv", "paths": files}}
    quarantine_files = [name for name in inventory if name.startswith("producer-defect-quarantine/")]
    if context is not None and not isinstance(context, dict):
        raise ReportError("context authority must be a JSON object")
    context = context or {}
    authority = {key: context[key] for key in (
        "original_execution_head", "a4_execution_head", "subject",
        "comparator_sha256", "source_tree") if key in context}
    return {"schema": "inferswarm.issue262.retained-report/1",
            "authority": authority,
            "evidence": {"root": "/home/hermes/is262-evidence",
                         "logical_root": "/home/hermes/is262-evidence",
                         "inventory": "remote-inventory.tsv",
                         "inventory_file_count": len(inventory),
                         "inventory_sha256": _sha((root.parent / "remote-inventory.tsv").read_bytes())},
            "arms": {arm: {"classification": classify_units(units),
                           "n_units": len(units),
                           "arm_env_single_factor": P.ARM_ENV[arm],
                           "units": [{**{k: u.get(k) for k in (
                               "unit_index", "row_digest", "source", "tag", "binary_sha256",
                               "request_sha256", "response_raw_sha256", "server_log_sha256")},
                                      "accepted_comparison": u.get("accepted_comparison", {
                                          "identity": "sha256(concat obs.row0.f32..obs.row7.f32)",
                                          "digest": u["row_digest"]}),
                                      "h2h3": u["markers"]["h2h3"], "h5": u["markers"]["h5"]}
                                     for u in units]}
                     for arm, units in arms.items()},
            "h2": {"result": "A1 serialized; BASE/A5/A4 normal" if a4_executed else
                              "A1 serialized; BASE/A5 normal; A4 pending" if a4_needed else
                              "A1 serialized; BASE/A5 normal","unit_observations": {arm: [{"unit_index": u["unit_index"],
                                                    "submission": u["markers"]["h2h3"].get("submission"),
                                                    "row_digest": u["row_digest"],
                                                    "source": u["source"]}
                                                   for u in units]
                                            for arm, units in arms.items()}},
            "h3": {"a5_target_choice_contrast": a5_contrast,
                   "a5_comparison_pairs": a5_pairs,
                   "a4_comparison_pairs": a4_pairs if a4_executed else [],
                   "a4_required": a4_needed, "a4_executed": a4_executed,
                   "a4_target_choice_contrast": a4_contrast, "status": h3_status},
            "h5": {"baseline_route": output_route,
                   "eligibility_reason": eligibility_reason,
                   "candidate_eligible": candidate_eligible,
                   "candidate_executed": "H5_CANDIDATE" in arms,
                   "mmv_control_live": candidate_eligible},
            "quarantined_units": len(quarantine_dirs),
            "quarantine": quarantine,
            "quarantine_inventory_files": len(quarantine_files),
            "interpretation": {
                "h2": "serialized/normal observations are retained facts, not a numerical causal conclusion",
                "h3": "target memory-choice contrast is necessary, not terminal mechanism proof",
                "h5": "actual baseline route determines candidate eligibility; H5 is not established by capability alone",
                "mmv_control": "MMV/vector path has no live coopmat2 control",
                "screening": "screening-variable is not terminal causal proof; retain all completed units"}}


def render(report: dict) -> str:
    """Render prose only from canonical reducer JSON, independent of key order."""
    report = json.loads(json.dumps(report, sort_keys=True))
    lines = ["# Issue #262 retained pilot report (CPU-only)", "", "## Evidence provenance",
             f"- Logical retained root: `{report['evidence'].get('logical_root', 'retained evidence')}`",
             f"- Inventory: `remote-inventory.tsv`, {report['evidence']['inventory_file_count']} files; SHA-256 `{report['evidence']['inventory_sha256']}`"]
    for key, value in report.get("authority", {}).items():
        lines.append(f"- {key}: `{value}`")
    lines += ["", "## Arms"]
    for arm, result in report["arms"].items():
        lines += [f"### {arm}: {result['classification']} ({len(result['units'])} units)"]
        for unit in result["units"]:
            target = unit["h2h3"].get("target")
            lines.append(f"- Unit {unit['unit_index']} (`{unit.get('tag')}`): row SHA-256 `{unit['row_digest']}`; "
                         f"unit metadata `{unit['source']['unit_json_sha256']}`; log `{unit['source']['server_log_sha256']}`")
            lines.append(f"  - Binary `{unit.get('binary_sha256')}`; request `{unit.get('request_sha256')}`; "
                         f"raw response `{unit.get('response_raw_sha256')}`; accepted comparison "
                         f"`{unit['accepted_comparison']['identity']}` = `{unit['accepted_comparison']['digest']}`")
            if target:
                lines.append(f"  - H3: branch `{target['branch']}`, type `{target['type']}`, flags `{target['flags']}`, "
                             f"buffer `{target['buffer']}`, offset `{target['offset']}`, bytes `{target['bytes']}`, "
                             f"allocation_size `{target['allocation_size']}`")
                for marker in target.get("provenance", []):
                    lines.append(f"  - Log line {marker['line']}: `{marker['text']}`")
            lines.append(f"  - H2 submission: `{unit['h2h3'].get('submission')}`")
    h3 = report["h3"]
    lines += ["", "## H2 observed submission paths",
              f"{report['h2']['result']}. This is a parsed submission-path observation, not numerical causal proof.",
              "", "## H3 full-pair contrasts",
              f"A5 contrast: **{h3['a5_target_choice_contrast']}**; A4 required: **{h3['a4_required']}**; "
              f"A4 executed: **{h3['a4_executed']}**; A4 target-choice contrast: **{h3['a4_target_choice_contrast']}**; "
              f"status: **{h3['status']}**. A contrast requires observed target memory type/flags change, "
              "not just a branch change, and is necessary but not terminal mechanistic proof."]
    for label, pairs in (("BASE vs A5", h3["a5_comparison_pairs"]), ("BASE vs A4", h3.get("a4_comparison_pairs", []))):
        lines += [f"### {label}"]
        for pair in pairs:
            lines.append(f"- Unit {pair['baseline_unit']} vs {pair['intervention_unit']}: "
                         f"choice_changed={pair['choice_changed']}; pair SHA-256 `{pair['comparison_sha256']}`; "
                         f"row digests `{pair['baseline_row_digest']}` / `{pair['intervention_row_digest']}`")
    h5 = report["h5"]
    lines += ["", "## H5", f"Baseline route: `{json.dumps(h5['baseline_route'], sort_keys=True)}`; "
              f"candidate eligible={h5['candidate_eligible']}; executed={h5['candidate_executed']}; "
              f"reason: {h5['eligibility_reason']}.", "",
              f"Quarantine: {report['quarantined_units']} known-defect units excluded; "
              f"{report['quarantine_inventory_files']} inventoried quarantine files."]
    for name, entry in report["quarantine"].items():
        lines.append(f"- `{name}`: known parser/producer defect, not an accepted unit; "
                     f"obs.meta.json SHA-256 `{entry['obs_meta_json_sha256']}`; "
                     f"server.log SHA-256 `{entry['server_log_sha256']}`; "
                     f"source `remote-inventory.tsv` ({len(entry['inventory']['paths'])} files).")
    lines += ["", "## Interpretation"]
    lines.extend(f"- {key}: {value}" for key, value in report["interpretation"].items())
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--text", dest="text_path", type=Path)
    parser.add_argument("--context", type=Path, help="optional preserved execution/provenance authority JSON")
    parser.add_argument("--require-complete", action="store_true",
                        help="refuse final publication while required A4 evidence is absent")
    args = parser.parse_args(argv)
    try:
        context = _read_json(args.context) if args.context else None
        report = reduce_evidence(args.evidence_root, context, require_complete=args.require_complete)
    except ReportError as exc:
        print(f"issue262-report: refusing: {exc}", file=sys.stderr)
        return 2
    encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.json_path:
        args.json_path.write_text(encoded, encoding="utf-8")
    if args.text_path:
        args.text_path.write_text(render(report), encoding="utf-8")
    if not args.json_path and not args.text_path:
        print(encoded, end="")
        print(render(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
