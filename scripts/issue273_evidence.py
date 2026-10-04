#!/usr/bin/env python3
"""Successor #273 serialized custody producer and authenticated terminal.

See docs/investigations/issue273-retained-producer.md for the wire layout,
independent capture-seal protocol, observation contract and trust boundary.
No hardware discovery/execution and no legacy evidence mutation occur here.
All verifiers operate on a no-follow snapshot of actual retained bytes.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

import issue270_authority as C
import issue270_comparator as K
import issue270_physical as P
import issue270_terminal as T
import issue273_admission as A
import issue273_reducer as R

CAMPAIGN = "issue273-r8i6a-v340-comparator2-corrective"
RUN_SCHEMA = "inferswarm.issue273.captured-run/1"
OBSERVATION_SCHEMA = "inferswarm.issue273.raw-run-observation/1"
FREEZE_SCHEMA = "inferswarm.issue273.subject-freeze/1"
SEAL_PHRASE = "R8I6A CORRECTIVE CAPTURE SEAL"
CORRECTIVE_PR = 274
PREDECESSOR = "6d594eafd5ee16a640f029f63ebdd2cd96856abb"
AUTHORITY_PATHS = (
    "scripts/issue270_authority.py", "scripts/issue270_comparator.py",
    "scripts/issue270_terminal.py", "scripts/issue248_identity.py",
    "scripts/issue250_diagnostic.py", "scripts/issue250_physical.py",
    "scripts/issue248_health.py", "scripts/issue250_terminal.py", "scripts/issue250_timeout.py",
    C.FIXTURE_LADDER_REL, C.R8I4_CENSUS_REL, C.R8I4_CONSTANTS_REL,
)
PRODUCER_PATHS = (
    "scripts/issue273_evidence.py", "scripts/issue273_reducer.py",
    "scripts/issue273_admission.py", "scripts/issue270_physical.py",
)
DECISION_SET = {str(d) for d in range(C.DECISIONS)}
BUILD_FLAGS = ["-DGGML_VULKAN=ON", "-DGGML_CUDA=OFF"]
BASE_PATHS = {"authority.json", "freeze.json", "preflight.json"}


class EvidenceError(RuntimeError):
    """Missing, unauthenticated, or semantically invalid custody."""


class InfrastructureError(EvidenceError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(doc: Any) -> bytes:
    return (json.dumps(doc, sort_keys=True, indent=2) + "\n").encode()


def require(ok: Any, message: str) -> None:
    if not ok:
        raise EvidenceError(message)


def timestamp(value: Any) -> dt.datetime:
    require(isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value), "UTC timestamp missing/malformed")
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def safe_root(root: Path) -> Path:
    root = Path(root).absolute()
    for part in (*reversed(root.parents), root):
        require(not part.is_symlink(), f"symlink evidence ancestor: {part}")
    require(root.is_dir(), f"evidence root missing: {root}")
    return root


def read_regular(path: Path | str, *, dir_fd: int | None = None) -> bytes:
    """No-follow, single-link, stable-descriptor byte read (no digest claims)."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                f"nonregular/hardlinked evidence: {path}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read()
        after = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                 before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                                        after.st_mtime_ns, after.st_ctime_ns),
                f"evidence changed during read: {path}")
        return data
    finally:
        os.close(fd)


def snapshot(root: Path) -> dict[str, bytes]:
    """Open every ancestor/directory by held no-follow descriptors.

    An adversary replacing an intermediate directory with a symlink cannot
    redirect a later file open. Directory mutations invalidate the snapshot.
    """
    root = safe_root(root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for part in root.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        files: dict[str, bytes] = {}
        directories = set()
        def walk(directory_fd: int, prefix: str) -> None:
            before = os.fstat(directory_fd)
            for name in sorted(os.listdir(directory_fd)):
                rel = f"{prefix}/{name}" if prefix else name
                mode = os.stat(name, dir_fd=directory_fd, follow_symlinks=False).st_mode
                require(not stat.S_ISLNK(mode), f"symlink evidence entry: {rel}")
                if stat.S_ISDIR(mode):
                    directories.add(rel)
                    child = os.open(name, flags, dir_fd=directory_fd)
                    try:
                        walk(child, rel)
                    finally:
                        os.close(child)
                else:
                    files[rel] = read_regular(name, dir_fd=directory_fd)
            after = os.fstat(directory_fd)
            require((before.st_ino, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_ino, after.st_mtime_ns, after.st_ctime_ns),
                    "evidence directory changed during snapshot")
        walk(fd, "")
        expected_dirs = {str(parent) for name in files
                         for parent in PurePosixPath(name).parents if str(parent) != "."}
        require(directories == expected_dirs, "extra/empty evidence directories")
        return files
    finally:
        os.close(fd)


def parse(data: bytes) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out = {}
        for key, value in pairs:
            require(key not in out, f"duplicate JSON field {key!r}")
            out[key] = value
        return out
    doc = json.loads(data, object_pairs_hook=unique_pairs,
                     parse_constant=lambda x: (_ for _ in ()).throw(EvidenceError(f"nonfinite JSON {x}")))
    require(isinstance(doc, dict), "evidence JSON is not an object")
    return doc


def expected_paths(include_candidate: bool = True) -> set[str]:
    paths = set(BASE_PATHS)
    for arm in (("reference", "candidate") if include_candidate else ("reference",)):
        for case in C.FIXTURE_CASES:
            for tag in (arm, arm + "-repeat"):
                paths.update({f"source/{case}/{tag}/receipt.json",
                              f"source/{case}/{tag}/observation.json",
                              f"units/{case}/{tag}.json"})
                for d in DECISION_SET:
                    paths.update({f"source/{case}/{tag}/rows/{d}.f32",
                                  f"units/{case}/{tag}/rows/{d}.f32"})
    return paths


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)


def authority_contract(repo_root: Path, head: str, dispatch: dict[str, Any]) -> dict[str, Any]:
    """Select authority from exact Git lineage/accepted constants, not root pins."""
    repo_root = safe_root(Path(repo_root))
    require(re.fullmatch(r"[0-9a-f]{40}", head or ""), "exact head malformed")
    require(_git(repo_root, "rev-parse", "HEAD").decode().strip() == head, "repository head drift")
    for predecessor in (PREDECESSOR, C.ACCEPTED_237_MERGE):
        _git(repo_root, "merge-base", "--is-ancestor", predecessor, head)
    closed = {}
    reader = K.custody_row_reader(repo_root)
    for rel in AUTHORITY_PATHS + PRODUCER_PATHS:
        actual = reader(rel)
        require(actual == _git(repo_root, "show", f"{head}:{rel}"), f"uncommitted producer/authority: {rel}")
        if rel in AUTHORITY_PATHS:
            require(actual == _git(repo_root, "show", f"{PREDECESSOR}:{rel}"), f"frozen predecessor redefined: {rel}")
        closed[rel] = sha(actual)
    P.verify_fixtures(repo_root)
    C.validate_candidate_authority(repo_root / C.R8I4_CENSUS_REL)
    reference = C.reference_identity()
    require(reference["host"] == C.REFERENCE_HOST, "reference predecessor unavailable")
    return {"schema": "inferswarm.issue273.independent-authority/1", "head_sha": head,
            "namespace": R.NAMESPACE_273, "dispatch": dispatch, "predecessor": PREDECESSOR,
            "source_pin": C.LLAMA_SOURCE_PIN, "source_tree": C.ACCEPTED_LLAMA_SOURCE_TREE,
            "comparator_sha256": C.COMPARATOR_SHA256, "canonical_sha256": C.CANONICAL_SHA256,
            "observer_libs": C.OBSERVER_LIBS, "model_members": C.MODEL_MEMBER_SHA256,
            "fixture_ladder_sha256": C.FIXTURE_LADDER_SHA256,
            "reference_identity": reference, "placement": dict(A.ARM_PLACEMENT), "source_closure": closed}


def _context(transport: Any, head: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    dispatch = R.authenticate_dispatch_273(transport, head, CORRECTIVE_PR)
    pull = transport(f"/repos/Zutfen-LLC/inferswarm/pulls/{CORRECTIVE_PR}")
    require(pull.get("base", {}).get("ref") == "main" and
            pull.get("base", {}).get("repo", {}).get("full_name") == "Zutfen-LLC/inferswarm",
            "corrective merge is not this repository's main")
    comments = transport("/repos/Zutfen-LLC/inferswarm/issues/273/comments")
    matches = [c for c in comments if c.get("id") == dispatch["comment_id"]]
    require(len(matches) == 1, "dispatch context ambiguous")
    selected = matches[0]
    require(timestamp(selected.get("created_at")) >= timestamp(pull.get("merged_at")),
            "dispatch predates corrective merge")
    return dispatch, selected, comments


def _seal(comments: list[dict[str, Any]], dispatch: dict[str, Any], manifest: bytes) -> dt.datetime:
    seals = []
    for comment in comments:
        lines = [s.strip() for s in str(comment.get("body", "")).splitlines()]
        if SEAL_PHRASE not in lines:
            continue
        fields = R.dispatch_fields_273(lines)
        if fields.get("head") != dispatch["head_sha"] or fields.get("namespace") != R.NAMESPACE_273:
            continue
        if (comment.get("author_association") not in ("OWNER", "MEMBER") or
                not comment.get("user", {}).get("login")):
            continue
        if fields.get("dispatch_id") == str(dispatch["comment_id"]):
            require(fields.get("manifest_sha256") == sha(manifest), "independent capture seal != retained manifest bytes")
            seals.append(comment)
    require(len(seals) == 1, "exactly one independent maintainer capture seal required")
    require(seals[0].get("id") != dispatch["comment_id"], "capture seal must be independent of dispatch")
    return timestamp(seals[0].get("created_at"))


def _freeze(files: dict[str, bytes], authority: dict[str, Any], dispatch_comment: dict[str, Any],
            *, physical: bool) -> dict[str, Any]:
    freeze = parse(files["freeze.json"])
    require(freeze.get("schema") == FREEZE_SCHEMA, "freeze schema")
    require(freeze.get("head_sha") == authority["head_sha"] and
            freeze.get("namespace") == R.NAMESPACE_273 and
            freeze.get("dispatch_id") == authority["dispatch"]["comment_id"], "freeze dispatch/head/namespace")
    require(freeze.get("authority_sha256") == C.authority_digest(authority), "freeze independent authority mismatch")
    require(freeze.get("placement") == A.ARM_PLACEMENT, "per-arm placement freeze drift")
    require(timestamp(freeze.get("frozen_at")) > timestamp(dispatch_comment.get("created_at")), "freeze predates dispatch")
    require(freeze.get("capture_mode") in ("CPU_RECORDING", "PHYSICAL"), "capture mode missing")
    require(not physical or freeze["capture_mode"] == "PHYSICAL", "CPU recording cannot mint live physical authority")
    preflight = parse(files["preflight.json"])
    selection = T.validate_selector_binding(preflight["selector_binding"], authority["head_sha"], C.COMPARATOR_SHA256)
    normalized = json.loads(json.dumps(selection))
    require(freeze.get("selection") == normalized, "freeze selection != independently derived preflight rule")
    raw = preflight["candidate_raw"]
    require(raw.get("host") == C.CANDIDATE_HOST and raw.get("icd", {}).get("path") == C.RADV_ICD,
            "candidate preflight raw host/ICD")
    require(raw.get("vulkaninfo", {}).get("rc") == 0, "candidate preflight command failed")
    drift = P.identity_problems_vs_frozen(P.derive_v340_identity(raw))
    require(not drift, "candidate preflight identity drift: " + "; ".join(drift))
    return freeze


def _reader(files: dict[str, bytes]):
    def read(rel: str) -> bytes:
        reason = K._reject_row_path(rel)
        require(reason is None, reason or "row path")
        require(rel in files, f"unretained row path {rel!r}")
        return files[rel]
    return read


def _observation(obs: dict[str, Any], receipt: dict[str, Any], arm: str, freeze: dict[str, Any],
                 seal_time: dt.datetime) -> None:
    require(obs.get("schema") == OBSERVATION_SCHEMA, "raw observation schema")
    for field in ("host", "run_id", "session_id", "boot_id", "start_ticks", "process_attribution"):
        require(obs.get(field) == receipt.get(field), f"raw observation/receipt {field} mismatch")
    start, finish = timestamp(receipt.get("started_at")), timestamp(receipt.get("finished_at"))
    observed = timestamp(obs.get("observed_at"))
    frozen_at = timestamp(freeze.get("frozen_at"))
    require(frozen_at < start <= observed < finish <= seal_time, "run/observation/seal freshness mismatch")
    require((finish - frozen_at).total_seconds() <= 86400, "stale capture outside dispatch day")
    require(obs.get("backend") == "Vulkan" and obs.get("icd") == A.ARM_ICD[arm], "raw executed backend/ICD")
    devices = obs.get("devices")
    require(isinstance(devices, list) and len(devices) == 2, "exact selected plus excluded physical GPU census required")
    require(len({d["bdf"] for d in devices}) == 2 and len({d["vulkan_uuid"] for d in devices}) == 2 and
            len({d["index"] for d in devices}) == 2, "ambiguous device census")
    env = receipt["process_attribution"]["server_env"]
    selected = [d for d in devices if d["index"] == env["GGML_VK_VISIBLE_DEVICES"] and d["icd"] == env["VK_ICD_FILENAMES"]]
    require(len(selected) == 1, "selector/ICD does not resolve one observed physical device")
    device = selected[0]
    require(device["bdf"] == receipt["bdf"] and device.get("physical_type") == "DISCRETE_GPU",
            "selected observed BDF/physical-device mismatch")
    require(obs.get("used_device_uuids") == [device["vulkan_uuid"]], "wrong device / CPU fallback / bystander participation")
    excluded = [d for d in devices if d is not device][0]
    require(excluded.get("physical_type") == "DISCRETE_GPU", "excluded census not a physical GPU")
    if arm == "reference":
        identity = C.reference_identity()
        require(obs.get("reference_identity") == identity and receipt.get("subject_identity") == identity,
                "fresh reference facts != accepted #248 identity")
        require(device.get("vendor_id") == "0x10de" and device.get("device_id") == "0x" + identity["pci_id"].split(":")[-1] and
                device.get("gpu_uuid") == identity["gpu_uuid"] and device.get("vulkan_uuid") == identity["vulkan_device_uuid"] and
                device.get("bdf") == identity["bdf"], "reference observed PCI/UUID lineage mismatch")
        require(excluded.get("vendor_id") == "0x1002" and excluded.get("device_id") == "0x67df" and
                "RX 580" in excluded.get("name", "") and excluded.get("icd") == C.RADV_ICD,
                "positive RX580 excluded census absent")
    else:
        selection = freeze["selection"]
        require(device.get("bdf") == selection["selected_bdf"] and device.get("index") == selection["selected_index"] and
                excluded.get("bdf") in selection["excluded_bdfs"], "candidate selector/preflight observed join mismatch")
        for d in devices:
            require(d.get("vendor_id") == C.EXPECTED_CANDIDATE["vendor_id"] and
                    d.get("device_id") == C.EXPECTED_CANDIDATE["device_id"] and d.get("icd") == C.RADV_ICD and
                    d.get("vulkan_uuid") == C.EXPECTED_VULKAN_DEVICE_UUIDS[d["bdf"]], "candidate observed vendor/BDF/UUID drift")
        require(receipt.get("subject_identity") == {"host": C.CANDIDATE_HOST, "bdf": device["bdf"]}, "candidate subject drift")
    residency = obs.get("residency", {})
    require(set(residency) == {d["bdf"] for d in devices}, "positive selected/excluded residency row set")
    for counters in residency.values():
        require(set(counters) == {"before", "peak", "after"} and all(type(v) is int and v >= 0 for v in counters.values()),
                "residency counters malformed")
    selected_delta = residency[device["bdf"]]["peak"] - residency[device["bdf"]]["before"]
    excluded_delta = residency[excluded["bdf"]]["peak"] - residency[excluded["bdf"]]["before"]
    require(selected_delta >= C.EXCLUDED_NOISE_BYTES and 0 <= excluded_delta < C.EXCLUDED_NOISE_BYTES,
            "selected/excluded residency unproven")
    require(receipt.get("excluded_device_residency_bytes") == {excluded["bdf"]: excluded_delta}, "receipt residency labels != raw counters")
    require(all(abs(c["after"] - c["before"]) < C.EXCLUDED_NOISE_BYTES for c in residency.values()), "run reclamation unproven")
    if arm == "candidate":
        require(C.NGL7_RESIDENCY_MIN_BYTES <= selected_delta <= C.NGL7_RESIDENCY_MAX_BYTES, "accepted candidate placement residency drift")
    runtime = obs.get("runtime", {})
    for field, expected in (("exe_sha256", C.COMPARATOR_SHA256), ("source_pin", C.LLAMA_SOURCE_PIN),
                            ("source_tree", C.ACCEPTED_LLAMA_SOURCE_TREE), ("observer_libs", C.OBSERVER_LIBS),
                            ("model_members_open", C.MODEL_MEMBER_SHA256), ("model_members_close", C.MODEL_MEMBER_SHA256)):
        require(runtime.get(field) == expected, f"raw runtime attestation {field} mismatch")
    observer = obs.get("observer", {})
    require(observer.get("canonical_sha256") == C.CANONICAL_SHA256 != C.COMPARATOR_SHA256, "canonical binary identity/distinctness")
    for tokens in (observer.get("disabled_tokens"), observer.get("canonical_tokens")):
        require(isinstance(tokens, list) and len(tokens) == C.DECISIONS and all(type(t) is int and 0 <= t < C.N_VOCAB for t in tokens),
                "observer control tokens missing/malformed")
    require(isinstance(observer.get("disabled_artifacts"), list) and isinstance(observer.get("canonical_artifacts"), list),
            "observer control artifact inventory missing")
    inert = K.validate_inertness(observer["disabled_tokens"], observer["canonical_tokens"],
                               bool(observer["disabled_artifacts"]), bool(observer["canonical_artifacts"]))
    require(inert["inert"], "observer inertness: " + "; ".join(inert["problems"]))
    platform = obs.get("platform", {})
    probes = platform.get("probe_rcs")
    valid = (isinstance(probes, dict) and set(probes) == {"kernel_log", "pcie", "thermal", "storage", "power"} and
             all(type(rc) is int and rc == 0 for rc in probes.values()) and platform.get("errors") == [] and
             platform.get("link_width") == 16 and platform.get("link_speed_gt_s") == 8.0 and
             type(platform.get("temperature_c")) in (int, float) and 0 <= platform["temperature_c"] < 85 and
             platform.get("throttled") is False and type(platform.get("oom_kills")) is int and platform["oom_kills"] == 0)
    if not valid:
        raise InfrastructureError("raw platform health/probe completeness/PCIe/cooling failure")


def _admit(files: dict[str, bytes], case: str, arm: str, repeat: bool, authority: dict[str, Any],
           freeze: dict[str, Any], seal_time: dt.datetime, seen: dict[str, set[Any]]) -> dict[str, Any]:
    tag = arm + ("-repeat" if repeat else "")
    stem = f"source/{case}/{tag}"
    source = parse(files[f"{stem}/receipt.json"])
    staged = parse(files[f"units/{case}/{tag}.json"])
    require(source.get("schema") == RUN_SCHEMA and staged.get("schema") == RUN_SCHEMA, "successor run schema mismatch")
    require(not R.legacy_terminal_present(source) and not R.legacy_terminal_present(staged),
            "historical #270 terminal is not successor authority")
    require(source.get("rows") and set(source["rows"]) == DECISION_SET and set(staged.get("rows", {})) == DECISION_SET,
            "exact primary/repeat row decision set required")
    computed = {}
    for d in sorted(DECISION_SET):
        source_path, staged_path = f"{stem}/rows/{d}.f32", f"units/{case}/{tag}/rows/{d}.f32"
        require(source["rows"][d].get("path") == source_path and staged["rows"][d].get("path") == staged_path,
                "row path not exact source/staged case/run/decision custody")
        raw, staged_raw = files[source_path], files[staged_path]
        require(raw == staged_raw, "staged row bytes != untouched source row bytes")
        require(len(raw) == C.ROW_BYTES and not K.validate_rows_finite(raw), "full-vocabulary finite FP32 custody")
        computed[d] = sha(raw)
        expected = {"path": source_path, "bytes": C.ROW_BYTES, "sha256": computed[d]}
        require(source["rows"][d] == expected and staged["rows"][d] == {**expected, "path": staged_path}, "row digest/size claims != actual bytes")
        values = struct.unpack(f"<{C.N_VOCAB}f", raw)
        winner = max(range(C.N_VOCAB), key=values.__getitem__)
        require(staged.get("sampled_winners", [])[int(d)] == winner, "row greedy winner != captured metadata")
    require(staged.get("staged_source", {}).get("path") == f"{stem}/receipt.json", "source binding wrong run path")
    binding_problems = A.admission_problems(staged, arm, source, sha(files[f"{stem}/receipt.json"]), computed)
    require(not binding_problems, "; ".join(binding_problems))
    stripped_source = {k: v for k, v in source.items() if k != "rows"}
    stripped_stage = {k: v for k, v in staged.items() if k not in ("rows", "staged_source")}
    require(stripped_stage == stripped_source, "staging rewrote source facts/metadata")
    require("staged_source" not in source, "source receipt is already staged")
    expected_fields = {"campaign": CAMPAIGN, "namespace": R.NAMESPACE_273, "head_sha": authority["head_sha"],
                       "dispatch_authority": authority["dispatch"], "comparator_id": C.COMPARATOR_V2_ID,
                       "case_id": case, "arm": arm, "repeat_of": arm if repeat else None,
                       "model_members": C.MODEL_MEMBER_SHA256, "llama_source_pin": C.LLAMA_SOURCE_PIN,
                       "server_sha256": C.COMPARATOR_SHA256, "build_flags": BUILD_FLAGS,
                       "fixture_ladder_sha256": C.FIXTURE_LADDER_SHA256,
                       "request_contract": C.REQUEST_CONTRACT, "context_settings": C.CONTEXT_SETTINGS}
    for field, value in expected_fields.items():
        require(staged.get(field) == value, f"source/staged {field} authority mismatch")
    require(staged.get("selector") == {"GGML_VK_VISIBLE_DEVICES": staged["process_attribution"]["server_env"]["GGML_VK_VISIBLE_DEVICES"],
                                       "CUDA_VISIBLE_DEVICES": "-1"}, "receipt selector != process selector")
    fx = C.load_fixtures(C.ROOT)[case]
    require(staged.get("prompt_token_ids") == fx["prompt_token_ids"] and staged.get("prompt_len") == fx["rendered_length"] and
            staged.get("prompt_text_sha256") == sha(fx["prompt_text"].encode()), "frozen fixture/prompt authority mismatch")
    require(staged.get("run_id") == f"{R.NAMESPACE_273}-{case}-{tag}" and isinstance(staged.get("session_id"), str) and
            staged["session_id"] and isinstance(staged.get("boot_id"), str) and staged["boot_id"] and
            type(staged.get("start_ticks")) is int and staged["start_ticks"] > 0, "fresh namespace/session/process incarnation missing")
    require(staged.get("observation_path") == f"{stem}/observation.json", "observation belongs to wrong captured run")
    _observation(parse(files[staged["observation_path"]]), staged, arm, freeze, seal_time)
    for label, value in (("session", staged["session_id"]), ("run", staged["run_id"]),
                         ("source", sha(files[f"{stem}/receipt.json"])),
                         ("pid", (staged["host"], staged["boot_id"], staged["process_attribution"]["server_pid"])),
                         ("incarnation", (staged["host"], staged["boot_id"], staged["start_ticks"]))):
        require(value not in seen.setdefault(label, set()), f"reused {label} provenance")
        seen[label].add(value)
    require(len(staged.get("sampled_winners", [])) == C.DECISIONS and len(staged.get("forced_tokens", [])) == C.DECISIONS,
            "exact eight-decision token accounting")
    meta_problems = K._meta_row_problems(staged, arm, None)
    require(not meta_problems, "; ".join(meta_problems))
    for d, meta in enumerate(staged.get("meta_rows", [])):
        require(meta.get("n_vocab") == C.N_VOCAB and meta.get("capture_before_force") is True, "untouched capture order/full-vocabulary metadata")
        require(meta.get("prefix_tokens") == fx["prompt_token_ids"] + (staged["sampled_winners"][:d] if arm == "reference" else staged["forced_tokens"][:d]),
                "continuous canonical-prefix metadata mismatch")
    require(arm != "reference" or staged["forced_tokens"] == [-1] * C.DECISIONS, "reference must never force tokens")
    return staged


def _verify_references(files: dict[str, bytes], authority: dict[str, Any], freeze: dict[str, Any],
                       seal_time: dt.datetime, seen: dict[str, set[Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    references, determinism = {}, {}
    for case in C.FIXTURE_CASES:
        primary = _admit(files, case, "reference", False, authority, freeze, seal_time, seen)
        repeat = _admit(files, case, "reference", True, authority, freeze, seal_time, seen)
        references[case] = (primary, repeat)
        determinism[case] = K.validate_determinism(primary, repeat, _reader(files))
        if not determinism[case]["deterministic"]:
            break
    return references, determinism


def _result(terminal: str, problems: list[str], *, physical: bool, diagnostics: dict[str, Any] | None = None,
            determinism: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"schema": R.SCHEMA, "namespace": R.NAMESPACE_273, "terminal": terminal,
            "physical_authority": physical and terminal == R.TERMINAL_PASS_273,
            "evidence_mode": "PHYSICAL" if physical else "CPU_RECORDING_NONPHYSICAL",
            "problems": problems, "pair_diagnostics": diagnostics or {}, "determinism": determinism or {}}


def reduce_evidence_273(evidence_root: Path, repo_root: Path, expected_head: str, *, transport: Any = None) -> dict[str, Any]:
    physical = transport is None
    transport = R.github_get_273 if physical else transport
    stage = R.TERMINAL_AUTHORITY_BLOCKED_273
    try:
        dispatch, comment, comments = _context(transport, expected_head)
        authority = authority_contract(Path(repo_root), expected_head, dispatch)
        files = snapshot(Path(evidence_root))
        require("manifest.json" in files, "manifest missing")
        seal_time = _seal(comments, dispatch, files["manifest.json"])
        manifest = parse(files["manifest.json"])
        require(set(manifest) in (expected_paths(True), expected_paths(False)), "manifest missing/extra source/staged/row/observation set")
        require(set(files) == set(manifest) | {"manifest.json"}, "retained missing/extra row/file set")
        require(all(manifest[p] == sha(files[p]) for p in manifest), "manifest != independently computed retained bytes")
        require(parse(files["authority.json"]) == authority, "root authority != independently selected Git/dispatch/predecessor contract")
        freeze = _freeze(files, authority, comment, physical=physical)
        stage = R.TERMINAL_RUNTIME_BLOCKED_273
        seen: dict[str, set[Any]] = {}
        references, ref_det = _verify_references(files, authority, freeze, seal_time, seen)
        for case, verdict in ref_det.items():
            if not verdict["deterministic"]:
                return _result(R.TERMINAL_REFERENCE_NONDETERMINISTIC_273, [f"{case}: {p}" for p in verdict["problems"]],
                               physical=physical, determinism=ref_det)
        require(set(manifest) == expected_paths(True), "candidate evidence missing after reference determinism")
        last_reference = max(timestamp(r["finished_at"]) for pair in references.values() for r in pair)
        diagnostics, determinism = {}, {}
        for case in C.FIXTURE_CASES:
            candidate = _admit(files, case, "candidate", False, authority, freeze, seal_time, seen)
            repeat = _admit(files, case, "candidate", True, authority, freeze, seal_time, seen)
            for r in (candidate, repeat):
                require(timestamp(r["started_at"]) > last_reference, "candidate ran before all reference determinism units completed")
            cand_det = K.validate_determinism(candidate, repeat, _reader(files))
            require(cand_det["deterministic"], "candidate determinism: " + "; ".join(cand_det["problems"]))
            reference, ref_repeat = references[case]
            for ref, cand in ((reference, candidate), (ref_repeat, repeat)):
                cross = A.cross_arm_problems(ref, cand)
                require(not cross, "; ".join(cross))
                for field in K.CROSS_BOUND_FIELDS:
                    if field != "ngl":
                        require(ref.get(field) == cand.get(field), f"cross-arm {field} mismatch")
                require(cand["forced_tokens"] == ref["sampled_winners"], "candidate forced prefix != reference winners")
                prefix = K._meta_row_problems(cand, "candidate", ref["sampled_winners"])
                require(not prefix, "; ".join(prefix))
            determinism[case] = {"reference": ref_det[case], "candidate": cand_det}
            rw, cw = reference["sampled_winners"], candidate["sampled_winners"]
            diagnostics[case] = {"first_divergent_decision": next((d for d, (r, c) in enumerate(zip(rw, cw)) if r != c), None),
                                 "winner_agreement": sum(r == c for r, c in zip(rw, cw)),
                                 "semantics": "comparator/2 continuous (unchanged)"}
        return _result(R.TERMINAL_PASS_273, [], physical=physical, diagnostics=diagnostics, determinism=determinism)
    except InfrastructureError as exc:
        return _result(R.TERMINAL_INFRASTRUCTURE_BLOCKED_273, [str(exc)], physical=physical)
    except (EvidenceError, R.ReducerError, C.AuthorityError, P.PhysicalError, T.ReducerError,
            ValueError, OSError, KeyError, TypeError, IndexError, AttributeError, subprocess.CalledProcessError) as exc:
        return _result(stage, [str(exc)], physical=physical)


def _write_new(root: Path, rel: str, data: bytes) -> None:
    require(K._reject_row_path(rel) is None, "producer traversal path")
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("xb") as stream:
        stream.write(data)


def produce_evidence_273(capture_root: Path, evidence_root: Path, repo_root: Path,
                         expected_head: str, *, transport: Any = None) -> dict[str, Any]:
    """Stage fresh captured source bytes without rewriting any capture fact.

    Authenticate merged-main dispatch BEFORE staging. Reference admission and
    actual repeat determinism precede even parsing/copying candidate receipts.
    Publish a manifest digest for an independent post-capture custody seal;
    the producer itself cannot authorize its own manifest. Never overwrite.
    """
    physical = transport is None
    transport = R.github_get_273 if physical else transport
    dispatch, comment, _ = _context(transport, expected_head)
    authority = authority_contract(Path(repo_root), expected_head, dispatch)
    capture = snapshot(Path(capture_root))
    allowed = {p for p in expected_paths(True) if p.startswith("source/")} | {"freeze.json", "preflight.json"}
    reference_only = {p for p in expected_paths(False) if p.startswith("source/")} | {"freeze.json", "preflight.json"}
    require(set(capture) in (allowed, reference_only), "capture missing/extra source/row/observation set")
    root = Path(evidence_root).absolute()
    require(not root.exists() and not root.is_symlink(), "append-only destination already exists")
    safe_root(root.parent)
    root.mkdir()
    output = {"authority.json": encode(authority), "freeze.json": capture["freeze.json"], "preflight.json": capture["preflight.json"]}
    freeze = _freeze(output, authority, comment, physical=physical)
    seen: dict[str, set[Any]] = {}
    ref_det = {}
    # The source tree is a capture input, not a reducer-ready admission dict.
    # Only row paths and a byte-derived staged binding are added at staging.
    for arm in ("reference", "candidate"):
        for case in C.FIXTURE_CASES:
            runs = []
            for repeat in (False, True):
                tag = arm + ("-repeat" if repeat else "")
                stem = f"source/{case}/{tag}"
                for suffix in ("receipt.json", "observation.json", *(f"rows/{d}.f32" for d in sorted(DECISION_SET))):
                    rel = f"{stem}/{suffix}"
                    output[rel] = capture[rel]
                source = parse(output[f"{stem}/receipt.json"])
                stage = copy.deepcopy(source)
                computed = {}
                require(set(source.get("rows", {})) == DECISION_SET, "capture exact row set")
                for d in sorted(DECISION_SET):
                    rel = f"units/{case}/{tag}/rows/{d}.f32"
                    output[rel] = output[f"{stem}/rows/{d}.f32"]
                    computed[d] = sha(output[rel])
                    stage["rows"][d]["path"] = rel
                stage["staged_source"] = A.bind_staged_source(source, f"{stem}/receipt.json", sha(output[f"{stem}/receipt.json"]), computed)
                output[f"units/{case}/{tag}.json"] = encode(stage)
                runs.append(_admit(output, case, arm, repeat, authority, freeze,
                                   timestamp(source["finished_at"]), seen))
            verdict = K.validate_determinism(*runs, _reader(output))
            if arm == "reference":
                ref_det[case] = verdict
            require(arm == "reference" or verdict["deterministic"], "candidate determinism unproven at staging")
        if arm == "reference" and any(not v["deterministic"] for v in ref_det.values()):
            break
    include_candidate = any(p.startswith("source/case-256/candidate/") for p in output)
    require(set(output) == expected_paths(include_candidate), "producer exact output inventory")
    for rel, data in sorted(output.items()):
        _write_new(root, rel, data)
    manifest = {rel: sha(data) for rel, data in sorted(output.items())}
    manifest_bytes = encode(manifest)
    _write_new(root, "manifest.json", manifest_bytes)
    # Verify durable serialized bytes, not only the in-memory stage result.
    require(snapshot(root) == {**output, "manifest.json": manifest_bytes}, "producer serialized readback mismatch")
    return {"manifest_sha256": sha(manifest_bytes), "reached_candidate": include_candidate,
            "requires_independent_capture_seal": True, "physical_execution_performed": False}
