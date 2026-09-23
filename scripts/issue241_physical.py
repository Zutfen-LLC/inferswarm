#!/usr/bin/env python3
"""Exact-head-gated #241 physical producer; dormant until maintainer dispatch.

Evidence lives outside the Git checkout, allowing fresh clean-HEAD and live
PR/review validation before every retained execution unit.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_constants as C
import issue241_census as census
import issue241_dispatch as dispatch
import issue241_host_producer as host
import issue241_placement as placement
import issue241_placement_producer as place_producer
import issue241_comparator_producer as cmp_producer

PHYSICAL_SCHEMA = "inferswarm.issue241.physical-campaign-receipt/2"
PR_NUMBER = 242
GATED_OPERATION_ATTRS = ("_load_fixture_content", "_probe_devices",
                         "_build_server", "_placement_probe", "_run_inference")


def _head(authority: dict[str, Any] | None) -> str:
    if not isinstance(authority, dict) or authority.get("schema") != dispatch.AUTHORITY_SCHEMA:
        raise RuntimeError("explicit validated dispatch authority required")
    head = authority.get("head_sha")
    if not isinstance(head, str) or not dispatch.SHA40.fullmatch(head):
        raise RuntimeError("exact dispatch head required")
    if (authority.get("review_commit_id") != head
            or authority.get("dispatch_phrase") != dispatch.DISPATCH_PHRASE
            or authority.get("pr_number") != PR_NUMBER
            or authority.get("issue_number") != C.ISSUE):
        raise RuntimeError("dispatch review binding invalid")
    return head


def require_dispatch_authority(repo_root: Path, pr_number: int = PR_NUMBER,
                               fetch: Callable[..., Any] | None = None) -> dict[str, Any]:
    if pr_number != PR_NUMBER:
        raise ValueError("physical execution restricted to PR #242")
    if fetch is None:
        authority = dispatch.require_live_dispatch(repo_root, pr_number)
    else:
        head = dispatch.current_clean_git_head(repo_root)
        authority = fetch(pr_number, head)
    _head(authority)
    return authority


def _revalidate(repo_root: Path, authority: dict[str, Any]) -> dict[str, Any]:
    head = _head(authority)
    fresh = require_dispatch_authority(repo_root)
    if fresh != authority or fresh["head_sha"] != head:
        raise RuntimeError("dispatch revoked or producer HEAD moved")
    return fresh


def _out(repo_root: Path, evidence_root: Path | None) -> Path:
    if evidence_root is None:
        raise ValueError("external evidence_root required")
    root, out = Path(repo_root).resolve(), Path(evidence_root).absolute()
    if out == root or root in out.parents:
        raise ValueError("evidence must stay outside clean producer worktree")
    if out.is_symlink() or any(p.is_symlink() for p in out.parents):
        raise ValueError("evidence root alias rejected")
    return out


def _atomic_json(path: Path, receipt: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to overwrite evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".pending")
    with temp.open("xb") as stream:
        stream.write((json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def _receipt(kind: str, authority: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {"schema": PHYSICAL_SCHEMA, "campaign": C.CAMPAIGN_ID,
            "kind": kind, "dispatch_authority": authority,
            "dispatch_head_sha": _head(authority),
            "physical_execution_performed": True, **fields}


def _phase1_receipt(path: Path, authority: dict[str, Any]) -> dict[str, Any]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Phase-1 census receipt missing or aliased")
    receipt = json.loads(path.read_bytes())
    if (receipt.get("schema") != PHYSICAL_SCHEMA
            or receipt.get("kind") != "phase1-census"
            or receipt.get("dispatch_authority") != authority
            or receipt.get("dispatch_head_sha") != _head(authority)):
        raise ValueError("Phase-1 census authority mismatch")
    observed = receipt.get("census")
    if not isinstance(observed, dict) or not isinstance(observed.get("census"), dict):
        raise ValueError("Phase-1 measured census missing")
    if observed.get("verdict") != census.validate_census(observed["census"]):
        raise ValueError("Phase-1 census verdict not derived from measured fields")
    captured = observed["census"].get("raw")
    hashes = observed["census"].get("raw_artifact_sha256")
    raw_root = path.parent / "census" / "raw"
    if (observed["census"].get("out_dir") != str(path.parent / "census")
            or not isinstance(captured, dict) or not captured
            or not isinstance(hashes, dict) or set(captured) != set(hashes)):
        raise ValueError("Phase-1 raw command custody missing")
    for key, command in captured.items():
        if not isinstance(key, str) or not key or "/" in key or key in (".", ".."):
            raise ValueError("Phase-1 raw command key invalid")
        artifact = raw_root / (key + ".json")
        if artifact.is_symlink() or not artifact.is_file():
            raise ValueError("Phase-1 raw command artifact missing/aliased")
        data = artifact.read_bytes()
        if hashlib.sha256(data).hexdigest() != hashes[key] or json.loads(data) != command:
            raise ValueError("Phase-1 raw command artifact differs from receipt")
    return receipt


def _build_receipt(path: Path, authority: dict[str, Any], server: Path) -> dict[str, Any]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Phase-2 comparator build receipt missing/aliased")
    doc = json.loads(path.read_bytes())
    binary = doc.get("binary")
    if (doc.get("schema") != "inferswarm.issue241.comparator-v2-build/1"
            or doc.get("dispatch_authority") != authority
            or doc.get("producer_head_sha") != _head(authority)
            or doc.get("source_pin") != C.LLAMA_CPP_PIN
            or doc.get("source_head") != C.LLAMA_CPP_PIN
            or doc.get("patched_source_sha256") != C.OBSERVER_PATCHED_SOURCE_SHA256
            or doc.get("cmake_flags") != C.OBSERVER_BUILD_FLAGS
            or not isinstance(binary, dict)
            or binary.get("path") != str(server)):
        raise ValueError("Phase-2 build/dispatch identity mismatch")
    server = Path(server)
    if server.is_symlink() or not server.is_file():
        raise ValueError("Phase-3 executable missing/aliased")
    if hashlib.sha256(server.read_bytes()).hexdigest() != binary.get("sha256"):
        raise ValueError("Phase-3 executable differs from Phase-2 built binary")
    source = Path(doc.get("worktree", "")) / "tools/server/server-context.cpp"
    if source.is_symlink() or not source.is_file():
        raise ValueError("patched source custody missing/aliased")
    if hashlib.sha256(source.read_bytes()).hexdigest() != doc["patched_source_sha256"]:
        raise ValueError("built patched source differs from frozen source")
    package = doc.get("package")
    if not isinstance(package, dict):
        raise ValueError("build package identity missing")
    package_file = Path(package.get("path", ""))
    if package_file.is_symlink() or not package_file.is_file():
        raise ValueError("build package missing/aliased")
    if hashlib.sha256(package_file.read_bytes()).hexdigest() != package.get("sha256"):
        raise ValueError("build package digest mismatch")
    return doc


def _load_fixture_content(case_id: str, *, authority: dict[str, Any]) -> dict[str, Any]:
    _head(authority)
    C.assert_historical_only(case_id)
    if case_id not in C.FIXTURE_CASES:
        raise RuntimeError("case outside bounded historical fixtures")
    return C.load_fixtures(C.ROOT)[case_id]


def _probe_devices(*, authority: dict[str, Any], runner: Any,
                   repo_root: Path, evidence_root: Path) -> dict[str, Any]:
    _head(authority)
    return host.collect_census(repo_root, runner, authority,
                               out_dir=evidence_root / "phase1" / "census")


def _build_server(*, authority: dict[str, Any], runner: Any,
                  source_tree: Path, repo_root: Path) -> dict[str, Any]:
    _head(authority)
    patch = repo_root / "docs/investigations/qwen38-flash-next-r8-e/evidence/instrumentation/applied-source.patch"
    return host.build_comparator(source_tree, patch, runner, authority)


def _placement_probe(*, authority: dict[str, Any], repo_root: Path,
                     evidence_root: Path, server: Path, runner: Any) -> dict[str, Any]:
    _head(authority)
    return place_producer.run_phase2_producer(
        repo_root, evidence_root / "phase2", server, authority,
        runner=runner, model=C.MODEL_DIR / C.MODEL_MEMBERS[0],
        revalidate_authority=lambda old: _revalidate(repo_root, old))


def _selected_receipt(path: Path, authority: dict[str, Any]) -> dict[str, Any]:
    """Re-derive matched ngl from both arms' digest-bound raw server logs."""
    _head(authority)
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Phase-2 selected placement receipt missing/aliased")
    doc = json.loads(path.read_bytes())
    if (doc.get("schema") != place_producer.SCHEMA
            or doc.get("authority") != authority
            or doc.get("campaign") != C.CAMPAIGN_ID):
        raise ValueError("Phase-2 selected placement authority mismatch")
    rows = doc.get("rung_receipts")
    if not isinstance(rows, list) or len(rows) != len(C.LADDER_NGLS) * 2:
        raise ValueError("Phase-2 must measure both arms at all five rungs")
    by_arm: dict[str, list[dict[str, Any]]] = {"B": [], "C": []}
    for i, row in enumerate(rows):
        ngl, arm = C.LADDER_NGLS[i // 2], ("C", "B")[i % 2]
        if row.get("ngl") != ngl or row.get("arm") != arm:
            raise ValueError("Phase-2 arms must share rung C then B")
        rel = row.get("raw_log")
        if not isinstance(rel, str) or Path(rel).name != rel:
            raise ValueError("Phase-2 raw log path invalid")
        log_path = path.parent / rel
        if log_path.is_symlink() or not log_path.is_file():
            raise ValueError("Phase-2 raw server log missing")
        raw = log_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row.get("raw_log_sha256"):
            raise ValueError("Phase-2 server log digest mismatch")
        telemetry_rel = row.get("raw_telemetry")
        if not isinstance(telemetry_rel, str) or Path(telemetry_rel).name != telemetry_rel:
            raise ValueError("Phase-2 raw telemetry path invalid")
        telemetry_path = path.parent / telemetry_rel
        if telemetry_path.is_symlink() or not telemetry_path.is_file():
            raise ValueError("Phase-2 raw process/device telemetry missing")
        telemetry_bytes = telemetry_path.read_bytes()
        if hashlib.sha256(telemetry_bytes).hexdigest() != row.get("raw_telemetry_sha256"):
            raise ValueError("Phase-2 raw telemetry digest mismatch")
        if row.get("process") != json.loads(telemetry_bytes):
            raise ValueError("Phase-2 summarized process differs from raw telemetry")
        recorded = doc.get("rungs", {}).get(arm, [])
        if len(recorded) <= i // 2:
            raise ValueError("Phase-2 rung measurement missing")
        process = row.get("process")
        if not isinstance(process, dict) or process.get("synthetic") is True:
            raise ValueError("Phase-2 unmeasured/synthetic process refused")
        response_rel = row.get("raw_response")
        if not isinstance(response_rel, str) or Path(response_rel).name != response_rel:
            raise ValueError("Phase-2 raw response path invalid")
        response_path = path.parent / response_rel
        if response_path.is_symlink() or not response_path.is_file():
            raise ValueError("Phase-2 raw response missing/aliased")
        response_raw = response_path.read_bytes()
        if hashlib.sha256(response_raw).hexdigest() != row.get("raw_response_sha256"):
            raise ValueError("Phase-2 raw response digest mismatch")
        place_producer._measurement({**process, "response_raw": response_raw}, arm)
        succeeded = (process.get("returncode") == 0
                     and process.get("http_status") == 200
                     and not process.get("failure"))
        if succeeded and (not process.get("proc_status") or not process.get("proc_io")
                          or not process.get("gpu_telemetry", {}).get("samples")):
            raise ValueError("Phase-2 successful rung missing process/device samples")
        rung = recorded[i // 2]
        if (rung.get("excluded_device_residency_mib") != process.get("excluded_device_residency_mib")
                or rung.get("loaded") is not succeeded):
            raise ValueError("Phase-2 rung differs from measured telemetry")
        if (rung.get("placement") != json.loads(json.dumps(placement.parse_placement(raw.decode(errors="replace"))))
                or rung.get("arm") != arm or rung.get("ngl") != ngl
                or row.get("verdict") != placement.judge_rung(rung)):
            raise ValueError("Phase-2 measurement not derived from raw evidence")
        # INDEPENDENT re-derivation of determinism/health/identity from
        # digest-bound raw artifacts (never the summary booleans):
        #  * every retained repeat's raw response is re-read, re-hashed,
        #    and required to equal its claimed digest, to carry exactly the
        #    expected token count/type, and to be byte-identical across
        #    repeats (independently computed digests equal);
        #  * per-rung device identity and health observations must be
        #    present and identical pre/post execution and must satisfy the
        #    frozen subject identity predicate;
        #  * the health artifact must carry the mandatory observed fields.
        repeats = row.get("repeats")
        if not isinstance(repeats, list) or len(repeats) != place_producer.RUNG_REPEATS:
            raise ValueError("Phase-2 rung lacks the bounded repeat evidence")
        repeat_digests: list[str] = []
        for rep in repeats:
            rep_rel = rep.get("response_raw")
            if not isinstance(rep_rel, str) or Path(rep_rel).name != rep_rel:
                raise ValueError("Phase-2 repeat raw response path invalid")
            rep_path = path.parent / rep_rel
            if rep_path.is_symlink() or not rep_path.is_file():
                raise ValueError("Phase-2 repeat raw response missing/aliased")
            rep_bytes = rep_path.read_bytes()
            if hashlib.sha256(rep_bytes).hexdigest() != rep.get("response_raw_sha256"):
                raise ValueError("Phase-2 repeat raw response digest mismatch")
            sane, tokens = place_producer._sane_completion(rep_bytes)
            # Summary-vs-raw CONSISTENCY: the retained summary booleans must
            # match what the digest-bound raw response actually shows. A
            # legitimately-failed/nondeterministic rung is simply invalid
            # (judge_rung records the problem and selection falls back); a
            # FORGED summary that disagrees with the raw evidence is a hard
            # integrity failure and stops the campaign.
            if sane != (rep.get("sane_completion") is True) or tokens != rep.get("response_tokens"):
                raise ValueError(
                    "Phase-2 repeat sane-completion summary differs from "
                    "the retained raw response")
            rep_log_rel = rep.get("raw_log")
            if not isinstance(rep_log_rel, str) or Path(rep_log_rel).name != rep_log_rel:
                raise ValueError("Phase-2 repeat raw log path invalid")
            rep_log = path.parent / rep_log_rel
            if rep_log.is_symlink() or not rep_log.is_file():
                raise ValueError("Phase-2 repeat raw log missing/aliased")
            if hashlib.sha256(rep_log.read_bytes()).hexdigest() != rep.get("raw_log_sha256"):
                raise ValueError("Phase-2 repeat raw log digest mismatch")
            rep_tel_rel = rep.get("raw_telemetry")
            if not isinstance(rep_tel_rel, str) or Path(rep_tel_rel).name != rep_tel_rel:
                raise ValueError("Phase-2 repeat raw telemetry path invalid")
            rep_tel = path.parent / rep_tel_rel
            if rep_tel.is_symlink() or not rep_tel.is_file():
                raise ValueError("Phase-2 repeat raw telemetry missing/aliased")
            if hashlib.sha256(rep_tel.read_bytes()).hexdigest() != rep.get("raw_telemetry_sha256"):
                raise ValueError("Phase-2 repeat raw telemetry digest mismatch")
            repeat_digests.append(hashlib.sha256(rep_bytes).hexdigest())
        if len(set(repeat_digests)) != 1:
            raise ValueError(
                "Phase-2 retained repeats are not byte-identical — "
                "determinism does not hold at this rung")
        if rung.get("repeats") != repeats:
            raise ValueError("Phase-2 rung repeat evidence differs from receipts")
        for identity_field in ("device_identity", "post_execution_device_identity"):
            observed = row.get(identity_field)
            if not isinstance(observed, dict) or not observed:
                raise ValueError(f"Phase-2 {identity_field} observation missing")
            problems = census.identity_problems(arm, observed)
            if problems:
                raise ValueError(
                    f"Phase-2 {identity_field} frozen-subject drift: {problems}")
        if row.get("device_identity") != rung.get("device_identity") or \
                row.get("post_execution_device_identity") != rung.get("post_execution_device_identity"):
            raise ValueError("Phase-2 rung identity differs from receipt observation")
        health = row.get("device_health")
        if not isinstance(health, dict) or health != rung.get("device_health"):
            raise ValueError("Phase-2 device-health artifact missing or divergent")
        observed_health = health.get("observed")
        if not isinstance(observed_health, dict) or not {
                "selected_device_present", "driver_in_use", "vulkan_icd",
                "bdf"}.issubset(observed_health):
            raise ValueError("Phase-2 device health lacks mandatory evidence")
        if health.get("fatal_states"):
            raise ValueError(
                f"Phase-2 fatal device/driver health state at {arm} ngl={ngl}: "
                f"{health['fatal_states']}")
        by_arm[arm].append(rung)
    selected = placement.select_matched_rung(by_arm)
    if (doc.get("selected") != selected or selected.get("placement_blocked")
            or selected.get("matched_ngl") is None):
        raise ValueError("Phase-2 selected ngl missing or forged")
    return doc


def _run_inference(*, authority: dict[str, Any], repo_root: Path,
                   evidence_root: Path, server: Path, selected: dict[str, Any],
                   runner: Any, canonical_server: Path) -> dict[str, Any]:
    _head(authority)
    return cmp_producer.run_phase3_producer(
        repo_root, evidence_root / "phase3", server, selected, authority, runner,
        canonical_server=canonical_server,
        revalidate_authority=lambda old: _revalidate(repo_root, old))


def run_phase1(repo_root: Path, pr_number: int = PR_NUMBER,
               fetch: Callable[..., Any] | None = None, *,
               evidence_root: Path | None = None, runner: Any = None) -> dict[str, Any]:
    authority = require_dispatch_authority(repo_root, pr_number, fetch)
    out = _out(repo_root, evidence_root)
    runner = runner if runner is not None else host.SubprocessRunner()
    authority = _revalidate(repo_root, authority)
    observed = _probe_devices(authority=authority, runner=runner,
                              repo_root=Path(repo_root), evidence_root=out)
    receipt = _receipt("phase1-census", authority, census=observed)
    _atomic_json(out / "phase1" / "census-receipt.json", receipt)
    return receipt


def run_phase2(repo_root: Path, pr_number: int = PR_NUMBER,
               fetch: Callable[..., Any] | None = None, *,
               evidence_root: Path | None = None, source_tree: Path | None = None,
               build_runner: Any = None, run_runner: Any = None) -> dict[str, Any]:
    authority = require_dispatch_authority(repo_root, pr_number, fetch)
    out = _out(repo_root, evidence_root)
    if source_tree is None:
        raise ValueError("pinned source tree required")
    build_runner = build_runner if build_runner is not None else host.SubprocessRunner()
    _phase1_receipt(out / "phase1" / "census-receipt.json", authority)
    authority = _revalidate(repo_root, authority)
    build = _build_server(authority=authority, runner=build_runner,
                          source_tree=source_tree, repo_root=Path(repo_root))
    _atomic_json(out / "phase2" / "build-receipt.json", build)
    authority = _revalidate(repo_root, authority)
    placed = _placement_probe(authority=authority, repo_root=Path(repo_root),
                              evidence_root=out, server=Path(build["binary"]["path"]),
                              runner=run_runner)
    return _receipt("phase2-placement", authority, build=build, selected=placed["selected"])


def run_phase3(repo_root: Path, pr_number: int = PR_NUMBER,
               fetch: Callable[..., Any] | None = None, *,
               evidence_root: Path | None = None, selected_path: Path | None = None,
               server: Path | None = None, canonical_server: Path | None = None,
               runner: Any = None) -> dict[str, Any]:
    authority = require_dispatch_authority(repo_root, pr_number, fetch)
    if selected_path is None or server is None or canonical_server is None:
        raise ValueError("Phase-3 requires Phase-2 selection, executable, and canonical no-hook binary")
    out = _out(repo_root, evidence_root)
    expected_selected = out / "phase2" / "phase2-placement-receipt.json"
    if Path(selected_path).absolute() != expected_selected:
        raise ValueError("Phase-3 selection must be the campaign Phase-2 artifact")
    _build_receipt(out / "phase2" / "build-receipt.json", authority, server)
    selected = _selected_receipt(expected_selected, authority)
    authority = _revalidate(repo_root, authority)
    result = _run_inference(authority=authority, repo_root=Path(repo_root),
                            evidence_root=out, server=server, selected=selected,
                            runner=runner, canonical_server=canonical_server)
    return _receipt("phase3-comparator-v2", authority,
                    matched_ngl=selected["selected"]["matched_ngl"],
                    measurements=result.get("measurements"), result=result)


def physical_entrypoints() -> tuple[str, ...]:
    return ("run_phase1", "run_phase2", "run_phase3")
