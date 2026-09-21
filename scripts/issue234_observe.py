#!/usr/bin/env python3
"""Issue #234 — R8-H observation execution-identity collector (physical producer).

Round-3 correction (maintainer finding on c1ac7237): the retained
position-0 observation corpus proves token/logit output but NOT the
GPU/backend execution identity behind it. Observation tokens equal to
the canonical stream cannot prove the intended GPU/backend was used
(the quarantined relative-ICD CPU-fallback incident produced different
tokens only by luck of nondeterminism-free CPU execution; equality is
not identity proof).

This collector launches each arm's bounded observation-only run under
the EXACT pinned selectors and mechanically captures an EXECUTION
RECEIPT (schema inferswarm.r8h.observation-execution-receipt/1):

  * host identity (hostname, kernel boot id);
  * exact observation binary (path, sha256, bin-dir object hashes)
    and, for arms built on the local r8h-obs worktree, the llama.cpp
    source pin, tree state, and observation-hook diff digest (arm C
    proves hook identity through byte-identity to arm B's binary);
  * exact launch argv (from /proc/PID/cmdline) and the exact relevant
    environment (from /proc/PID/environ — the environment AT exec,
    which cannot drift after the fact);
  * in-process backend participation (/proc/PID/maps: which libggml
    backend objects are actually mapped into the server);
  * device identity under the EXACT launch environment:
      - llama-server --list-devices output (restricted + both-index
        attempts for Vulkan arms);
      - vulkaninfo --summary physical-device UUIDs (Vulkan arms),
        joined to BDF (NVIDIA via nvidia-smi UUID<->bus_id; RADV via
        the BDF-encoding deviceUUID);
      - nvidia-smi UUID/BDF table + LIVE compute-apps binding (CUDA
        arm: the server PID must be bound to the frozen GPU UUID);
  * pre / during / post accelerator residency and activity for the
    selected AND excluded devices (model-scale delta required on the
    selected device; excluded devices under the frozen noise bound);
  * CPU-fallback rejection evidence (no-usable-GPU warning absent,
    devices listed under the launch env, model-scale residency);
  * artifact digests (observation JSONL, float32 row, response,
    server log) binding the receipt to the retained bytes;
  * the generated token stream — any mismatch with the canonical arm
    stream QUARANTINES the run before a receipt is emitted.

The collector emits NO correctness verdict: the terminal reducer
(issue234_reduce.reduce_observation_execution_truth) re-validates
every relation from the receipt bytes and fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc

RECEIPT_SCHEMA = rc.OBSERVATION_RECEIPT_SCHEMA
POSITION = 0
MODEL_SCALE_BYTES = rc.EXCLUDED_DEVICE_MAX_BYTES  # 8 MiB noise bound;
# a selected device carrying LESS than this never held model tensors.

CANONICAL = rc.CANONICAL_CASE256_STREAMS

EXPECTED_HOST = {"A": "inferswarm01", "B": "inferswarm01",
                 "C": "inferswarm02"}


class CollectError(RuntimeError):
    pass


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _run(cmd: list[str], env: dict | None = None,
         timeout: int = 300) -> tuple[int, str]:
    full = {"PATH": "/usr/bin:/bin"}
    if env:
        full.update(env)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          env=full, timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# ---------------------------------------------------------------------
# Accelerator state sampling
# ---------------------------------------------------------------------

def nvidia_state() -> dict[str, Any]:
    """UUID -> {bdf, mem_used_mib}; plus live compute-apps list."""
    rc1, out = _run(["nvidia-smi", "--query-gpu=uuid,pci.bus_id,memory.used",
                     "--format=csv,noheader"])
    gpus: dict[str, Any] = {}
    if rc1 == 0:
        for line in out.splitlines():
            f = [x.strip() for x in line.split(",")]
            if len(f) == 3:
                gpus[f[0]] = {"bdf": f[1], "mem_used_mib": int(f[2].split()[0])}
    rc2, apps = _run(["nvidia-smi",
                      "--query-compute-apps=pid,gpu_uuid,used_memory",
                      "--format=csv,noheader"])
    compute_apps = []
    if rc2 == 0:
        for line in apps.splitlines():
            f = [x.strip() for x in line.split(",")]
            if len(f) == 3 and f[0].isdigit():
                compute_apps.append({"pid": int(f[0]), "gpu_uuid": f[1],
                                     "used_memory": f[2]})
    return {"gpus": gpus, "compute_apps": compute_apps}


def amd_state() -> dict[str, Any]:
    """16-char BDF -> {vis_vram_used, vram_used} via sysfs."""
    res: dict[str, Any] = {}
    for dev in sorted(Path("/sys/bus/pci/devices").iterdir()):
        name = dev.name
        if len(name) == 12:
            # short PCI form "0000:06:00.0" -> 16-char domain form
            # "00000000:06:00.0" (8-hex domain field)
            name = "00000000:" + name[5:]
        drm = sorted(dev.glob("drm/card*"))
        if not drm:
            continue
        m = {}
        for key in ("mem_info_vis_vram_used", "mem_info_vram_used",
                    "mem_info_gtt_used"):
            f = drm[0] / "device" / key
            if f.is_file():
                m[key] = int(f.read_text().strip())
        if m:
            res[name] = m
    return {"gpus": res, "compute_apps": []}


def _res_bytes(key: str, v: int) -> int:
    return v * 1024 * 1024 if key.endswith("_mib") else v


def _model_residency(entry: dict[str, int]) -> int:
    keys = [k for k in entry if "vis_vram_used" in k
            or k == "mem_used_mib" or k.endswith(".mem_info_vram_used")]
    vals = [_res_bytes(k, entry[k]) for k in keys]
    return max(vals) if vals else max(
        (_res_bytes(k, v) for k, v in entry.items()), default=0)


# ---------------------------------------------------------------------
# Device identity under the exact launch environment
# ---------------------------------------------------------------------

def parse_list_devices(text: str) -> list[dict[str, Any]]:
    """Parse `--list-devices` rows; names may themselves contain
    parentheses (e.g. 'AMD Radeon Pro V340 (RADV VEGA10)'), so the
    MiB field anchors the split — the LAST parenthesized group that
    starts with an integer."""
    devs = []
    for line in text.splitlines():
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        label = parts[0].strip()
        if not (label.startswith(("Vulkan", "CUDA")) and
                label[-1].isdigit()):
            continue
        rest = parts[1]
        mib = ""
        cut = -1
        for i in range(len(rest) - 1, -1, -1):
            if rest[i] == "(":
                seg = rest[i + 1:].split(")")[0].strip()
                toks = seg.split()[0] if seg.split() else ""
                if toks.isdigit():
                    mib = toks
                    cut = i
                    break
        name = rest[:cut].strip() if cut >= 0 else rest.strip()
        devs.append({"label": label, "name": name, "mib": mib})
    return devs


def list_devices(server: Path, env: dict) -> dict[str, Any]:
    rc0, out = _run([str(server), "--list-devices"], env=env, timeout=120)
    return {"raw": out, "parsed": parse_list_devices(out)}


def vulkan_summary(icd: str) -> dict[str, Any]:
    """vulkaninfo --summary under the exact ICD; parse GPU blocks."""
    rc0, out = _run(["vulkaninfo", "--summary"],
                    env={"VK_ICD_FILENAMES": icd}, timeout=120)
    gpus: dict[str, dict[str, str]] = {}
    cur = None
    for line in out.splitlines():
        s = line.strip()
        if s.endswith(":") and s.startswith("GPU") and " " not in s:
            cur = s[:-1]
            gpus[cur] = {}
            continue
        if cur and "=" in s:
            k, _, v = s.partition("=")
            gpus[cur][k.strip()] = v.strip()
        elif s and not s.startswith(("apiVersion", "deviceName")) and cur is None:
            continue
    return {"raw": out, "gpus": gpus}


def radv_uuid_to_bdf(uuid: str) -> str:
    """RADV deviceUUID encodes the BDF: dd_dd_dd_dd... form."""
    h = uuid.replace("-", "")
    if len(h) != 32:
        return ""
    return f"{h[0:8]}:{h[8:10]}:{h[10:12]}.{int(h[12:14], 16) & 0x7}"


def nvidia_uuid_bdf_table() -> dict[str, str]:
    st = nvidia_state()
    return {u: v.get("bdf", "") for u, v in st.get("gpus", {}).items()}


# ---------------------------------------------------------------------
# Source / binary identity
# ---------------------------------------------------------------------

def source_identity(worktree: Path | None) -> dict[str, Any]:
    if worktree is None:
        return {"provenance": "byte_identity_to_arm_B_binary"}
    rc0, head_out = _run(["git", "-C", str(worktree), "rev-parse", "HEAD"])
    rc1, status = _run(["git", "-C", str(worktree), "status",
                        "--porcelain"])
    rc2, diff = _run(["git", "-C", str(worktree), "diff"])
    head = head_out.strip()
    lines = [l for l in status.splitlines() if l.strip()]
    hook_files = [l for l in lines
                  if "server-context.cpp" in l and l.startswith(" M")]
    return {
        "provenance": "local_r8h_obs_worktree",
        "worktree": str(worktree),
        "llama_cpp_pin": head,
        "modified_paths": lines,
        "clean_excluding_hook": lines == hook_files,
        "hook_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "hook_diff_lines": len(diff.splitlines()),
    }


def execution_package_manifest(server: Path) -> dict[str, Any]:
    """Hash the complete executable/shared-object package before launch.

    Aliases are retained by name, while each record hashes the resolved regular
    file.  Authority therefore survives soname symlinks but never reduces to a
    basename-only assertion.
    """
    root = server.parent.resolve()
    objects: dict[str, dict[str, Any]] = {}
    for entry in sorted(root.iterdir()):
        if entry.name != "llama-server" and ".so" not in entry.name:
            continue
        try:
            resolved = entry.resolve(strict=True)
            st = resolved.stat()
        except OSError as e:
            raise CollectError(f"package object unavailable {entry}: {e}") from e
        if not resolved.is_file():
            raise CollectError(f"package object is not a regular file: {entry}")
        objects[entry.name] = {
            "realpath": str(resolved),
            "bytes": st.st_size,
            "sha256": sha(resolved),
        }
    if "llama-server" not in objects:
        raise CollectError("execution package lacks llama-server")
    return {"root": str(root), "objects": objects}


def maps_backend_objects(pid: int) -> list[dict[str, Any]]:
    """Capture mapped libggml objects as paths plus underlying-byte identity."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        for line in Path(f"/proc/{pid}/maps").read_text().splitlines():
            fields = line.split()
            if len(fields) < 6:
                continue
            path = fields[-1]
            if "libggml" not in Path(path).name or path.endswith(" (deleted)"):
                continue
            p = Path(path)
            try:
                resolved = p.resolve(strict=True)
                st = resolved.stat()
            except OSError:
                continue
            key = (str(p), str(resolved))
            found[key] = {"name": p.name, "path": str(p),
                          "realpath": str(resolved), "bytes": st.st_size,
                          "sha256": sha(resolved)}
    except (FileNotFoundError, ProcessLookupError):
        pass
    return sorted(found.values(), key=lambda x: (x["name"], x["path"]))


def bin_dir_hashes(server: Path) -> dict[str, str]:
    """Legacy summary retained for readers; /2 authority is package manifest."""
    return {name: meta["sha256"] for name, meta in
            execution_package_manifest(server)["objects"].items()}


def maps_backend_libraries(pid: int) -> list[str]:
    """Legacy basename summary retained alongside object-identity records."""
    return sorted({m["name"] for m in maps_backend_objects(pid)})


def proc_env(pid: int) -> dict[str, str]:
    raw = Path(f"/proc/{pid}/environ").read_bytes()
    out = {}
    for chunk in raw.split(b"\0"):
        if b"=" in chunk:
            k, _, v = chunk.partition(b"=")
            out[k.decode(errors="replace")] = v.decode(errors="replace")
    return out


def proc_argv(pid: int) -> list[str]:
    raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    return [c.decode(errors="replace") for c in raw.split(b"\0") if c]


# ---------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------

def collect(arm: str, server: Path, model_dir: Path, out_dir: Path,
            prompt_path: Path, source_worktree: Path | None,
            port: int = 18493) -> Path:
    if arm not in ("A", "B", "C"):
        raise CollectError(f"bad arm {arm!r}")
    server = server.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pfx = out_dir / arm
    jsonl_path = Path(f"{pfx}.jsonl")
    for stale in (jsonl_path, Path(f"{pfx}.resp.json"),
                  Path(f"{pfx}.request.json"), Path(f"{pfx}.server.log"),
                  Path(f"{pfx}.jsonl.pos0.f32"), Path(f"{pfx}.jsonl.pos0.f32.tmp")):
        stale.unlink(missing_ok=True)

    hostname = os.uname().nodename
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if hostname != EXPECTED_HOST[arm]:
        raise CollectError(
            f"arm {arm} must run on {EXPECTED_HOST[arm]}, not {hostname}")

    # ---- pre-launch identity --------------------------------------
    prompt_sha = sha(prompt_path)
    if prompt_sha != rc.PROMPT_CASE256_SHA256:
        raise CollectError("prompt identity drift")
    prompt_raw = prompt_path.read_bytes()
    prompt_doc = json.loads(prompt_raw)
    model_files = sorted(model_dir.glob("*.gguf"))
    if len(model_files) != len(rc.MODEL_MEMBERS):
        raise CollectError("model member count drift")
    model_members = []
    for want, member in zip(rc.MODEL_MEMBERS, model_files):
        actual = {"name": member.name, "bytes": member.stat().st_size,
                  "sha256": sha(member)}
        if actual != {"name": want["member"], "bytes": want["bytes"],
                      "sha256": want["sha256"]}:
            raise CollectError(f"model member identity drift: {member.name}")
        model_members.append(actual)
    execution_package = execution_package_manifest(server)
    binary_sha = execution_package["objects"]["llama-server"]["sha256"]

    icd_path: str | None = None
    icd_doc: dict[str, Any] | None = None
    launch_env_spec = dict(rc.OBSERVATION_LAUNCH_ENV[arm])
    if arm in ("B", "C"):
        icd_path = launch_env_spec["VK_ICD_FILENAMES"]
        if not os.path.isabs(icd_path):
            raise CollectError(
                f"arm {arm} ICD must be absolute: {icd_path!r}")
        icd_doc = {"path": icd_path, "sha256": sha(Path(icd_path)),
                   "parsed": json.loads(Path(icd_path).read_text())}

    env: dict[str, str] = {"PATH": "/usr/bin:/bin"}
    env.update(launch_env_spec)
    if arm in ("B", "C"):
        env["LD_LIBRARY_PATH"] = str(server.parent)
    env["LLAMA_OBSERVE_LOGITS"] = str(jsonl_path)
    env["LLAMA_OBSERVE_FOCUS"] = rc.OBSERVATION_FOCUS_ENV
    env["LLAMA_OBSERVE_POS"] = str(POSITION)
    request_body = {**rc.REQUEST_CONTRACT, "prompt": prompt_doc}
    request_raw = rc.canonical(request_body)
    request_path = Path(f"{pfx}.request.json")
    request_path.write_bytes(request_raw)

    src_id = source_identity(source_worktree)
    if src_id.get("provenance") == "local_r8h_obs_worktree":
        if src_id["llama_cpp_pin"] != rc.LLAMA_CPP_PIN:
            raise CollectError("llama.cpp source pin drift")
        if src_id["hook_diff_sha256"] != rc.OBSERVATION_HOOK_DIFF_SHA256:
            raise CollectError("observation hook diff digest drift")
        if not src_id["clean_excluding_hook"]:
            raise CollectError("source worktree dirty beyond the hook")

    # ---- device census under the exact launch environment ---------
    dev_proof: dict[str, Any] = {"backend": "cuda" if arm == "A" else "vulkan"}
    ld_env = {k: v for k, v in env.items()
              if k not in ("LLAMA_OBSERVE_LOGITS",)}
    dev_proof["list_devices"] = list_devices(server, ld_env)
    if arm in ("B", "C"):
        assert icd_path is not None
        attempts = {}
        for idx in ("0", "1"):
            e = dict(ld_env)
            e["GGML_VK_VISIBLE_DEVICES"] = idx
            attempts[idx] = list_devices(server, e)
        dev_proof["list_devices_attempts"] = attempts
        vs = vulkan_summary(icd_path)
        dev_proof["vulkaninfo"] = vs
        smi_table = (nvidia_uuid_bdf_table() if arm == "B" else {})
        phys = []
        for gpu, fields in sorted(vs["gpus"].items()):
            entry = {"gpu_index": gpu,
                     "deviceName": fields.get("deviceName"),
                     "deviceUUID": fields.get("deviceUUID"),
                     "driverName": fields.get("driverName"),
                     "driverID": fields.get("driverID")}
            uuid = fields.get("deviceUUID") or ""
            if arm == "B":
                cand = "GPU-" + uuid
                entry["bdf"] = smi_table.get(cand, "")
            else:
                entry["bdf"] = radv_uuid_to_bdf(uuid)
            phys.append(entry)
        dev_proof["vulkan_physical_devices"] = phys
        dev_proof["nvidia_uuid_bdf_table"] = smi_table if arm == "B" else None

    frozen = rc.OBSERVATION_FROZEN_DEVICES
    selected: dict[str, Any] = {}
    excluded: list[dict[str, Any]] = []
    if arm == "A":
        g3060 = frozen["frozen_rtx3060"]
        selected = {"uuid": g3060["uuid"], "bdf": g3060["bdf"],
                    "name": "NVIDIA GeForce RTX 3060",
                    "identity_source": "nvidia-smi uuid/pci.bus_id table"}
        excluded = [{"uuid": g3060["sibling"]["uuid"],
                     "bdf": g3060["sibling"]["bdf"],
                     "identity_source": "nvidia-smi uuid/pci.bus_id table"}]
        st = nvidia_state()
        tbl = {u: v.get("bdf") for u, v in st["gpus"].items()}
        if tbl.get(selected["uuid"]) != selected["bdf"]:
            raise CollectError(
                f"frozen GPU {selected['uuid']} not at {selected['bdf']}: {tbl}")
    elif arm == "B":
        g3060 = frozen["frozen_rtx3060"]
        selected = {"deviceUUID": g3060["vulkan_deviceUUID"],
                    "uuid": g3060["uuid"], "bdf": g3060["bdf"],
                    "identity_source": "vulkaninfo GPU0 + nvidia-smi join"}
        excluded = [{"uuid": g3060["sibling"]["uuid"],
                     "bdf": g3060["sibling"]["bdf"],
                     "identity_source": "vulkaninfo GPU1 + smi join"}]
    else:
        selected = {"bdf": frozen["C_selected_die"]["bdf"],
                    "deviceUUID": frozen["C_selected_die"]["deviceUUID"],
                    "identity_source": "vulkaninfo GPU0 RADV BDF-encoded UUID"}
        excluded = [{"bdf": frozen["C_excluded_die"]["bdf"],
                     "deviceUUID": frozen["C_excluded_die"]["deviceUUID"],
                     "identity_source": "vulkaninfo GPU1 RADV UUID"}]
    dev_proof["selected"] = selected
    dev_proof["excluded"] = excluded

    # ---- residency monitoring --------------------------------------
    is_nvidia = arm in ("A", "B")
    samples: list[dict[str, Any]] = []
    phase = ["pre"]
    stop = threading.Event()

    def monitor() -> None:
        while not stop.is_set():
            snap = nvidia_state() if is_nvidia else amd_state()
            samples.append({"t": time.time(), "phase": phase[0], **snap})
            stop.wait(5)

    mon = threading.Thread(target=monitor, daemon=True)
    mon.start()

    def snapshot() -> dict[str, Any]:
        return nvidia_state() if is_nvidia else amd_state()

    mem_pre = snapshot()
    t0 = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    log_path = Path(f"{pfx}.server.log")
    argv = [str(server), "--model", str(model_files[0]),
            "--n-gpu-layers", str(rc.MATCHED_NGL),
            "--ctx-size", str(rc.CONTEXT_SETTINGS["ctx-size"]),
            "--batch-size", str(rc.CONTEXT_SETTINGS["batch-size"]),
            "--port", str(port), "--host", "127.0.0.1"]
    log = open(log_path, "w")
    proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                            env=env)
    pid = proc.pid
    try:
        # wait for health
        deadline = time.time() + 7200
        healthy = False
        while time.time() < deadline:
            if proc.poll() is not None:
                raise CollectError(
                    f"server exited early rc={proc.returncode}")
            import urllib.request
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=5)
                healthy = True
                break
            except Exception:
                time.sleep(5)
        if not healthy:
            raise CollectError("server never became healthy")
        phase[0] = "loaded"
        argv_proc = proc_argv(pid)
        env_proc = proc_env(pid)
        mapped_objects = maps_backend_objects(pid)
        maps_libs = sorted({m["name"] for m in mapped_objects})
        mem_loaded = snapshot()

        # Send the exact retained canonical bytes, never a second serialization.
        phase[0] = "generation"
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/completion",
            data=request_raw,
            headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=7200).read())
        Path(f"{pfx}.resp.json").write_text(
            json.dumps(resp, sort_keys=True) + "\n", encoding="utf-8")
        phase[0] = "post"
        mem_post = snapshot()
    finally:
        phase[0] = "exiting"
        proc.terminate()
        try:
            proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        stop.set()
        mon.join(timeout=10)
        log.close()
        time.sleep(10)
        mem_post_exit = snapshot()

    tokens = resp.get("tokens")
    server_log_text = log_path.read_text(errors="replace")
    no_gpu_warning = "no usable GPU found" in server_log_text

    # ---- residency derivation --------------------------------------
    def _entry(state: dict, key_uuid: str | None, key_bdf: str | None):
        g = state.get("gpus", {})
        if key_uuid is not None and key_uuid in g:
            return g[key_uuid]
        if key_bdf is not None:
            if key_bdf in g:
                return g[key_bdf]
            for v in g.values():
                if v.get("bdf") == key_bdf:
                    return v
        return {}

    sel_key_uuid = selected.get("uuid")
    sel_key_bdf = selected.get("bdf")
    sel_pre = _entry(mem_pre, sel_key_uuid, sel_key_bdf)
    sel_loaded = _entry(mem_loaded, sel_key_uuid, sel_key_bdf)
    sel_post = _entry(mem_post, sel_key_uuid, sel_key_bdf)
    sel_post_exit = _entry(mem_post_exit, sel_key_uuid, sel_key_bdf)

    def _deltas(a: dict, b: dict) -> dict[str, int]:
        keys = (set(a) | set(b)) - {"bdf"}
        return {k: b.get(k, 0) - a.get(k, 0)
                for k in keys
                if isinstance(a.get(k, 0), int) and isinstance(b.get(k, 0), int)}

    sel_delta_loaded = _deltas(sel_pre, sel_loaded)
    sel_delta_post = _deltas(sel_pre, sel_post)
    # during-run peak across monitor samples in loaded/generation phases
    during_peak = 0
    for s in samples:
        if s["phase"] not in ("loaded", "generation", "post"):
            continue
        e = _entry(s, sel_key_uuid, sel_key_bdf)
        during_peak = max(during_peak, _model_residency(e) -
                          _model_residency(sel_pre))
    excluded_states = []
    for ex in excluded:
        ex_pre = _entry(mem_pre, ex.get("uuid"), ex.get("bdf"))
        ex_peak = 0
        for s in samples:
            if s["phase"] == "pre":
                continue
            e = _entry(s, ex.get("uuid"), ex.get("bdf"))
            ex_peak = max(ex_peak, _model_residency(e) -
                          _model_residency(ex_pre))
        excluded_states.append({
            "uuid": ex.get("uuid"), "bdf": ex.get("bdf"),
            "pre": ex_pre,
            "peak_delta_bytes": ex_peak,
        })
    selected_delta_bytes = max(
        _model_residency(sel_delta_loaded),
        _model_residency(sel_delta_post), during_peak)

    # live compute-app binding for the server pid (nvidia hosts)
    compute_bound = []
    for s in samples:
        for a in s.get("compute_apps", []):
            if a.get("pid") == pid:
                compute_bound.append({"t": s["t"], "phase": s["phase"],
                                      **a})

    # ---- non-perturbation gate (quarantine before any receipt) ----
    if tokens != CANONICAL[arm]:
        qdir = out_dir / "quarantine"
        qdir.mkdir(exist_ok=True)
        for suffix in (".jsonl", ".jsonl.pos0.f32", ".resp.json",
                       ".server.log"):
            src = Path(f"{pfx}{suffix}")
            if src.is_file():
                src.rename(qdir / src.name)
        (qdir / "INCIDENT.json").write_text(json.dumps({
            "arm": arm, "reason": "token_mismatch_vs_canonical_stream",
            "generated_tokens": tokens,
            "canonical_tokens": CANONICAL[arm],
        }, indent=1) + "\n")
        raise CollectError(
            f"arm {arm} observation tokens deviate from canonical "
            f"stream; quarantined")

    # ---- receipt ----------------------------------------------------
    body_contract = {k: v for k, v in rc.REQUEST_CONTRACT.items()}
    backing_rel = {"A": "armA-backing.json", "B": "armB-backing.json",
                   "C": "armC-backing.json"}
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "campaign": rc.CAMPAIGN_ID,
        "case_id": "case-256",
        "generated_position": POSITION,
        "arm": arm,
        "host": {"hostname": hostname, "boot_id": boot_id},
        "collector": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha(Path(__file__).resolve()),
            "dependencies": {
                "issue234_receipt.py": sha(Path(rc.__file__).resolve()),
            },
        },
        "observation_binary": {
            "path": str(server),
            "sha256": binary_sha,
            "bin_dir": {name: meta["sha256"] for name, meta in
                        execution_package["objects"].items()},
            "package": execution_package,
        },
        "source": src_id,
        "launch": {
            "pid": pid,
            "argv": argv_proc,
            "env": {k: env_proc.get(k) for k in sorted(env)},
            "env_present_keys": sorted(env_proc),
            "icd": ({"path": icd_doc["path"],
                     "sha256": icd_doc["sha256"],
                     "library_path":
                         icd_doc["parsed"].get("ICD", {}).get(
                             "library_path")}
                    if icd_doc else None),
        },
        "in_process_backends": {"mapped_libggml": maps_libs,
                                "mapped_objects": mapped_objects},
        "model": {
            "path": str(model_files[0].parent),
            "first_member": str(model_files[0]),
            "members": model_members,
            "total_bytes": sum(m["bytes"] for m in model_members),
            "backing_receipt": backing_rel[arm],
        },
        "geometry": {"ngl": rc.MATCHED_NGL,
                     "ctx": dict(rc.CONTEXT_SETTINGS)},
        "request": {
            "contract": body_contract,
            "prompt_sha256": prompt_sha,
            "prompt_len": len(prompt_doc),
            "payload": {"path": request_path.name,
                        "sha256": sha(request_path),
                        "bytes": len(request_raw)},
        },
        "device_proof": dev_proof,
        "residency": {
            "sampler_interval_s": 5,
            "selected_pre": sel_pre,
            "selected_loaded": sel_loaded,
            "selected_post": sel_post,
            "selected_post_exit": sel_post_exit,
            "selected_delta_loaded": sel_delta_loaded,
            "selected_delta_post": sel_delta_post,
            "selected_during_peak_delta_bytes": during_peak,
            "selected_delta_bytes": selected_delta_bytes,
            "excluded": excluded_states,
            "compute_apps_bound_to_pid": compute_bound,
            "n_samples": len(samples),
        },
        "cpu_fallback": {
            "no_usable_gpu_warning_present": no_gpu_warning,
            "devices_listed_under_launch_env": bool(
                dev_proof["list_devices"]["parsed"]),
            "selected_model_scale_residency":
                selected_delta_bytes >= MODEL_SCALE_BYTES,
            "fallback": bool(no_gpu_warning or not
                             dev_proof["list_devices"]["parsed"] or
                             selected_delta_bytes < MODEL_SCALE_BYTES),
        },
        "exit": {"returncode": proc.returncode,
                 "terminated_by_driver": proc.returncode in (-15, 143, 0)},
        "t_start": t0,
        "t_end": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "artifacts": {
            "observation_jsonl": sha(jsonl_path),
            "pos0_f32": sha(Path(f"{pfx}.jsonl.pos0.f32"))
            if Path(f"{pfx}.jsonl.pos0.f32").is_file() else None,
            "request_payload": sha(request_path),
            "response": sha(Path(f"{pfx}.resp.json")),
            "server_log": sha(log_path),
        },
        "generated_tokens": tokens,
    }
    receipt["digest"] = "PENDING"
    receipt["digest"] = rc.sha256_bytes(rc.canonical(receipt))
    out = out_dir / f"observation-receipt-{arm}.json"
    out.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "arm": arm, "host": hostname, "binary_sha256": binary_sha[:12],
        "selected": selected, "selected_delta_bytes": selected_delta_bytes,
        "excluded_peak_deltas": {e.get("bdf"): e["peak_delta_bytes"]
                                 for e in excluded_states},
        "cpu_fallback": receipt["cpu_fallback"]["fallback"],
        "compute_bound": len(compute_bound),
        "tokens_ok": True,
    }))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", choices=("A", "B", "C"), required=True)
    ap.add_argument("--server", type=Path, required=True)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--prompt", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--source-worktree", type=Path)
    ap.add_argument("--port", type=int, default=18493)
    args = ap.parse_args()
    collect(args.arm, args.server, args.model_dir, args.out_dir,
            args.prompt, args.source_worktree, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
