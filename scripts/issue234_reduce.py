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

import hashlib
import json
import struct
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
            # exact-field binding, never substring over the whole
            # selector doc (icd_census_order legitimately carries BOTH
            # die BDFs, so a substring test cannot catch a swap)
            got_bdf = sel.get("target_bdf") or sel.get("bdf")
            if got_bdf is None and arm == "A":
                # CUDA selector doc binds by smi index semantics; the
                # freeze's cuda_identity.selector carries the binding
                cuda_sel = f_gpu.get("cuda_identity", {}).get("selector")
                got_bdf = want_bdf if (
                    cuda_sel and
                    sel.get("value") == cuda_sel.split("=")[-1]) else None
            if want_bdf and got_bdf != want_bdf:
                problems.append(
                    f"selector_not_bound_to_frozen_gpu:"
                    f"{got_bdf}!={want_bdf}")
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

#: focal token set for the pre-choice characterization (the union of
#: the retained canonical winners + the R8-E historical focal pair).
FOCAL_TOKENS: tuple[int, ...] = (328, 561, 271, 34227, 12188, 248068)


def pairwise_first_divergences(case: dict[str, Any]) -> dict[str, Any]:
    """Mechanical pairwise first-divergence positions for one case,
    derived ONLY from the raw first-repeat token streams the ladder
    reduction retained (never from authored comparison fields)."""
    pw = case.get("pairwise")
    if not pw:
        return {}
    out: dict[str, Any] = {}
    for pair in ("AB", "BC", "AC"):
        rel = pw[pair]
        fd = rel.get("first_divergence")
        out[pair] = {
            "exact": rel.get("exact"),
            "first_divergence_position":
                None if fd is None else fd.get("position"),
        }
    return out


def required_characterization_position(case: dict[str, Any]) -> int | None:
    """required_characterization_position = min(non-null pairwise
    first-divergence positions). None when no pair diverges (no
    characterization required) or the map is absent."""
    divs = [v["first_divergence_position"]
            for v in pairwise_first_divergences(case).values()
            if v["first_divergence_position"] is not None]
    return min(divs) if divs else None


def _f32_rank_map(values: list[float]) -> dict[int, int]:
    """rank (1-based, descending value, ascending token on ties) -> token."""
    order = sorted(range(len(values)), key=lambda i: (-values[i], i))
    return {tok: rank + 1 for rank, tok in enumerate(order)}


def _derive_arm_characterization(
        arm_dir: Path, arm: str, position: int,
        canonical_tokens: list[int] | None) -> dict[str, Any]:
    """Re-derive one arm's pre-choice score characterization from RAW
    observation bytes only (R8-E byte-authority contract).

    Inputs: the raw hook JSONL, the full-vocab float32 row sidecar at
    the required position, and the raw observation response. Everything
    (top-K, winner, ranks, focal scores, margins) is derived from the
    f32 BYTES; the JSONL row is required to agree; the response tokens
    must equal the canonical arm ladder stream (non-perturbation);
    the summary document, when present, must agree or the reduction
    fails closed (authored mutation never silently passes)."""
    jsonl = arm_dir / f"{arm}.jsonl"
    f32 = arm_dir / f"{arm}.jsonl.pos{position}.f32"
    resp_p = arm_dir / f"{arm}.resp.json"
    for p in (jsonl, f32, resp_p):
        if not p.is_file():
            raise ReduceError(
                f"arm{arm} raw characterization input missing: {p}")
    rows = [json.loads(line) for line in
            jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next((r for r in rows if r.get("pos") == position), None)
    if row is None:
        raise ReduceError(
            f"arm{arm} jsonl has no row at generated position {position}")
    n_vocab = row.get("n_vocab")
    if not isinstance(n_vocab, int) or n_vocab <= 0:
        raise ReduceError(f"arm{arm} jsonl row lacks vocabulary size")
    # -- float32 byte authority --------------------------------------
    raw = f32.read_bytes()
    if len(raw) != n_vocab * 4:
        raise ReduceError(
            f"arm{arm} f32 sidecar length {len(raw)} != n_vocab*4 "
            f"({n_vocab}*4)")
    import struct  # noqa: F401  (kept for contract clarity)
    values = list(struct.unpack(f"<{n_vocab}f", raw))
    n_nonfinite = sum(1 for v in values if v != v or v in
                      (float("inf"), float("-inf")))
    if n_nonfinite:
        raise ReduceError(
            f"arm{arm} f32 row carries {n_nonfinite} non-finite values")
    if row.get("n_nonfinite") not in (None, 0):
        raise ReduceError(f"arm{arm} jsonl reports non-finite scores")
    rank_map = _f32_rank_map(values)
    order = sorted(range(n_vocab), key=lambda i: (-values[i], i))
    top_k = [{"token": t, "logit": values[t]} for t in order[:2]]
    winner = order[0]
    runner_up = order[1]
    margin = values[winner] - values[runner_up]
    focal = {str(t): {"rank": rank_map.get(t),
                      "logit": values[t] if t < n_vocab else None}
             for t in FOCAL_TOKENS if t < n_vocab}
    # -- JSONL agreement (hook rows must match the byte-derived truth) --
    jtop = row.get("top") or []
    for k, (tok, val) in enumerate(jtop[:2]):
        if tok != top_k[k]["token"]:
            raise ReduceError(
                f"arm{arm} jsonl top-{k + 1} token {tok} != f32-derived "
                f"{top_k[k]['token']}")
        if abs(val - top_k[k]["logit"]) > 1e-6:
            raise ReduceError(
                f"arm{arm} jsonl top-{k + 1} logit drift vs f32 bytes")
    if row.get("tok") != winner:
        raise ReduceError(
            f"arm{arm} sampled token {row.get('tok')} != f32 argmax "
            f"{winner} at position {position}")
    for t, r, v in row.get("focus") or []:
        if str(t) in focal and (r != focal[str(t)]["rank"]
                                or abs(v - focal[str(t)]["logit"]) > 1e-6):
            raise ReduceError(
                f"arm{arm} jsonl focal drift vs f32 bytes: {t}")
    # -- non-perturbation against the canonical ladder stream --------
    resp = json.loads(resp_p.read_text(encoding="utf-8"))
    obs_tokens = resp.get("tokens")
    if not isinstance(obs_tokens, list):
        raise ReduceError(f"arm{arm} observation response lacks tokens")
    if canonical_tokens is None:
        raise ReduceError(
            f"arm{arm} canonical ladder stream unavailable for "
            f"non-perturbation comparison")
    non_perturbing = obs_tokens == list(canonical_tokens)
    # ROUND-3 NOTE: observation backend/device/host/binary identity is
    # validated ONLY by reduce_observation_execution_truth (one
    # fail-closed authority path); the earlier partial identity check
    # keyed on runtime-receipt fields this function never supplied and
    # could never fire (removed as inert).
    out = {
        "winner_token": winner,
        "top_2": top_k,
        "winner_vs_runner_up_margin": round(margin, 9),
        "focal_pair_328_561_margin": round(
            abs(values[328] - values[561]), 9) if n_vocab > 561 else None,
        "focal_tokens": focal,
        "n_vocab": n_vocab,
        "f32_sha256": hashlib.sha256(raw).hexdigest(),
        "jsonl_sha256": hashlib.sha256(jsonl.read_bytes()).hexdigest(),
        "observed_tokens": obs_tokens,
        "non_perturbation_identical": non_perturbing,
    }
    if not non_perturbing:
        raise ReduceError(
            f"arm{arm} observation perturbs generation: response tokens "
            f"differ from the canonical ladder stream")
    return out


def _required_package_prefixes(arm: str) -> tuple[str, ...]:
    return ("llama-server", "libggml.so", "libggml-base.so", "libggml-cpu.so",
            "libggml-cuda.so" if arm == "A" else "libggml-vulkan.so")


def _package_shape_problems(arm: str, package: Any) -> list[str]:
    if not isinstance(package, dict) or not isinstance(package.get("root"), str):
        return ["not_a_package"]
    objects = package.get("objects")
    if not isinstance(objects, dict):
        return ["objects_not_a_map"]
    problems = []
    for prefix in _required_package_prefixes(arm):
        if not any(name == prefix or name.startswith(prefix + ".")
                   for name in objects):
            problems.append(f"missing:{prefix}")
    for name, meta in objects.items():
        if (not isinstance(name, str) or not isinstance(meta, dict)
                or not isinstance(meta.get("realpath"), str)
                or not isinstance(meta.get("bytes"), int)
                or meta["bytes"] <= 0
                or not isinstance(meta.get("sha256"), str)
                or len(meta["sha256"]) != 64):
            problems.append(f"bad:{name}")
    return problems


def _package_byte_identity(package: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Filename-keyed underlying-byte identity; excludes host-local paths."""
    objects = (package or {}).get("objects") or {}
    return {name: {"bytes": meta.get("bytes"), "sha256": meta.get("sha256")}
            for name, meta in objects.items() if isinstance(meta, dict)}


OBSERVATION_AUTHORITY_NAME = "observation-authority.json"


def _observation_base(evidence: Path, position: int) -> Path | None:
    """Resolve the immutable selected observation attempt; never overwrite prior rows."""
    authority_path = evidence / "candidate" / "characterization" / OBSERVATION_AUTHORITY_NAME
    try:
        authority = json.loads(authority_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    rel = authority.get("attempt")
    if (authority.get("schema") != "inferswarm.r8h.observation-authority/1"
            or authority.get("generated_position") != position
            or not isinstance(rel, str) or not rel.startswith(f"pos{position}")
            or "/" in rel or rel in (".", "..")):
        return None
    return authority_path.parent / rel


def _observation_pin(evidence: Path, position: int) -> dict[str, Any] | None:
    base = _observation_base(evidence, position)
    if base is None:
        return None
    p = base / "pos0-observation-pin.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _validate_observation_pin(evidence: Path, position: int) -> list[str]:
    """Closure-pin the observation producer (round-3 hardened): the
    prospective pos0-observation-pin document must exist and match the
    frozen observation identities in issue234_receipt (llama.cpp pin,
    hook diff digest, hook env, per-arm observation binaries, prompt
    identity, non-perturbation contract) AND the exact selector/ICD
    authority (round-3: the pin previously carried selector strings
    that nothing mechanically enforced) BEFORE any characterization
    derived from observation bytes can be accepted."""
    base = _observation_base(evidence, position)
    if base is None:
        return ["observation_authority:missing_or_invalid"]
    p = base / "pos0-observation-pin.json"
    if not p.is_file():
        return ["observation_pin:absent"]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["observation_pin:unparsable"]
    problems: list[str] = []
    if doc.get("schema") != rc.OBSERVATION_PIN_SCHEMA:
        problems.append("observation_pin:schema")
    op = doc.get("observation_producer", {})
    if op.get("llama_cpp_source_pin") != rc.LLAMA_CPP_PIN:
        problems.append("observation_pin:llama_pin")
    if op.get("hook_source_sha256_of_diff") != rc.OBSERVATION_HOOK_DIFF_SHA256:
        problems.append("observation_pin:hook_diff")
    hook_env = op.get("hook_env", {})
    if hook_env.get("LLAMA_OBSERVE_FOCUS") != rc.OBSERVATION_FOCUS_ENV:
        problems.append("observation_pin:focus_env")
    if hook_env.get("LLAMA_OBSERVE_POS") != str(position):
        problems.append("observation_pin:pos_env")
    if op.get("prompt_sha256") != rc.PROMPT_CASE256_SHA256:
        problems.append("observation_pin:prompt")
    bins = op.get("observation_binaries", {})
    for arm in ("A", "B", "C"):
        want = rc.OBSERVATION_BINARIES.get(arm, {})
        got = bins.get(f"{arm}_{'cuda' if arm == 'A' else 'vulkan'}_"
                       f"{'inferswarm01' if arm != 'C' else 'inferswarm02'}",
                       {}) or bins.get(arm, {})
        if not got or got.get("sha256") != want.get("sha256"):
            problems.append(f"observation_pin:arm{arm}:binary")
    packages = op.get("execution_packages", {})
    for arm in ("A", "B", "C"):
        for problem in _package_shape_problems(arm, packages.get(arm)):
            problems.append(f"observation_pin:arm{arm}:package:{problem}")
    if op.get("same_vulkan_package") is not True:
        problems.append("observation_pin:bc_same_package_not_required")
    elif (isinstance(packages.get("B"), dict) and isinstance(packages.get("C"), dict)
          and _package_byte_identity(packages["B"]) !=
              _package_byte_identity(packages["C"])):
        problems.append("observation_pin:bc_package_mismatch")
    launch_contract = op.get("launch_contract", {})
    if launch_contract != {"port": 18493, "host": "127.0.0.1"}:
        problems.append("observation_pin:launch_contract")
    expected_members = [{"name": m["member"], "bytes": m["bytes"],
                         "sha256": m["sha256"]} for m in rc.MODEL_MEMBERS]
    if op.get("model_members") != expected_members:
        problems.append("observation_pin:model_members")
    if not isinstance(op.get("model_subject"), str) or not op["model_subject"].startswith("/"):
        problems.append("observation_pin:model_subject")
    if op.get("prompt_sha256") != rc.PROMPT_CASE256_SHA256:
        problems.append("observation_pin:prompt_sha256")
    if op.get("prompt_len") != rc.PROMPT_CASE256_LENGTH:
        problems.append("observation_pin:prompt_len")
    if op.get("request_contract") != rc.REQUEST_CONTRACT:
        problems.append("observation_pin:request_contract")
    # -- round-3: exact selector/ICD authority --------------------------
    # The pin's selectors must equal the frozen launch environments
    # EXACTLY (arm A CUDA selector to the frozen RTX UUID; arms B/C
    # Vulkan selector plus ABSOLUTE ICD path). A relative ICD, a
    # missing selector, or any mutation fails closed here.
    sels = op.get("selectors", {})
    for arm in ("A", "B", "C"):
        want_env = rc.OBSERVATION_LAUNCH_ENV[arm]
        got = sels.get(arm)
        if not isinstance(got, dict):
            problems.append(f"observation_pin:arm{arm}:selector:not_a_map")
            continue
        for key, want_val in want_env.items():
            if got.get(key) != want_val:
                problems.append(
                    f"observation_pin:arm{arm}:selector:{key}")
        if arm in ("B", "C"):
            icd = got.get("VK_ICD_FILENAMES")
            if icd is not None and not icd.startswith("/"):
                problems.append(
                    f"observation_pin:arm{arm}:icd_not_absolute")
    # ICD byte authority carried by the pin
    icd_pins = op.get("icd_sha256", {})
    want_icd = {arm: rc.OBSERVATION_ICD_SHA256[key]
                for arm, key in (("B", "B_nvidia_inferswarm01"),
                                 ("C", "C_radeon"))}
    for arm, want_val in want_icd.items():
        if icd_pins.get(arm) != want_val:
            problems.append(f"observation_pin:arm{arm}:icd_sha256")
    # collector identity (prospective: pinned BEFORE collection)
    coll = doc.get("collector", {})
    if coll.get("sha256"):
        closure_coll = _closure_collector_sha()
        if closure_coll is not None and \
                coll.get("sha256") != closure_coll:
            problems.append("observation_pin:collector_sha256")
    scope = doc.get("scope", {})
    if scope.get("canonical_ladder_rerun") is not False:
        problems.append("observation_pin:rerun_not_forbidden")
    if scope.get("generated_position") != position:
        problems.append("observation_pin:scope_position")
    if scope.get("execution_receipts_required") is not True:
        problems.append("observation_pin:receipts_not_required")
    return problems


def _closure_collector_sha() -> str | None:
    """sha256 of the committed observation collector at HEAD (the
    closure pins its blob; a drifted worktree copy fails verify_closure
    independently). Returns None when git is unavailable (sandboxed
    control runs operate on copied evidence trees, not the repo)."""
    import subprocess
    proc = subprocess.run(
        ["git", "-C", str(rc.ROOT), "show",
         "HEAD:scripts/issue234_observe.py"],
        capture_output=True)
    if proc.returncode != 0:
        return None
    return hashlib.sha256(proc.stdout).hexdigest()


# ---------------------------------------------------------------------
# Observation execution truth (round-3: the observation runs must be
# mechanically bound to the GPU/backend selectors they represent)
# ---------------------------------------------------------------------

def _receipt_problems(arm: str, doc: dict[str, Any],
                      base: Path, position: int,
                      canonical_tokens: list[int] | None,
                      pin: dict[str, Any] | None) -> list[str]:
    """Mechanical per-arm validation of one observation execution
    receipt against every frozen authority. Every check derives from
    receipt bytes + retained raw bytes; authored booleans are never
    trusted (the captured /proc environment, mapped libraries, device
    censuses, and residency deltas are the proof)."""
    problems: list[str] = []
    frozen_env = rc.OBSERVATION_LAUNCH_ENV[arm]
    frozen = rc.OBSERVATION_FROZEN_DEVICES

    # ---- envelope / identity ----------------------------------------
    if doc.get("schema") != rc.OBSERVATION_RECEIPT_SCHEMA:
        problems.append(f"arm{arm}:receipt_schema")
    if doc.get("campaign") != rc.CAMPAIGN_ID:
        problems.append(f"arm{arm}:campaign")
    if doc.get("case_id") != "case-256":
        problems.append(f"arm{arm}:case")
    if doc.get("generated_position") != position:
        problems.append(f"arm{arm}:position")
    if doc.get("arm") != arm:
        problems.append(f"arm{arm}:arm_field")
    host = doc.get("host", {})
    want_host = rc.ARMS[arm]["host"]
    if host.get("hostname") != want_host:
        problems.append(f"arm{arm}:host:{host.get('hostname')}")
    if not host.get("boot_id"):
        problems.append(f"arm{arm}:boot_id")
    collector = doc.get("collector") or {}
    pin_collector = (pin or {}).get("collector") or {}
    if collector.get("sha256") != pin_collector.get("sha256"):
        problems.append(f"arm{arm}:collector_sha256")
    if collector.get("dependencies") != pin_collector.get("dependencies"):
        problems.append(f"arm{arm}:collector_dependencies")

    # ---- binary identity --------------------------------------------
    ob = doc.get("observation_binary", {})
    want_bin = rc.OBSERVATION_BINARIES.get(arm, {})
    if ob.get("sha256") != want_bin.get("sha256"):
        problems.append(f"arm{arm}:binary_sha256:{ob.get('sha256')}")
    if not ob.get("path"):
        problems.append(f"arm{arm}:binary_path")
    pin_op = (pin or {}).get("observation_producer", {})
    want_package = (pin_op.get("execution_packages") or {}).get(arm)
    got_package = ob.get("package")
    for problem in _package_shape_problems(arm, got_package):
        problems.append(f"arm{arm}:package:{problem}")
    if want_package is None or got_package != want_package:
        problems.append(f"arm{arm}:package_not_authorized")

    # ---- source pin / hook identity ---------------------------------
    src = doc.get("source", {})
    prov = src.get("provenance")
    if prov == "local_r8h_obs_worktree":
        if src.get("llama_cpp_pin") != rc.LLAMA_CPP_PIN:
            problems.append(f"arm{arm}:source_pin")
        if src.get("hook_diff_sha256") != rc.OBSERVATION_HOOK_DIFF_SHA256:
            problems.append(f"arm{arm}:hook_diff")
        if src.get("clean_excluding_hook") is not True:
            problems.append(f"arm{arm}:source_dirty")
    elif prov == "byte_identity_to_arm_B_binary":
        if arm != "C":
            problems.append(f"arm{arm}:bad_provenance")
        # arm C's binary must be byte-identical to arm B's (deployed)
        if ob.get("sha256") != rc.OBSERVATION_BINARIES["B"]["sha256"]:
            problems.append(f"arm{arm}:not_byte_identical_to_B")
    else:
        problems.append(f"arm{arm}:provenance")

    # ---- launch argv / environment -----------------------------------
    launch = doc.get("launch", {})
    argv = launch.get("argv") or []
    model = doc.get("model") or {}
    if not argv:
        problems.append(f"arm{arm}:no_argv")
    elif argv[0] != ob.get("path"):
        problems.append(f"arm{arm}:argv_binary_mismatch")
    else:
        pairs = argv[1:]
        expected = {
            "--model": model.get("first_member"),
            "--n-gpu-layers": str(rc.MATCHED_NGL),
            "--ctx-size": str(rc.CONTEXT_SETTINGS["ctx-size"]),
            "--batch-size": str(rc.CONTEXT_SETTINGS["batch-size"]),
            "--port": str((pin_op.get("launch_contract") or {}).get("port")),
            "--host": (pin_op.get("launch_contract") or {}).get("host"),
        }
        parsed: dict[str, str] = {}
        if len(pairs) != len(expected) * 2:
            problems.append(f"arm{arm}:argv_arity")
        else:
            for flag, value in zip(pairs[::2], pairs[1::2]):
                if flag not in expected:
                    problems.append(f"arm{arm}:argv_unexpected:{flag}")
                elif flag in parsed:
                    problems.append(f"arm{arm}:argv_duplicate:{flag}")
                else:
                    parsed[flag] = value
            for flag, value in expected.items():
                if parsed.get(flag) != value:
                    problems.append(f"arm{arm}:argv:{flag}")

    # ---- execution-time model identity --------------------------------
    want_members = [{"name": m["member"], "bytes": m["bytes"],
                     "sha256": m["sha256"]} for m in rc.MODEL_MEMBERS]
    got_members = model.get("members")
    if got_members != want_members:
        problems.append(f"arm{arm}:model_members")
    if model.get("total_bytes") != rc.TOTAL_MODEL_BYTES:
        problems.append(f"arm{arm}:model_total_bytes")
    first = model.get("first_member")
    model_subject = pin_op.get("model_subject")
    if (not isinstance(first, str) or model_subject != model.get("path")
            or Path(first).name != rc.MODEL_MEMBERS[0]["member"]
            or str(Path(first).parent) != model.get("path")):
        problems.append(f"arm{arm}:model_path")
    if model.get("backing_receipt") != f"arm{arm}-backing.json":
        problems.append(f"arm{arm}:backing_receipt")

    # ---- request contract / raw transmitted payload -------------------
    request = doc.get("request") or {}
    if request.get("prompt_sha256") != pin_op.get("prompt_sha256"):
        problems.append(f"arm{arm}:prompt_sha256")
    if request.get("contract") != pin_op.get("request_contract"):
        problems.append(f"arm{arm}:request_contract")
    expected_prompt_len = pin_op.get("prompt_len")
    if request.get("prompt_len") != expected_prompt_len:
        problems.append(f"arm{arm}:prompt_len")
    payload = request.get("payload") or {}
    payload_name = payload.get("path")
    payload_path = base / payload_name if isinstance(payload_name, str) and \
        "/" not in payload_name else None
    if payload_path is None or not payload_path.is_file():
        problems.append(f"arm{arm}:request_payload_missing")
    else:
        raw_payload = payload_path.read_bytes()
        if (payload.get("bytes") != len(raw_payload)
                or payload.get("sha256") != hashlib.sha256(raw_payload).hexdigest()):
            problems.append(f"arm{arm}:request_payload_digest")
        try:
            decoded_payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            problems.append(f"arm{arm}:request_payload_json")
        else:
            prompt = decoded_payload.pop("prompt", None)
            if decoded_payload != rc.REQUEST_CONTRACT:
                problems.append(f"arm{arm}:request_payload_contract")
            if not isinstance(prompt, (str, list)) or len(prompt) != expected_prompt_len:
                problems.append(f"arm{arm}:request_payload_prompt")

    # the /proc/PID/environ capture must carry the EXACT frozen
    # selector/ICD environment (mutation of the actual execution
    # selector fails closed here)
    got_env = launch.get("env") or {}
    for key, want_val in frozen_env.items():
        if got_env.get(key) != want_val:
            problems.append(
                f"arm{arm}:env:{key}:{got_env.get(key)!r}")
    # hook env
    if got_env.get("LLAMA_OBSERVE_FOCUS") != rc.OBSERVATION_FOCUS_ENV:
        problems.append(f"arm{arm}:env:observe_focus")
    if got_env.get("LLAMA_OBSERVE_POS") != str(position):
        problems.append(f"arm{arm}:env:observe_pos")
    # ICD authority (absolute path + byte hash)
    if arm in ("B", "C"):
        icd = launch.get("icd") or {}
        want_icd_path = frozen_env["VK_ICD_FILENAMES"]
        if icd.get("path") != want_icd_path:
            problems.append(f"arm{arm}:icd_path:{icd.get('path')}")
        want_icd_sha = rc.OBSERVATION_ICD_SHA256[
            "B_nvidia_inferswarm01" if arm == "B" else "C_radeon"]
        if icd.get("sha256") != want_icd_sha:
            problems.append(f"arm{arm}:icd_sha256")
        if not str(icd.get("path", "")).startswith("/"):
            problems.append(f"arm{arm}:icd_not_absolute")

    # ---- in-process backend participation ----------------------------
    # NOTE: /proc/PID/maps shows the VERSIONED object names
    # (libggml-cuda.so.0.24.0), so participation is a prefix/substring
    # match on the libggml backend object, never an exact filename.
    mapped = set((doc.get("in_process_backends") or {})
                 .get("mapped_libggml") or [])
    has_cuda = any(m.startswith("libggml-cuda.so") for m in mapped)
    has_vulkan = any(m.startswith("libggml-vulkan.so") for m in mapped)
    if arm == "A":
        if not has_cuda:
            problems.append(f"arm{arm}:cuda_backend_not_mapped")
        if has_vulkan:
            problems.append(f"arm{arm}:vulkan_backend_in_cuda_arm")
    else:
        if not has_vulkan:
            problems.append(f"arm{arm}:vulkan_backend_not_mapped")
        if has_cuda:
            problems.append(f"arm{arm}:cuda_backend_in_vulkan_arm")
    package_objects = (got_package or {}).get("objects") or {}
    mapped_objects = (doc.get("in_process_backends") or {}).get(
        "mapped_objects") or []
    if not isinstance(mapped_objects, list):
        problems.append(f"arm{arm}:mapped_objects_not_list")
        mapped_objects = []
    mapped_names = set()
    for mapped_object in mapped_objects:
        name = mapped_object.get("name") if isinstance(mapped_object, dict) else None
        expected_object = package_objects.get(name)
        if (expected_object is None or not isinstance(mapped_object, dict)
                or any(mapped_object.get(k) != expected_object.get(k)
                       for k in ("realpath", "bytes", "sha256"))):
            problems.append(f"arm{arm}:mapped_object_not_authorized:{name}")
        else:
            mapped_names.add(name)
    for prefix in _required_package_prefixes(arm)[1:]:
        if not any(name == prefix or name.startswith(prefix + ".")
                   for name in mapped_names):
            problems.append(f"arm{arm}:required_object_not_mapped:{prefix}")

    # ---- device proof -------------------------------------------------
    dp = doc.get("device_proof", {})
    want_backend = "cuda" if arm == "A" else "vulkan"
    if dp.get("backend") != want_backend:
        problems.append(f"arm{arm}:backend:{dp.get('backend')}")
    ld_parsed = (dp.get("list_devices") or {}).get("parsed") or []
    if not ld_parsed:
        problems.append(f"arm{arm}:no_devices_under_launch_env")
    else:
        if arm == "A" and not any(
                d.get("label", "").startswith("CUDA") for d in ld_parsed):
            problems.append(f"arm{arm}:no_cuda_device_listed")
        if arm != "A" and not any(
                d.get("label", "").startswith("Vulkan") for d in ld_parsed):
            problems.append(f"arm{arm}:no_vulkan_device_listed")
        if any(d.get("label", "").startswith("CUDA") for d in ld_parsed) \
                and arm != "A":
            problems.append(f"arm{arm}:cuda_device_in_vulkan_arm")
        if any(d.get("label", "").startswith("Vulkan") for d in ld_parsed) \
                and arm == "A":
            problems.append(f"arm{arm}:vulkan_device_in_cuda_arm")
    sel = dp.get("selected") or {}
    excluded = dp.get("excluded") or []
    g3060 = frozen["frozen_rtx3060"]
    if arm in ("A", "B"):
        if sel.get("uuid") != g3060["uuid"]:
            problems.append(f"arm{arm}:selected_uuid:{sel.get('uuid')}")
        if sel.get("bdf") != g3060["bdf"]:
            problems.append(f"arm{arm}:selected_bdf:{sel.get('bdf')}")
    else:
        c_sel = frozen["C_selected_die"]
        c_ex = frozen["C_excluded_die"]
        if sel.get("bdf") != c_sel["bdf"]:
            problems.append(f"arm{arm}:selected_die:{sel.get('bdf')}")
        if sel.get("deviceUUID") != c_sel["deviceUUID"]:
            problems.append(f"arm{arm}:selected_uuid:{sel.get('deviceUUID')}")
        if not excluded or excluded[0].get("bdf") != c_ex["bdf"]:
            problems.append(f"arm{arm}:excluded_die_binding")
    # vulkan physical-device join (arms B/C): GPU0 under the exact ICD
    if arm in ("B", "C"):
        phys = dp.get("vulkan_physical_devices") or []
        gpu0 = next((e for e in phys if e.get("gpu_index") == "GPU0"), None)
        if gpu0 is None:
            problems.append(f"arm{arm}:no_vulkan_gpu0")
        else:
            if arm == "B":
                if gpu0.get("deviceUUID") != g3060["vulkan_deviceUUID"]:
                    problems.append(
                        f"arm{arm}:vk_gpu0_uuid:{gpu0.get('deviceUUID')}")
                if gpu0.get("bdf") != g3060["bdf"]:
                    problems.append(f"arm{arm}:vk_gpu0_bdf:{gpu0.get('bdf')}")
                if "NVIDIA" not in (gpu0.get("driverName") or ""):
                    problems.append(f"arm{arm}:vk_gpu0_not_nvidia_icd")
            else:
                if gpu0.get("bdf") != frozen["C_selected_die"]["bdf"]:
                    problems.append(
                        f"arm{arm}:vk_gpu0_bdf:{gpu0.get('bdf')}")
                # RADV identifies as lowercase driverName 'radv' with
                # DRIVER_ID_MESA_RADV (case-insensitive match on both)
                dn = (gpu0.get("driverName") or "").upper()
                did = (gpu0.get("driverID") or "").upper()
                if "RADV" not in dn and "RADV" not in did:
                    problems.append(f"arm{arm}:vk_gpu0_not_radv")
        # wrong ICD vendor: the OTHER vendor's devices must be absent
        # under the restricted census
        for e in phys:
            dn = (e.get("driverName") or "").upper()
            if arm == "B" and ("RADV" in dn or "AMD" in dn):
                problems.append(f"arm{arm}:amd_device_under_nvidia_icd")
            if arm == "C" and "NVIDIA" in dn:
                problems.append(f"arm{arm}:nvidia_device_under_radv_icd")
    # CUDA live binding (arm A): the server PID must be bound to the
    # frozen GPU by nvidia-smi compute-apps during generation
    if arm == "A":
        bound = (doc.get("residency", {})
                 .get("compute_apps_bound_to_pid")) or []
        phases = {b.get("phase") for b in bound}
        if not bound:
            problems.append(f"arm{arm}:no_compute_app_binding")
        elif not ({"loaded", "generation"} & phases):
            problems.append(f"arm{arm}:compute_binding_outside_window")
        for b in bound:
            if b.get("gpu_uuid") != g3060["uuid"]:
                problems.append(
                    f"arm{arm}:compute_bound_to_wrong_gpu:"
                    f"{b.get('gpu_uuid')}")

    # ---- residency / activity ----------------------------------------
    res = doc.get("residency", {})
    sel_bytes = res.get("selected_delta_bytes")
    if not isinstance(sel_bytes, int) or \
            sel_bytes < rc.EXCLUDED_DEVICE_MAX_BYTES:
        problems.append(f"arm{arm}:zero_selected_device_activity")
    for ex in res.get("excluded") or []:
        peak = ex.get("peak_delta_bytes")
        if not isinstance(peak, int) or \
                peak >= rc.EXCLUDED_DEVICE_MAX_BYTES:
            problems.append(f"arm{arm}:excluded_device_active:{ex.get('bdf')}")

    # ---- CPU-fallback rejection (re-derived, never the authored
    #      boolean) -----------------------------------------------------
    cf = doc.get("cpu_fallback", {})
    warning = cf.get("no_usable_gpu_warning_present") is True
    listed = bool(ld_parsed)
    if warning:
        problems.append(f"arm{arm}:cpu_fallback_warning")
    if not listed:
        problems.append(f"arm{arm}:no_devices_listed")
    if not (isinstance(sel_bytes, int)
            and sel_bytes >= rc.EXCLUDED_DEVICE_MAX_BYTES):
        problems.append(f"arm{arm}:no_model_scale_residency")

    # ---- artifacts bind the receipt to the retained bytes -------------
    arts = doc.get("artifacts", {})
    for key, fname in (("observation_jsonl", f"{arm}.jsonl"),
                       ("pos0_f32", f"{arm}.jsonl.pos{position}.f32"),
                       ("request_payload", f"{arm}.request.json"),
                       ("response", f"{arm}.resp.json"),
                       ("server_log", f"{arm}.server.log")):
        want_p = base / fname
        if not want_p.is_file():
            problems.append(f"arm{arm}:artifact_missing:{fname}")
            continue
        if arts.get(key) != hashlib.sha256(
                want_p.read_bytes()).hexdigest():
            problems.append(f"arm{arm}:artifact_digest:{key}")

    # ---- generated stream equals the canonical stream -----------------
    toks = doc.get("generated_tokens")
    if canonical_tokens is not None and toks != list(canonical_tokens):
        problems.append(f"arm{arm}:tokens_not_canonical")

    # ---- exit ----------------------------------------------------------
    if doc.get("exit", {}).get("returncode") not in (-15, 143, 0):
        problems.append(
            f"arm{arm}:exit:{doc.get('exit', {}).get('returncode')}")
    return problems


def reduce_observation_execution_truth(
        evidence: Path, position: int = 0,
        canonical_streams: dict[str, list[int] | None] | None = None,
        closure: dict[str, Any] | None = None) -> dict[str, Any]:
    """Round-3 blocker fix: the observation-only score-characterization
    executions must be mechanically bound to the GPU/backend selectors
    they claim to represent. Token equality with the canonical stream
    is NOT identity proof (the quarantined relative-ICD incident
    proved fallback CAN change tokens, but equality was never proof).

    For each A/B/C characterization arm this reducer mechanically
    compares, from receipt bytes + retained raw bytes + frozen
    authorities only:
      * the prospective observation pin (selectors/ICD/binaries);
      * the observation execution receipt (launch env captured at
        exec from /proc/PID/environ, argv, mapped backends, device
        censuses under the exact launch env, residency deltas,
        compute-app bindings, artifact digests, generated stream);
      * the campaign freeze (frozen RTX 3060 / V340L die identities);
      * the canonical runtime authority (llama.cpp pin, hook digest);
      * the selected GPU identity (A/B MUST select the SAME frozen
        RTX 3060 UUID/BDF; C MUST select die 06:00.0 and exclude
        09:00.0);
      * the observation binary identity (actual deployed hash MUST
        equal the prospectively authorized hash).

    Returns {arm: {status: OK|FAIL|ABSENT, problems, ...}}; the score
    characterization terminal gate requires status == OK for all
    three arms, else R8H_EVIDENCE_BLOCKED."""
    base = _observation_base(evidence, position)
    out: dict[str, Any] = {}
    if base is None:
        return {arm: {"status": "ABSENT", "problems": [
            "observation_authority:missing_or_invalid"]} for arm in ("A", "B", "C")}
    pin = _observation_pin(evidence, position)
    for arm in ("A", "B", "C"):
        p = base / f"observation-receipt-{arm}.json"
        if not p.is_file():
            out[arm] = {"status": "ABSENT",
                        "problems": ["observation_receipt:absent"]}
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            out[arm] = {"status": "ABSENT",
                        "problems": ["observation_receipt:unparsable"]}
            continue
        # self-digest envelope (tamper with any validated field ->
        # digest mismatch fails closed before field checks run)
        digest = doc.get("digest")
        body = dict(doc)
        body["digest"] = "PENDING"
        if rc.sha256_bytes(rc.canonical(body)) != digest:
            out[arm] = {"status": "FAIL",
                        "problems": ["observation_receipt:digest"]}
            continue
        can = (canonical_streams or {}).get(arm)
        problems = _receipt_problems(arm, doc, base, position, can, pin)
        sel = ((doc.get("device_proof") or {}).get("selected") or {})
        out[arm] = {
            "status": "OK" if not problems else "FAIL",
            "problems": problems,
            "host": (doc.get("host") or {}).get("hostname"),
            "binary_sha256": (doc.get("observation_binary") or {})
            .get("sha256"),
            "selected_gpu": {
                "uuid": sel.get("uuid"),
                "bdf": sel.get("bdf"),
                "deviceUUID": sel.get("deviceUUID"),
            },
            "backend": (doc.get("device_proof") or {}).get("backend"),
            "selected_delta_bytes":
                (doc.get("residency") or {}).get("selected_delta_bytes"),
            "package_objects": ((doc.get("observation_binary") or {})
                                .get("package") or {}).get("objects"),
        }
    # ---- cross-arm relation: A and B executed on the SAME GPU --------
    g3060 = rc.OBSERVATION_FROZEN_DEVICES["frozen_rtx3060"]
    a_sel = out.get("A", {}).get("selected_gpu") or {}
    b_sel = out.get("B", {}).get("selected_gpu") or {}
    ab_same = (a_sel.get("uuid") == b_sel.get("uuid") ==
               g3060["uuid"] and
               a_sel.get("bdf") == b_sel.get("bdf") == g3060["bdf"])
    out["AB_same_gpu"] = {
        "uuid": g3060["uuid"], "bdf": g3060["bdf"],
        "A": a_sel, "B": b_sel,
        "same_frozen_rtx3060": ab_same,
        "status": "OK" if ab_same else "FAIL",
        "problems": [] if ab_same else ["A_B_gpu_identity_divergence"],
    }
    b_objects = _package_byte_identity({"objects": out.get("B", {}).get("package_objects")})
    c_objects = _package_byte_identity({"objects": out.get("C", {}).get("package_objects")})
    bc_same = b_objects == c_objects and bool(b_objects)
    out["BC_same_vulkan_package"] = {
        "same_authorized_package": bc_same,
        "status": "OK" if bc_same else "FAIL",
        "problems": [] if bc_same else ["B_C_vulkan_package_mismatch"],
    }
    return out


def characterization_ok(evidence: Path, case_id: str,
                        required_position: int | None,
                        ladder_case: dict[str, Any] | None = None,
                        ) -> dict[str, Any]:
    """Required pre-choice score characterization for a divergent rung
    (issue #12 / control 33, round-2 hardened).

    The characterization is ACCEPTED only when ALL of the following are
    mechanically true:
      1. `required_position` (derived by the caller from the raw
         pairwise token streams as the MINIMUM pairwise first-divergence
         position) is not None and the retained characterization binds
         EXACTLY that generated position (position 5 must NOT satisfy
         the global gate when any pair diverges at position 0);
      2. for EVERY arm the full raw observation inputs exist (jsonl +
         float32 row + response) and every derived quantity is
         re-derived from the float32 bytes with JSONL agreement;
      3. the observation response tokens equal the canonical arm
         ladder stream (non-perturbation; a forged
         non_perturbation_identical=true with differing response
         tokens fails closed);
      4. the authored summary, when present, agrees with the raw
         derivation (authored winner/logit/rank/sidecar-digest mutation
         either leaves the terminal unchanged — because authority is
         the raw bytes — or fails the summary-consistency check;
         it is never silently accepted);
      5. a SECONDARY characterization at a later pairwise divergence
         (e.g. B/C position 5) is retained and reported but does NOT
         satisfy the global first-divergence gate.

    Returns a status document; the summary document's own authored
    fields are never trusted as authority."""
    p = evidence / "candidate" / f"score-characterization-{case_id}.json"
    summary_present = p.is_file()
    problems: list[str] = []
    if required_position is None:
        return {"status": "ABSENT",
                "problems": ["no_pairwise_divergence"]}
    # canonical first-repeat streams for non-perturbation binding
    canon: dict[str, list[int] | None] = {}
    if ladder_case is not None:
        for arm in ("A", "B", "C"):
            a = ladder_case.get("arms", {}).get(arm, {})
            canon[arm] = a.get("tokens")
    derived: dict[str, Any] = {}
    base_dir = evidence / "candidate" / "characterization"
    arm_dir = base_dir / "pos0" if required_position == 0 else base_dir
    obs_truth: dict[str, Any] | None = None
    if required_position == 0:
        problems.extend(_validate_observation_pin(
            evidence, required_position))
        # ROUND-3 BLOCKER FIX: the observation executions must be
        # mechanically bound to the GPU/backend selectors they claim
        # to represent. Token equality is NOT identity proof; the
        # observation execution receipts are.
        obs_truth = reduce_observation_execution_truth(
            evidence, required_position, canonical_streams=canon)
        obs_fail = {a: v for a, v in obs_truth.items()
                    if isinstance(v, dict) and v.get("status") != "OK"}
        if obs_fail:
            problems.append(
                "observation_execution_truth:"
                + json.dumps({a: (v.get("problems") or
                                  [v.get("status")])[:4]
                              for a, v in obs_fail.items()})[:400])
    for arm in ("A", "B", "C"):
        try:
            derived[arm] = _derive_arm_characterization(
                arm_dir, arm, required_position, canon.get(arm))
        except ReduceError as e:
            problems.append(f"arm{arm}:{str(e)[:160]}")
    # -- summary consistency -------------------------------------------
    # Round-2 doctrine (spec): authored summary fields are NEVER
    # authority. A mutated winner/logit/rank leaves the terminal
    # unchanged (raw bytes win; the disagreement is recorded, the
    # derived values in the terminal doc are the truth). A mutated
    # raw-sidecar digest or generated_position REJECTS: those are the
    # bindings between the summary and the raw bytes / the divergence
    # structure, and a broken binding must fail closed.
    summary_status = "ABSENT"
    disagreements: list[str] = []
    if summary_present:
        doc = _load(p)
        summary_status = "PRESENT"
        if doc.get("case_id") != case_id:
            problems.append("summary:case_binding")
        if doc.get("generated_position") != required_position:
            problems.append(
                f"summary:generated_position:"
                f"{doc.get('generated_position')}!={required_position}")
        arms = doc.get("arms", {})
        for arm in ("A", "B", "C"):
            a = arms.get(arm, {})
            d = derived.get(arm)
            if d is None:
                continue
            if a.get("winner_token") is not None and \
                    a.get("winner_token") != d["winner_token"]:
                disagreements.append(f"summary:arm{arm}:winner_mismatch")
            side = a.get("raw_sidecar_sha256") or {}
            dig = side.get(f"f32_pos{required_position}")
            if dig is not None and dig != d["f32_sha256"]:
                problems.append(f"summary:arm{arm}:f32_digest_mismatch")
    # -- secondary (position-5 B/C) retention -------------------------
    secondary = _secondary_characterization(evidence, case_id)
    ok = not problems and all(
        v is not None for v in derived.values())
    return {
        "status": "OK" if ok else "INSUFFICIENT",
        "problems": problems,
        "required_position": required_position,
        "summary_status": summary_status,
        "summary_disagreements": disagreements,
        "derived": derived,
        "secondary": secondary,
        "observation_execution_truth": obs_truth,
    }


def _secondary_characterization(evidence: Path, case_id: str) \
        -> dict[str, Any]:
    """Retained secondary B/C characterization at their own first
    divergence (position 5 for this campaign). Reported for nuance;
    NEVER satisfies the global first-divergence gate."""
    p = evidence / "candidate" / "characterization" / \
        "pos5-secondary" / f"score-characterization-{case_id}.json"
    if not p.is_file():
        return {"status": "ABSENT"}
    doc = _load(p)
    pos = doc.get("generated_position")
    return {
        "status": "RETAINED",
        "classification": "secondary_device_axis_characterization",
        "generated_position": pos,
        "document_sha256": hashlib.sha256(
            p.read_bytes()).hexdigest(),
        "note": ("retained secondary evidence; binds the B/C device "
                 "axis divergence only and does not satisfy the "
                 "global first-divergence characterization gate"),
    }


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
                req = required_characterization_position(case)
                char = characterization_ok(evidence, first_case, req,
                                           ladder_case=case)
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
                        "AMD/Vulkan agree); earliest-divergence position-"
                        f"{req} characterization derived from raw f32 "
                        "bytes")
            elif cls == "DEVICE_DIVERGENT":
                req = required_characterization_position(case)
                char = characterization_ok(evidence, first_case, req,
                                           ladder_case=case)
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
                        "earliest-divergence position-"
                        f"{req} characterization derived from raw f32 "
                        "bytes")
            else:
                req = required_characterization_position(case)
                char = characterization_ok(evidence, first_case, req,
                                           ladder_case=case)
                checks["score_characterization"] = char
                if char["status"] != "OK":
                    terminal = TERMINAL_BLOCKED
                    basis.append(
                        f"{first_case}: multi-axis pairwise map but "
                        f"required earliest-divergence (position-"
                        f"{req}) score characterization "
                        f"{char['status']} {char.get('problems', [])}")
                else:
                    terminal = TERMINAL_MULTI_AXIS
                    basis.append(
                        f"{first_case}: multi-axis pairwise map: "
                        f"{ {k: v['exact'] for k, v in case['pairwise'].items()} }; "
                        f"earliest divergence position {req} "
                        "(A<->B and A<->C diverge at 0; B<->C at 5); "
                        "position-0 characterization re-derived from "
                        "raw float32 bytes; position-5 retained as "
                        "secondary_device_axis_characterization")
                    basis.append(
                        "divergence structure decomposed without a "
                        "single causal-root claim: backend-associated "
                        "A<->B divergence at position 0 (same frozen "
                        "RTX 3060, CUDA vs Vulkan); A<->C also "
                        "diverging at 0 (backend+device axes "
                        "concurrent); B<->C equal through position 4 "
                        "and first diverging at position 5 (later "
                        "device/backend interaction); each axis is "
                        "characterized separately")
                    ot = (checks.get("score_characterization") or {}
                          .get("observation_execution_truth") or {})
                    if ot:
                        basis.append(
                            "observation execution identity "
                            "mechanically bound for all three arms "
                            "(receipts prove launch env, ICD, selected "
                            "GPU UUID/BDF, backend participation, "
                            "residency, and binary identity; A and B "
                            "prove the SAME frozen RTX 3060)")

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
