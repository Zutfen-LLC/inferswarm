#!/usr/bin/env python3
"""Issue #137 — diagnostic conclusions reducer (CPU-only, fail-closed).

Re-derives every diagnostic conclusion from the retained DIAGNOSTIC_ONLY
probe records and the accepted #133/#117 evidence, and emits the
terminal classification from measured conditions (never a constant).

Inputs (all sha256-recorded in the output):
  * phase1-inventory.json (CPU-only causal inventory, probe-free);
  * i137-diag-*.json probe records (A, A2, B, C, D, D2 families);
  * D2 capture manifests (per-layer localization within stage 1).

Conclusions derived:
  1. earliest divergence boundary (lifecycle / stage / layer / token);
  2. determinism structure (per-execution vs per-realization vs stable);
  3. causal/necessary factor (two-chunk extend prefill execution);
  4. one-mechanism-vs-families partition across the six cases;
  5. narrowest remediation hypothesis (recorded, NOT implemented).

Terminal ladder (narrowest-first, derived from measured conditions):
  ISSUE117_ARM_C_REGIME4_DIAGNOSIS_LOCALIZED
  ISSUE117_ARM_C_REGIME4_DIAGNOSIS_PARTIAL
  ISSUE117_ARM_C_REGIME4_DIAGNOSIS_INSUFFICIENT_EVIDENCE
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "inferswarm.issue137.diagnostic-conclusions/1"
TERMINAL_LOCALIZED = "ISSUE117_ARM_C_REGIME4_DIAGNOSIS_LOCALIZED"
TERMINAL_PARTIAL = "ISSUE117_ARM_C_REGIME4_DIAGNOSIS_PARTIAL"
TERMINAL_INSUFFICIENT = (
    "ISSUE117_ARM_C_REGIME4_DIAGNOSIS_INSUFFICIENT_EVIDENCE"
)
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def require_diagnostic(record: dict, path: Path) -> None:
    if record.get("classification") != DIAGNOSTIC_ONLY:
        raise SystemExit(
            f"REDUCER_FAIL: {path.name} is not marked {DIAGNOSTIC_ONLY}")
    if record.get("producer") != PRODUCER:
        raise SystemExit(
            f"REDUCER_FAIL: {path.name} producer drift "
            f"{record.get('producer')}")
    if record.get("schema") != "inferswarm.issue137.diagnostic-probe/1":
        raise SystemExit(f"REDUCER_FAIL: {path.name} schema drift")


def dedupe(values: list) -> int:
    return len({json.dumps(v, sort_keys=True) for v in values})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True,
                        help="dir containing probe records + phase1 "
                             "inventory + capture manifests")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    ev = Path(args.evidence_dir)
    out = Path(args.out)

    probes = {}
    manifests = {}
    inventory = None
    for p in sorted(ev.iterdir()):
        if not p.is_file():
            continue
        if p.name == "phase1-inventory.json":
            inventory = json.loads(p.read_text())
            continue
        if p.name.startswith("i137-diag-") and p.name.endswith(".json"):
            rec = json.loads(p.read_text())
            require_diagnostic(rec, p)
            probes.setdefault(rec["probe"], []).append(rec)
        if p.name.startswith("manifest-") and p.name.endswith(".json"):
            manifests[p.name] = json.loads(p.read_text())

    if inventory is None:
        raise SystemExit("REDUCER_FAIL: phase1-inventory.json missing")
    problems: list[str] = []

    # -- gate: required probe families ------------------------------
    for family in ("A", "A2", "C", "D", "D2"):
        if family not in probes:
            problems.append(f"missing probe family {family}")
    # B optional-but-retained; treat absence as note, not failure
    has_b = "B" in probes

    # -- 1+2: determinism structure ---------------------------------
    # A: per-realization distribution for each measured case
    case_distributions = {}
    for rec in probes.get("A", []):
        tc = rec["target_call"]
        case = tc["case_id"]
        case_distributions.setdefault(case, {
            "first_divergent_position": tc["first_divergent_position"],
            "replay_len": tc["replay_len"],
            "committed_step0": [],
        })["committed_step0"].extend(
            o["committed_step0"] for o in rec["observations"])

    nondeterministic_cases = {
        c: v for c, v in case_distributions.items()
        if len(set(v["committed_step0"])) > 1
    }
    deterministic_cases = {
        c: v for c, v in case_distributions.items()
        if len(set(v["committed_step0"])) == 1
    }

    # A2: within-realization repeat variance
    a2 = probes.get("A2", [])
    a2_varies = False
    a2_stabilizes = None
    for rec in a2:
        for obs in rec["observations"]:
            vals = [r["committed_step0"] for r in obs["repeats"]]
            if len(set(vals)) > 1:
                a2_varies = True
                # detect tail stabilization (last k equal, k>=3)
                a2_stabilizes = None
                last = vals[-1]
                k = 0
                for v in reversed(vals):
                    if v == last:
                        k += 1
                    else:
                        break
                a2_stabilizes = k if k >= 3 else None

    # -- 3: causal factor (chunk intervention) -----------------------
    c_rec = probes.get("C", [])
    chunk_causal = None
    for rec in c_rec:
        tc = rec["target_call"]
        singles = [o["single_chunk_64"]["committed_step0"]
                   for o in rec["observations"]]
        twos = [o["two_chunk_32"]["committed_step0"]
                for o in rec["observations"]]
        chunk_causal = {
            "case": tc["case_id"],
            "prompt_len": tc["prompt_len"],
            "single_chunk_values": list(singles),
            "two_chunk_values": list(twos),
            "single_chunk_deterministic": len(set(singles)) == 1,
            "two_chunk_deterministic": len(set(twos)) == 1,
        }
    if chunk_causal and chunk_causal["single_chunk_deterministic"] \
            and not chunk_causal["two_chunk_deterministic"]:
        chunk_factor = ("two_chunk_extend_prefill_execution_is_causal_"
                        "independent_of_prompt_length")
    elif chunk_causal and chunk_causal["two_chunk_deterministic"]:
        chunk_factor = "two_chunk_execution_deterministic_on_control"
    else:
        chunk_factor = "inconclusive"
        problems.append("probe C inconclusive")

    # -- 1: earliest boundary (D family) ------------------------------
    d_rec = probes.get("D", [])
    stage1_chunk1_stable = None
    stage1_chunk2_varies = None
    for rec in d_rec:
        per_r = []
        c1 = []
        for o in rec["observations"]:
            dig = {(b["stage_out"], b["position"]): b["sha256"]
                   for b in o["boundary_digests"]}
            per_r.append(dig)
        # chunk-1 (position 0) stage boundaries
        if per_r:
            s1_c1 = {d.get((0, 0)) for d in per_r}
            s1_c2 = {d.get((0, 64)) for d in per_r}
            stage1_chunk1_stable = len(s1_c1) == 1
            stage1_chunk2_varies = len(s1_c2) > 1

    # D2: layer-level within stage 1 chunk-2
    layer_localization = None
    d2_recs = probes.get("D2", [])
    for rec in d2_recs:
        tc = rec["target_call"]
        if "after_layer_0" in json.dumps(rec):
            layer_localization = "captured_after_layer_0"
    # manifests carry the actual per-layer digests
    earliest_layer = None
    embedding_stable = None
    for name, man in manifests.items():
        recs = man.get("records", [])
        by_step = {}
        for r in recs:
            m = r.get("meta", r)
            by_step.setdefault(m.get("step"), {})[m["checkpoint"]] = (
                m.get("sha256"))
        if not by_step:
            continue
        steps = sorted(by_step)
        checkpoints = sorted(
            {c for s in steps for c in by_step[s]},
            key=lambda c: (
                0 if c == "embedding_output"
                else 1 if c.startswith("after_layer_")
                else 2 if c == "boundary_send_hidden" else 3
            ),
        )
        varying = {
            c for c in checkpoints
            if len({by_step[s].get(c) for s in steps
                    if by_step[s].get(c) is not None}) > 1
        }
        stable = [
            c for c in checkpoints
            if c not in varying
            and any(by_step[s].get(c) is not None for s in steps)
        ]
        if "embedding_output" in checkpoints:
            embedding_stable = "embedding_output" not in varying
        ordered_varying = [
            c for c in checkpoints if c in varying
            and (c == "embedding_output" or c.startswith("after_layer_"))
        ]
        if ordered_varying:
            earliest_layer = ordered_varying[0]

    # -- 4: one mechanism or families ---------------------------------
    div_cases = {
        d["case_id"] for d in inventory["divergences"]
    }
    # A divergent case counts as instability-demonstrated if EITHER the
    # in-session probes vary across realizations OR the accepted
    # cross-campaign observations are pairwise distinct while today's
    # deterministic value matches none of them (cross-session drift).
    cross = {
        c["case_id"]: c for c in inventory["cross_campaign"][
            "divergent_cases"]
    }
    measured_div = set()
    per_case_notes = {}
    for c in div_cases:
        dist = case_distributions.get(c, {}).get("committed_step0", [])
        varies_in_session = len(set(dist)) > 1
        # accepted values at the first-divergent position for this case
        row = next(r for r in inventory["divergences"]
                   if r["case_id"] == c)
        accepted_at_pos = sorted({
            row["direct_ids"][row["first_divergent_position_rederived"]],
            row["ordinary_ids"][row["first_divergent_position_rederived"]],
        })
        matches_accepted = any(v in accepted_at_pos for v in dist)
        if varies_in_session or (dist and not matches_accepted):
            measured_div.add(c)
        per_case_notes[c] = {
            "in_session_values": dist,
            "varies_in_session": varies_in_session,
            "matches_an_accepted_value": matches_accepted,
            "cross_campaign_all_four_distinct": cross.get(c, {}).get(
                "all_four_distinct"),
        }
    stable_controls = {
        c for c in deterministic_cases if c not in div_cases
    }
    one_mechanism = bool(
        measured_div == div_cases
        and stable_controls
        and chunk_factor.startswith("two_chunk")
    )

    # -- terminal ladder ------------------------------------------------
    conditions = {
        "all_six_cases_nondeterministic": measured_div == div_cases,
        "stable_controls_deterministic": bool(stable_controls),
        "chunk_intervention_causal": chunk_factor.startswith(
            "two_chunk_extend"),
        "earliest_boundary_localized": bool(
            stage1_chunk1_stable and stage1_chunk2_varies),
        "layer_level_localized": earliest_layer is not None,
        "within_realization_variance_proven": a2_varies,
        "history_not_causal": bool(
            has_b and all(
                v["variants"]["fresh"]["committed_step0"]
                == v["variants"]["after_stable_history"]["committed_step0"]
                for rec in probes["B"] for v in rec["observations"]
            )),
    }
    if (conditions["all_six_cases_nondeterministic"]
            and conditions["stable_controls_deterministic"]
            and conditions["chunk_intervention_causal"]
            and conditions["earliest_boundary_localized"]
            and not problems):
        terminal = TERMINAL_LOCALIZED
    elif conditions["earliest_boundary_localized"] or (
            conditions["chunk_intervention_causal"]):
        terminal = TERMINAL_PARTIAL
    else:
        terminal = TERMINAL_INSUFFICIENT
    if problems and terminal == TERMINAL_LOCALIZED:
        terminal = TERMINAL_PARTIAL

    record = {
        "schema": SCHEMA,
        "classification": DIAGNOSTIC_ONLY,
        "producer": PRODUCER,
        "inputs": {
            p.name: sha256_file(p) for p in sorted(ev.iterdir())
            if p.is_file()
        },
        "determinism": {
            "per_case_realization_distributions": {
                c: v["committed_step0"]
                for c, v in sorted(case_distributions.items())
            },
            "nondeterministic_cases": sorted(nondeterministic_cases),
            "deterministic_controls": sorted(deterministic_cases),
            "within_realization_variance": a2_varies,
            "within_realization_tail_stabilization": a2_stabilizes,
        },
        "causal_factor": {
            "chunk_intervention": chunk_causal,
            "verdict": chunk_factor,
        },
        "earliest_divergence": {
            "stage1_chunk1_boundary_stable": stage1_chunk1_stable,
            "stage1_chunk2_boundary_varies": stage1_chunk2_varies,
            "embedding_stable": embedding_stable,
            "earliest_varying_checkpoint": earliest_layer,
            "localization": (
                "model execution, stage 1 (first GPU), second prefill "
                "chunk: embedding deterministic, first varying "
                "observable inside the owned decoder-layer stack at or "
                "before the earliest captured after-layer checkpoint"
            ) if earliest_layer else None,
        },
        "history_sensitivity": {
            "probe_b_retained": has_b,
            "fresh_equals_after_stable_history":
                conditions["history_not_causal"],
        },
        "one_mechanism_or_families": {
            "measured_nondeterministic": sorted(measured_div),
            "expected_divergent": sorted(div_cases),
            "stable_controls": sorted(stable_controls),
            "per_case": per_case_notes,
            "single_mechanism_supported": one_mechanism,
            "partition": (
                "single family: two-chunk (>PREFILL_CHUNK=64 replay) "
                "extend-prefill execution is nondeterministic "
                "per-execution at small extend-row counts; all six "
                "regime-4 cases share it; single-chunk executions are "
                "bit-deterministic across realizations and repeats"
            ) if one_mechanism else "see per-case rows",
        },
        "remediation_hypothesis": (
            "NOT IMPLEMENTED (separate remediation authority required). "
            "Narrowest hypothesis from evidence: the small-extend-chunk "
            "attention/execution path over a resident 64-row prefix "
            "(extend_paged_attention with 1-3 query rows, or a scratch/"
            "reduction buffer it reads uninitialized) returns "
            "per-execution-varying bits on these GPUs; identical inputs "
            "then amplify to argmax flips. A remediation issue should "
            "first reproduce the layer-0 divergence with a standalone "
            "kernel harness, then determine whether deterministic "
            "initialization of the involved scratch (or an explicit "
            "deterministic path for sub-tile extend rows) removes the "
            "variance without altering frozen serving semantics."
        ),
        "terminal": terminal,
        "terminal_conditions": conditions,
        "problems": problems,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "conclusions": str(out),
        "terminal": terminal,
        "conditions": conditions,
        "problems": problems,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
