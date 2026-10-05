#!/usr/bin/env python3
"""Issue #276 (R8-I6A) — admit retained collector bytes end to end.

Production path: the #275 collector's retained ORIGINAL capture bytes
(raw probe originals, row bytes, receipt) are staged verbatim into a
staged unit, then the reader recomputes every digest from the staged
bytes themselves and RE-DERIVES all identity-bearing fields (selector,
ICD, backend, used Vulkan device, process incarnation, executable,
model members, residency). Authored labels — receipt claims and the
collector's own observation.json summary — are cross-checks only: any
contradiction with the bytes fails closed. Staging cannot replace the
observations because nothing staged is ever consumed as an observation
without being re-derived from bytes.

Trust boundary (finite and explicit): the reviewed collector code
(scripts/issue275_collector.py, accepted at the #275 head) and the
contemporaneous OS/runtime observations it retained. SHA-256 digests
prove BYTE INTEGRITY within that boundary — they do not, by
themselves, prove origin. There is deliberately NO seal, signature,
or manifest assertion here that could move the unsupported
trust-by-itself claim: a staged binding carries only byte digests and
plain custody fields, an unknown authority-ish field on a binding is
REJECTED, and origin rests solely on "bytes of the shape only the
reviewed collector path produces, validated by the same law the
collector enforces at capture time."

Fail-closed everywhere; fixture/CPU-only tests exercise this path —
no hardware, network, holdout, or historical-evidence access.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
import struct
from pathlib import Path
from typing import Any

import issue270_authority as C
import issue270_comparator as CMP
import issue275_collector as KC

SCHEMA = "inferswarm.issue276.byte-admission/1"
BINDING_SCHEMA = "inferswarm.issue276.staged-binding/1"
CAMPAIGN = "issue276-r8i6a-retained-byte-admission"

# Exactly the fields a staged binding may carry. Anything else — in
# particular an invented seal/hash/manifest AUTHORITY field — is refused:
# a binding is custody + byte digests, never authority.
BINDING_FIELDS = ("schema", "campaign", "case", "arm", "repeat",
                  "source_stem", "files")

_REQUIRED_RAW_START = (
    "raw/boot_identity.start.bin", "raw/start_ticks.start.bin",
    "raw/process_census.start.bin", "raw/process_cmdline.start.bin",
    "raw/exe_identity.start.bin", "raw/open_model_members.start.bin",
    "raw/device_census.start.bin", "raw/process_environ.start.bin",
    "raw/used_vulkan_device.start.bin",
)
_REQUIRED_RAW_END = ("raw/boot_identity.end.bin", "raw/start_ticks.end.bin")
_BDF_RE = re.compile(r"[0-9a-f]{4,8}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]")


class ReaderError(RuntimeError):
    """Hard custody failure (missing/extra/inconsistent bundle)."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2) + "\n").encode()


def _parse(data: bytes, label: str) -> Any:
    def no_duplicates(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            dup = sorted({k for k in keys if keys.count(k) > 1})[0]
            raise ReaderError(f"{label}: duplicate key {dup!r} — ambiguous identity fails closed")
        return dict(pairs)
    try:
        return json.loads(data, object_pairs_hook=no_duplicates)
    except ReaderError:
        raise
    except ValueError as exc:
        raise ReaderError(f"{label} is not valid JSON: {exc}") from exc


def _collect_files(root: Path) -> dict[str, bytes]:
    """No-follow snapshot of a retained run directory, keyed by relative
    POSIX path. Symlinks and traversal-shaped names fail closed."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ReaderError(f"retained run directory missing or unsafe: {root}")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ReaderError(f"symlink in retained run: {rel}")
        if path.is_dir():
            continue
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode):
            raise ReaderError(f"non-regular retained file: {rel}")
        files[rel] = path.read_bytes()
    return files


def _require(cond: Any, message: str, problems: list[str]) -> bool:
    if not cond:
        problems.append(message)
    return bool(cond)


# ---------------------------------------------------------------------------
# Re-derivation: identity-bearing fields from bytes only
# ---------------------------------------------------------------------------

def _residency_files(bdfs: list[str]) -> list[str]:
    return [f"raw/residency.{phase}.{bdf}.bin"
            for bdf in bdfs for phase in ("start", "peak", "end")]


def derive_from_bytes(files: dict[str, bytes], arm: str) -> tuple[dict[str, Any], list[str]]:
    """Re-derive every identity-bearing observation from retained bytes.

    Returns (derived, problems). `derived` contains ONLY byte-derived
    fields; receipt/observation labels are checked by the caller against
    it, never the other way around.
    """
    problems: list[str] = []
    # --- process incarnation ------------------------------------------------
    try:
        boot = files["raw/boot_identity.start.bin"].decode().strip()
        ticks = int(files["raw/start_ticks.start.bin"].decode().strip())
        close_boot = files["raw/boot_identity.end.bin"].decode().strip()
        close_ticks = int(files["raw/start_ticks.end.bin"].decode().strip())
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        return {}, [f"process identity bytes missing/malformed: {exc}"]
    _require(boot and ticks >= 0, "boot identity empty or start ticks negative", problems)
    _require(close_boot == boot and close_ticks == ticks,
             "closing incarnation != opening (spliced capture window)", problems)
    census = _parse(files.get("raw/process_census.start.bin", b""), "process_census")
    if not _require(isinstance(census, dict), "process census malformed", problems):
        return {}, problems
    # Census/boot law must match the collector: the top-level boot_id and
    # the matched row's boot_id both equal the boot bytes.
    _require(census.get("boot_id") == boot, "process census/boot mismatch", problems)
    pid_rows = []
    if isinstance(census.get("processes"), list):
        pid_rows = [r for r in census["processes"] if isinstance(r, dict)]
    # The single process row must carry the same incarnation as the ticks
    # bytes; the pid is taken from the row the bytes themselves identify.
    incarn_rows = [r for r in pid_rows
                   if r.get("boot_id") == boot and r.get("start_ticks") == ticks]
    if not _require(len(incarn_rows) == 1, "process not found uniquely in census", problems):
        return {}, problems
    _require(incarn_rows[0].get("pid") is not None
             and [r for r in pid_rows if r.get("pid") == incarn_rows[0].get("pid")] == [incarn_rows[0]],
             "census/boot mismatch vs start-tick bytes (pid not unique)", problems)
    pid = incarn_rows[0].get("pid")
    _require(type(pid) is int and pid > 0, "census pid malformed", problems)
    # --- executable / model -------------------------------------------------
    try:
        exe_path, exe_sha = KC._read_exe(files["raw/exe_identity.start.bin"])
    except (KeyError, KC.CollectorError, ValueError) as exc:
        return {}, [f"exe identity bytes unusable: {exc}"]
    _require(exe_sha == C.COMPARATOR_SHA256, "derived exe sha != frozen comparator sha", problems)
    try:
        model_path = KC._effective_model(files["raw/process_cmdline.start.bin"])
    except (KeyError, KC.CollectorError, ValueError) as exc:
        return {}, [f"process cmdline bytes unusable: {exc}"]
    _require(model_path == f"{C.MODEL_DIR}/{C.MODEL_MEMBER_1}",
             "derived effective --model does not bind the frozen model", problems)
    try:
        members = KC._json(files["raw/open_model_members.start.bin"], "open_model_members")
    except (KeyError, KC.CollectorError) as exc:
        return {}, [f"open model members bytes unusable: {exc}"]
    _require(members == C.MODEL_MEMBER_SHA256,
             "derived open model members contradict the frozen member set", problems)
    # --- device census ------------------------------------------------------
    devices = _parse(files.get("raw/device_census.start.bin", b""), "device_census")
    if not _require(isinstance(devices, list) and devices, "device census empty/malformed", problems):
        return {}, problems
    required = ("bdf", "vendor_id", "device_id", "vulkan_uuid", "icd", "name", "physical_type")
    for d in devices:
        if not isinstance(d, dict):
            problems.append("census entry malformed: expected object"); continue
        for key in required:
            if not isinstance(d.get(key), str) or not d[key].strip():
                problems.append(f"census entry missing/malformed {key}")
        if isinstance(d.get("bdf"), str) and _BDF_RE.fullmatch(d["bdf"]) is None:
            problems.append("census entry malformed bdf: expected PCI BDF")
        if type(d.get("index")) is not int:
            problems.append("census entry missing/malformed index")
    for key in ("bdf", "vulkan_uuid", "index"):
        vals = [d.get(key) for d in devices if isinstance(d, dict)]
        if any(v is None for v in vals) or len(set(vals)) != len(vals):
            problems.append(f"ambiguous device census duplicate/missing {key}")
    if problems:
        return {}, problems
    # --- observed selection (environ + used device, resolved on census) ------
    try:
        proc_env = KC._parse_environ(files["raw/process_environ.start.bin"])
        obs_selector = KC._required_env(proc_env, KC._ENV_SELECTOR_KEY)
        obs_icd = KC._required_env(proc_env, KC._ENV_ICD_KEY)
    except (KeyError, KC.CollectorError, ValueError) as exc:
        return {}, [f"process environ bytes unusable: {exc}"]
    _require(re.fullmatch(r"[0-9]+", obs_selector) is not None,
             "observed environ selector must be a digit string", problems)
    used = _parse(files.get("raw/used_vulkan_device.start.bin", b""), "used_vulkan_device")
    if not _require(isinstance(used, dict), "used_vulkan_device malformed", problems):
        return {}, problems
    for key in ("backend", "icd", "vulkan_uuid", "bdf", "driver_id"):
        _require(isinstance(used.get(key), str) and used[key].strip(),
                 f"used_vulkan_device missing/malformed {key}", problems)
    _require(type(used.get("index")) is int, "used_vulkan_device missing/malformed index", problems)
    _require(used.get("backend") == "vulkan", f"unsupported observed backend {used.get('backend')!r}", problems)
    if problems:
        return {}, problems
    selected = [d for d in devices if d["vulkan_uuid"] == used["vulkan_uuid"]]
    _require(len(selected) == 1, "observed used Vulkan UUID absent/ambiguous in device census", problems)
    if selected:
        _require(selected[0]["bdf"] == used["bdf"],
                 "used_vulkan_device BDF contradicts census entry for the used UUID", problems)
        _require(selected[0]["index"] == used["index"] and selected[0]["index"] == int(obs_selector),
                 "observed selector/used-device index disagreement", problems)
        _require(selected[0]["icd"] == obs_icd and used["icd"] == obs_icd,
                 "observed ICD disagrees between environ and used-device observation", problems)
    # --- residency ----------------------------------------------------------
    bdfs = [d["bdf"] for d in devices]
    residencies: dict[str, dict[str, int]] = {}
    for bdf in bdfs:
        samples = []
        for phase, key in (("start", "before"), ("peak", "peak"), ("end", "after")):
            try:
                value = KC._json(files[f"raw/residency.{phase}.{bdf}.bin"], f"residency {phase}/{bdf}")
            except KeyError:
                problems.append(f"residency bytes missing for {bdf}/{phase}"); samples = []; break
            except KC.CollectorError as exc:
                problems.append(f"residency {phase}/{bdf} malformed: {exc}"); samples = []; break
            if not isinstance(value, dict) or type(value.get("bytes")) is not int or value["bytes"] < 0:
                problems.append(f"residency {phase}/{bdf} counter malformed"); samples = []; break
            samples.append(value["bytes"])
        if len(samples) == 3:
            residencies[bdf] = dict(zip(("before", "peak", "after"), samples))
    if selected and residencies and not problems:
        sel = residencies.get(selected[0]["bdf"])
        _require(sel is not None and sel["peak"] - sel["before"] >= C.EXCLUDED_NOISE_BYTES,
                 "selected device residency delta below proof bound", problems)
        for bdf, counters in residencies.items():
            if bdf != selected[0]["bdf"]:
                _require(counters["peak"] - counters["before"] < C.EXCLUDED_NOISE_BYTES,
                         f"excluded device {bdf} residency delta exceeds noise bound", problems)
    # --- arm law, derived from bytes ----------------------------------------
    if selected and not problems:
        d = selected[0]
        if arm == "reference":
            identity = C.reference_identity()
            _require(obs_icd == C.NVIDIA_ICD and used["icd"] == C.NVIDIA_ICD,
                     "reference law: observed ICD is not the NVIDIA ICD", problems)
            _require(used.get("driver_id") == KC.NVIDIA_VULKAN_DRIVER_ID,
                     "reference law: observed Vulkan driver identity is not NVIDIA", problems)
            _require(d["vendor_id"] == "0x10de" and d["device_id"] == "0x" + identity["pci_id"].split(":")[-1]
                     and d.get("gpu_uuid") == identity["gpu_uuid"]
                     and d["vulkan_uuid"] == identity["vulkan_device_uuid"]
                     and d["bdf"] == identity["bdf"],
                     "reference law: observed PCI/UUID lineage mismatch", problems)
            excluded = [x for x in devices if x is not d]
            _require(any(x["vendor_id"] == "0x1002" and x["device_id"] == "0x67df"
                         and "RX 580" in x["name"] and x["icd"] == C.RADV_ICD for x in excluded),
                     "reference law: positive RX580 excluded census absent", problems)
        else:
            _require(obs_icd == C.RADV_ICD and used["icd"] == C.RADV_ICD,
                     "candidate law: observed ICD is not the RADV ICD", problems)
            _require(used.get("driver_id") == C.EXPECTED_CANDIDATE["vulkan_driver_id"],
                     "candidate law: observed Vulkan driver identity drift", problems)
            _require({x["bdf"] for x in devices} == set(C.DIE_BDFS),
                     "candidate law: census does not match the frozen two-die BDF set", problems)
            for x in devices:
                _require(x["vendor_id"] == C.EXPECTED_CANDIDATE["vendor_id"]
                         and x["device_id"] == C.EXPECTED_CANDIDATE["device_id"]
                         and x["icd"] == C.RADV_ICD
                         and x["vulkan_uuid"] == C.EXPECTED_VULKAN_DEVICE_UUIDS[x["bdf"]],
                         "candidate law: observed vendor/device/ICD/UUID drift", problems)
    derived = {
        "pid": pid, "boot_id": boot, "start_ticks": ticks,
        "exe_path": exe_path, "exe_sha256": exe_sha,
        "effective_model": model_path, "open_model_members": members,
        "devices": devices, "residency": residencies,
        "selector": obs_selector, "icd": obs_icd,
        "backend": used.get("backend"), "used_vulkan_uuid": used.get("vulkan_uuid"),
        "used_bdf": used.get("bdf"), "used_index": used.get("index"),
        "used_driver_id": used.get("driver_id"),
        "_cmdline_bytes": files.get("raw/process_cmdline.start.bin"),
    }
    return derived, problems


# ---------------------------------------------------------------------------
# Label cross-checks: authored fields may only AGREE with the bytes
# ---------------------------------------------------------------------------

def _label_problems(receipt: dict, obs: dict, derived: dict[str, Any],
                    sizes: dict[str, int] | None = None) -> list[str]:
    problems: list[str] = []
    _require(isinstance(receipt, dict), "retained receipt malformed", problems)
    if not isinstance(receipt, dict):
        return problems
    attribution = receipt.get("process_attribution")
    if not _require(isinstance(attribution, dict), "receipt process_attribution malformed", problems):
        attribution = {}
    env = attribution.get("server_env") or {}
    claim_pid = attribution.get("server_pid")
    if claim_pid is not None:
        _require(claim_pid == derived.get("pid"),
                 "receipt claim process_attribution.server_pid contradicts byte-derived census pid",
                 problems)
    claim_selector = env.get(KC._ENV_SELECTOR_KEY) if isinstance(env, dict) else None
    if claim_selector is not None:
        _require(claim_selector == derived.get("selector"),
                 f"receipt claim {KC._ENV_SELECTOR_KEY} contradicts observed selector", problems)
    claim_icd = env.get(KC._ENV_ICD_KEY) if isinstance(env, dict) else None
    if claim_icd is not None:
        _require(claim_icd == derived.get("icd"),
                 f"receipt claim {KC._ENV_ICD_KEY} contradicts observed ICD", problems)
    subject = receipt.get("subject_identity")
    if isinstance(subject, dict):
        _require(subject.get("bdf") == derived.get("used_bdf"),
                 "receipt claim subject_identity.bdf contradicts derived selected device", problems)
    if receipt.get("model_members") is not None:
        _require(receipt.get("model_members") == derived.get("open_model_members"),
                 "receipt claim model_members contradicts derived open members", problems)
    if receipt.get("exe_sha256") is not None:
        _require(receipt.get("exe_sha256") == derived.get("exe_sha256"),
                 "receipt claim exe_sha256 contradicts derived exe sha", problems)
    # observation.json is the collector's OWN summary — checked, not trusted.
    _require(obs.get("schema") == KC.SCHEMA, "retained observation schema mismatch", problems)
    selection = obs.get("observed_selection")
    if isinstance(selection, dict):
        for field, key in (("selector", "selector"), ("icd", "icd"), ("backend", "backend"),
                           ("used_vulkan_uuid", "used_vulkan_uuid"), ("used_bdf", "used_bdf"),
                           ("used_index", "used_index"), ("used_driver_id", "used_driver_id")):
            if field in selection:
                _require(selection[field] == derived.get(key),
                         f"observation label {field} contradicts byte-derived value", problems)
    process = obs.get("process")
    if isinstance(process, dict):
        _require(process.get("pid") == derived.get("pid")
                 and process.get("boot_id") == derived.get("boot_id")
                 and process.get("start_ticks") == derived.get("start_ticks"),
                 "observation process labels contradict byte-derived incarnation", problems)
        exe = process.get("exe")
        if isinstance(exe, dict):
            _require(exe.get("sha256") == derived.get("exe_sha256"),
                     "observation exe label contradicts byte-derived exe sha", problems)
            _require(exe.get("path") == derived.get("exe_path"),
                     "observation exe path label contradicts byte-derived exe identity", problems)
        cmdline_bytes = derived.get("_cmdline_bytes")
        if cmdline_bytes is not None:
            _require(process.get("cmdline") == cmdline_bytes.decode().rstrip("\0").split("\0"),
                     "observation cmdline labels contradict byte-derived cmdline", problems)
        close = process.get("incarnation_close")
        if isinstance(close, dict):
            _require(close.get("boot_id") == derived.get("boot_id")
                     and close.get("start_ticks") == derived.get("start_ticks")
                     and close.get("bound_same_process") is True,
                     "observation closing-incarnation labels contradict byte-derived incarnation",
                     problems)
        _require(process.get("effective_model") == derived.get("effective_model"),
                 "observation model label contradicts byte-derived effective model", problems)
        _require(process.get("open_model_members") == derived.get("open_model_members"),
                 "observation members label contradicts byte-derived members", problems)
    if derived.get("devices") is not None:
        obs_devices = obs.get("devices")
        if isinstance(obs_devices, list):
            # The collector's summary adds `selected` flags to the census;
            # they must agree with the byte-derived used device.
            stripped = [{k: v for k, v in d.items() if k != "selected"}
                        for d in obs_devices if isinstance(d, dict)]
            _require(stripped == derived.get("devices"),
                     "observation device summary contradicts byte-derived census", problems)
            flagged = [d for d in obs_devices
                       if isinstance(d, dict) and d.get("selected") is True]
            _require(len(flagged) == 1 and flagged[0].get("bdf") == derived.get("used_bdf"),
                     "observation selected flag contradicts byte-derived used device", problems)
        else:
            problems.append("observation device summary missing")
    if derived.get("residency"):
        _require(obs.get("residency") == derived.get("residency"),
                 "observation residency summary contradicts byte-derived counters", problems)
    inventory = obs.get("probe_inventory")
    if isinstance(inventory, dict) and sizes is not None:
        for rel, meta in sorted(inventory.items()):
            if isinstance(meta, dict):
                _require(meta.get("bytes") == sizes.get(rel),
                         f"observation inventory length mismatch for {rel}", problems)
    return problems


# ---------------------------------------------------------------------------
# Staging: verbatim copy + digest binding (append-only)
# ---------------------------------------------------------------------------

def _expected_run_files(obs: dict) -> set[str] | None:
    """File set a complete retained run must have, from its own inventory."""
    inventory = obs.get("probe_inventory")
    if not isinstance(inventory, dict) or not inventory:
        return None
    expected = {"receipt.json", "observation.json"}
    expected |= {str(d) for d in range(C.DECISIONS) and set(f"rows/{d}.f32" for d in range(C.DECISIONS))}
    expected |= set(inventory)
    return expected


def stage_capture_276(capture_root: Path, staged_root: Path, case: str, arm: str,
                      repeat: bool) -> Path:
    """Stage one retained collector run into a staged unit, verbatim.

    Fails closed BEFORE any write when the source bundle is incomplete,
    carries extra files, or its bytes contradict its own labels. The
    destination is append-only: an existing unit is never overwritten.
    """
    if arm not in ("reference", "candidate"):
        raise ReaderError(f"unknown arm {arm!r}")
    if not isinstance(case, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", case or ""):
        raise ReaderError(f"unusable case component {case!r}")
    tag = arm + ("-repeat" if repeat else "")
    stem = f"source/{case}/{tag}"
    source_run = Path(capture_root) / stem
    files = _collect_files(source_run)
    if "receipt.json" not in files or "observation.json" not in files:
        raise ReaderError(f"incomplete retained bundle: {stem} lacks receipt/observation")
    obs = _parse(files["observation.json"], "observation.json")
    # Missing retained originals are reported as MISSING (never parsed).
    for rel in _REQUIRED_RAW_START + _REQUIRED_RAW_END:
        if rel not in files:
            raise ReaderError(f"incomplete retained bundle: missing {rel}")
    # Re-derive identity from the bytes and cross-check every label first:
    # a bundle whose bytes contradict its labels is refused unstaged.
    derived, problems = derive_from_bytes(files, arm)
    if derived:
        census_bdfs = [d["bdf"] for d in derived["devices"]]
        need = set(_residency_files(census_bdfs))
        missing = need - set(files)
        if missing:
            problems.append(f"incomplete retained bundle: missing {sorted(missing)[0]}")
    else:
        problems = problems or ["identity derivation failed"]
    # Complete row set: every decision's row bytes must be retained.
    for d in range(C.DECISIONS):
        if f"rows/{d}.f32" not in files:
            problems.append(f"incomplete retained bundle: missing rows/{d}.f32")
            break
    sizes = {rel: len(data) for rel, data in files.items() if rel.startswith("raw/")}
    problems += _label_problems(_parse(files["receipt.json"], "receipt.json"), obs, derived, sizes)
    expected = _expected_run_files(obs)
    if expected is None:
        problems.append("retained bundle probe inventory missing/empty")
    else:
        extra = set(files) - expected
        if extra:
            problems.append(f"retained bundle has unbound extra files: {sorted(extra)[0]}")
    if problems:
        raise ReaderError("; ".join(problems))
    # Append-only destination, preflighted before the first write.
    unit_dir = Path(staged_root) / "units" / case / tag
    binding_path = Path(staged_root) / "units" / case / f"{tag}.json"
    for dest in (unit_dir, binding_path):
        if dest.exists() or dest.is_symlink():
            raise ReaderError(f"append-only destination exists: {dest}")
    binding = {"schema": BINDING_SCHEMA, "campaign": CAMPAIGN, "case": case,
               "arm": arm, "repeat": repeat, "source_stem": stem,
               "files": {rel: _sha(data) for rel, data in sorted(files.items())}}
    unit_dir.parent.mkdir(parents=True, exist_ok=True)
    for rel, data in sorted(files.items()):
        target = unit_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    with binding_path.open("xb") as stream:
        stream.write(_canonical(binding))
    return unit_dir


# ---------------------------------------------------------------------------
# Admission: reader over staged bytes
# ---------------------------------------------------------------------------

def _require_custody_binding(custody_root: Path, binding_path: Path, unit_dir: Path,
                             case: str, arm: str, repeat: bool,
                             problems: list[str]) -> None:
    """Round 3: original-to-staged byte binding.

    Every staged byte must equal its collector-owned retained original
    under custody_root/source/<case>/<tag>, byte for byte. The retained
    originals are already-authenticated collector output (validated by
    the same law at staging); the staged copy may not diverge from them
    in either direction, and missing accepted source custody fails
    closed. Plain byte equality only — no digest-only comparison (a
    staged-side digest can be recomputed by an attacker), no seal.
    """
    tag = arm + ("-repeat" if repeat else "")
    source_run = Path(custody_root) / "source" / case / tag
    try:
        originals = _collect_files(source_run)
    except ReaderError as exc:
        problems.append(f"accepted source custody missing/unsafe for {tag}: {exc}")
        return
    staged = _collect_files(unit_dir)
    bound = _parse(binding_path.read_bytes(), "staged binding")
    bound_files = bound.get("files") if isinstance(bound, dict) else None
    expected = set(originals)
    if isinstance(bound_files, dict):
        expected |= set(bound_files)
    for rel in sorted(expected):
        if rel not in staged:
            problems.append(f"staged file absent from unit: {rel}")
        elif rel not in originals:
            problems.append(f"no collector-owned retained original for staged file {rel} "
                            "(staged bytes are not collector output)")
        elif staged[rel] != originals[rel]:
            problems.append(f"staged bytes != collector-owned retained original: {rel} "
                            "(custody binding violation)")
    for rel in sorted(set(staged) - expected):
        problems.append(f"staged file has no custody basis: {rel}")


def admit_staged_276(staged_root: Path, case: str, arm: str, repeat: bool,
                     custody_root: Path | None = None) -> dict[str, Any]:
    """Admit one staged unit from its bytes.

    Every digest is recomputed from the staged bytes, every identity
    field re-derived, and every authored label cross-checked. The staged
    binding may carry ONLY custody fields and byte digests — any other
    authority-ish field (an invented seal, signature, or manifest
    assertion) is rejected.

    custody_root (round 3) closes the original-to-staged byte-binding
    gap: the collector-owned retained originals. When provided, every
    staged byte must equal its retained original exactly — the staging
    copy is not a second source of truth, and any post-staging edit of
    EITHER side fails closed. Missing accepted source custody also
    fails closed. (The parameter is not authority: the originals are
    already-authenticated collector output, compared by plain byte
    equality; the default-None legacy form remains self-contained
    integrity+derivation admission for callers without retained
    custody.)
    """
    tag = arm + ("-repeat" if repeat else "")
    problems: list[str] = []
    if arm not in ("reference", "candidate"):
        return {"schema": SCHEMA, "case": case, "arm": arm, "repeat": repeat,
                "admitted": False,
                "problems": [f"unknown arm {arm!r} — only the frozen arms exist"],
                "derived": {}}
    binding_path = Path(staged_root) / "units" / case / f"{tag}.json"
    unit_dir = Path(staged_root) / "units" / case / tag
    if not binding_path.is_file() or not unit_dir.is_dir():
        return {"schema": SCHEMA, "case": case, "arm": arm, "repeat": repeat,
                "admitted": False,
                "problems": [f"staged unit missing: {binding_path}"], "derived": {}}
    # Original-to-staged byte binding (round 3). The retained originals
    # are already-authenticated collector output (their integrity is
    # enforced at staging); here every staged byte must EQUAL its
    # collector-owned original. This is the only original-to-staged
    # authority: plain byte equality through the production path, never
    # a digest the staged side can recompute or a seal it can forge.
    if custody_root is not None:
        _require_custody_binding(custody_root, binding_path, unit_dir, case,
                                 arm, repeat, problems)
    binding = _parse(binding_path.read_bytes(), "staged binding")
    if not isinstance(binding, dict):
        return {"schema": SCHEMA, "case": case, "arm": arm, "repeat": repeat,
                "admitted": False, "problems": ["staged binding malformed"], "derived": {}}
    _require(binding.get("schema") == BINDING_SCHEMA, "staged binding schema mismatch", problems)
    _require(set(binding) == set(BINDING_FIELDS),
             "staged binding carries unknown fields — authority assertions "
             "outside the custody contract are rejected", problems)
    _require(binding.get("arm") == arm, f"binding arm {binding.get('arm')!r} != requested {arm!r}", problems)
    _require(binding.get("case") == case, "binding case mismatch", problems)
    _require(binding.get("repeat") is repeat, "binding repeat flag mismatch", problems)
    _require(binding.get("campaign") == CAMPAIGN,
             "binding campaign is not this byte-admission campaign", problems)
    _require(binding.get("source_stem") == f"source/{case}/{tag}",
             "binding source stem does not name this unit's retained run", problems)
    bound_files = binding.get("files")
    if not _require(isinstance(bound_files, dict) and bound_files,
                    "staged binding file digest map missing", problems):
        bound_files = {}
    files = _collect_files(unit_dir)
    # Exact file-set custody: no missing, no extra unbound files.
    _require(set(files) == set(bound_files),
             "staged file set != binding file set (missing or unbound extra files)", problems)
    # Byte integrity: digests recomputed from the staged bytes themselves.
    for rel in sorted(set(files) & set(bound_files)):
        _require(_sha(files[rel]) == bound_files[rel],
                 f"staged byte integrity failure: digest mismatch for {rel}", problems)
    # Mandatory retained-original shape (inventory-independent floor).
    for rel in _REQUIRED_RAW_START + _REQUIRED_RAW_END:
        _require(rel in files, f"staged bundle missing retained original {rel}", problems)
    # Metadata is NOT optional: deleting the labels cannot bypass derivation.
    for rel in ("receipt.json", "observation.json"):
        _require(rel in files, f"staged bundle missing mandatory metadata {rel}", problems)
    derived: dict[str, Any] = {}
    if "receipt.json" in files and "observation.json" in files:
        receipt = _parse(files["receipt.json"], "receipt.json")
        obs = _parse(files["observation.json"], "observation.json")
        derived, derive_problems = derive_from_bytes(files, arm)
        problems += derive_problems
        if derived:
            sizes = {rel: len(data) for rel, data in files.items() if rel.startswith("raw/")}
            problems += _label_problems(receipt, obs, derived, sizes)
            # The collector's inventory must match the staged raw bytes.
            inventory = obs.get("probe_inventory") if isinstance(obs, dict) else None
            if isinstance(inventory, dict):
                raw_present = {rel for rel in files if rel.startswith("raw/")}
                _require(set(inventory) == raw_present,
                         "probe inventory != staged raw file set", problems)
                for rel, meta in sorted(inventory.items()):
                    if isinstance(meta, dict) and rel in files:
                        _require(meta.get("sha256") == _sha(files[rel]) and meta.get("bytes") == len(files[rel]),
                                 f"probe inventory digest/length != staged bytes for {rel}", problems)
            if arm == "reference":
                _require(obs.get("reference_identity_expected") == C.reference_identity(),
                         "reference bundle lacks the frozen expected identity cross-check", problems)
            else:
                _require("reference_identity_expected" not in obs,
                         "candidate bundle carries a reference identity block", problems)
            # Row bytes: full decision set, full-vocabulary finite FP32 shape
            # (the accepted comparator row law — arbitrary bytes are not rows).
            row_digests = {}
            for d in range(C.DECISIONS):
                rel = f"rows/{d}.f32"
                if rel not in files:
                    continue
                raw = files[rel]
                _require(len(raw) == C.ROW_BYTES,
                         f"row {d} is not full-vocabulary sized ({len(raw)} != {C.ROW_BYTES} bytes)", problems)
                try:
                    nonfinite = CMP.validate_rows_finite(raw)
                except ValueError as exc:
                    problems.append(f"row {d} is not decodable FP32: {exc}")
                    continue
                _require(not nonfinite, f"row {d} contains non-finite FP32 values", problems)
                row_digests[str(d)] = _sha(raw)
            derived = dict(derived)
            derived["row_sha256"] = row_digests
            _require(set(row_digests) == {str(d) for d in range(C.DECISIONS)},
                     "staged bundle row decision set incomplete", problems)
            # Derived-echo binding: the binding's digest for receipt.json and
            # observation.json must equal the digests derived FROM those very
            # bytes (recomputed above), so the binding cannot be rewritten to
            # bless attacker-authored labels over the derived facts.
    derived_out = {k: v for k, v in derived.items() if not k.startswith("_")}
    return {"schema": SCHEMA, "case": case, "arm": arm, "repeat": repeat,
            "admitted": not problems, "problems": problems, "derived": derived_out}


def admit_pair_276(staged_root: Path, case: str,
                   custody_root: Path | None = None) -> dict[str, Any]:
    """Admit one case's full staged bundle: both arms, primary + repeat.

    Order follows the corrected #273 law: per-arm admission (primary then
    repeat), per-arm deterministic-repeat equality, then cross-arm
    anti-aliasing. Source-run reuse, row aliasing, and shared process
    provenance across arms all fail closed. custody_root binds every
    unit to its collector-owned retained originals (round 3).
    """
    problems: list[str] = []
    units: dict[tuple[str, bool], dict[str, Any]] = {}
    for arm in ("reference", "candidate"):
        for repeat in (False, True):
            verdict = admit_staged_276(staged_root, case, arm, repeat,
                                       custody_root=custody_root)
            units[(arm, repeat)] = verdict
            problems += [f"{arm}{'+repeat' if repeat else ''}: {p}" for p in verdict["problems"]]
    # Per-arm deterministic repeats: identical row bytes per decision.
    for arm in ("reference", "candidate"):
        primary, repeat = units[(arm, False)], units[(arm, True)]
        if primary["admitted"] and repeat["admitted"]:
            for decision in sorted(primary["derived"]["row_sha256"]):
                if primary["derived"]["row_sha256"][decision] != repeat["derived"]["row_sha256"].get(decision):
                    problems.append(f"{arm} primary/repeat decision {decision} row digest "
                                    "mismatch — determinism claim rejected")
            # A repeat is a DISTINCT physical execution: its process
            # incarnation (pid, boot id, start ticks) as a whole must
            # differ from the primary's, and it may not reuse the
            # primary's retained capture bytes. Sharing SOME fields is
            # the normal same-host shape — two processes of one boot
            # session share the boot id, sequential PIDs may repeat
            # across hosts — so distinctness is judged on the complete
            # incarnation tuple, never per-field.
            prim_incarn = tuple(primary["derived"].get(f) for f in ("pid", "boot_id", "start_ticks"))
            rep_incarn = tuple(repeat["derived"].get(f) for f in ("pid", "boot_id", "start_ticks"))
            if prim_incarn == rep_incarn:
                problems.append(f"{arm} repeat shares the primary's full process "
                                "incarnation (pid, boot id, start ticks) — one capture "
                                "cannot impersonate its own repeat")
            prim_binding = _parse((Path(staged_root) / "units" / case / f"{arm}.json").read_bytes(), "binding")
            rep_binding = _parse((Path(staged_root) / "units" / case / f"{arm}-repeat.json").read_bytes(), "binding")
            if prim_binding.get("files") == rep_binding.get("files"):
                problems.append(f"{arm} repeat binds byte-identical source files — "
                                "the same retained capture cannot serve as its own repeat")
    # Cross-arm anti-aliasing.
    ref, cand = units[("reference", False)], units[("candidate", False)]
    if ref["admitted"] and cand["admitted"]:
        ref_rows, cand_rows = ref["derived"]["row_sha256"], cand["derived"]["row_sha256"]
        for decision in sorted(set(ref_rows) & set(cand_rows)):
            if ref_rows[decision] == cand_rows[decision]:
                problems.append(f"row {decision} byte-aliasing across arms — identical row "
                                "digest for reference and candidate")
        _require(ref["derived"]["icd"] != cand["derived"]["icd"],
                 "reference/candidate ICDs identical — mutually exclusive backends required", problems)
        # Cross-arm anti-aliasing on the COMPLETE incarnation tuple: the
        # two arms must be distinct executions (same-host/same-boot is
        # legal, identical incarnation is not).
        ref_incarn = tuple(ref["derived"].get(f) for f in ("pid", "boot_id", "start_ticks"))
        cand_incarn = tuple(cand["derived"].get(f) for f in ("pid", "boot_id", "start_ticks"))
        _require(ref_incarn != cand_incarn,
                 "reference/candidate share the same full process incarnation — "
                 "not distinct executions", problems)
        ref_binding = _parse((Path(staged_root) / "units" / case / "reference.json").read_bytes(), "binding")
        cand_binding = _parse((Path(staged_root) / "units" / case / "candidate.json").read_bytes(), "binding")
        ref_src = ref_binding.get("files", {}).get("receipt.json")
        cand_src = cand_binding.get("files", {}).get("receipt.json")
        if ref_src is not None and ref_src == cand_src:
            problems.append("reference/candidate staged evidence binds the SAME source "
                            "run receipt — cross-arm source reuse")
    return {"schema": SCHEMA, "case": case,
            "admitted": not problems, "problems": problems,
            "units": {f"{arm}{'+repeat' if repeat else ''}": units[(arm, repeat)]["admitted"]
                      for arm in ("reference", "candidate") for repeat in (False, True)}}
