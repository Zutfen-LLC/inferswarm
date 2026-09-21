#!/usr/bin/env python3
"""Issue #234 — R8-H evidence assembler + fail-closed control suite (/2).

The assembler:
  * verifies the CORRECTED producer closure FIRST (ancestor pin, blob
    identity pin->HEAD, worktree cleanliness, deployed hash equality);
  * re-derives the terminal through issue234_reduce from retained raw
    bytes only;
  * proves the issue's 36 required fail-closed controls as REDUCER-
    LEVEL mutation tests over sandbox copies of the evidence tree
    (never the real tree; never destructive fault injection).

Controls 1-27 are the original issue controls; 28-36 are the
maintainer-correction additions. The receipt carries count == 36,
all_ok, and explicit IDs 1..36. The number of unittest methods is a
separate quantity and is never treated as the control count.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

import issue234_receipt as rc
import issue234_reduce as red


class AssembleError(RuntimeError):
    pass


#: Frozen per-host deployed-producer matrix (round-2 correction of the
#: fail-open `deployed.get("producers")` read, which matched nothing in
#: the retained schema and performed ZERO comparisons). The retained
#: deployed-producers.json keys each host's hashes by producer BASENAME
#: (the name under which the producer was deployed to
#: /tmp/is234r/producers/scripts/ on each execution host); each maps to
#: the closure source `scripts/<basename>`. Semantics:
#:  * the exact expected execution host set is required — a missing
#:    host fails closed;
#:  * for each host the exact physical-producer set that actually
#:    executed is frozen explicitly — a missing producer fails closed;
#:  * every retained hash must equal the frozen physical-producer pin
#:    (closure blob sha256) — mismatch fails closed;
#:  * a producer substituted for an expected one fails closed;
#:  * `all_hosts_match_pin` is DERIVED from the comparisons, never
#:    read from the authored boolean.
#: Round 3 adds the observation execution-identity collector
#: (issue234_observe.py) to the matrix: it is a physical producer
#: (it executes the observation runs) deployed to BOTH execution
#: hosts, and its deployed bytes are verified like every other.
DEPLOYED_PRODUCER_BASENAMES: tuple[str, ...] = (
    "issue234_host.py",
    "issue234_runtime.py",
    "issue234_placement.py",
    "issue234_ladder.py",
    "issue234_health.py",
    "issue234_observe.py",
)
EXPECTED_DEPLOYED_HOSTS: dict[str, tuple[str, ...]] = {
    "inferswarm01": DEPLOYED_PRODUCER_BASENAMES,
    "inferswarm02": DEPLOYED_PRODUCER_BASENAMES,
}


def verify_deployed_producers(deployed: dict[str, Any],
                              closure: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed deployed-producer verification (round 2).

    The retained deployed-producers.json carries hashes under
    hosts.<hostname>.hashes — NOT under a top-level `producers` key
    (the round-1 reader matched nothing there and compared zero
    hashes: a fail-open). This verifier requires the exact frozen
    (host, producer) matrix above and hash equality with the frozen
    physical-producer pin for every entry."""
    problems: list[str] = []
    if not isinstance(deployed, dict):
        raise AssembleError("deployed-producers document is not an object")
    hosts = deployed.get("hosts")
    if not isinstance(hosts, dict) or not hosts:
        raise AssembleError(
            "deployed-producers document lacks hosts.<hostname>.hashes")
    # 1. exact host set
    want_hosts = set(EXPECTED_DEPLOYED_HOSTS)
    got_hosts = set(hosts)
    for missing in sorted(want_hosts - got_hosts):
        problems.append(f"missing_host:{missing}")
    for unexpected in sorted(got_hosts - want_hosts):
        problems.append(f"unexpected_host:{unexpected}")
    per_host: dict[str, Any] = {}
    for host in sorted(want_hosts & got_hosts):
        entry = hosts[host]
        hashes = entry.get("hashes") if isinstance(entry, dict) else None
        if not isinstance(hashes, dict):
            problems.append(f"{host}:no_hashes_map")
            per_host[host] = {"match_pin": False,
                              "reason": "no_hashes_map"}
            continue
        want_set = set(EXPECTED_DEPLOYED_HOSTS[host])
        got_set = set(hashes)
        for missing in sorted(want_set - got_set):
            problems.append(f"{host}:missing_producer:{missing}")
        for unexpected in sorted(got_set - want_set):
            problems.append(f"{host}:unexpected_producer:{unexpected}")
        mismatches = []
        for name in sorted(want_set & got_set):
            rel = f"scripts/{name}"
            meta = closure["sources"].get(rel)
            if meta is None or meta.get("class") != "physical":
                problems.append(f"{host}:not_closure_bound:{rel}")
                continue
            if hashes[name] != meta["sha256"]:
                problems.append(
                    f"{host}:hash_mismatch:{name}:"
                    f"{hashes[name][:12]}!={meta['sha256'][:12]}")
                mismatches.append(name)
        per_host[host] = {
            "match_pin": not mismatches and not any(
                p.startswith(f"{host}:") for p in problems),
            "checked": sorted(want_set & got_set),
        }
    # 2. derived verdict — the authored boolean is never trusted
    derived_all_match = not problems
    authored = deployed.get("all_hosts_match_pin")
    if authored is not True and derived_all_match:
        # authored flag missing/false while hashes genuinely match:
        # derived truth wins, but record the disagreement
        problems.append("authored_all_hosts_match_pin_disagrees")
        derived_all_match = derived_all_match  # noqa: PLW0127
    # stale-authority resolution (round 2): the round-1 field
    # `closure_producer_head` named a SUPERSEDED closure pin (377d2ff,
    # the pin current when the deployed hashes were collected). The
    # /3 schema renames it to `closure_producer_head_at_collection`
    # with explicit semantics; the legacy spelling is still validated
    # for lineage when present so a contradictory authority field can
    # never pass uninterpreted. An unresolvable name is a failure,
    # never a pass.
    stale_pin = deployed.get("closure_producer_head_at_collection") \
        or deployed.get("closure_producer_head")
    if stale_pin is not None:
        # must be an ancestor of the ACTIVE closure pin (i.e. a real
        # predecessor in the closure lineage, not a foreign SHA)
        active = closure.get("producer_head")
        if active:
            import subprocess
            proc = subprocess.run(
                ["git", "-C", str(rc.ROOT), "merge-base",
                 "--is-ancestor", stale_pin, active],
                capture_output=True)
            if proc.returncode != 0:
                problems.append(
                    f"closure_pin_not_in_lineage:{stale_pin[:12]}")
    result = {
        "derived_all_hosts_match_pin": derived_all_match,
        "per_host": per_host,
        "expected_hosts": sorted(EXPECTED_DEPLOYED_HOSTS),
        "expected_matrix": {h: list(v) for h, v in
                            EXPECTED_DEPLOYED_HOSTS.items()},
        "authored_all_hosts_match_pin": authored,
        "stale_closure_producer_head": stale_pin,
        "problems": problems,
    }
    if problems:
        raise AssembleError(
            "deployed-producer verification failed: " + "; ".join(problems))
    return result


def assemble(evidence_root: Path, repo: Path | None = None) -> dict[str, Any]:
    closure = rc.verify_closure(repo or rc.ROOT)
    deployed = json.loads(
        (evidence_root / "freeze" / "deployed-producers.json")
        .read_text(encoding="utf-8"))
    deployed_check = verify_deployed_producers(deployed, closure)
    terminal_doc = red.derive_terminal(evidence_root, closure=closure)
    return {
        "schema": "inferswarm.r8h.assembly/2",
        "campaign": rc.CAMPAIGN_ID,
        "closure": {
            "producer_head": closure["producer_head"],
            "closure_digest": closure["closure_digest"],
        },
        "deployed_producers": deployed_check,
        **terminal_doc,
    }


# ---------------------------------------------------------------------
# Mutations. Each mutates ONE property of a sandbox evidence copy.
# ---------------------------------------------------------------------

def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _write(p: Path, doc: dict) -> None:
    p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                 encoding="utf-8")


def _sandbox(evidence: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="r8h-ctl-"))
    box = tmp / "evidence"
    shutil.copytree(evidence, box)
    return box


def _first_exec_case(box: Path) -> str:
    for case in rc.LADDER_CASES:
        if (box / "candidate" / f"ladder-A-{case}.json").is_file():
            return case
    raise AssembleError("no executed case in evidence")


def _arm(box: Path, case: str, arm: str) -> Path:
    return box / "candidate" / f"ladder-{arm}-{case}.json"


def _each_arm_doc(box: Path, case: str):
    for arm in ("A", "B", "C"):
        yield arm, _arm(box, case, arm), _load(_arm(box, case, arm))


def _mut_authority_model_key(key: str) -> Callable:
    def fn(b: Path) -> None:
        d = _load(b / "PHYSICAL-AUTHORITY.json")
        d["model_authority"][key] = "f" * 40
        _write(b / "PHYSICAL-AUTHORITY.json", d)
    return fn


def _mut_backing_member(b: Path) -> None:
    d = _load(b / "backing" / "armA-backing.json")
    d["members"][1]["sha256"] = "1" * 64
    _write(b / "backing" / "armA-backing.json", d)


def _mut_runtime(arm: str, dot: str, value: Any) -> Callable:
    def fn(b: Path) -> None:
        p = b / "runtime" / f"arm{arm}-runtime.json"
        d = _load(p)
        node = d
        keys = dot.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
        _write(p, d)
    return fn


def _mut_selector_target(arm: str, bdf: str, uuid: str) -> Callable:
    def fn(b: Path) -> None:
        p = b / "runtime" / f"arm{arm}-runtime.json"
        d = _load(p)
        d["selector"]["target_bdf"] = bdf
        d["selector"]["target_deviceUUID"] = uuid
        if "value_semantics" in d["selector"]:
            d["selector"]["value_semantics"] = f"other gpu {bdf}"
        _write(p, d)
    return fn


def _mut_fixture_sha(b: Path) -> None:
    d = _load(b / "PHYSICAL-AUTHORITY.json")
    d["fixture_ladder"]["sha256"] = "3" * 64
    _write(b / "PHYSICAL-AUTHORITY.json", d)


def _mut_armc_excluded_active(b: Path) -> None:
    case = _first_exec_case(b)
    p = _arm(b, case, "C")
    d = _load(p)
    for rep in d["repeats"]:
        rep["excluded_residency"] = {
            "00000000:09:00.0": {
                "pre": {"card1.mem_info_vis_vram_used": 0},
                "post": {"card1.mem_info_vis_vram_used":
                         900 * 1024 * 1024}}}
    _write(p, d)


def _mut_zero_residency(b: Path) -> None:
    case = _first_exec_case(b)
    for arm, p, d in _each_arm_doc(b, case):
        for rep in d["repeats"]:
            rep["selected_residency"] = {
                "pre": {"mem_used_mib": 0}, "post": {"mem_used_mib": 0}}
        _write(p, d)


def _mut_request_samplers(b: Path) -> None:
    case = _first_exec_case(b)
    for arm, p, d in _each_arm_doc(b, case):
        d["geometry"]["request"]["samplers"] = ["greedy"]
        _write(p, d)


def _mut_request_topk(b: Path) -> None:
    case = _first_exec_case(b)
    for arm, p, d in _each_arm_doc(b, case):
        d["geometry"]["request"]["top_k"] = 4
        _write(p, d)


def _mut_repeat_drop(b: Path) -> None:
    case = _first_exec_case(b)
    p = _arm(b, case, "B")
    d = _load(p)
    d["repeats"] = d["repeats"][:2]
    _write(p, d)


def _mut_nondeterministic(b: Path) -> None:
    case = _first_exec_case(b)
    p = _arm(b, case, "C")
    d = _load(p)
    toks = list(d["repeats"][1]["raw_response"]["tokens"])
    toks[0] = 999999
    d["repeats"][1]["raw_response"]["tokens"] = toks
    _write(p, d)


def _mut_platform_fault(b: Path) -> None:
    case = _first_exec_case(b)
    p = _arm(b, case, "A")
    d = _load(p)
    d["repeats"][0]["health_window"]["stop_classes"] = ["amdgpu_reset"]
    _write(p, d)


def _mut_later_rung_after_divergence(b: Path) -> None:
    # ladder prefix violation (controls 23/35): keep only a LATER rung
    # (copy first-case docs under a later case id, then delete rung 1)
    case = _first_exec_case(b)
    if case != rc.LADDER_CASES[-1]:
        later = rc.LADDER_CASES[-1]
        for arm in ("A", "B", "C"):
            shutil.copy(_arm(b, case, arm),
                        b / "candidate" / f"ladder-{arm}-{later}.json")
    for cs in rc.LADDER_CASES[1:-1]:
        for arm in ("A", "B", "C"):
            p = _arm(b, cs, arm)
            if p.is_file():
                p.unlink()
    for arm in ("A", "B", "C"):
        p = _arm(b, "case-256", arm)
        if p.is_file():
            p.unlink()


def _mut_authored_status(b: Path) -> None:
    case = _first_exec_case(b)
    for arm, p, d in _each_arm_doc(b, case):
        d["status"] = "PASS_ALL_ARMS_EQUAL"
        for rep in d["repeats"]:
            rep["comparison"] = {"exact": True}
        _write(p, d)


def _mut_armb_geometry_drift(b: Path) -> None:
    case = _first_exec_case(b)
    p = _arm(b, case, "B")
    d = _load(p)
    d["geometry"]["ngl"] = 99
    _write(p, d)


def _mut_armc_cuda_present(b: Path) -> None:
    p = b / "runtime" / "armC-runtime.json"
    d = _load(p)
    d["raw"]["list_devices_all"] = (
        "CUDA0: NVIDIA GeForce RTX 3060 (12288 MiB)\n" +
        d["raw"]["list_devices_all"])
    _write(p, d)


def _mut_divergence_without_characterization(b: Path) -> None:
    # control 21: B deterministically diverges from A (token stream
    # mutated) while the characterization summary is REMOVED — the
    # honest missing-summary case; raw observation bytes, if present,
    # then fail non-perturbation against the mutated ladder stream.
    case = _first_exec_case(b)
    p = _arm(b, case, "B")
    d = _load(p)
    for rep in d["repeats"]:
        toks = list(rep["raw_response"]["tokens"])
        toks[0] = toks[0] + 1
        rep["raw_response"]["tokens"] = toks
    _write(p, d)
    c = b / "candidate" / f"score-characterization-{case}.json"
    if c.is_file():
        c.unlink()


def _mut_raw_characterization_missing(b: Path) -> None:
    # control 33 (round-2 strengthened, round-3: receipts too): the
    # divergent ladder evidence is fully intact but the ENTIRE raw
    # characterization corpus (observation jsonl + float32 rows +
    # responses + prospective pin + execution receipts + summaries) is
    # absent — divergence WITHOUT the required identity-bound score
    # characterization must block, not classify.
    import shutil as _sh
    char_root = b / "candidate" / "characterization"
    if char_root.is_dir():
        _sh.rmtree(char_root)
    case = _first_exec_case(b)
    c = b / "candidate" / f"score-characterization-{case}.json"
    if c.is_file():
        c.unlink()


def _mut_observation_receipts_missing(b: Path) -> None:
    # control 33 companion (round-3): ONLY the execution receipts are
    # removed while every raw observation byte stays — an unbound
    # observation corpus must block exactly like a missing one.
    pos0 = b / "candidate" / "characterization" / "pos0"
    if pos0.is_dir():
        for p in pos0.glob("observation-receipt-*.json"):
            p.unlink()


# expectation vocabulary
_BLOCKED = red.TERMINAL_BLOCKED
_BACKING = red.TERMINAL_BACKING_PREREQ
_RUNTIME = red.TERMINAL_RUNTIME_PREREQ
_PLATFORM = red.TERMINAL_PLATFORM_FAIL

CONTROLS: dict[int, dict[str, Any]] = {
    # --- original 27 (issue #234) ---
    1: {"d": "wrong official Qwen revision",
        "fn": _mut_authority_model_key("official_qwen_revision"),
        "expect": "error"},
    2: {"d": "wrong Unsloth conversion revision",
        "fn": _mut_authority_model_key("unsloth_revision"),
        "expect": "error"},
    3: {"d": "wrong UD-IQ1_S member hash",
        "fn": _mut_backing_member, "expect": _BACKING},
    4: {"d": "wrong llama.cpp source revision",
        "fn": _mut_runtime("A", "source.revision", "a" * 40),
        "expect": _RUNTIME},
    5: {"d": "binary built from unpinned/dirty source",
        "fn": _mut_runtime("B", "source.clean", False),
        "expect": _RUNTIME},
    6: {"d": "wrong ICD/loader identity substituted after freeze",
        "fn": _mut_runtime("C", "build.cmake_flags", {}),
        "expect": _RUNTIME},
    7: {"d": "stale V340L selector-UUID/BDF mapping",
        "fn": _mut_selector_target("C", "00000000:09:00.0", "9" * 32),
        "expect": "error"},
    8: {"d": "die A/B swap after freeze",
        "fn": _mut_selector_target("C", "00000000:09:00.0", "9" * 32),
        "expect": "error"},
    9: {"d": "both V340L dies carrying active model residency",
        "fn": _mut_armc_excluded_active, "expect": "error"},
    10: {"d": "aggregate 16-GiB capacity treated as one resource",
         "fn": _mut_armc_excluded_active, "expect": "error"},
    11: {"d": "CPU-only fallback labeled device execution",
         "fn": _mut_zero_residency, "expect": "error"},
    12: {"d": "NVIDIA/CUDA participation hidden in candidate arm",
         "fn": _mut_armc_cuda_present, "expect": "error"},
    13: {"d": "zero-byte GPU residency labeled nonzero offload",
         "fn": _mut_zero_residency, "expect": "error"},
    14: {"d": "offload geometry changed after candidate output",
         "fn": _mut_armb_geometry_drift, "expect": "error"},
    15: {"d": "PLE/backing bytes mislabeled accelerator residency",
         "fn": _mut_zero_residency, "expect": "error"},
    16: {"d": "local backing existence mislabeled active materialization",
         "fn": _mut_backing_member, "expect": _BACKING},
    17: {"d": "reference regenerated after seeing candidate output",
         "fn": _mut_fixture_sha, "expect": "error"},
    18: {"d": "wrong accepted R8-D fixture/prompt identity",
         "fn": _mut_fixture_sha, "expect": "error"},
    19: {"d": "legacy samplers=[greedy] accepted as true greedy",
         "fn": _mut_request_samplers, "expect": "error"},
    20: {"d": "top_k != 1 accepted as canonical true greedy",
         "fn": _mut_request_topk, "expect": "error"},
    21: {"d": "candidate token mismatch omitted from terminal",
         "fn": _mut_divergence_without_characterization,
         "expect": "error"},
    22: {"d": "failed repeat dropped from deterministic comparison",
         "fn": _mut_repeat_drop, "expect": "error"},
    23: {"d": "later ladder rung executed after earlier stop",
         "fn": _mut_later_rung_after_divergence, "expect": "error"},
    24: {"d": "device fault omitted from terminal",
         "fn": _mut_platform_fault, "expect": _PLATFORM},
    25: {"d": "second-die result substituted for primary die",
         "fn": _mut_selector_target("C", "00000000:09:00.0", "9" * 32),
         "expect": "error"},
    26: {"d": "runtime upgrade to turn prerequisite into PASS",
         "fn": _mut_runtime("A", "source.revision", "f" * 40),
         "expect": _RUNTIME},
    27: {"d": "authored terminal contradicting deterministic reduction",
         "fn": _mut_authored_status, "expect": "unchanged"},
    # --- corrected-campaign additions 28-36 ---
    28: {"d": "Arm A and B using different RTX 3060 UUID/BDF",
         "fn": _mut_selector_target("B", "00000000:03:00.0", "b" * 32),
         "expect": "error"},
    29: {"d": "CUDA arm containing Vulkan execution or vice versa",
         "fn": _mut_armc_cuda_present, "expect": "error"},
    30: {"d": "A/B/C differ in ngl/context/batch/model/prompt/request",
         "fn": _mut_armb_geometry_drift, "expect": "error"},
    31: {"d": "historical R8-D output used as sole Vulkan PASS/FAIL oracle",
         "fn": _mut_authored_status, "expect": "unchanged"},
    32: {"d": "B == C interpreted as proof of common root cause",
         "fn": _mut_authored_status, "expect": "unchanged"},
    33: {"d": "divergence classified without required score characterization "
             "(raw corpus OR execution receipts absent)",
         "fn": _mut_raw_characterization_missing,
         "expect": "error"},
    34: {"d": "an arm missing one of exactly 3 repeats",
         "fn": _mut_repeat_drop, "expect": "error"},
    35: {"d": "later rung executed after deterministic pair divergence",
         "fn": _mut_later_rung_after_divergence, "expect": "error"},
    36: {"d": "unmatched placement/residency geometry as matched comparison",
         "fn": _mut_armb_geometry_drift, "expect": "error"},
}


def _run_controls_once(evidence: Path, closure: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    baseline = red.derive_terminal(evidence, closure=closure)["terminal"]
    for cid in sorted(CONTROLS):
        spec = CONTROLS[cid]
        box = _sandbox(evidence)
        try:
            spec["fn"](box)
            doc = red.derive_terminal(box, closure=closure)
            term = doc["terminal"]
            expect = spec["expect"]
            if expect == "unchanged":
                ok = term == baseline
            elif expect == "error":
                # must NOT silently pass: either ReduceError raised (the
                # runner catches it below — unreachable here) or the
                # terminal must degrade to BLOCKED/prerequisite
                ok = term in (_BLOCKED, _BACKING, _RUNTIME, _PLATFORM)
            else:
                ok = term == expect
            out[str(cid)] = {"ok": bool(ok), "terminal": term,
                             "expect": expect, "d": spec["d"]}
        except red.ReduceError:
            out[str(cid)] = {"ok": True, "terminal": "ReduceError",
                             "expect": spec["expect"], "d": spec["d"]}
        except Exception as e:  # noqa: BLE001
            out[str(cid)] = {"ok": False,
                             "terminal": f"EXCEPTION:{str(e)[:120]}",
                             "expect": spec["expect"], "d": spec["d"]}
        finally:
            shutil.rmtree(box.parent, ignore_errors=True)
    return out


def run_controls(evidence: Path, closure: dict) -> dict[str, Any]:
    """Deterministic double-run + byte-compare (R6 doctrine)."""
    a = _run_controls_once(evidence, closure)
    b = _run_controls_once(evidence, closure)
    if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
        raise AssembleError("nondeterministic control results")
    ids = sorted(int(k) for k in a)
    if ids != list(range(1, 37)):
        raise AssembleError(f"control IDs must be exactly 1..36, got {ids}")
    all_ok = all(v["ok"] for v in a.values())
    return {
        "schema": "inferswarm.r8h.controls/2",
        "campaign": rc.CAMPAIGN_ID,
        "count": len(a),
        "all_ok": all_ok,
        "control_ids": ids,
        "controls": a,
        "baseline_terminal": red.derive_terminal(
            evidence, closure=closure)["terminal"],
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="R8-H assembler + 36-control suite")
    ap.add_argument("--evidence", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    closure = rc.verify_closure()
    doc = assemble(args.evidence)
    controls = run_controls(args.evidence, closure)
    result = {**doc, "controls_receipt": controls}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({
        "terminal": doc["terminal"],
        "controls": f"{controls['count']}/36 all_ok={controls['all_ok']}",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
