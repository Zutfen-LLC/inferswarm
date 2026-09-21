#!/usr/bin/env python3
"""Issue #234 — R8-H matched-arm deterministic reduction (schema /2).

Re-derives every condition from PRIMARY RAW BYTES retained under the
evidence root; authored status/comparison/exact/first_divergence fields
are NEVER trusted (issue #9). For each (arm, case) the reducer consumes
only retained raw candidate observations:

  * generated token IDs (response["tokens"]);
  * stop type / semantics;

and mechanically re-derives repeat equality, determinism, pairwise
A<->B / B<->C / A<->C token+stop relations, first divergent position,
and the terminal from the CORRECTED vocabulary. Mutation of authored
comparison/status fields must not change the terminal.

Terminal vocabulary (corrected):
  R8H_QWEN38_MATCHED_BACKEND_DEVICE_PARITY_PASS
  R8H_QWEN38_VULKAN_BACKEND_DIVERGENCE_CHARACTERIZED
  R8H_QWEN38_VULKAN_DEVICE_DIVERGENCE_CHARACTERIZED
  R8H_QWEN38_MULTI_AXIS_DIVERGENCE_CHARACTERIZED
  R8H_QWEN38_VULKAN_PLATFORM_FAIL
  R8H_QWEN38_VULKAN_RUNTIME_PREREQUISITE
  R8H_QWEN38_BACKING_PREREQUISITE
  R8H_EVIDENCE_BLOCKED

R8H_QWEN38_VULKAN_CORRECTNESS_FAIL is RETIRED and can never be emitted.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import issue234_receipt as rc

TERMINAL_PARITY_PASS = "R8H_QWEN38_MATCHED_BACKEND_DEVICE_PARITY_PASS"
TERMINAL_BACKEND_DIV = "R8H_QWEN38_VULKAN_BACKEND_DIVERGENCE_CHARACTERIZED"
TERMINAL_DEVICE_DIV = "R8H_QWEN38_VULKAN_DEVICE_DIVERGENCE_CHARACTERIZED"
TERMINAL_MULTI_AXIS = "R8H_QWEN38_MULTI_AXIS_DIVERGENCE_CHARACTERIZED"
TERMINAL_PLATFORM_FAIL = "R8H_QWEN38_VULKAN_PLATFORM_FAIL"
TERMINAL_RUNTIME_PREREQ = "R8H_QWEN38_VULKAN_RUNTIME_PREREQUISITE"
TERMINAL_BACKING_PREREQ = "R8H_QWEN38_BACKING_PREREQUISITE"
TERMINAL_BLOCKED = "R8H_EVIDENCE_BLOCKED"
RETIRED_TERMINAL = "R8H_QWEN38_VULKAN_CORRECTNESS_FAIL"

ALL_TERMINALS = (
    TERMINAL_PARITY_PASS, TERMINAL_BACKEND_DIV, TERMINAL_DEVICE_DIV,
    TERMINAL_MULTI_AXIS, TERMINAL_PLATFORM_FAIL, TERMINAL_RUNTIME_PREREQ,
    TERMINAL_BACKING_PREREQ, TERMINAL_BLOCKED,
)


class ReduceError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ReduceError(f"evidence input missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# -----------------------------------------------------------------------
# Raw-observation extraction (never authored summaries)
# -----------------------------------------------------------------------

def arm_case_repeats(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract raw observations from one ladder-{arm}-{case} receipt."""
    reps = doc.get("repeats", [])
    out = []
    for r in reps:
        raw = r.get("raw_response", {})
        tokens = raw.get("tokens")
        if not isinstance(tokens, list):
            tokens = r.get("generated_tokens")  # ladder-emitted copy
        out.append({
            "repeat": r.get("repeat"),
            "tokens": tokens,
            "stop_type": raw.get("stop_type", r.get("stop_type")),
        })
    return out


def repeat_integrity(reps: list[dict[str, Any]]) -> dict[str, Any]:
    """Exactly 3 repeats, IDs {1,2,3}, no dup/missing (issue #10)."""
    ids = [r.get("repeat") for r in reps]
    problems: list[str] = []
    want = sorted(i for i in rc.REQUIRED_REPEAT_IDS)
    got = sorted(i for i in ids if i is not None)
    if got != want:
        problems.append(f"repeat_ids:{got}")
    return {
        "count": len(reps),
        "ids": sorted(x for x in ids if x is not None),
        "ok": not problems,
        "problems": problems,
    }


def determinism(reps: list[dict[str, Any]]) -> dict[str, Any]:
    toks = [tuple(r["tokens"] or []) for r in reps]
    stops = [r["stop_type"] for r in reps]
    tok_ok = all(t == toks[0] for t in toks) if toks else False
    stop_ok = all(s == stops[0] for s in stops) if stops else False
    return {"deterministic": bool(tok_ok and stop_ok and toks),
            "tokens_identical": tok_ok, "stops_identical": stop_ok}


def pairwise(x: dict[str, Any], y: dict[str, Any]) -> dict[str, Any]:
    """Raw pairwise relation between two arms' first-repeat streams."""
    xt, yt = x["tokens"] or [], y["tokens"] or []
    tok_eq = xt == yt
    stop_eq = x["stop_type"] == y["stop_type"]
    first_div = None
    if not tok_eq:
        for i, (a, b) in enumerate(zip(xt, yt)):
            if a != b:
                first_div = {"position": i, "left": a, "right": b}
                break
        if first_div is None:
            first_div = {"position": min(len(xt), len(yt)),
                         "left": xt[len(yt):] or None,
                         "right": yt[len(xt):] or None}
    return {"tokens_equal": tok_eq, "stop_equal": stop_eq,
            "exact": tok_eq and stop_eq, "first_divergence": first_div}


# -----------------------------------------------------------------------
# Evidence dimension reducers
# -----------------------------------------------------------------------

def reduce_authority(evidence: Path) -> dict[str, Any]:
    doc = _load(evidence / "PHYSICAL-AUTHORITY.json")
    if doc.get("campaign") != rc.CAMPAIGN_ID:
        raise ReduceError("authority campaign mismatch")
    if doc.get("runtime_authority", {}).get("llama_cpp_pin") != \
            rc.LLAMA_CPP_PIN:
        raise ReduceError("runtime pin drift")
    if doc.get("fixture_ladder", {}).get("sha256") != rc.R8D_FIXTURE_SHA256:
        raise ReduceError("fixture identity drift")
    ma = doc.get("model_authority", {})
    if ma.get("official_qwen_revision") != rc.OFFICIAL_QWEN_REVISION:
        raise ReduceError("official Qwen revision drift (control 1)")
    if ma.get("unsloth_revision") != rc.UNSLOTH_REVISION:
        raise ReduceError("Unsloth conversion revision drift (control 2)")
    members = ma.get("members", [])
    if len(members) != len(rc.MODEL_MEMBERS):
        raise ReduceError("model member count drift (control 3)")
    for want, got in zip(rc.MODEL_MEMBERS, members):
        if (got.get("member") != want["member"]
                or got.get("sha256") != want["sha256"]
                or got.get("bytes") != want["bytes"]):
            raise ReduceError(f"model member drift (control 3): "
                              f"{want['member']}")
    return doc


def reduce_backing(evidence: Path) -> dict[str, Any]:
    out = {}
    for arm in ("A", "B", "C"):
        p = evidence / "backing" / f"arm{arm}-backing.json"
        if not p.is_file():
            out[arm] = {"status": "ABSENT"}
            continue
        doc = _load(p)
        members = doc.get("members", [])
        ok = len(members) == len(rc.MODEL_MEMBERS)
        if ok:
            for want, got in zip(rc.MODEL_MEMBERS, members):
                if (got.get("member") != want["member"]
                        or got.get("sha256") != want["sha256"]
                        or got.get("bytes") != want["bytes"]
                        or got.get("sha256_ok") is not True):
                    ok = False
                    break
        total = sum(m.get("bytes", 0) for m in members)
        out[arm] = {
            "status": "VERIFIED" if ok and total == rc.TOTAL_MODEL_BYTES
            else "MISMATCH",
            "total_bytes": total,
            "host": doc.get("host"),
        }
    return out


def reduce_runtime(evidence: Path) -> dict[str, Any]:
    out = {}
    for arm, rel in (("A", "runtime/armA-runtime.json"),
                     ("B", "runtime/armB-runtime.json"),
                     ("C", "runtime/armC-runtime.json")):
        p = evidence / rel
        if not p.is_file():
            out[arm] = {"status": "ABSENT"}
            continue
        doc = _load(p)
        problems = []
        if doc.get("source", {}).get("revision") != rc.LLAMA_CPP_PIN:
            problems.append("source_revision")
        if doc.get("source", {}).get("clean") is not True:
            problems.append("dirty_source")
        want_vk = "ON" if arm in ("B", "C") else "OFF"
        want_cu = "ON" if arm == "A" else "OFF"
        flags = doc.get("build", {}).get("cmake_flags", {})
        if (flags.get("GGML_VULKAN"), flags.get("GGML_CUDA")) != \
                (want_vk, want_cu):
            problems.append("backend_flags")
        if doc.get("binaries", {}).get("llama-server", {}).get("sha256") \
                is None:
            problems.append("no_binary_hash")
        out[arm] = {"status": "PREREQUISITE" if problems else "QUALIFIED",
                    "problems": problems,
                    "binary_sha256": doc.get("binaries", {})
                    .get("llama-server", {}).get("sha256")}
    return out


def reduce_placement(evidence: Path) -> dict[str, Any]:
    out = {}
    for arm in ("A", "B", "C"):
        p = evidence / "placement" / f"arm{arm}-placement.json"
        if not p.is_file():
            out[arm] = {"status": "ABSENT"}
            continue
        doc = _load(p)
        problems = []
        res = doc.get("residency", {})
        sel_delta = res.get("selected", {}).get("delta", {})
        sel_bytes = max([_bytes_of(k, v)
                         for k, v in sel_delta.items()] or [0])
        if not doc.get("loaded"):
            problems.append("model_did_not_load")
        if sel_bytes <= 0:
            problems.append("zero_selected_residency")
        for ex, deltas in (res.get("excluded") or {}).items():
            exb = max([_bytes_of(k, v) for k, v in deltas.items()] or [0])
            if exb >= rc.EXCLUDED_DEVICE_MAX_BYTES:
                problems.append(f"excluded_active:{ex}")
        post = doc.get("post_exit", {})
        if post.get("exit_code") != 0:
            problems.append(f"exit:{post.get('exit_code')}")
        out[arm] = {"status": "ILLEGAL" if problems else "LEGAL",
                    "problems": problems,
                    "selected_delta_bytes": sel_bytes,
                    "ngl": doc.get("geometry", {}).get("ngl")}
    return out


def _bytes_of(key: str, v: int) -> int:
    return v * 1024 * 1024 if key.endswith("_mib") else v


def reduce_ladder(evidence: Path) -> dict[str, Any]:
    """Per-case, per-arm raw reduction + pairwise relations.

    Also verifies, from retained evidence (never trusting authored
    outcomes): each executed arm-case doc binds the frozen request
    contract, fixture identity, ngl, context, model members, and prompt
    length; all three arms of a case share IDENTICAL geometry (control
    30); executed cases form a ladder prefix (controls 23/35)."""
    authority = _load(evidence / "PHYSICAL-AUTHORITY.json")
    prompt_lens = authority["fixture_ladder"]["prompt_lengths"]
    cases: dict[str, Any] = {}
    for case_id in rc.LADDER_CASES:
        centry: dict[str, Any] = {"arms": {}, "executed": True}
        geometries = []
        for arm in ("A", "B", "C"):
            p = evidence / "candidate" / f"ladder-{arm}-{case_id}.json"
            if not p.is_file():
                centry["arms"][arm] = {"status": "NOT_EXECUTED"}
                centry["executed"] = False
                continue
            doc = _load(p)
            geo = doc.get("geometry", {})
            problems = []
            if geo.get("ngl") != rc.MATCHED_NGL:
                problems.append(f"ngl:{geo.get('ngl')}")
            if geo.get("ctx") != rc.CONTEXT_SETTINGS:
                problems.append("context")
            req = geo.get("request", {})
            if req.get("samplers") != rc.REQUEST_CONTRACT["samplers"]:
                problems.append(f"samplers:{req.get('samplers')}")
            if req.get("top_k") != 1:
                problems.append(f"top_k:{req.get('top_k')}")
            if doc.get("fixture_sha256") != rc.R8D_FIXTURE_SHA256:
                problems.append("fixture_identity")
            if doc.get("prompt_len") != prompt_lens.get(case_id):
                problems.append(f"prompt_len:{doc.get('prompt_len')}")
            if len(doc.get("model_members", [])) != len(rc.MODEL_MEMBERS):
                problems.append("model_members")
            if problems:
                raise ReduceError(
                    f"{arm}/{case_id} geometry contract violation: "
                    f"{problems}")
            geometries.append(geo)
            reps = arm_case_repeats(doc)
            integ = repeat_integrity(reps)
            det = determinism(reps) if integ["ok"] else \
                {"deterministic": False}
            centry["arms"][arm] = {
                "status": "EXECUTED",
                "repeats": integ,
                "determinism": det,
                "tokens": reps[0]["tokens"] if reps else None,
                "stop_type": reps[0]["stop_type"] if reps else None,
            }
        if centry["executed"]:
            if any(g != geometries[0] for g in geometries):
                raise ReduceError(
                    f"{case_id}: arms do not share identical geometry "
                    "(control 30)")
            a, b, c = (centry["arms"][x] for x in ("A", "B", "C"))
            centry["pairwise"] = {
                "AB": pairwise(a, b), "BC": pairwise(b, c),
                "AC": pairwise(a, c)}
            centry["all_deterministic"] = all(
                x["determinism"]["deterministic"] for x in (a, b, c))
            centry["all_repeats_ok"] = all(
                x["repeats"]["ok"] for x in (a, b, c))
        cases[case_id] = centry
    # executed cases must form a ladder prefix
    executed = [c for c in rc.LADDER_CASES if cases[c].get("executed")]
    if executed and executed != list(rc.LADDER_CASES[:len(executed)]):
        raise ReduceError(
            f"ladder prefix violation (controls 23/35): executed "
            f"{executed}")
    return {"cases": cases}


def reduce_health(evidence: Path) -> dict[str, Any]:
    out = {}
    for arm in ("A", "B", "C"):
        stops: list[str] = []
        docs = []
        for p in sorted((evidence / "candidate").glob(
                f"ladder-{arm}-*.json")):
            doc = _load(p)
            docs.append(p.name)
            for r in doc.get("repeats", []):
                stops += r.get("health_window", {}).get(
                    "stop_classes", []) or []
            stops += doc.get("post_exit", {}).get(
                "journal_final_stop_classes", []) or []
        pf = evidence / "platform" / f"arm{arm}-platform.json"
        if pf.is_file():
            pd = _load(pf)
            stops += pd.get("stop_classes", []) or []
        out[arm] = {"status": "CLEAN" if not stops else "FAULT",
                    "stop_classes": sorted(set(stops)),
                    "sources": docs}
    return out


def reduce_execution_truth(evidence: Path) -> dict[str, Any]:
    """Per-arm mechanical execution truth from raw bytes (issue #11).

    Includes the DURING-generation excluded-device bound (controls
    9/10/36): every repeat's excluded devices must stay under the
    frozen noise bound while the selected device carries residency."""
    out = {}
    freeze = None
    fz = evidence / "freeze" / "campaign-freeze.json"
    if fz.is_file():
        try:
            freeze = json.loads(fz.read_text(encoding="utf-8"))
        except rc.FreezeError:
            freeze = None
    for arm in ("A", "B", "C"):
        p = evidence / "runtime" / f"arm{arm}-runtime.json"
        if not p.is_file():
            out[arm] = {"status": "ABSENT"}
            continue
        doc = _load(p)
        problems = []
        backend = "cuda" if arm == "A" else "vulkan"
        sel = doc.get("selector", {})
        if arm == "A":
            if sel.get("vulkan_devices_present"):
                problems.append("vulkan_execution_in_cuda_arm")
        else:
            all_raw = doc.get("raw", {}).get("list_devices_all", "")
            if "CUDA" in all_raw:
                problems.append("cuda_execution_in_vulkan_arm")
        if freeze:
            f_gpu = (freeze.get("arms", {}).get(arm, {})
                     .get("gpu", {}))
            want_bdf = f_gpu.get("bdf")
            if want_bdf and want_bdf not in json.dumps(sel):
                problems.append("selector_not_bound_to_frozen_gpu")
        case_docs = sorted((evidence / "candidate").glob(
            f"ladder-{arm}-*.json"))
        sel_res_ok = False
        for cd in case_docs:
            d = _load(cd)
            for rep in d.get("repeats", []):
                pre = (rep.get("selected_residency", {})
                       .get("pre", {}))
                post = (rep.get("selected_residency", {})
                        .get("post", {}))
                if _residency_bytes(pre, post) > 0:
                    sel_res_ok = True
                for ex, snap in (rep.get("excluded_residency",
                                         {}) or {}).items():
                    for side in ("pre", "post"):
                        if _residency_bytes({}, snap.get(side, {})) >= \
                                rc.EXCLUDED_DEVICE_MAX_BYTES:
                            problems.append(
                                f"excluded_device_active_during_run:{ex}")
        if case_docs and not sel_res_ok:
            problems.append("no_selected_device_residency_during_run")
        out[arm] = {"status": "OK" if not problems else "FAIL",
                    "problems": problems, "backend": backend}
    return out


def _residency_bytes(pre: dict, post: dict) -> int:
    def best(d: dict) -> int:
        vals = []
        for k, v in d.items():
            if isinstance(v, int):
                vals.append(v * 1024 * 1024 if k.endswith("_mib") else v)
        return max(vals, default=0)
    return max(best(pre), best(post))


# -----------------------------------------------------------------------
# Terminal derivation
# -----------------------------------------------------------------------

def characterization_ok(evidence: Path, case_id: str) -> dict[str, Any]:
    """Required pre-choice score characterization for a divergent rung
    (issue #12 / control 33). Must bind the case, the first divergent
    position, and ALL THREE arms with the R8-E observation methodology
    and a non-perturbation proof."""
    p = evidence / "candidate" / f"score-characterization-{case_id}.json"
    if not p.is_file():
        return {"status": "ABSENT"}
    doc = _load(p)
    problems = []
    if doc.get("case_id") != case_id:
        problems.append("case_binding")
    arms = doc.get("arms", {})
    for arm in ("A", "B", "C"):
        a = arms.get(arm, {})
        if not a.get("top_k"):
            problems.append(f"arm{arm}:no_topk")
        if a.get("non_perturbation_identical") is not True:
            problems.append(f"arm{arm}:no_nonperturbation_proof")
    if doc.get("generated_position") is None:
        problems.append("no_generated_position")
    return {"status": "OK" if not problems else "INSUFFICIENT",
            "problems": problems}


def classify_pairwise(case: dict[str, Any]) -> str | None:
    """Corrected pairwise interpretation (issue #13)."""
    pw = case.get("pairwise")
    if not pw:
        return None
    ab, bc, ac = pw["AB"], pw["BC"], pw["AC"]
    if ab["exact"] and bc["exact"]:
        return "ALL_EQUAL"
    if not ab["exact"] and bc["exact"]:
        return "BACKEND_DIVERGENT"
    if ab["exact"] and not bc["exact"]:
        return "DEVICE_DIVERGENT"
    return "MULTI_AXIS"


def derive_terminal(evidence: Path, closure: dict[str, Any] | None = None
                    ) -> dict[str, Any]:
    basis: list[str] = []
    checks: dict[str, Any] = {}

    authority = reduce_authority(evidence)
    backing = reduce_backing(evidence)
    runtime = reduce_runtime(evidence)
    placement = reduce_placement(evidence)
    ladder = reduce_ladder(evidence)
    health_r = reduce_health(evidence)
    truth = reduce_execution_truth(evidence)

    checks["authority_ok"] = True
    checks["backing"] = backing
    checks["runtime"] = runtime
    checks["placement"] = placement
    checks["execution_truth"] = truth
    checks["health"] = health_r
    checks["ladder"] = {
        c: {
            "executed": v.get("executed"),
            "all_deterministic": v.get("all_deterministic"),
            "all_repeats_ok": v.get("all_repeats_ok"),
            "classification": classify_pairwise(v),
        } for c, v in ladder["cases"].items()}

    terminal: str
    # -- prerequisite / blocked layers (fail closed) --------------------
    if closure is not None and closure.get("schema") != \
            "inferswarm.r8h.producer-closure/2":
        terminal = TERMINAL_BLOCKED
        basis.append("corrected producer closure absent/invalid")
    elif any(v["status"] == "ABSENT" for v in backing.values()):
        terminal = TERMINAL_BACKING_PREREQ
        basis.append(f"backing absent: "
                     f"{[a for a, v in backing.items() if v['status']=='ABSENT']}")
    elif any(v["status"] == "MISMATCH" for v in backing.values()):
        terminal = TERMINAL_BACKING_PREREQ
        basis.append("backing hash mismatch")
    elif any(v["status"] in ("ABSENT", "PREREQUISITE")
             for v in runtime.values()):
        terminal = TERMINAL_RUNTIME_PREREQ
        basis.append(f"runtime: "
                     f"{ {a: v['status'] for a, v in runtime.items()} }")
    elif any(v["status"] in ("ABSENT", "ILLEGAL") for v in placement.values()):
        terminal = TERMINAL_RUNTIME_PREREQ
        basis.append(f"placement: "
                     f"{ {a: v.get('status') for a, v in placement.items()} }")
    elif any(v["status"] == "FAIL" for v in truth.values()):
        terminal = TERMINAL_BLOCKED
        basis.append(f"execution truth failure: "
                     f"{ {a: v.get('problems') for a, v in truth.items() if v['status']=='FAIL'} }")
    else:
        # -- adjudicate executed rungs in frozen order ------------------
        executed = [c for c in rc.LADDER_CASES
                    if ladder["cases"][c].get("executed")]
        if not executed:
            terminal = TERMINAL_BLOCKED
            basis.append("no matched-arm execution evidence")
        else:
            faults = {a: v for a, v in health_r.items()
                      if v["status"] == "FAULT"}
            first_case = executed[0]
            case = ladder["cases"][first_case]
            cls = classify_pairwise(case)
            # repeat/determinism gates
            if not case.get("all_repeats_ok"):
                terminal = TERMINAL_BLOCKED
                basis.append(f"{first_case}: incomplete repeats")
            elif not case.get("all_deterministic"):
                terminal = TERMINAL_BLOCKED
                basis.append(f"{first_case}: nondeterministic arm")
            elif faults:
                terminal = TERMINAL_PLATFORM_FAIL
                basis.append(f"platform fault: "
                             f"{ {a: v['stop_classes'] for a, v in faults.items()} }")
            elif cls == "ALL_EQUAL":
                # every frozen rung executed and equal?
                all_rungs = (executed == list(rc.LADDER_CASES) and all(
                    ladder["cases"][c].get("executed") and
                    classify_pairwise(ladder["cases"][c]) == "ALL_EQUAL"
                    for c in rc.LADDER_CASES))
                if all_rungs:
                    terminal = TERMINAL_PARITY_PASS
                    basis.append("all 4 rungs A==B==C deterministic, "
                                 "execution-truth + platform clean")
                else:
                    # ladder incomplete (escalation stopped by controller
                    # or evidence gap) — blocked, not PASS
                    terminal = TERMINAL_BLOCKED
                    basis.append(f"parity at {executed} but ladder "
                                 "incomplete for PASS")
            elif cls == "BACKEND_DIVERGENT":
                char = characterization_ok(evidence, first_case)
                checks["score_characterization"] = char
                if char["status"] != "OK":
                    terminal = TERMINAL_BLOCKED
                    basis.append(
                        f"{first_case}: A!=B, B==C but required score "
                        f"characterization {char['status']} "
                        f"{char.get('problems', [])}")
                else:
                    terminal = TERMINAL_BACKEND_DIV
                    basis.append(
                        f"{first_case}: A!=B, B==C (Vulkan differs from "
                        "CUDA on the same RTX 3060; NVIDIA/Vulkan and "
                        "AMD/Vulkan agree); score characterization "
                        "retained")
            elif cls == "DEVICE_DIVERGENT":
                char = characterization_ok(evidence, first_case)
                checks["score_characterization"] = char
                if char["status"] != "OK":
                    terminal = TERMINAL_BLOCKED
                    basis.append(
                        f"{first_case}: A==B, B!=C but required score "
                        f"characterization {char['status']} "
                        f"{char.get('problems', [])}")
                else:
                    terminal = TERMINAL_DEVICE_DIV
                    basis.append(
                        f"{first_case}: A==B, B!=C (same RTX 3060 agrees "
                        "across CUDA/Vulkan; V340L/Vulkan differs); "
                        "score characterization retained")
            else:
                char = characterization_ok(evidence, first_case)
                checks["score_characterization"] = char
                if char["status"] != "OK":
                    terminal = TERMINAL_BLOCKED
                    basis.append(
                        f"{first_case}: multi-axis pairwise map but "
                        f"required score characterization "
                        f"{char['status']} {char.get('problems', [])}")
                else:
                    terminal = TERMINAL_MULTI_AXIS
                    basis.append(f"{first_case}: multi-axis pairwise map: "
                                 f"{ {k: v['exact'] for k, v in case['pairwise'].items()} }; "
                                 "score characterization retained")

    # retired-terminal guard: can never be emitted
    assert terminal != RETIRED_TERMINAL

    doc = {
        "schema": "inferswarm.r8h.terminal-reduction/2",
        "campaign": rc.CAMPAIGN_ID,
        "terminal": terminal,
        "terminal_basis": basis,
        "checks": checks,
        "pairwise_map": {
            c: classify_pairwise(v) for c, v in ladder["cases"].items()},
        "external_anchor_note": (
            "R8-D streams retained as external anchor; they did not "
            "participate in terminal derivation."),
    }
    return doc


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="R8-H matched-arm deterministic reduction")
    ap.add_argument("--evidence", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    doc = derive_terminal(args.evidence)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(doc["terminal"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
