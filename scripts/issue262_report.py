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


def classify_units(units: list[dict]) -> str:
    return P.screen_class(units)


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


def a4_required(a5_contrast: bool) -> bool:
    if type(a5_contrast) is not bool:
        raise ReportError("A5 contrast must be a proven boolean")
    return not a5_contrast


def h5_candidate_eligibility(route: dict) -> bool:
    """Only retained output node coopmat2-dependent paths admit candidate."""
    if not isinstance(route, dict):
        raise ReportError("missing retained BASE H5 route")
    # The accepted H5 parser's route objects bind output projection by node
    # identity and state whether this exact dispatch uses coopmat2.
    if route.get("node") != "result.output" or not route.get("coopmat2"):
        raise ReportError("BASE output path proves H5_CANDIDATE is not live")
    return True


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
    target = h2h3.get("target")
    selected = []
    if target:
        buffer_marker = f"|buffer={target['buffer']}|"
        for number, line in enumerate(log.decode("utf-8", errors="strict").splitlines(), 1):
            if (("ggml_vk_i260:v1|memory|role=backend|" in line and buffer_marker in line)
                    or ("ggml_vk_i260:v1|tensor|name=output.weight|" in line
                        and buffer_marker in line)):
                selected.append({"line": number, "text": line})
    h2h3["source_lines"] = selected
    h2h3["graphs"] = len(h2h3.get("graphs", []))
    h5_lines = _source_lines(log, ("ggml_vk_i262:v1|route|",))
    markers["h5"]["source_lines"] = h5_lines
    if arm != "A1" and not h2h3.get("target"):
        raise ReportError(f"missing parsed output.weight target: {path}")
    return {"unit_index": meta["unit_index"], "row_digest": digest,
            "server_log_sha256": log_hash, "log": log, "markers": markers,
            "source": {"unit_dir": path.name,
                       "unit_json_sha256": _sha((path / "unit.json").read_bytes()),
                       "server_log_sha256": log_hash}}


def reduce_evidence(root: Path) -> dict:
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
    base_target = arms["BASE"][0]["markers"]["h2h3"].get("target")
    a5_contrast = False
    if "A5" in arms:
        a5_target = arms["A5"][0]["markers"]["h2h3"].get("target")
        if base_target is None or a5_target is None:
            raise ReportError("H3 comparison requires retained BASE and A5 target")
        a5_contrast = compare_memory_choices({"target": base_target},
                                             {"target": a5_target})
    h3_pairs = []
    if "A5" in arms:
        for base_unit, a5_unit in zip(arms["BASE"], arms["A5"]):
            bt = base_unit["markers"]["h2h3"]["target"]
            at = a5_unit["markers"]["h2h3"]["target"]
            identity = {"baseline_unit": base_unit["unit_index"],
                        "intervention_arm": "A5", "intervention_unit": a5_unit["unit_index"],
                        "baseline_target": bt, "intervention_target": at,
                        "choice_changed": compare_memory_choices({"target": bt}, {"target": at})}
            identity["comparison_sha256"] = _sha(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
            h3_pairs.append(identity)
    a4_needed = a4_required(a5_contrast)
    a4_executed = "A4" in arms
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
        a4_contrast = compare_memory_choices(
            {"target": base_target},
            {"target": arms["A4"][0]["markers"]["h2h3"]["target"]})
        h3_status = "contrast-observed" if a4_contrast else "no-memory-choice-contrast"
    base_h5 = arms["BASE"][0]["markers"]["h5"]
    routes = base_h5.get("routes", {})
    output_route = routes.get("mat-vec") or routes.get("mat-mat")
    candidate_eligible = bool(output_route and output_route.get("family") != "mmv")
    if "H5_CANDIDATE" in arms and not candidate_eligible:
        raise ReportError("retained H5_CANDIDATE ran without live BASE contrast")
    quarantine_dirs = sorted(p for p in (root / "producer-defect-quarantine").iterdir()
                             if p.is_dir()) if (root / "producer-defect-quarantine").is_dir() else []
    quarantine_files = [name for name in inventory if name.startswith("producer-defect-quarantine/")]
    return {"schema": "inferswarm.issue262.retained-report/1",
            "evidence": {"root": str(root), "inventory": str(root.parent / "remote-inventory.tsv"),
                         "inventory_file_count": len(inventory),
                         "inventory_sha256": _sha((root.parent / "remote-inventory.tsv").read_bytes())},
            "arms": {arm: {"classification": classify_units(units),
                           "units": [{**{k: u[k] for k in ("unit_index", "row_digest", "source")},
                                      "h2h3": u["markers"]["h2h3"], "h5": u["markers"]["h5"]}
                                     for u in units]}
                     for arm, units in arms.items()},
            "h2": {"unit_observations": {arm: [{"unit_index": u["unit_index"],
                                                    "submission": u["markers"]["h2h3"].get("submission"),
                                                    "row_digest": u["row_digest"],
                                                    "source": u["source"]}
                                                   for u in units]
                                            for arm, units in arms.items()}},
            "h3": {"a5_target_choice_contrast": a5_contrast,
                   "a5_comparison_pairs": h3_pairs,
                   "a4_required": a4_needed, "a4_executed": a4_executed,
                   "a4_target_choice_contrast": a4_contrast, "status": h3_status},
            "h5": {"baseline_route": output_route,
                   "candidate_eligible": candidate_eligible,
                   "candidate_executed": "H5_CANDIDATE" in arms,
                   "mmv_control_live": candidate_eligible},
            "quarantined_units": len(quarantine_dirs),
            "quarantine_inventory_files": len(quarantine_files),
            "interpretation": {
                "h2": "serialized/normal observations are retained facts, not a numerical causal conclusion",
                "h3": "target memory-choice contrast is necessary, not terminal mechanism proof",
                "h5": "actual baseline route determines candidate eligibility; H5 is not established by capability alone",
                "mmv_control": "MMV/vector path has no live coopmat2 control",
                "screening": "screening-variable is not terminal causal proof; retain all completed units"}}


def render(report: dict) -> str:
    """Render prose only from reducer JSON; no additional observations inferred."""
    lines = ["Issue #262 retained pilot report (CPU-only)"]
    for arm, result in report["arms"].items():
        lines.append(f"{arm}: {result['classification']} ({len(result['units'])} retained units)")
    h3 = report["h3"]
    lines.append(f"H3: A5 target choice contrast={h3['a5_target_choice_contrast']}; A4 required={h3['a4_required']}; A4 executed={h3['a4_executed']}; status={h3['status']}.")
    h5 = report["h5"]
    lines.append(f"H5: baseline route={h5['baseline_route']}; candidate eligible={h5['candidate_eligible']}; executed={h5['candidate_executed']}.")
    lines.append(f"Quarantined units retained but excluded: {report['quarantined_units']}.")
    lines.extend(report["interpretation"].values())
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--text", dest="text_path", type=Path)
    args = parser.parse_args(argv)
    try:
        report = reduce_evidence(args.evidence_root)
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
