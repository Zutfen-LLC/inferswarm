#!/usr/bin/env python3
"""Phase-2 sequential matched-placement runner and raw custody producer.

Physical execution is reachable only through an exact-head dispatch authority
supplied and revalidated by the orchestration layer. Tests inject a fake runner.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

try:
    from . import issue241_census as census
    from . import issue241_constants as C
    from . import issue241_dispatch as dispatch
    from . import issue241_placement as placement
except ImportError:  # direct script import from scripts/ used by older callers
    import issue241_census as census
    import issue241_constants as C
    import issue241_dispatch as dispatch
    import issue241_placement as placement

RUNG_REPEATS = placement.RUNG_REPEATS

SCHEMA = "inferswarm.issue241.phase2-producer-receipt/1"
IDENTITY_OBSERVATION_SCHEMA = "inferswarm.issue241.phase2-identity-observation/1"
SERVER_TIMEOUT_S = 900
HEALTH_TIMEOUT_S = 300
REQUEST_TIMEOUT_S = 300
SAMPLE_INTERVAL_S = 1.0
MEASURED_FIELDS = ("rss_file_kib", "rss_anon_kib", "swap_kib",
                   "physical_read_bytes", "major_faults")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _authority(value: Any, initial: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != dispatch.AUTHORITY_SCHEMA:
        raise ValueError("explicit validated dispatch authority required")
    head = value.get("head_sha")
    if (not isinstance(head, str) or not dispatch.SHA40.fullmatch(head)
            or value.get("review_commit_id") != head
            or value.get("dispatch_phrase") != dispatch.DISPATCH_PHRASE
            or value.get("pr_number") != 242 or value.get("issue_number") != C.ISSUE
            or isinstance(value.get("review_id"), bool)
            or not isinstance(value.get("review_id"), int) or value["review_id"] <= 0):
        raise ValueError("dispatch authority head/review binding invalid")
    if initial is not None and value != initial:
        raise RuntimeError("dispatch authority changed before arm execution")
    return value


def _proc_root(pid: int) -> Path:
    return Path(f"/proc/{pid}")


def _proc_snapshot(pid: int) -> dict[str, Any]:
    """Read measured resident, swap, physical IO and major-fault counters."""
    base = _proc_root(pid)
    status = (base / "status").read_text()
    io = (base / "io").read_text()
    stat = (base / "stat").read_text()
    def number(text: str, key: str, unit: str = "") -> int:
        matches = [line.split() for line in text.splitlines() if line.startswith(key + ":")]
        if len(matches) != 1 or len(matches[0]) != (3 if unit else 2):
            raise ValueError(f"missing process counter {key}")
        if unit and matches[0][2] != unit:
            raise ValueError(f"invalid process counter unit {key}")
        value = int(matches[0][1])
        if value < 0:
            raise ValueError(f"negative process counter {key}")
        return value
    # /proc/pid/stat field 12 (majflt) follows pid + parenthesized comm.
    fields = stat.rsplit(") ", 1)
    if len(fields) != 2 or not fields[1].startswith(("R ", "S ", "D ", "I ", "Z ")):
        raise ValueError("malformed process stat")
    rest = fields[1].split()  # state=field 3; majflt=field 12 => index 9
    if len(rest) <= 9:
        raise ValueError("missing process major faults")
    major_faults = int(rest[9])
    if major_faults < 0:
        raise ValueError("negative process major faults")
    return {"pid": pid, "status": status, "io": io, "stat": stat,
            "cmdline": (base / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip(),
            "rss_file_kib": number(status, "RssFile", "kB"),
            "rss_anon_kib": number(status, "RssAnon", "kB"),
            "swap_kib": number(status, "VmSwap", "kB"),
            "physical_read_bytes": number(io, "read_bytes"),
            "major_faults": major_faults}


def _device_snapshot() -> dict[str, Any]:
    """Independent NVIDIA and AMD residency sources, keyed by physical BDF."""
    nvidia: dict[str, dict[str, Any]] = {}
    try:
        proc = subprocess.run(["nvidia-smi", "--query-gpu=uuid,pci.bus_id,memory.used",
                               "--format=csv,noheader,nounits"], capture_output=True,
                              text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("NVIDIA residency sampling failed") from exc
    for line in proc.stdout.splitlines():
        fields = [x.strip() for x in line.split(",")]
        if len(fields) != 3:
            raise RuntimeError("malformed NVIDIA residency sample")
        uuid, bdf, used = fields
        nvidia[bdf] = {"uuid": uuid, "used_mib": int(used)}
    amd: dict[str, dict[str, int]] = {}
    for dev in sorted(Path("/sys/bus/pci/devices").iterdir()):
        bdf = dev.name
        if len(bdf) == 12:  # sysfs 0000:02:00.0 -> frozen 00000000:02:00.0
            bdf = "00000000:" + bdf[5:]
        for card in sorted(dev.glob("drm/card[0-9]*")):
            path = card / "device/mem_info_vram_used"
            if path.is_file():
                amd[bdf] = {"vram_used_bytes": int(path.read_text().strip())}
                break
    return {"captured_at": time.time(), "nvidia": nvidia, "amd": amd}


def _residency(device: dict[str, Any], bdf: str) -> float:
    if bdf in device["nvidia"]:
        return float(device["nvidia"][bdf]["used_mib"])
    if bdf in device["amd"]:
        return device["amd"][bdf]["vram_used_bytes"] / (1024 * 1024)
    raise RuntimeError(f"excluded physical device {bdf} not observed")


def _vulkan_devices(text: str) -> list[dict[str, str]]:
    """Parse ``vulkaninfo --summary`` GPU blocks into key/value dicts."""
    gpus: list[dict[str, str]] = []
    for line in text.splitlines():
        s = line.strip()
        if re.fullmatch(r"GPU\d+:", s):
            gpus.append({})
        elif gpus and "=" in s:
            k, _, v = s.partition("=")
            gpus[-1][k.strip()] = v.strip()
    return gpus


def derive_identity_from_raw(arm: str, raw: Any) -> dict[str, Any]:
    """Mechanically derive the identity observation fields from the
    retained RAW source values (pure function; no host access). The
    same derivation backs the live observer, the rung receipts, and the
    independent Phase-3 re-verification, so a forged parsed identity
    with no supporting raw bytes cannot pass anywhere."""
    if arm not in ("B", "C"):
        raise ValueError(f"unsupported arm {arm!r}")
    cfg = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    bdf = cfg["bdf"]
    if not isinstance(raw, dict) or raw.get("sysfs_present") is not True:
        return {"bdf": bdf, "selected_device_present": False}
    sysfs = raw.get("sysfs")
    if not isinstance(sysfs, dict):
        raise ValueError("raw identity observation lacks sysfs source values")
    def attr(name: str) -> str:
        value = sysfs.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"raw identity sysfs source missing {name}")
        return value.strip()
    identity: dict[str, Any] = {
        "bdf": bdf,
        "vendor_id": attr("vendor").lower().removeprefix("0x"),
        "device_id": attr("device").lower().removeprefix("0x"),
        "subsystem_vendor_id": attr("subsystem_vendor").lower().removeprefix("0x"),
        "subsystem_device_id": attr("subsystem_device").lower().removeprefix("0x"),
        "revision": attr("revision").lower().removeprefix("0x"),
        "link_width": "x" + attr("current_link_width"),
        "max_link_width": "x" + attr("max_link_width"),
        # canonical spelling (kernel sysfs spells "8.0 GT/s PCIe"; the
        # frozen constants and every downstream identity field use the
        # normalized form; the retained raw artifact keeps the kernel text)
        "max_link_speed": census.normalize_link_speed(attr("max_link_speed")),
        "link_speed": census.normalize_link_speed(attr("current_link_speed")),
        "driver_in_use": attr("driver"),
    }
    identity["pci_id"] = f"{identity['vendor_id']}:{identity['device_id']}"
    if arm == "B":
        text = raw.get("nvidia_smi")
        if not isinstance(text, str):
            raise ValueError("raw NVIDIA UUID/BDF observation missing")
        for line in text.splitlines():
            fields = [x.strip() for x in line.split(",")]
            if len(fields) == 2:
                uuid, bus = fields
                if len(bus) == 12:
                    bus = "00000000:" + bus[5:]
                if bus == bdf:
                    identity["gpu_uuid"] = uuid
    text = raw.get("vulkaninfo_summary")
    if not isinstance(text, str):
        raise ValueError("raw Vulkan summary observation missing")
    gpus = _vulkan_devices(text)
    if gpus:
        identity["vulkan_device_name"] = gpus[0].get("deviceName")
        identity["vulkan_device_uuid"] = gpus[0].get("deviceUUID")
        identity["vulkan_api_version"] = gpus[0].get("apiVersion")
        identity["vulkan_icd"] = cfg["icd"]
    if arm == "C":
        vram = raw.get("amd_vram_total_bytes")
        if isinstance(vram, int) and not isinstance(vram, bool) and vram > 0:
            identity["vram_mib"] = vram // (1024 * 1024)
    return identity


def _observe_arm_identity(arm: str) -> dict[str, Any]:
    """Live per-repeat device-identity observation for the EXECUTING arm:
    read the RAW source values (sysfs PCI attrs, driver symlink,
    nvidia-smi UUID/BDF, per-ICD vulkaninfo summary, AMD VRAM total)
    and derive the identity mechanically from exactly those values. The
    returned raw block is what gets retained and SHA-bound per repeat."""
    if arm not in ("B", "C"):
        raise ValueError(f"unsupported arm {arm!r}")
    cfg = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    bdf = cfg["bdf"]
    sysfs_dir = Path("/sys/bus/pci/devices") / (f"{int(bdf[:8],16):04x}" + bdf[8:])
    if not sysfs_dir.is_dir():
        return {"raw": {"sysfs_present": False},
                "identity": {"bdf": bdf, "selected_device_present": False}}
    raw: dict[str, Any] = {"sysfs_present": True, "sysfs": {
        name: (sysfs_dir / name).read_text().strip()
        for name in ("vendor", "device", "subsystem_vendor", "subsystem_device",
                     "revision", "current_link_width", "current_link_speed",
                     "max_link_width", "max_link_speed")}}
    raw["sysfs"]["driver"] = (sysfs_dir / "driver").resolve().name
    try:
        proc = subprocess.run(["nvidia-smi", "--query-gpu=uuid,pci.bus_id",
                               "--format=csv,noheader,nounits"], capture_output=True,
                              text=True, timeout=5, check=True)
        raw["nvidia_smi"] = proc.stdout
    except (OSError, subprocess.SubprocessError):
        raw["nvidia_smi"] = ""
    env = dict(os.environ)
    env.update(cfg["selector"])
    env["VK_ICD_FILENAMES"] = cfg["icd"]
    env["VK_DRIVER_FILES"] = cfg["icd"]
    try:
        proc = subprocess.run(["vulkaninfo", "--summary"], capture_output=True,
                              text=True, timeout=15, env=env)
        raw["vulkaninfo_summary"] = proc.stdout
    except (OSError, subprocess.SubprocessError):
        raw["vulkaninfo_summary"] = ""
    if arm == "C":
        for card in sorted(sysfs_dir.glob("drm/card[0-9]*")):
            total = card / "device/mem_info_vram_total"
            if total.is_file():
                raw["amd_vram_total_bytes"] = int(total.read_text().strip())
                break
    return {"raw": raw, "identity": derive_identity_from_raw(arm, raw)}


def _verified_identity_observation(observe: Callable[[str], dict[str, Any]],
                                    arm: str) -> dict[str, Any]:
    """Observer seam contract: the returned identity must equal the
    mechanical derivation from the returned raw source values — a
    claimed parsed identity with no supporting raw bytes fails closed
    here, at production time, before any execution unit is retained."""
    observation = observe(arm)
    if (not isinstance(observation, dict) or "raw" not in observation
            or "identity" not in observation):
        raise ValueError("identity observer must return {raw, identity}")
    derived = derive_identity_from_raw(arm, observation["raw"])
    if observation["identity"] != derived:
        raise ValueError(
            "observer identity differs from raw-source derivation")
    return observation


def _device_health(arm: str, identity: dict[str, Any],
                   baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Derive objective device/driver health from the live identity
    observation plus retained telemetry; NO invented thresholds."""
    cfg = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    fatal: list[str] = []
    observed = dict(identity)
    observed["selected_device_present"] = identity.get(
        "selected_device_present", True) and cfg["bdf"] == identity.get("bdf")
    if not observed["selected_device_present"]:
        fatal.append("selected_device_disappeared")
    if identity.get("driver_in_use") not in (None, cfg["kernel_driver"]):
        fatal.append("driver_drift")
    if identity.get("bdf") != cfg["bdf"]:
        fatal.append("bdf_drift")
    if identity.get("vulkan_icd") not in (None, cfg["icd"]):
        fatal.append("icd_drift")
    # GPU-side reset/error state from retained dmesg-class evidence, if the
    # caller supplied it; absence of the channel is NOT fatal (retained
    # telemetry elsewhere carries the residency evidence).
    if baseline and isinstance(baseline.get("gpu_error_markers"), list):
        if baseline["gpu_error_markers"]:
            fatal.append("device_reset_or_error")
    return {"fatal_states": sorted(set(fatal)), "observed": observed}


def _sane_completion(response_body: bytes) -> tuple[bool, list[int] | None]:
    """Sane completion evidence under the frozen return_tokens contract:
    HTTP JSON carrying exactly n_predict integer tokens, each a valid
    vocabulary id (0 <= token < C.N_VOCAB)."""
    try:
        doc = json.loads(response_body)
    except (ValueError, TypeError):
        return False, None
    tokens = doc.get("tokens")
    if not isinstance(tokens, list) or len(tokens) != C.REQUEST_CONTRACT["n_predict"]:
        return False, None
    if any(not isinstance(t, int) or isinstance(t, bool) for t in tokens):
        return False, None
    if any(not 0 <= t < C.N_VOCAB for t in tokens):
        return False, None
    return True, tokens


def _real_runner(argv: list[str], *, log_path: Path, arm: str, ngl: int,
                 prompt_tokens: list[int], timeout_s: int = SERVER_TIMEOUT_S,
                 **_: Any) -> dict[str, Any]:
    """Bounded server + frozen geometry, with sampling during HTTP execution."""
    if arm not in ("B", "C"):
        raise ValueError(f"unsupported arm {arm!r}")
    env = os.environ.copy()
    arm_config = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    env.update(arm_config["selector"])
    env["VK_ICD_FILENAMES"] = arm_config["icd"]
    if "--model" not in argv:
        argv = [*argv, "--model", str(C.MODEL_DIR / C.MODEL_MEMBERS[0])]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    argv = [*argv, "--ctx-size", str(C.CONTEXT_SETTINGS["ctx-size"]),
            "--batch-size", str(C.CONTEXT_SETTINGS["batch-size"]),
            "--host", "127.0.0.1", "--port", str(port), "-lv", "5"]
    excluded = C.EXCLUDED_BY_ARM[arm]
    baseline = _device_snapshot()
    for bdf in excluded:
        _residency(baseline, bdf)
    samples: list[dict[str, Any]] = []
    errors: list[Exception] = []
    stop = threading.Event()
    started = time.monotonic()
    response_body = b""
    with log_path.open("xb") as log:
        try:
            proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env,
                                    start_new_session=True)
        except OSError as exc:
            return {"pid": None, "argv": argv, "returncode": None,
                    "http_status": None, "spawn_failure": True, "response_raw": response_body,
                    "failure": f"server spawn failed: {type(exc).__name__}: {exc}",
                    "proc_status": [], "proc_io": [], "process_measurements": {},
                    "gpu_telemetry": {"source": "live-device-samples", "baseline": baseline,
                                      "samples": []},
                    "excluded_device_residency_mib": {},
                    "environment": {k: env.get(k) for k in
                                    ("VK_ICD_FILENAMES", "GGML_VK_VISIBLE_DEVICES", "CUDA_VISIBLE_DEVICES")}}
        def sample() -> None:
            try:
                while not stop.is_set() and proc.poll() is None:
                    samples.append({"t": time.time(), "proc": _proc_snapshot(proc.pid),
                                    "device": _device_snapshot()})
                    stop.wait(SAMPLE_INTERVAL_S)
            except Exception as exc:
                errors.append(exc)
                stop.set()
        worker = threading.Thread(target=sample, daemon=True)
        worker.start()
        failure: str | None = None
        http_status: int | None = None
        try:
            health_deadline = min(started + HEALTH_TIMEOUT_S, started + timeout_s)
            while time.monotonic() < health_deadline:
                if errors:
                    raise RuntimeError("placement sampling failed") from errors[0]
                if proc.poll() is not None:
                    failure = f"server exited before health check: {proc.returncode}"
                    break
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(SAMPLE_INTERVAL_S)
            else:
                failure = "server health timeout"
            if failure is None:
                request_body = json.dumps({"prompt": prompt_tokens,
                                           **C.REQUEST_CONTRACT}).encode()
                request = urllib.request.Request(f"http://127.0.0.1:{port}/completion",
                                                 data=request_body,
                                                 headers={"Content-Type": "application/json"})
                remaining = timeout_s - (time.monotonic() - started)
                if remaining <= 0:
                    failure = "placement arm timeout"
                else:
                    try:
                        with urllib.request.urlopen(request, timeout=min(REQUEST_TIMEOUT_S, remaining)) as response:
                            http_status = response.status
                            response_body = response.read(1024 * 1024)
                            if http_status != 200 or not response_body:
                                failure = "server HTTP completion failed"
                    except urllib.error.HTTPError as exc:
                        http_status = exc.code
                        failure = f"server HTTP completion failed: {exc.code}"
                    except (urllib.error.URLError, OSError, TimeoutError) as exc:
                        failure = f"server HTTP completion failed: {type(exc).__name__}: {exc}"
        finally:
            stop.set()
            worker.join(timeout=10)
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
        if errors or worker.is_alive():
            raise RuntimeError("placement sampling failed") from (errors[0] if errors else None)
        if failure is None and not samples:
            raise RuntimeError("successful placement has no process samples")
        measured = {k: max(s["proc"][k] for s in samples) for k in MEASURED_FIELDS} if samples else {}
        excluded_residency = {
            bdf: max(abs(_residency(s["device"], bdf) - _residency(baseline, bdf))
                     for s in samples) for bdf in excluded} if samples else {}
        result = {"pid": proc.pid, "argv": argv,
                  "returncode": proc.returncode if failure else 0,
                  "http_status": http_status, "request_wall_s": time.monotonic() - started,
                  "proc_status": [s["proc"]["status"] for s in samples],
                  "proc_io": [s["proc"]["io"] for s in samples],
                  "process_measurements": measured,
                  "gpu_telemetry": {"source": "live-device-samples", "baseline": baseline,
                                    "samples": samples},
                  "excluded_device_residency_mib": excluded_residency,
                  "environment": {k: env.get(k) for k in
                                  ("VK_ICD_FILENAMES", "GGML_VK_VISIBLE_DEVICES", "CUDA_VISIBLE_DEVICES")}}
        if failure is not None:
            result["failure"] = failure
        result["response_raw"] = response_body
        if failure is None:
            try:
                response_doc = json.loads(response_body)
                timing = response_doc["timings"]
                prompt_ms, decode_ms = timing["prompt_ms"], timing["predicted_ms"]
                if any(not isinstance(x, (int, float)) or isinstance(x, bool)
                       or not 0 <= x < float("inf") for x in (prompt_ms, decode_ms)):
                    raise ValueError("invalid completion timings")
                result["request_timings"] = {"prompt_ms": prompt_ms,
                                             "decode_ms": decode_ms}
            except (ValueError, KeyError, TypeError) as exc:
                raise RuntimeError("placement response lacks measured prompt/decode timings") from exc
        return result


def _measurement(result: Any, arm: str) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("synthetic") is True:
        raise ValueError("synthetic or missing process measurement")
    if not (result.get("spawn_failure") is True and result.get("pid") is None and
            isinstance(result.get("failure"), str) and result["failure"] and
            result.get("returncode") is None) and (
            not isinstance(result.get("pid"), int) or isinstance(result["pid"], bool)
            or result["pid"] <= 0):
        raise ValueError("invalid process attribution PID")
    failed = (result.get("returncode") != 0 or result.get("http_status") != 200
              or bool(result.get("failure")))
    for field in ("proc_status", "proc_io", "gpu_telemetry"):
        if field not in result or (not failed and not result[field]):
            raise ValueError(f"missing process/GPU measurement: {field}")
    telemetry = result["gpu_telemetry"]
    if (not isinstance(telemetry, dict) or telemetry.get("synthetic") is True
            or not isinstance(telemetry.get("samples"), list)
            or (not failed and not telemetry["samples"])):
        raise ValueError("missing or synthetic GPU telemetry samples")
    measurements = result.get("process_measurements")
    if not isinstance(measurements, dict):
        raise ValueError("missing process measurements")
    for key in MEASURED_FIELDS:
        val = measurements.get(key)
        if (val is None and failed):
            continue
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise ValueError(f"missing/invalid process measurement {key}")
    excluded = result.get("excluded_device_residency_mib")
    if (not isinstance(excluded, dict) or
            (not failed and set(excluded) != C.EXCLUDED_BY_ARM[arm]) or
            (failed and not set(excluded) <= C.EXCLUDED_BY_ARM[arm])):
        raise ValueError("excluded device residency must cover exact arm BDF set")
    for value in excluded.values():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value < float("inf"):
            raise ValueError("invalid excluded device residency measurement")
    if failed and result.get("http_status") not in (None, 200) and not isinstance(result["http_status"], int):
        raise ValueError("invalid observed HTTP status")
    if not failed:
        raw_response = result.get("response_raw")
        timing = result.get("request_timings")
        if not isinstance(raw_response, bytes) or not raw_response or not isinstance(timing, dict):
            raise ValueError("successful placement missing raw response/timings")
        try:
            observed = json.loads(raw_response)["timings"]
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("successful placement response has no timings") from exc
        if (timing.get("prompt_ms") != observed.get("prompt_ms")
                or timing.get("decode_ms") != observed.get("predicted_ms")):
            raise ValueError("placement timing summary differs from raw response")
    return result


def _atomic_json(path: Path, doc: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to overwrite receipt: {path}")
    temp = path.with_name(path.name + ".pending")
    with temp.open("xb") as stream:
        stream.write((json.dumps(doc, sort_keys=True, indent=2) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def run_phase2_producer(repo_root: Path, out_root: Path, server: Path,
                        authority: dict[str, Any], *, runner: Callable[..., Any] | None = None,
                        telemetry: Callable[[int], dict[str, Any]] | None = None,
                        revalidate_authority: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                        model: Path | None = None,
                        identity_observer: Callable[[str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Execute all five rungs C then B; no receipt until raw custody is complete.

    Each retained execution unit at each rung is REPEATED RUNG_REPEATS
    times (bounded prospectively). Per repeat (correction pass 5):
      * the exact-head dispatch authority is revalidated BEFORE the unit;
      * a raw device-identity observation (sysfs PCI attrs, driver,
        nvidia-smi, per-ICD vulkaninfo, AMD VRAM) is captured immediately
        BEFORE execution, retained as its own SHA-256-bound artifact, and
        the identity is mechanically derived from exactly those raw
        values;
      * the complete raw HTTP response is retained and SHA-256-bound
        (custody); the acceptance-bearing deterministic output is the
        canonical little-endian u32 encoding of its exactly-8 in-vocabulary
        token ids and its SHA-256 — timings/metadata never enter it;
      * a second raw identity/health observation is captured immediately
        AFTER execution and bound the same way.
    The rung-level identity/health fields are aggregates of the per-repeat
    observations, so no later good observation can hide an earlier drift."""
    if not callable(revalidate_authority):
        raise ValueError("required live dispatch authority revalidator missing")
    initial = _authority(authority)
    authority = _authority(revalidate_authority(initial), initial)
    observe_identity = identity_observer or _observe_arm_identity
    root, out = Path(repo_root).resolve(), Path(out_root)
    if not root.is_dir():
        raise ValueError("repo_root must be an existing directory")
    target = out / "phase2-placement-receipt.json"
    if target.exists() or target.is_symlink():
        raise ValueError("refusing to overwrite placement receipt")
    out.mkdir(parents=True, exist_ok=True)
    execute = runner or _real_runner
    fixtures = C.load_fixtures(root)
    prompt_tokens = fixtures["case-256"]["prompt_token_ids"]
    if (not isinstance(prompt_tokens, list) or not prompt_tokens
            or any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in prompt_tokens)):
        raise ValueError("invalid frozen historical placement prompt tokens")
    by_arm: dict[str, list[dict[str, Any]]] = {"C": [], "B": []}
    receipts: list[dict[str, Any]] = []
    for ngl in C.LADDER_NGLS:
        for arm in ("C", "B"):
            repeats: list[dict[str, Any]] = []
            repeat_raw_paths: list[Path] = []
            log_paths: list[Path] = []
            exec_results: list[dict[str, Any]] = []
            for repeat_index in range(RUNG_REPEATS):
                # Revalidate exact-head dispatch BEFORE each retained
                # execution unit (each repeat is a retained unit).
                authority = _authority(revalidate_authority(authority), initial)
                suffix = "" if repeat_index == 0 else f".repeat{repeat_index}"
                log_path = out / f"{arm}-ngl{ngl}{suffix}.server.log"
                telemetry_path = out / f"{arm}-ngl{ngl}{suffix}.telemetry.json"
                ident_pre_path = out / f"{arm}-ngl{ngl}{suffix}.identity-pre.json"
                ident_post_path = out / f"{arm}-ngl{ngl}{suffix}.identity-post.json"
                if any(p.exists() or p.is_symlink() for p in
                       (log_path, telemetry_path, ident_pre_path, ident_post_path)):
                    raise ValueError("refusing to overwrite raw placement evidence")
                # Live exact subject-identity observation for the executing
                # arm, IMMEDIATELY BEFORE this execution unit, from raw
                # sources that are retained and SHA-bound (drift vs the
                # frozen subject fails closed in judge_rung via
                # identity_problems, on EVERY repeat).
                pre = _verified_identity_observation(observe_identity, arm)
                _atomic_json(ident_pre_path, {
                    "schema": IDENTITY_OBSERVATION_SCHEMA,
                    "campaign": C.CAMPAIGN_ID, "arm": arm, "ngl": ngl,
                    "repeat_index": repeat_index, "capture_stage": "pre-execution",
                    "raw": pre["raw"], "derived_identity": pre["identity"]})
                argv = [str(Path(server)), "--n-gpu-layers", str(ngl)]
                if model is not None:
                    argv += ["--model", str(model)]
                result = _measurement(execute(argv, arm=arm, ngl=ngl,
                                               log_path=log_path, authority=authority,
                                               prompt_tokens=prompt_tokens), arm)
                response_bytes = result.pop("response_raw", b"")
                if not isinstance(response_bytes, bytes):
                    raise ValueError("placement raw response must be bytes")
                response_path = out / f"{arm}-ngl{ngl}{suffix}.response.json"
                if response_path.exists() or response_path.is_symlink():
                    raise ValueError("refusing to overwrite raw placement response")
                with response_path.open("xb") as stream:
                    stream.write(response_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                if not log_path.is_file() or (not log_path.stat().st_size and
                                              result.get("returncode") == 0 and result.get("http_status") == 200
                                              and not result.get("failure")):
                    raise ValueError(f"missing raw server log for {arm} ngl={ngl}")
                # Preserve complete sampled process/device telemetry before deriving summary.
                _atomic_json(telemetry_path, result)
                # Second identity/health observation IMMEDIATELY AFTER this
                # same execution unit, retained and bound the same way.
                post = _verified_identity_observation(observe_identity, arm)
                post_health = _device_health(arm, post["identity"])
                _atomic_json(ident_post_path, {
                    "schema": IDENTITY_OBSERVATION_SCHEMA,
                    "campaign": C.CAMPAIGN_ID, "arm": arm, "ngl": ngl,
                    "repeat_index": repeat_index, "capture_stage": "post-execution",
                    "raw": post["raw"], "derived_identity": post["identity"],
                    "derived_health": post_health})
                sane, tokens = _sane_completion(response_bytes)
                canonical = placement.canonical_token_bytes(tokens)
                det_sha = (hashlib.sha256(canonical).hexdigest()
                           if canonical is not None else None)
                repeats.append({
                    "index": repeat_index,
                    "sane_completion": sane,
                    "response_tokens": tokens,
                    "deterministic_output_sha256": det_sha,
                    "response_raw": response_path.name,
                    "response_raw_sha256": _sha(response_path),
                    "raw_log": log_path.name,
                    "raw_log_sha256": _sha(log_path),
                    "raw_telemetry": telemetry_path.name,
                    "raw_telemetry_sha256": _sha(telemetry_path),
                    "identity_pre": pre["identity"],
                    "raw_identity_pre": ident_pre_path.name,
                    "raw_identity_pre_sha256": _sha(ident_pre_path),
                    "identity_post": post["identity"],
                    "raw_identity_post": ident_post_path.name,
                    "raw_identity_post_sha256": _sha(ident_post_path),
                    "identity_post_health": post_health,
                    "request_timings": result.get("request_timings"),
                    "failure": result.get("failure"),
                })
                repeat_raw_paths.append(response_path)
                log_paths.append(log_path)
                exec_results.append(result)
            primary = exec_results[0]
            log_path = log_paths[0]
            parsed = placement.parse_placement(log_path.read_text(errors="replace"))
            record = {"schema": placement.RUNG_SCHEMA, "arm": arm, "ngl": ngl,
                      "loaded": (primary["returncode"] == 0 and primary.get("http_status") == 200
                                 and not primary.get("failure")),
                      "placement": parsed,
                      "excluded_device_residency_mib": primary["excluded_device_residency_mib"],
                      "process_measurements": primary.get("process_measurements"),
                      "request_timings": primary.get("request_timings"),
                      "device_identity": repeats[0]["identity_pre"],
                      "post_execution_device_identity": repeats[-1]["identity_post"],
                      "device_health": repeats[-1]["identity_post_health"],
                      "repeats": repeats}
            verdict = placement.judge_rung(record)
            by_arm[arm].append(record)
            receipts.append({"arm": arm, "ngl": ngl,
                             "raw_log": log_path.name,
                             "raw_log_sha256": _sha(log_path),
                             "raw_response": repeat_raw_paths[0].name,
                             "raw_response_sha256": _sha(repeat_raw_paths[0]),
                             "raw_telemetry": repeats[0]["raw_telemetry"],
                             "raw_telemetry_sha256": repeats[0]["raw_telemetry_sha256"],
                             "repeats": repeats,
                             "device_identity": repeats[0]["identity_pre"],
                             "post_execution_device_identity": repeats[-1]["identity_post"],
                             "device_health": repeats[-1]["identity_post_health"],
                             "process": primary, "verdict": verdict})
    selected = placement.select_matched_rung(by_arm)
    doc = {"schema": SCHEMA, "campaign": C.CAMPAIGN_ID,
           "authority": authority, "rungs": by_arm,
           "rung_receipts": receipts, "selected": selected}
    doc["digest"] = hashlib.sha256(json.dumps(doc, sort_keys=True,
                                                separators=(",", ":")).encode()).hexdigest()
    _atomic_json(target, doc)
    return doc
