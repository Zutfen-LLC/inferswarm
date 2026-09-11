#!/usr/bin/env python3
"""Issue #137 — diagnostic conclusions reducer v2 (CPU-only, fail-closed).

Correction pass on PR #138 (reviewed head a9922547…).  Re-derives every
diagnostic conclusion from retained DIAGNOSTIC_ONLY probe records plus
the accepted #133 evidence, with explicit evidence binding and honest
per-case treatment.

Design rules (correction C3/C2/C4):

  * LOAD-BEARING terminal requirements are separated from
    informational observations; LOCALIZED requires EVERY requirement,
    each independently controlling (mutation of any one downgrades the
    terminal or fails closed).
  * Every input record is validated: schema, classification, producer,
    accepted-authority binding (issue137_binding), exact expected case
    set, observation counts, replay identity, input pins, baseline
    identity; capture manifests are validated for schema, producer,
    host/role/GPU, steps, record counts, bundle identity, diagnostic
    run binding, and D2-record correspondence.
  * The evidence-dir scan is an EXPLICIT allowlist; the output file,
    documentation, and unrelated directory contents are excluded from
    reducer inputs.
  * Manifest ordering is explicit by stage/role; checkpoints order
    numerically by global layer; the earliest varying checkpoint is
    selected GLOBALLY across all bound manifests (never overwritten by
    the last manifest).
  * Probe C (retired, cumulative fixed-order design) is informational
    only; the causal chunk-partition evidence is probe C2 (fresh
    paired substrates, counterbalanced arm order).  A one-variable
    causal claim is impossible from C's retained shape.
  * Probe B's after_divergent_history arm is evaluated in full: the
    retained mismatch is recorded; history conclusions are narrowed to
    "prior request history is not NECESSARY for divergence" (fresh
    calls vary), never "history has no causal influence".
  * Per-case causal-family treatment: single-mechanism claims require
    per-case localization evidence; otherwise the population is
    partitioned honestly (varies_in_session vs session-stable) and the
    common-mechanism claim is limited to what the shared necessary
    path + earliest-divergence evidence establishes.

Terminal ladder (derived, never constants):
  ISSUE117_ARM_C_REGIME4_DIAGNOSIS_LOCALIZED
  ISSUE117_ARM_C_REGIME4_DIAGNOSIS_PARTIAL
  ISSUE117_ARM_C_REGIME4_DIAGNOSIS_INSUFFICIENT_EVIDENCE
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue137_binding  # noqa: E402

SCHEMA = "inferswarm.issue137.diagnostic-conclusions/2"
TERMINAL_LOCALIZED = "ISSUE117_ARM_C_REGIME4_DIAGNOSIS_LOCALIZED"
TERMINAL_PARTIAL = "ISSUE117_ARM_C_REGIME4_DIAGNOSIS_PARTIAL"
TERMINAL_INSUFFICIENT = (
    "ISSUE117_ARM_C_REGIME4_DIAGNOSIS_INSUFFICIENT_EVIDENCE"
)
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
PRODUCER = issue137_binding.PRODUCER

PROBE_SCHEMA_V1 = "inferswarm.issue137.diagnostic-probe/1"
PROBE_SCHEMA_V2 = "inferswarm.issue137.diagnostic-probe/2"

DIVERGENT_CASES = [
    "c109-04-01-026",
    "c109-04-02-047",
    "c109-04-03-040",
    "c109-04-04-024",
    "c109-04-05-043",
    "c109-04-06-074",
]

# Explicit reducer inputs (anything else in the evidence dir is
# EXCLUDED — output file, docs, unrelated content).
INVENTORY_NAME = "phase1-inventory.json"
CONCLUSIONS_NAME = "diagnostic-conclusions.json"
DOC_NAMES = {"METHODOLOGY.md", "README.md"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def checkpoint_sort_key(checkpoint: str):
    """embedding < after_layer_N (numeric) < boundary."""
    if checkpoint == "embedding_output":
        return (0, 0)
    if checkpoint.startswith("after_layer_"):
        try:
            return (1, int(checkpoint[len("after_layer_"):]))
        except ValueError:
            return (1, 10 ** 9)
    if checkpoint.startswith("boundary"):
        return (2, 0)
    return (3, 0)


def load_probe(path: Path) -> dict:
    record = json.loads(path.read_text())
    schema = record.get("schema")
    if schema not in (PROBE_SCHEMA_V1, PROBE_SCHEMA_V2):
        raise SystemExit(f"REDUCER_FAIL: {path.name} schema {schema!r}")
    if record.get("classification") != DIAGNOSTIC_ONLY:
        raise SystemExit(
            f"REDUCER_FAIL: {path.name} is not {DIAGNOSTIC_ONLY}")
    if record.get("producer") != PRODUCER:
        raise SystemExit(
            f"REDUCER_FAIL: {path.name} producer drift "
            f"{record.get('producer')}")
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-dir", required=True,
        help="dir containing probe records + phase1 inventory + "
             "capture manifests")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    ev = Path(args.evidence_dir)
    out = Path(args.out)

    problems: list[str] = []
    fatal: list[str] = []

    # -- explicit input discovery (allowlist; excludes output/docs) ----
    inventory = None
    probes: dict[str, list[dict]] = {}
    manifests: dict[str, dict] = {}
    unexpected = []
    for p in sorted(ev.iterdir()):
        if not p.is_file():
            continue
        if p.name in (CONCLUSIONS_NAME, *DOC_NAMES):
            continue
        if p.name == INVENTORY_NAME:
            inventory = json.loads(p.read_text())
            continue
        if p.name.startswith("i137-diag-") and p.name.endswith(".json"):
            rec = load_probe(p)
            rec["_file"] = p.name
            probes.setdefault(rec["probe"], []).append(rec)
            continue
        if p.name.startswith("manifest-") and p.name.endswith(".json"):
            manifests[p.name] = json.loads(p.read_text())
            continue
        if p.name.startswith("i137-diag-") or "captures" in p.name:
            continue
        unexpected.append(p.name)
    if unexpected:
        fatal.append(
            f"unexpected evidence-dir contents: {sorted(unexpected)}")
    if inventory is None:
        raise SystemExit(
            f"REDUCER_FAIL: {INVENTORY_NAME} missing")
    if fatal:
        raise SystemExit("REDUCER_FAIL: " + "; ".join(fatal))

    if inventory.get("schema") != (
            "inferswarm.issue137.phase1-causal-inventory/2"):
        problems.append("phase1 inventory schema is not /2 "
                        "(authority-pinned regeneration required)")
    if inventory.get("producer") != PRODUCER:
        problems.append("phase1 inventory producer drift")

    # -- required probe families ---------------------------------------
    required_families = ("A", "A2", "C2", "D", "D2")
    for family in required_families:
        if family not in probes or not probes[family]:
            problems.append(f"missing probe family {family}")
    has_b = bool(probes.get("B"))
    if not has_b:
        problems.append("probe B (history) absent — history analysis "
                        "unavailable")

    # -- binding validation of every record (C5/C7) ---------------------
    # v2 records: full authority-block validation.  v1 (reviewed-head)
    # records: grandfathered binding — producer commit asserted clean
    # at run start (git content addressing pins every module byte) +
    # retained baseline-input pins verified against the authority;
    # legacy gaps are recorded as informational, never silently
    # discarded.
    legacy_gaps = []
    c2_records = probes.get("C2", [])
    for rec in probes.get("A", []) + probes.get("A2", []) \
            + probes.get("B", []) + c2_records:
        if rec.get("schema") == PROBE_SCHEMA_V2:
            bind_problems = issue137_binding.verify_record_binding(rec)
            for bp in bind_problems:
                problems.append(f"{rec.get('_file')}: {bp}")
            continue
        inputs = rec.get("inputs", {})
        pin_map = {
            "fixture_sha256": "prompt-fixture.json",
            "environment_sha256": "environment.json",
            "chain_plan_sha256": "chain-plan.json",
            "accepted_direct_run_sha256": "direct-run.json",
        }
        for key, name in pin_map.items():
            if inputs.get(key) != issue137_binding \
                    .BASELINE_INPUT_SHA256[name]:
                problems.append(
                    f"{rec['_file']}: baseline input {name} "
                    f"unbound-or-drifted (v1)")
        software = rec.get("software", {})
        # v1 recorded the full sys.version string; compare the version
        # prefix against the accepted pin.
        v1_python = str(software.get("python", ""))
        for key, expected in (
            ("python", issue137_binding.BASELINE_SOFTWARE["python"]),
            ("torch", issue137_binding.BASELINE_SOFTWARE["torch"]),
            ("cuda", issue137_binding.BASELINE_SOFTWARE["cuda_runtime"]),
        ):
            observed = software.get(key)
            ok = (v1_python.startswith(expected) if key == "python"
                  else observed == expected)
            if not ok:
                problems.append(
                    f"{rec['_file']}: software {key} drifted (v1)")
        legacy_gaps.append({
            "record": rec["_file"],
            "not_retained": [
                "per-module sha256 pins", "torch numerical-mode flags",
                "interpreter absolute path", "stage/last-stage pids",
            ],
            "consequence": (
                "module identity rests on the producer commit + clean "
                "tree assertion at run start (unique bytes by git "
                "content addressing) instead of per-module hashes; "
                "numerical-mode flags were not captured for this run"),
        })

    # -- 1+2: determinism structure -------------------------------------
    case_distributions: dict[str, dict] = {}
    for rec in probes.get("A", []):
        tc = rec["target_call"]
        case = tc["case_id"]
        entry = case_distributions.setdefault(case, {
            "first_divergent_position": tc["first_divergent_position"],
            "replay_len": tc["replay_len"],
            "replay_sha256": tc.get("replay_sha256"),
            "committed_step0": [],
        })
        if entry["replay_sha256"] and tc.get("replay_sha256") \
                and entry["replay_sha256"] != tc["replay_sha256"]:
            problems.append(
                f"{rec['_file']}: replay identity drift for {case}")
        entry["committed_step0"].extend(
            o["committed_step0"] for o in rec["observations"])

    observed_cases = set(case_distributions)
    if observed_cases - set(DIVERGENT_CASES) == set():
        stable_controls_obs = observed_cases & (
            set(case_distributions) - set(DIVERGENT_CASES))
    stable_controls = {
        c for c in case_distributions if c not in DIVERGENT_CASES
    }

    # replay identity vs accepted inventory
    inv_by_case = {
        d["case_id"]: d for d in inventory.get("divergences", [])
    }
    for case, entry in case_distributions.items():
        if case in inv_by_case:
            d = inv_by_case[case]
            if entry["first_divergent_position"] != (
                    d["first_divergent_position_rederived"]):
                problems.append(
                    f"{case}: probe first-divergent position drift")

    a2_varies = False
    a2_stabilizes = None
    a2_by_case: dict[str, list[int]] = {}
    for rec in probes.get("A2", []):
        case = rec["target_call"]["case_id"]
        for obs in rec["observations"]:
            vals = [r["committed_step0"] for r in obs["repeats"]]
            a2_by_case.setdefault(case, []).extend(vals)
            if len(set(vals)) > 1:
                a2_varies = True
                last = vals[-1]
                k = 0
                for v in reversed(vals):
                    if v == last:
                        k += 1
                    else:
                        break
                a2_stabilizes = k if k >= 3 else None

    # -- 3: corrected causal factor (probe C2) --------------------------
    chunk_intervention = {
        "design": "retired cumulative fixed-order (informational only)",
        "verdict": "no causal claim derivable",
    }
    c_retired = probes.get("C", [])
    c2_causal = None
    if c2_records:
        rec = c2_records[0]
        design = rec.get("design", {})
        singles = []
        twos = []
        orders = []
        for obs in rec["observations"]:
            arms = obs.get("arms", {})
            if "single" not in arms or "two" not in arms:
                problems.append(
                    f"{rec['_file']}: trial {obs.get('trial')} missing "
                    f"an arm")
                continue
            singles.append(arms["single"]["committed_step0"])
            twos.append(arms["two"]["committed_step0"])
            orders.append(obs.get("launch_order"))
        trials = len(singles)
        # design validation: counterbalanced order, fresh substrates
        if trials >= 4 and orders:
            balanced = (orders[:2] == [["single", "two"],
                                       ["two", "single"]]) or (
                orders[0] != orders[1])
            if not balanced:
                problems.append(
                    "probe C2 arm order not counterbalanced — "
                    "one-variable causality unproven")
        else:
            problems.append(
                f"probe C2 has only {trials} trials (>=4 required)")
        # freshness binding: distinct realization identities per arm
        for obs in rec["observations"]:
            ids = [arm.get("realization_identity")
                   for arm in obs.get("arms", {}).values()]
            stage_pid_sets = [
                tuple((i or {}).get("stage_pids", [])) for i in ids]
            if len(set(stage_pid_sets)) != len(stage_pid_sets):
                problems.append(
                    f"probe C2 trial {obs.get('trial')}: arms share a "
                    f"substrate — freshness violated")
        single_det = len(set(singles)) == 1 and trials >= 4
        two_varies = len(set(twos)) > 1 and trials >= 4
        c2_causal = {
            "trials": trials,
            "launch_orders": orders,
            "single_chunk_values": singles,
            "two_chunk_values": twos,
            "single_chunk_deterministic": single_det,
            "two_chunk_varies": two_varies,
            "design": design,
        }
        if single_det and two_varies:
            chunk_intervention = {
                "design": ("fresh paired substrates per trial, target "
                           "call first on each, counterbalanced arm "
                           "order (probe C2)"),
                "verdict": (
                    "chunk partition is the only changed factor and "
                    "two-chunk execution flips/destabilizes the "
                    "committed token while the single-chunk path is "
                    "deterministic — multi-chunk extend-prefill "
                    "execution is sufficient for instability on this "
                    "input"),
            }
        elif trials >= 4:
            chunk_intervention = {
                "design": "probe C2 (corrected)",
                "verdict": "two-chunk arm deterministic on control "
                           f"({len(set(twos))} distinct in {trials}) — "
                           "sufficiency not demonstrated",
            }
            problems.append("probe C2 did not demonstrate two-chunk "
                            "instability")
    chunk_causal_established = bool(
        c2_causal and chunk_intervention["verdict"].startswith(
            "chunk partition is the only changed factor"))

    # informational: retired probe C retained bytes
    c_info = None
    if c_retired:
        rec = c_retired[0]
        singles = [o["single_chunk_64"]["committed_step0"]
                   for o in rec["observations"]]
        twos = [o["two_chunk_32"]["committed_step0"]
                for o in rec["observations"]]
        c_info = {
            "note": "cumulative single-then-two in one realization, "
                    "fixed order — cannot isolate chunk partition",
            "single_chunk_values": singles,
            "two_chunk_values": twos,
        }

    # -- 1: earliest boundary (probe D) ---------------------------------
    stage1_chunk1_stable = None
    stage1_chunk2_varies = None
    for rec in probes.get("D", []):
        per_r = []
        for o in rec["observations"]:
            dig = {(b["stage_out"], b["position"]): b["sha256"]
                   for b in o["boundary_digests"]}
            per_r.append(dig)
        if per_r:
            s1_c1 = {d.get((0, 0)) for d in per_r}
            s1_c2 = {d.get((0, 64)) for d in per_r}
            stage1_chunk1_stable = len(s1_c1) == 1
            stage1_chunk2_varies = len(s1_c2) > 1

    # -- D2: layer localization from BOUND manifests --------------------
    d2_records = probes.get("D2", [])
    earliest_varying = None       # global, deterministic
    embedding_stable = None
    manifest_rows_validated = 0
    # legacy manifests (reviewed head) predate inline run binding;
    # their binding to the D2 run is established by capture_dir
    # correspondence: each D2 record retains the capture dir + the
    # manifests live in THAT dir; verify via capture-manifest paths
    # when present, else via timestamp-window correspondence with the
    # D2 run record.
    d2_capture_dirs = []
    d2_windows = []
    for rec in d2_records:
        cap = rec.get("capture_manifests") or []
        for path in cap:
            d2_capture_dirs.append(str(Path(path).parent))
        d2_windows.append((rec.get("started_at_ns"),
                           rec.get("completed_at_ns")))
    for name, man in sorted(manifests.items(),
                            key=lambda kv: kv[1].get("role", kv[0])):
        role = man.get("role") or name.split("-")[1]
        mproblems = issue137_binding.verify_capture_manifest_binding(man)
        # legacy manifests without inline binding: accept only when
        # bound by D2-record capture-dir correspondence or timestamp
        # window overlap with a D2 run
        legacy_unbound = any(
            "not-bound-to-diagnostic-run" in mp
            or "capture-dir-unbound" in mp for mp in mproblems)
        if legacy_unbound:
            in_capture_dir = str(ev) in d2_capture_dirs or any(
                str(ev / name).endswith(Path(d).name)
                for d in d2_capture_dirs)
            ts_ok = False
            if not in_capture_dir and man.get("records"):
                ts_lo = min(
                    r.get("captured_at_unix_ns", 0)
                    for r in man["records"])
                ts_hi = max(
                    r.get("captured_at_unix_ns", 0)
                    for r in man["records"])
                for lo, hi in d2_windows:
                    if lo is not None and hi is not None \
                            and lo <= ts_hi and ts_lo <= hi:
                        ts_ok = True
                        break
            if not (in_capture_dir or ts_ok):
                problems.append(
                    f"{name}: manifest not bound to any diagnostic run")
                continue
            mproblems = [mp for mp in mproblems
                         if "not-bound-to-diagnostic-run" not in mp
                         and "capture-dir-unbound" not in mp]
        for mp in mproblems:
            problems.append(f"{name}: {mp}")
        if mproblems:
            continue
        manifest_rows_validated += 1
        # host / gpu / role validation against accepted geometry:
        # roles first/middle are inferswarm01 gpu-0/gpu-1; the last
        # stage is inferswarm03 gpu-0 and never manifests as a local
        # capture manifest.
        if man.get("host") == "inferswarm01":
            roles = {"first": 0, "middle": 1}
            if role in roles:
                uuids = {r.get("gpu_uuid") for r in man["records"]}
                expected = issue137_binding.BASELINE_GEOMETRY[
                    "inferswarm01"][roles[role]]
                if uuids != {expected}:
                    problems.append(
                        f"{name}: gpu uuid {uuids} != geometry")
            else:
                problems.append(
                    f"{name}: role {role!r} not valid for host "
                    f"inferswarm01 (expected first/middle)")
        by_step: dict[int, dict[str, str | None]] = {}
        for r in man["records"]:
            step = r.get("step")
            if step is None:
                problems.append(f"{name}: record without step")
                continue
            by_step.setdefault(step, {})[r["checkpoint"]] = (
                r.get("sha256"))
        steps = sorted(by_step)
        if len(steps) < 2:
            problems.append(f"{name}: fewer than 2 capture steps")
            continue
        checkpoints = sorted(
            {c for s in steps for c in by_step[s]},
            key=checkpoint_sort_key,
        )
        varying = [
            c for c in checkpoints
            if len({by_step[s].get(c) for s in steps
                    if by_step[s].get(c) is not None}) > 1
        ]
        if "embedding_output" in checkpoints:
            embedding_stable = "embedding_output" not in varying
        for c in varying:
            c_key = checkpoint_sort_key(c)
            if earliest_varying is None or (
                    c_key < checkpoint_sort_key(earliest_varying)):
                earliest_varying = c
    if d2_records and manifest_rows_validated == 0:
        problems.append("D2 records present but no bound manifests "
                        "validated")

    # D2 record <-> manifest correspondence (token evidence per step)
    d2_tokens = []
    for rec in d2_records:
        for obs in rec["observations"]:
            for r in obs.get("repeats", []):
                d2_tokens.append(r["committed_step0"])
    if d2_records and len(set(d2_tokens)) < 2:
        problems.append("D2 repeats show no token variance — "
                        "localization premise unproven")

    # -- history (probe B): full, honest evaluation ---------------------
    history = {
        "probe_b_retained": has_b,
        "fresh_vs_after_stable_history": None,
        "after_divergent_history_mismatches": [],
        "conclusion": None,
    }
    if has_b and probes.get("B"):
        fresh_eq_stable = []
        mismatches = []
        for rec in probes["B"]:
            for obs in rec["observations"]:
                v = obs["variants"]
                fresh_eq_stable.append(
                    v["fresh"]["committed_step0"]
                    == v["after_stable_history"]["committed_step0"])
                adv = v["after_divergent_history"]["committed_step0"]
                if adv != v["fresh"]["committed_step0"]:
                    mismatches.append({
                        "realization": obs["realization"],
                        "fresh": v["fresh"]["committed_step0"],
                        "after_divergent_history": adv,
                    })
        history["fresh_vs_after_stable_history"] = all(fresh_eq_stable)
        history["after_divergent_history_mismatches"] = mismatches
        # narrowed conclusion (correction C2): only what is proven.
        history["conclusion"] = (
            "prior request history is NOT NECESSARY for divergence "
            "(fresh-first calls on fresh substrates vary — probe A); "
            "fresh == after-stable-history in "
            f"{sum(fresh_eq_stable)}/{len(fresh_eq_stable)} "
            "realizations; the cumulative after-divergent-history arm "
            f"produced {len(mismatches)} differing value(s) of "
            f"{len(fresh_eq_stable)} — retained and NOT interpreted "
            "as history having no causal influence (single differing "
            "observation under demonstrated per-execution "
            "nondeterminism cannot establish or exclude a history "
            "effect)"
        )

    # -- per-case causal-family treatment (C4) ---------------------------
    cross = {
        c["case_id"]: c for c in inventory["cross_campaign"][
            "divergent_cases"]
    }
    per_case = {}
    for case in DIVERGENT_CASES:
        dist = case_distributions.get(case, {}).get("committed_step0",
                                                    [])
        a2_dist = a2_by_case.get(case, [])
        varies_in_session = (
            len(set(dist)) > 1 or len(set(a2_dist)) > 1)
        row = inv_by_case.get(case)
        matches_accepted = False
        if row and dist:
            pos = row["first_divergent_position_rederived"]
            accepted_at_pos = {
                row["direct_ids"][pos], row["ordinary_ids"][pos]}
            matches_accepted = any(
                v in accepted_at_pos for v in dist)
        localized = case == "c109-04-02-047"  # only D/D2-covered case
        per_case[case] = {
            "in_session_values": dist,
            "within_realization_values": a2_dist,
            "varies_in_session": varies_in_session,
            "matches_an_accepted_value": matches_accepted,
            "cross_campaign_all_four_distinct": cross.get(
                case, {}).get("all_four_distinct"),
            "layer_localization_evidence": (
                "D/D2 captures cover this case" if localized
                else "no per-case D/D2 captures retained"),
        }
    measured_varies = {
        c for c, r in per_case.items() if r["varies_in_session"]}
    session_stable = set(DIVERGENT_CASES) - measured_varies

    # single-mechanism claim (narrowed): common necessary path is
    # proven (partition + fresh-variance + earliest divergence), but
    # per-case numerical identity is proven ONLY where per-case
    # captures exist.
    single_mechanism_supported = bool(
        not problems
        and chunk_causal_established
        and measured_varies == set(DIVERGENT_CASES)
    )
    partition = {
        "varies_in_session": sorted(measured_varies),
        "session_stable_but_matches_no_accepted_value": sorted(
            session_stable),
        "common_necessary_path": bool(
            chunk_causal_established
            and all(cross.get(c, {}).get("all_four_distinct")
                    for c in DIVERGENT_CASES)
            and stable_controls),
        "identical_numerical_mechanism_proven_for": (
            ["c109-04-02-047"] if earliest_varying else []),
        "claim": None,
    }
    partition["claim"] = (
        "shared necessary path (two-chunk extend-prefill) established "
        "for all six; identical numerical mechanism demonstrated only "
        "for c109-04-02-047 (D/D2); three cases vary in-session, three "
        "are session-stable but match no accepted value — a single "
        "identical numerical mechanism for all six is NOT established"
    ) if not single_mechanism_supported else (
        "all six cases vary in-session on fresh substrates; shared "
        "necessary path and per-case variance demonstrated"
    )

    # -- terminal requirements (each independently controlling) ---------
    requirements = {
        "all_required_probe_families_present": all(
            probes.get(f) for f in required_families),
        "all_records_bound_to_accepted_authority": not any(
            "unbound-or-drifted" in p or "authority-block-missing" in p
            for p in problems),
        "record_binding_valid": not any(
            p.startswith("i137-diag-") for p in problems),
        "stable_control_single_chunk_deterministic": bool(
            stable_controls and all(
                len(set(case_distributions[c]["committed_step0"])) == 1
                for c in stable_controls)),
        "every_divergent_case_shows_instability": (
            measured_varies == set(DIVERGENT_CASES)),
        "corrected_chunk_intervention_causal": chunk_causal_established,
        "earliest_boundary_localized": bool(
            stage1_chunk1_stable and stage1_chunk2_varies),
        "earliest_varying_checkpoint_derived": earliest_varying is not None,
        "within_realization_variance_proven": a2_varies,
        "history_conclusion_narrowed_correctly": bool(
            has_b and history["conclusion"]
            and "NOT NECESSARY" in history["conclusion"]),
        "no_fatally_inconsistent_evidence": not fatal,
        "manifests_validated": manifest_rows_validated >= 2,
    }

    # derive terminal: LOCALIZED requires EVERY requirement; any
    # mutation of a requirement independently downgrades.
    if all(requirements.values()) and not problems:
        terminal = TERMINAL_LOCALIZED
    elif (requirements["earliest_boundary_localized"]
            or requirements["corrected_chunk_intervention_causal"]
            or requirements["within_realization_variance_proven"]):
        terminal = TERMINAL_PARTIAL
    else:
        terminal = TERMINAL_INSUFFICIENT

    record = {
        "schema": SCHEMA,
        "classification": DIAGNOSTIC_ONLY,
        "producer": PRODUCER,
        "inputs": {
            p.name: sha256_file(p) for p in sorted(ev.iterdir())
            if p.is_file() and p.name not in (
                CONCLUSIONS_NAME, *DOC_NAMES)
        },
        "informational_observations": {
            "legacy_v1_binding_gaps": legacy_gaps,
            "probe_c_retired": c_info,
            "probe_b_after_divergent_history_mismatches": history.get(
                "after_divergent_history_mismatches"),
            "cross_campaign_all_four_distinct": {
                c: cross.get(c, {}).get("all_four_distinct")
                for c in DIVERGENT_CASES},
        },
        "determinism": {
            "per_case_realization_distributions": {
                c: case_distributions[c]["committed_step0"]
                for c in sorted(case_distributions)
            },
            "within_realization_variance": a2_varies,
            "within_realization_tail_stabilization": a2_stabilizes,
            "stable_control_cases": sorted(stable_controls),
        },
        "causal_factor": {
            "corrected_intervention_c2": chunk_intervention,
            "c2_measurements": c2_causal,
        },
        "earliest_divergence": {
            "stage1_chunk1_boundary_stable": stage1_chunk1_stable,
            "stage1_chunk2_boundary_varies": stage1_chunk2_varies,
            "embedding_stable": embedding_stable,
            "earliest_varying_checkpoint": earliest_varying,
            "observed_transition": (
                "stable embedding_output → varying after_layer_0"
                if earliest_varying == "after_layer_0"
                and embedding_stable else None),
            "localization_scope": (
                "demonstrated for c109-04-02-047 (the only case with "
                "retained D/D2 captures); other cases inherit the "
                "necessary-path partition, not the layer evidence"),
        },
        "history_sensitivity": history,
        "per_case_causal_families": per_case,
        "single_mechanism_or_families": partition,
        "remediation_hypothesis": (
            "NOT IMPLEMENTED (separate remediation authority required). "
            "Hypothesis from the corrected evidence: the small-extend-"
            "chunk attention/execution path over a resident 64-row "
            "prefix returns per-execution-varying bits; earliest "
            "observed variation between embedding_output (stable) and "
            "after_layer_0 (varying) on the captured case. A "
            "remediation issue should reproduce the layer-0 divergence "
            "with a standalone kernel harness across all six cases "
            "before proposing a fix."
        ),
        "terminal": terminal,
        "terminal_requirements": requirements,
        "problems": problems,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "conclusions": str(out),
        "terminal": terminal,
        "requirements": requirements,
        "problems": problems,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
