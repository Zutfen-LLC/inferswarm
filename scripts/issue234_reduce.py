#!/usr/bin/env python3
"""Issue #234 — R8-H deterministic reduction (CPU-only).

Re-derives every passing condition from PRIMARY RAW BYTES retained
under the evidence root; nothing is taken from authored summaries. The
reducer derives exactly one terminal:

  R8H_QWEN38_VULKAN_SINGLE_DIE_QUALIFICATION_PASS
  R8H_QWEN38_VULKAN_CORRECTNESS_FAIL
  R8H_QWEN38_VULKAN_PLATFORM_FAIL
  R8H_QWEN38_VULKAN_RUNTIME_PREREQUISITE
  R8H_QWEN38_BACKING_PREREQUISITE
  R8H_EVIDENCE_BLOCKED

Priority (fail closed): runtime/backing prerequisites first (they gate
whether any execution could be interpreted), then platform faults
before correctness (an untrustworthy platform invalidates the
correctness comparison), then deterministic correctness.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import issue234_receipt as rc

TERMINAL_PASS = "R8H_QWEN38_VULKAN_SINGLE_DIE_QUALIFICATION_PASS"
TERMINAL_CORRECTNESS_FAIL = "R8H_QWEN38_VULKAN_CORRECTNESS_FAIL"
TERMINAL_PLATFORM_FAIL = "R8H_QWEN38_VULKAN_PLATFORM_FAIL"
TERMINAL_RUNTIME_PREREQ = "R8H_QWEN38_VULKAN_RUNTIME_PREREQUISITE"
TERMINAL_BACKING_PREREQ = "R8H_QWEN38_BACKING_PREREQUISITE"
TERMINAL_BLOCKED = "R8H_EVIDENCE_BLOCKED"

ALL_TERMINALS = (TERMINAL_PASS, TERMINAL_CORRECTNESS_FAIL,
                 TERMINAL_PLATFORM_FAIL, TERMINAL_RUNTIME_PREREQ,
                 TERMINAL_BACKING_PREREQ, TERMINAL_BLOCKED)


class ReduceError(RuntimeError):
    """The retained evidence cannot support this reduction."""


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ReduceError(f"evidence input missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def reduce_authority(evidence: Path) -> dict[str, Any]:
    doc = _load(evidence / "PHYSICAL-AUTHORITY.json")
    if doc.get("campaign") != rc.CAMPAIGN_ID:
        raise ReduceError("authority campaign mismatch")
    if doc.get("runtime_authority", {}).get("llama_cpp_pin") != \
            rc.LLAMA_CPP_PIN:
        raise ReduceError("runtime pin drift")
    if doc.get("fixture_ladder", {}).get("sha256") != rc.R8D_FIXTURE_SHA256:
        raise ReduceError("fixture identity drift")
    for merge in ("r8a", "r8d", "v2g"):
        if not doc.get("predecessor_merges", {}).get(merge):
            raise ReduceError(f"missing predecessor authority: {merge}")
    return doc


def reduce_backing(evidence: Path) -> dict[str, Any]:
    """Model bytes on the candidate host vs accepted authority."""
    p = evidence / "backing" / "backing-verification.json"
    if not p.is_file():
        return {"status": "ABSENT"}
    doc = _load(p)
    members = doc.get("members", [])
    if len(members) != len(rc.MODEL_MEMBERS):
        return {"status": "INCOMPLETE", "doc": doc}
    for want, got in zip(rc.MODEL_MEMBERS, members):
        if (got.get("member") != want["member"]
                or got.get("sha256") != want["sha256"]
                or got.get("bytes") != want["bytes"]
                or got.get("sha256_ok") is not True):
            return {"status": "MISMATCH", "doc": doc,
                    "member": want["member"]}
    total = sum(m["bytes"] for m in members)
    if total != rc.TOTAL_MODEL_BYTES:
        return {"status": "TOTAL_MISMATCH", "total": total}
    return {"status": "VERIFIED", "source": doc.get("source"),
            "total_bytes": total}


def reduce_runtime(evidence: Path) -> dict[str, Any]:
    p = evidence / "runtime" / "runtime-qualification.json"
    if not p.is_file():
        return {"status": "ABSENT"}
    doc = _load(p)
    src = doc.get("source", {})
    sel = doc.get("vulkan_selector_mapping", {})
    problems = []
    if src.get("revision") != rc.LLAMA_CPP_PIN:
        problems.append("source_revision")
    if src.get("clean") is not True:
        problems.append("dirty_source")
    flags = doc.get("build", {}).get("cmake_flags", {})
    if flags.get("GGML_VULKAN") != "ON" or flags.get("GGML_CUDA") != "OFF":
        problems.append("backend_flags")
    restricted = sel.get("restricted_devices", [])
    if len(restricted) != 1:
        problems.append("selector_not_unique")
    if not sel.get("selected_die", {}).get("bdf"):
        problems.append("no_selected_die_binding")
    if not sel.get("excluded_die", {}).get("bdf"):
        problems.append("no_excluded_die_binding")
    if doc.get("binaries", {}).get("llama-server", {}).get("sha256") is None:
        problems.append("no_binary_hash")
    if problems:
        return {"status": "PREREQUISITE", "problems": problems}
    return {
        "status": "QUALIFIED",
        "server_sha256": doc["binaries"]["llama-server"]["sha256"],
        "selected_die": sel["selected_die"],
        "excluded_die": sel["excluded_die"],
        "boot_id": doc.get("census_boot_id"),
    }


def reduce_placement(evidence: Path) -> dict[str, Any]:
    p = evidence / "placement" / "placement.json"
    if not p.is_file():
        return {"status": "ABSENT"}
    doc = _load(p)
    sel = doc.get("selection", {})
    if not sel.get("selected_ngl"):
        return {"status": "NO_LEGAL_GEOMETRY", "attempts":
                [(a.get("ngl"), a.get("loaded")) for a in
                 doc.get("attempts", [])]}
    attempts = doc.get("attempts", [])
    by_ngl = {a.get("ngl"): a for a in attempts}
    chosen = by_ngl.get(sel["selected_ngl"])
    if not chosen or not chosen.get("loaded"):
        return {"status": "SELECTION_INCONSISTENT"}
    exc = chosen.get("excluded_die_mem_delta_bytes", {})
    exc_vram = max((v for k, v in exc.items() if "vram_used" in k),
                   default=0)
    sel_mem = chosen.get("selected_die_mem_delta_bytes", {})
    sel_vram = max((v for k, v in sel_mem.items() if "vram_used" in k),
                   default=0)
    problems = []
    if sel_vram <= 0:
        problems.append("zero_selected_die_residency")
    if exc_vram >= rc.EXCLUDED_DIE_MAX_BYTES:
        problems.append("excluded_die_active")
    if sel.get("headroom_bytes") is not None and \
            sel["headroom_bytes"] < 0:
        problems.append("headroom_violation")
    if problems:
        return {"status": "ILLEGAL", "problems": problems}
    return {
        "status": "FROZEN",
        "ngl": sel["selected_ngl"],
        "selected_die_model_bytes": sel.get("selected_die_model_bytes"),
        "excluded_die_model_bytes": exc_vram,
        "headroom_bytes": sel.get("headroom_bytes"),
        "attempts_retained": len(attempts),
    }


def reduce_ladder(evidence: Path) -> dict[str, Any]:
    p = evidence / "candidate" / "ladder.json"
    if not p.is_file():
        return {"status": "ABSENT"}
    doc = _load(p)
    results = doc.get("results", {})
    out: dict[str, Any] = {"halted": doc.get("halted"),
                           "cases": {}, "deterministic": None}
    any_fail = None
    escalation_ok = True
    prev_pass = True
    for case_id in rc.LADDER_CASES:
        r = results.get(case_id)
        if r is None:
            out["cases"][case_id] = {"status": "ABSENT"}
            escalation_ok = False
            continue
        status = r.get("status")
        repeats = r.get("repeats", [])
        toks = [rep["observation"]["generated_tokens"] for rep in repeats]
        stops = [rep["observation"]["stop_type"] for rep in repeats]
        deterministic = all(t == toks[0] for t in toks) and \
            all(s == stops[0] for s in stops)
        out["cases"][case_id] = {
            "status": status,
            "repeats_retained": len(repeats),
            "deterministic": deterministic,
            "first_divergence": (
                repeats[0]["comparison"]["first_divergence"]
                if repeats else None),
        }
        if status in ("FAIL", "FAIL_DETERMINISTIC",
                      "FAIL_NONDETERMINISTIC") and any_fail is None:
            any_fail = case_id
        if status == "NOT_EXECUTED" and prev_pass:
            escalation_ok = False
        prev_pass = status == "PASS"
    out["escalation_rule_ok"] = escalation_ok
    out["first_failing_case"] = any_fail
    out["status"] = "PRESENT"
    return out


def reduce_health(evidence: Path) -> dict[str, Any]:
    p = evidence / "candidate" / "ladder.json"
    if not p.is_file():
        return {"status": "ABSENT"}
    doc = _load(p)
    h = doc.get("health", {})
    stops: list[str] = []
    for case_id, r in doc.get("results", {}).items():
        for s in r.get("health_window", {}).get("stop_classes", []):
            stops.append(f"{case_id}:{s}")
    for s in h.get("journal_final", {}).get("stop_classes", []):
        stops.append(f"final:{s}")
    delta = h.get("delta", {})
    uncorrectable = sum(
        v for k, v in delta.get("selected_aer", {}).items()
        if k.startswith("unc_") and v > 0)
    uncorrectable += sum(
        v for k, v in delta.get("excluded_aer", {}).items()
        if k.startswith("unc_") and v > 0)
    if uncorrectable:
        stops.append(f"aer:uncorrectable_delta={uncorrectable}")
    link_change = None
    lb, la = delta.get("selected_link_before", {}), \
        delta.get("selected_link_after", {})
    if lb and la and lb.get("current_link_width") != \
            la.get("current_link_width"):
        link_change = {
            "before": lb.get("current_link_width"),
            "after": la.get("current_link_width")}
    vram_released = h.get("post_exit", {}).get("vram_released")
    return {
        "status": "CLEAN" if not stops and not link_change else "FAULT",
        "stop_classes": sorted(set(stops)),
        "link_change": link_change,
        "vram_released": vram_released,
        "correctable_rxerr_lines": h.get("journal_final", {}).get(
            "correctable_rxerr_lines"),
    }


def derive_terminal(evidence: Path, closure: dict[str, Any] | None = None
                    ) -> dict[str, Any]:
    """Exactly one terminal, derived deterministically."""
    checks: dict[str, Any] = {}
    basis: list[str] = []

    authority = reduce_authority(evidence)
    checks["authority"] = {"ok": True, "merges":
                           list(authority.get("predecessor_merges", {}))}

    backing = reduce_backing(evidence)
    runtime = reduce_runtime(evidence)
    placement = reduce_placement(evidence)
    ladder = reduce_ladder(evidence)
    health_r = reduce_health(evidence)

    checks["backing"] = {"status": backing["status"]}
    checks["runtime"] = {"status": runtime["status"]}
    checks["placement"] = {"status": placement["status"]}
    checks["ladder"] = ladder
    checks["health"] = health_r

    terminal: str
    if closure is not None and not closure.get("closure_digest"):
        terminal = TERMINAL_BLOCKED
        basis.append("producer closure missing")
    elif backing["status"] == "ABSENT":
        # bytes could not be staged/verified on the host
        terminal = (TERMINAL_BACKING_PREREQ if runtime["status"] in
                    ("QUALIFIED",) else TERMINAL_RUNTIME_PREREQ)
        basis.append(f"backing {backing['status']}; runtime "
                     f"{runtime['status']}")
    elif backing["status"] in ("MISMATCH", "INCOMPLETE", "TOTAL_MISMATCH"):
        terminal = TERMINAL_BACKING_PREREQ
        basis.append(f"backing {backing['status']}")
    elif runtime["status"] in ("ABSENT", "PREREQUISITE"):
        terminal = TERMINAL_RUNTIME_PREREQ
        basis.append(f"runtime {runtime['status']}: "
                     f"{runtime.get('problems', ['absent'])}")
    elif placement["status"] == "ABSENT":
        terminal = TERMINAL_BLOCKED
        basis.append("placement evidence absent")
    elif placement["status"] in ("NO_LEGAL_GEOMETRY", "ILLEGAL",
                                 "SELECTION_INCONSISTENT"):
        checks["placement"]["problems"] = placement.get("problems", [])
        terminal = TERMINAL_RUNTIME_PREREQ
        basis.append(f"placement {placement['status']}: "
                     f"{placement.get('problems', '')}")
    elif health_r["status"] == "FAULT" and ladder["status"] == "ABSENT":
        terminal = TERMINAL_PLATFORM_FAIL
        basis.append(f"platform fault before correctness: "
                     f"{health_r['stop_classes']}")
    elif ladder["status"] == "ABSENT":
        terminal = TERMINAL_BLOCKED
        basis.append("no candidate execution evidence")
    elif health_r["status"] == "FAULT":
        terminal = TERMINAL_PLATFORM_FAIL
        basis.append(f"platform fault classes: {health_r['stop_classes']}")
    else:
        failed = ladder["first_failing_case"]
        if failed is None and all(
                c["status"] == "PASS" and c["deterministic"]
                for c in ladder["cases"].values()):
            restart = reduce_restart(evidence)
            checks["restart"] = restart
            if restart.get("status") == "PASS":
                terminal = TERMINAL_PASS
                basis.append("all 4 cases exact + deterministic; "
                             "restart stable; platform clean")
            elif restart.get("status") == "ABSENT":
                terminal = TERMINAL_BLOCKED
                basis.append("ladder passed but restart control absent")
            else:
                terminal = TERMINAL_CORRECTNESS_FAIL
                basis.append(f"restart control {restart.get('status')}")
        elif failed is not None:
            terminal = TERMINAL_CORRECTNESS_FAIL
            div = ladder["cases"][failed].get("first_divergence")
            det = ladder["cases"][failed].get("deterministic")
            basis.append(f"{failed} "
                         f"{'deterministic' if det else 'NONdeterministic'} "
                         f"difference from reference: {div}")
        else:
            terminal = TERMINAL_CORRECTNESS_FAIL
            basis.append("nondeterministic repeat or non-PASS case "
                         "without clean platform fault")

    doc = {
        "schema": "inferswarm.r8h.terminal-reduction/1",
        "campaign": rc.CAMPAIGN_ID,
        "terminal": terminal,
        "terminal_basis": basis,
        "checks": checks,
    }
    return doc


def reduce_restart(evidence: Path) -> dict[str, Any]:
    p = evidence / "candidate" / "restart.json"
    if not p.is_file():
        return {"status": "ABSENT"}
    doc = _load(p)
    cases = doc.get("results", {})
    out: dict[str, Any] = {"status": None, "cases": {}}
    all_ok = True
    for case_id, r in cases.items():
        ref = r.get("reference")
        obs = r.get("observation", {})
        ok = (obs.get("generated_tokens") ==
              (ref or {}).get("generated_tokens") and
              obs.get("stop_type") == (ref or {}).get("stop_type"))
        out["cases"][case_id] = {"exact": ok}
        all_ok = all_ok and ok
    placement_ok = doc.get("placement_identity_equivalent") is True
    out["placement_identity_equivalent"] = placement_ok
    out["status"] = "PASS" if all_ok and placement_ok else "FAIL"
    return out


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--evidence", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    doc = derive_terminal(args.evidence)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(doc["terminal"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
