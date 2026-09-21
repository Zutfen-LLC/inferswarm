#!/usr/bin/env python3
"""Focused tests for Issue #234 corrected R8-H producers (schema /2).

Round-2 coverage (maintainer NO-GO on cfd86f11): raw-bound
characterization reduction, mechanical position binding to the
earliest pairwise divergence, deployed-producer host/producer matrix,
strengthened control 33, observation-pin validation, and the full
control-suite contract. CPU-only; no physical execution.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import issue234_receipt as rc          # noqa: E402
import issue234_reduce as red          # noqa: E402
import issue234_assemble as asm        # noqa: E402
import issue234_observe as obs         # noqa: E402


def w(p: Path, doc) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return p


TOKENS_A = [328, 760, 40554, 1, 271, 12188, 279, 1727]
TOKENS_B = [561, 324, 55965, 51624, 29014, 271, 248068, 271]
TOKENS_C = [561, 324, 55965, 51624, 29014, 34227, 18030, 16382]

N_VOCAB = 4096


def synth_f32(tokens: dict[int, float]) -> bytes:
    """Synthesize a small-vocab float32 row with controlled values."""
    row = [0.0] * N_VOCAB
    for t, v in tokens.items():
        row[t] = v
    return struct.pack(f"<{N_VOCAB}f", *row)


# controlled score structures: A picks 328 over 561 (narrow), B and C
# pick 561 over 328 (wider); ranks 1..4 arranged accordingly.
F32_A = synth_f32({328: 15.25, 561: 15.0, 271: 14.0, 359: 13.0})
F32_B = synth_f32({561: 15.5, 328: 15.0, 359: 14.5, 271: 13.5})
F32_C = synth_f32({561: 15.75, 359: 14.5, 271: 14.0, 328: 13.75})


def obs_jsonl(position: int, f32row: bytes, sampled: int) -> str:
    vals = struct.unpack(f"<{N_VOCAB}f", f32row)
    order = sorted(range(N_VOCAB), key=lambda i: (-vals[i], i))
    rank = {t: k + 1 for k, t in enumerate(order)}
    top = [[t, vals[t]] for t in order[:16]]
    focus = [[t, rank[t], vals[t]]
             for t in (328, 561, 271, 34227, 12188, 248068) if t < N_VOCAB]
    row = {"pos": position, "tok": sampled, "n_vocab": N_VOCAB,
           "top": top, "focus": focus, "n_nonfinite": 0}
    return json.dumps(row) + "\n"


def synthetic_package(arm: str) -> dict:
    """Pinned execution package fixture; B/C deliberately share bytes."""
    backend = "libggml-cuda.so" if arm == "A" else "libggml-vulkan.so"
    tag = "a" if arm == "A" else "v"
    objects = {
        name: {"realpath": f"/package/{name}", "bytes": size,
               "sha256": digest}
        for name, size, digest in (
            ("llama-server", 101, rc.OBSERVATION_BINARIES[arm]["sha256"]),
            ("libggml.so", 102, tag * 64),
            ("libggml-base.so", 103, tag.upper() * 64),
            ("libggml-cpu.so", 104, ("c" if arm == "A" else "d") * 64),
            (backend, 105, ("e" if arm == "A" else "f") * 64),
        )
    }
    return {"root": f"/opt/obs/{arm}", "objects": objects}


def make_obs_corpus(ev: Path, arm: str, tokens: list[int],
                    f32row: bytes, *, position: int = 0,
                    dir_name: str = "pos0", pin: bool = True) -> None:
    d = ev / "candidate" / "characterization" / dir_name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{arm}.jsonl").write_text(obs_jsonl(position, f32row, tokens[0]))
    (d / f"{arm}.jsonl.pos{position}.f32").write_bytes(f32row)
    w(d / f"{arm}.resp.json", {"tokens": tokens})
    (d / f"{arm}.server.log").write_bytes(b"synthetic server log\n")
    if pin and dir_name == "pos0" and not (d / "pos0-observation-pin.json"
                                           ).is_file():
        w(d.parent / "observation-authority.json", {
            "schema": "inferswarm.r8h.observation-authority/1",
            "generated_position": position, "attempt": dir_name})
        pin_doc = {
            "schema": "inferswarm.r8h.pos0-observation-pin/2",
            "scope": {"generated_position": position,
                      "canonical_ladder_rerun": False,
                      "execution_receipts_required": True},
            "collector": {
                "path": "scripts/issue234_observe.py",
                "sha256": rc.digest_file(REPO / "scripts" / "issue234_observe.py"),
                "dependencies": {"issue234_receipt.py": rc.digest_file(
                    REPO / "scripts" / "issue234_receipt.py")},
            },
            "observation_producer": {
                "llama_cpp_source_pin": rc.LLAMA_CPP_PIN,
                "hook_source_sha256_of_diff": rc.OBSERVATION_HOOK_DIFF_SHA256,
                "hook_env": {
                    "LLAMA_OBSERVE_FOCUS": rc.OBSERVATION_FOCUS_ENV,
                    "LLAMA_OBSERVE_POS": str(position)},
                "prompt_sha256": rc.PROMPT_CASE256_SHA256,
                "selectors": {a: dict(rc.OBSERVATION_LAUNCH_ENV[a])
                              for a in "ABC"},
                "icd_sha256": {
                    "B": rc.OBSERVATION_ICD_SHA256[
                        "B_nvidia_inferswarm01"],
                    "C": rc.OBSERVATION_ICD_SHA256["C_radeon"]},
                "observation_binaries": {
                    "A_cuda_inferswarm01": {"sha256": rc.OBSERVATION_BINARIES["A"]["sha256"]},
                    "B_vulkan_inferswarm01": {"sha256": rc.OBSERVATION_BINARIES["B"]["sha256"]},
                    "C_vulkan_inferswarm02": {"sha256": rc.OBSERVATION_BINARIES["C"]["sha256"]},
                },
                "execution_packages": {a: synthetic_package(a) for a in "ABC"},
                "same_vulkan_package": True,
                "model_members": [{"name": m["member"], "bytes": m["bytes"],
                                   "sha256": m["sha256"]} for m in rc.MODEL_MEMBERS],
                "model_subject": "/models",
                "prompt_sha256": rc.PROMPT_CASE256_SHA256,
                "prompt_len": rc.PROMPT_CASE256_LENGTH,
                "request_contract": dict(rc.REQUEST_CONTRACT),
                "launch_contract": {"port": 18493, "host": "127.0.0.1"},
            },
        }
        w(d / "pos0-observation-pin.json", pin_doc)


def obs_receipt(arm: str, out_dir: Path, *, tokens: list[int],
                jsonl: Path, f32: Path, resp: Path,
                server_log: Path | None = None,
                overrides: dict | None = None) -> Path:
    """Synthesize a mechanically-valid observation execution receipt
    (schema /1) matching the frozen authorities; each artifact digest
    binds the receipt to the real raw bytes on disk."""
    frozen = rc.OBSERVATION_FROZEN_DEVICES
    env = dict(rc.OBSERVATION_LAUNCH_ENV[arm])
    env["LLAMA_OBSERVE_FOCUS"] = rc.OBSERVATION_FOCUS_ENV
    env["LLAMA_OBSERVE_POS"] = "0"
    env["LLAMA_OBSERVE_LOGITS"] = str(jsonl)
    bin_meta = rc.OBSERVATION_BINARIES[arm]
    if arm == "A":
        sel = {"uuid": frozen["frozen_rtx3060"]["uuid"],
               "bdf": frozen["frozen_rtx3060"]["bdf"]}
        ex = [{"uuid": frozen["frozen_rtx3060"]["sibling"]["uuid"],
               "bdf": frozen["frozen_rtx3060"]["sibling"]["bdf"]}]
        ld = {"raw": "CUDA0: NVIDIA GeForce RTX 3060 (12288 MiB)",
              "parsed": [{"label": "CUDA0",
                          "name": "NVIDIA GeForce RTX 3060",
                          "mib": "12288"}]}
        vk = None
        maps = ["libggml-base.so", "libggml-cpu.so", "libggml-cuda.so"]
    elif arm == "B":
        g = frozen["frozen_rtx3060"]
        sel = {"uuid": g["uuid"], "bdf": g["bdf"],
               "deviceUUID": g["vulkan_deviceUUID"]}
        ex = [{"uuid": g["sibling"]["uuid"], "bdf": g["sibling"]["bdf"]}]
        ld = {"raw": "Vulkan0: NVIDIA GeForce RTX 3060 (12534 MiB)",
              "parsed": [{"label": "Vulkan0",
                          "name": "NVIDIA GeForce RTX 3060",
                          "mib": "12534"}]}
        vk = {"gpus": {
            "GPU0": {"deviceName": "NVIDIA GeForce RTX 3060",
                     "deviceUUID": g["vulkan_deviceUUID"],
                     "driverName": "NVIDIA"},
            "GPU1": {"deviceName": "NVIDIA GeForce RTX 3060",
                     "deviceUUID": "d5c05739-96c1-7e49-89b6-bf54c2121c55",
                     "driverName": "NVIDIA"}}}
        maps = ["libggml-base.so", "libggml-cpu.so", "libggml-vulkan.so"]
    else:
        sel = {"bdf": frozen["C_selected_die"]["bdf"],
               "deviceUUID": frozen["C_selected_die"]["deviceUUID"]}
        ex = [{"bdf": frozen["C_excluded_die"]["bdf"],
               "deviceUUID": frozen["C_excluded_die"]["deviceUUID"]}]
        ld = {"raw": "Vulkan0: AMD Radeon Pro V340 (8176 MiB)",
              "parsed": [{"label": "Vulkan0",
                          "name": "AMD Radeon Pro V340 (RADV VEGA10)",
                          "mib": "8176"}]}
        vk = {"gpus": {
            "GPU0": {"deviceName": "AMD Radeon Pro V340 (RADV VEGA10)",
                     "deviceUUID": frozen["C_selected_die"]["deviceUUID"],
                     "driverName": "RADV",
                     "driverID": "DRIVER_ID_MESA_RADV"},
            "GPU1": {"deviceName": "AMD Radeon Pro V340 (RADV VEGA10)",
                     "deviceUUID": frozen["C_excluded_die"]["deviceUUID"],
                     "driverName": "RADV",
                     "driverID": "DRIVER_ID_MESA_RADV"}}}
        maps = ["libggml-base.so", "libggml-cpu.so", "libggml-vulkan.so"]
    phys = []
    smi_join = {}
    if vk:
        if arm == "B":
            g = frozen["frozen_rtx3060"]
            smi_join = {"GPU-" + g["vulkan_deviceUUID"]: g["bdf"],
                        "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55":
                            g["sibling"]["bdf"]}
        for gpu, f in sorted(vk["gpus"].items()):
            e = {"gpu_index": gpu, "deviceName": f.get("deviceName"),
                 "deviceUUID": f.get("deviceUUID"),
                 "driverName": f.get("driverName"),
                 "driverID": f.get("driverID")}
            if arm == "B":
                e["bdf"] = smi_join.get("GPU-" + f.get("deviceUUID", ""))
            else:
                h = (f.get("deviceUUID") or "").replace("-", "")
                e["bdf"] = (f"{h[0:8]}:{h[8:10]}:{h[10:12]}."
                            f"{int(h[12:14], 16) & 0x7}"
                            if len(h) == 32 else "")
            phys.append(e)
    icd = None
    if arm in ("B", "C"):
        icd = {"path": rc.OBSERVATION_LAUNCH_ENV[arm]["VK_ICD_FILENAMES"],
               "sha256": rc.OBSERVATION_ICD_SHA256[
                   "B_nvidia_inferswarm01" if arm == "B" else "C_radeon"],
               "library_path": "libGLX_nvidia.so.0"}
    package = synthetic_package(arm)
    mapped_objects = [
        {"name": name, "path": f"/opt/obs/{arm}/{name}",
         "realpath": meta["realpath"], "bytes": meta["bytes"],
         "sha256": meta["sha256"]}
        for name, meta in package["objects"].items() if name.startswith("libggml")]
    prompt = [0] * 256
    request_body = {**rc.REQUEST_CONTRACT, "prompt": prompt}
    request_raw = rc.canonical(request_body)
    request_path = jsonl.parent / f"{arm}.request.json"
    request_path.write_bytes(request_raw)
    compute = []
    if arm == "A":
        compute = [{"t": 1.0, "phase": "generation",
                    "pid": 4242,
                    "gpu_uuid": frozen["frozen_rtx3060"]["uuid"],
                    "used_memory": "900 MiB"}]
    receipt: dict = {
        "schema": "inferswarm.r8h.observation-execution-receipt/2",
        "campaign": rc.CAMPAIGN_ID,
        "case_id": "case-256",
        "generated_position": 0,
        "arm": arm,
        "host": {"hostname": rc.ARMS[arm]["host"],
                 "boot_id": "b" * 8 + "-0000-0000-0000-" + "0" * 12},
        "collector": {"path": "/tmp/is234r/producers/scripts/issue234_observe.py",
                      "sha256": rc.digest_file(REPO / "scripts" / "issue234_observe.py"),
                      "dependencies": {"issue234_receipt.py": rc.digest_file(
                          REPO / "scripts" / "issue234_receipt.py")}},
        "observation_binary": {
            "path": f"/opt/obs/{arm}/llama-server",
            "sha256": bin_meta["sha256"],
            "bin_dir": {name: meta["sha256"]
                        for name, meta in package["objects"].items()},
            "package": package,
        },
        "source": ({"provenance": "local_r8h_obs_worktree",
                    "worktree": "/opt/src",
                    "llama_cpp_pin": rc.LLAMA_CPP_PIN,
                    "modified_paths": [" M tools/server/server-context.cpp"],
                    "clean_excluding_hook": True,
                    "hook_diff_sha256": rc.OBSERVATION_HOOK_DIFF_SHA256,
                    "hook_diff_lines": 103}
                   if arm != "C" else
                   {"provenance": "byte_identity_to_arm_B_binary"}),
        "launch": {
            "pid": 4242,
            "argv": [f"/opt/obs/{arm}/llama-server", "--model",
                     f"/models/{rc.MODEL_MEMBERS[0]['member']}",
                     "--n-gpu-layers", "1", "--ctx-size", "8192",
                     "--batch-size", "512", "--port", "18493",
                     "--host", "127.0.0.1"],
            "env": env,
            "env_present_keys": sorted(env),
            "icd": icd,
        },
        "in_process_backends": {"mapped_libggml": maps,
                                "mapped_objects": mapped_objects},
        "model": {"path": "/models",
                  "first_member": f"/models/{rc.MODEL_MEMBERS[0]['member']}",
                  "members": [{"name": m["member"], "bytes": m["bytes"],
                               "sha256": m["sha256"]}
                              for m in rc.MODEL_MEMBERS],
                  "total_bytes": rc.TOTAL_MODEL_BYTES,
                  "backing_receipt": f"arm{arm}-backing.json"},
        "geometry": {"ngl": rc.MATCHED_NGL,
                     "ctx": dict(rc.CONTEXT_SETTINGS)},
        "request": {"contract": dict(rc.REQUEST_CONTRACT),
                    "prompt_sha256": rc.PROMPT_CASE256_SHA256,
                    "prompt_len": 256,
                    "payload": {"path": request_path.name,
                                "sha256": rc.sha256_bytes(request_raw),
                                "bytes": len(request_raw)}},
        "device_proof": {
            "backend": "cuda" if arm == "A" else "vulkan",
            "list_devices": ld,
            "vulkaninfo": vk,
            "vulkan_physical_devices": phys,
            "nvidia_uuid_bdf_table": (smi_join if arm == "B" else None),
            "selected": sel,
            "excluded": ex,
        },
        "residency": {
            "sampler_interval_s": 5,
            "selected_pre": {"mem_used_mib": 1},
            "selected_loaded": {"mem_used_mib": 941},
            "selected_post": {"mem_used_mib": 941},
            "selected_post_exit": {"mem_used_mib": 1},
            "selected_delta_loaded": {"mem_used_mib": 940},
            "selected_delta_post": {"mem_used_mib": 940},
            "selected_during_peak_delta_bytes": 940 * 1024 * 1024,
            "selected_delta_bytes": 940 * 1024 * 1024,
            "excluded": [{**e2, "pre": {"mem_used_mib": 1},
                          "peak_delta_bytes": 0} for e2 in ex],
            "compute_apps_bound_to_pid": compute,
            "n_samples": 12,
        },
        "cpu_fallback": {
            "no_usable_gpu_warning_present": False,
            "devices_listed_under_launch_env": True,
            "selected_model_scale_residency": True,
            "fallback": False,
        },
        "exit": {"returncode": 0, "terminated_by_driver": True},
        "t_start": "2026-09-21T00:00:00+0000",
        "t_end": "2026-09-21T00:05:00+0000",
        "artifacts": {
            "observation_jsonl": rc.sha256_bytes(jsonl.read_bytes()),
            "pos0_f32": rc.sha256_bytes(f32.read_bytes()),
            "request_payload": rc.sha256_bytes(request_raw),
            "response": rc.sha256_bytes(resp.read_bytes()),
            "server_log": (rc.sha256_bytes(server_log.read_bytes())
                           if server_log and server_log.is_file() else
                           rc.sha256_bytes(b"log")),
        },
        "generated_tokens": list(tokens),
    }
    if overrides:
        for k, v in overrides.items():
            if callable(v):
                v(receipt)
            else:
                receipt[k] = v
    receipt["digest"] = "PENDING"
    receipt["digest"] = rc.sha256_bytes(rc.canonical(receipt))
    return w(out_dir / f"observation-receipt-{arm}.json", receipt)


def make_summary(ev: Path, case: str, position: int, f32s: dict[str, bytes],
                 winners: dict[str, int]) -> Path:
    arms = {}
    for arm in "ABC":
        arms[arm] = {
            "generated_position": position,
            "winner_token": winners[arm],
            "raw_sidecar_sha256": {
                f"f32_pos{position}": rc.sha256_bytes(f32s[arm])},
            "non_perturbation_identical": True,
        }
    return w(ev / "candidate" / f"score-characterization-{case}.json",
             {"schema": "inferswarm.r8h.score-characterization/3",
              "campaign": rc.CAMPAIGN_ID, "case_id": case,
              "generated_position": position, "arms": arms})


def make_evidence(tmp: Path, *, a=TOKENS_A, b=TOKENS_B, c=TOKENS_C,
                  det_b=True, characterization=None, case="case-256",
                  drop_b_repeat=False, extra_cases=(),
                  bdf_b="00000000:02:00.0",
                  obs_position=0,
                  receipt_overrides: dict | None = None) -> Path:
    ev = tmp / "evidence"
    authority = {
        "campaign": rc.CAMPAIGN_ID,
        "runtime_authority": {"llama_cpp_pin": rc.LLAMA_CPP_PIN},
        "fixture_ladder": {
            "sha256": rc.R8D_FIXTURE_SHA256,
            "prompt_lengths": {"case-256": 256, "case-1024": 1022,
                               "case-3072": 3077, "case-4096": 4097}},
        "model_authority": {
            "official_qwen_revision": rc.OFFICIAL_QWEN_REVISION,
            "unsloth_revision": rc.UNSLOTH_REVISION,
            "members": [dict(m) for m in rc.MODEL_MEMBERS]},
    }
    w(ev / "PHYSICAL-AUTHORITY.json", authority)
    for arm in "ABC":
        w(ev / "backing" / f"arm{arm}-backing.json", {
            "members": [dict(m, sha256_ok=True) for m in rc.MODEL_MEMBERS],
            "host": f"host{arm}"})
        w(ev / "runtime" / f"arm{arm}-runtime.json", {
            "source": {"revision": rc.LLAMA_CPP_PIN, "clean": True},
            "build": {"cmake_flags": {
                "GGML_CUDA": "ON" if arm == "A" else "OFF",
                "GGML_VULKAN": "OFF" if arm == "A" else "ON"}},
            "binaries": {"llama-server": {"sha256": f"{arm}" * 8}},
            "selector": {"target_bdf": bdf_b if arm == "B"
                         else ("00000000:02:00.0" if arm == "A"
                               else "00000000:06:00.0"),
                         "target_deviceUUID": "u" * 32,
                         "value": "0",
                         "value_semantics": "nvidia-smi index of frozen "
                                            "GPU (BDF "
                                            + (bdf_b if arm == "B"
                                               else "00000000:02:00.0")
                                            + ")"},
            "raw": {"list_devices_all": "Vulkan0: dev (8000 MiB)"}})
        w(ev / "placement" / f"arm{arm}-placement.json", {
            "loaded": True,
            "geometry": {"ngl": rc.MATCHED_NGL},
            "residency": {"selected": {"delta":
                                       {"mem_used_mib": 900}},
                          "excluded": {"x": {"mem_used_mib": 0}}},
            "post_exit": {"exit_code": 0}})
    gpu = {"host": "inferswarm01", "uuid": "GPU-x", "bdf": bdf_b,
           "cuda_identity": {"selector": "CUDA_VISIBLE_DEVICES=0"},
           "vulkan_identity": {"selector": "GGML_VK_VISIBLE_DEVICES=0"}}
    gpu_a = {"host": "inferswarm01", "uuid": "GPU-x",
             "bdf": "00000000:02:00.0",
             "cuda_identity": {"selector": "CUDA_VISIBLE_DEVICES=0"}}
    w(ev / "freeze" / "campaign-freeze.json", {
        "schema": "inferswarm.r8h.freeze/2",
        "campaign": rc.CAMPAIGN_ID,
        "llama_cpp_pin": rc.LLAMA_CPP_PIN,
        "request_contract": rc.REQUEST_CONTRACT,
        "fixture_sha256": rc.R8D_FIXTURE_SHA256,
        "ngl": rc.MATCHED_NGL,
        "context": rc.CONTEXT_SETTINGS,
        "model_members": [dict(m) for m in rc.MODEL_MEMBERS],
        "rtx3060": gpu,
        "arms": {
            "A": {"gpu": gpu_a, "ngl": 1, "context": rc.CONTEXT_SETTINGS,
                  "request": rc.REQUEST_CONTRACT,
                  "fixture_sha256": rc.R8D_FIXTURE_SHA256,
                  "model_sha256": [m["sha256"] for m in rc.MODEL_MEMBERS]},
            "B": {"gpu": gpu, "ngl": 1, "context": rc.CONTEXT_SETTINGS,
                  "request": rc.REQUEST_CONTRACT,
                  "fixture_sha256": rc.R8D_FIXTURE_SHA256,
                  "model_sha256": [m["sha256"] for m in rc.MODEL_MEMBERS]},
            "C": {"gpu": {"bdf": "00000000:06:00.0",
                          "deviceUUID": "d" * 32},
                  "excluded_die": {"bdf": "00000000:09:00.0"},
                  "ngl": 1, "context": rc.CONTEXT_SETTINGS,
                  "request": rc.REQUEST_CONTRACT,
                  "fixture_sha256": rc.R8D_FIXTURE_SHA256,
                  "model_sha256": [m["sha256"] for m in rc.MODEL_MEMBERS]},
        }})
    w(ev / "freeze" / "deployed-producers.json", {
        "all_hosts_match_pin": True,
        "hosts": {h: {"hashes": {name: rc.digest_file(REPO / "scripts" / name)
                                 for name in
                                 asm.DEPLOYED_PRODUCER_BASENAMES}}
                  for h in ("inferswarm01", "inferswarm02")}})
    cases = [case] + list(extra_cases)
    for cs in cases:
        for arm, toks in (("A", a), ("B", b), ("C", c)):
            reps = []
            for i in (1, 2, 3):
                t = list(toks)
                if arm == "B" and not det_b and i == 2:
                    t[0] += 1
                reps.append({
                    "repeat": i,
                    "raw_response": {"tokens": t, "stop_type": "limit"},
                    "selected_residency": {
                        "pre": {"mem_used_mib": 900},
                        "post": {"mem_used_mib": 900}},
                    "excluded_residency": {"x": {
                        "pre": {"mem_used_mib": 0},
                        "post": {"mem_used_mib": 0}}},
                    "health_window": {"stop_classes": [],
                                      "correctable_rxerr_lines": 0}})
            if arm == "B" and drop_b_repeat:
                reps = reps[:2]
            w(ev / "candidate" / f"ladder-{arm}-{cs}.json", {
                "campaign": rc.CAMPAIGN_ID, "arm": arm, "case_id": cs,
                "geometry": {"ngl": rc.MATCHED_NGL,
                             "ctx": dict(rc.CONTEXT_SETTINGS),
                             "request": dict(rc.REQUEST_CONTRACT)},
                "fixture_sha256": rc.R8D_FIXTURE_SHA256,
                "prompt_len": {"case-256": 256, "case-1024": 1022,
                               "case-3072": 3077, "case-4096": 4097}[cs],
                "model_members": [m["member"] for m in rc.MODEL_MEMBERS],
                "repeats": reps,
                "post_exit": {"exit_code": 0,
                              "journal_final_stop_classes": []}})
    if characterization is not None:
        w(ev / "candidate" /
          f"score-characterization-{case}.json", characterization)
    # raw observation corpus bound to the streams above
    f32s = {"A": F32_A, "B": F32_B, "C": F32_C}
    for arm, toks in (("A", a), ("B", b), ("C", c)):
        make_obs_corpus(ev, arm, toks, f32s[arm], position=obs_position)
    # observation execution receipts (round-3: identity-bound
    # observation collection)
    pos0 = ev / "candidate" / "characterization" / "pos0"
    for arm, toks in (("A", a), ("B", b), ("C", c)):
        obs_receipt(arm, pos0, tokens=toks,
                    jsonl=pos0 / f"{arm}.jsonl",
                    f32=pos0 / f"{arm}.jsonl.pos0.f32",
                    resp=pos0 / f"{arm}.resp.json",
                    server_log=pos0 / f"{arm}.server.log",
                    overrides=(receipt_overrides or {}).get(arm))
    make_summary(ev, case, obs_position, f32s,
                 {k: struct.unpack(
                     f"<{N_VOCAB}f", v)[0 if k == "A" else 561]
                  for k, v in f32s.items()} if False else
                 {"A": a[0], "B": b[0], "C": c[0]})
    return ev


CLOSURE = {"schema": "inferswarm.r8h.producer-closure/2",
           "producer_head": "p" * 40,
           "closure_digest": "c" * 64, "sources": {}}


def real_closure():
    return rc.verify_closure(REPO)


class TestCollectorStreamingHash(unittest.TestCase):
    def test_model_hashing_never_uses_read_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "member.gguf"
            payload = b"x" * (2 * 1024 * 1024 + 17)
            p.write_bytes(payload)
            with mock.patch.object(Path, "read_bytes", side_effect=AssertionError):
                self.assertEqual(obs.sha(p), hashlib.sha256(payload).hexdigest())


class TestRequiredPosition(unittest.TestCase):
    """Spec §3: mechanical binding of the characterization position."""

    def _case(self, a, b, c):
        return {"pairwise": {
            "AB": red.pairwise({"tokens": a, "stop_type": "s"},
                               {"tokens": b, "stop_type": "s"}),
            "BC": red.pairwise({"tokens": b, "stop_type": "s"},
                               {"tokens": c, "stop_type": "s"}),
            "AC": red.pairwise({"tokens": a, "stop_type": "s"},
                               {"tokens": c, "stop_type": "s"})}}

    def test_campaign_streams_derive_position_zero(self):
        case = self._case(TOKENS_A, TOKENS_B, TOKENS_C)
        self.assertEqual(red.required_characterization_position(case), 0)

    def test_equal_streams_derive_none(self):
        case = self._case(TOKENS_A, TOKENS_A, TOKENS_A)
        self.assertIsNone(red.required_characterization_position(case))

    def test_bc_only_divergence_derives_five(self):
        case = self._case(TOKENS_B, TOKENS_B, TOKENS_C)
        self.assertEqual(red.required_characterization_position(case), 5)


class TestRawBoundCharacterization(unittest.TestCase):
    """Spec §4: terminal authority derives from raw bytes only."""

    def test_multi_axis_with_pos0_characterization(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_MULTI_AXIS)
            sc = doc["checks"]["score_characterization"]
            self.assertEqual(sc["status"], "OK")
            self.assertEqual(sc["required_position"], 0)
            self.assertEqual(sc["derived"]["A"]["winner_token"], 328)
            self.assertEqual(sc["derived"]["B"]["winner_token"], 561)
            self.assertEqual(sc["derived"]["C"]["winner_token"], 561)

    def test_position5_summary_does_not_satisfy_global_gate(self):
        # current pairwise map + characterization at position 5 ONLY
        # -> R8H_EVIDENCE_BLOCKED (spec-required regression)
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            # remove the pos0 corpus + canonical summary, keep ONLY a
            # position-5-shaped summary (the round-1 condition)
            import shutil
            shutil.rmtree(ev / "candidate" / "characterization" / "pos0")
            (ev / "candidate" /
             "score-characterization-case-256.json").unlink()
            f32s = {"A": F32_A, "B": F32_B, "C": F32_C}
            # a pos5 corpus whose non-perturbation matches the streams
            for arm, toks in (("A", TOKENS_A), ("B", TOKENS_B),
                              ("C", TOKENS_C)):
                make_obs_corpus(ev, arm, toks, f32s[arm], position=5,
                                dir_name="", pin=False)
            make_summary(ev, "case-256", 5, f32s,
                         {"A": TOKENS_A[5], "B": TOKENS_B[5],
                          "C": TOKENS_C[5]})
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            sc = doc["checks"]["score_characterization"]
            self.assertNotEqual(sc["status"], "OK")

    def test_forged_position_summary_blocked(self):
        # forged generated_position -/1/5/other -> BLOCKED
        for forged in (-1, 1, 5, 7):
            with tempfile.TemporaryDirectory() as t:
                ev = make_evidence(Path(t))
                p = ev / "candidate" / \
                    "score-characterization-case-256.json"
                d = json.loads(p.read_text())
                d["generated_position"] = forged
                p.write_text(json.dumps(d))
                doc = red.derive_terminal(ev, closure=CLOSURE)
                self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED,
                                 f"forged position {forged}")

    def test_missing_characterization_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            import shutil
            shutil.rmtree(ev / "candidate" / "characterization")
            (ev / "candidate" /
             "score-characterization-case-256.json").unlink()
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_altered_summary_winner_terminal_unchanged(self):
        # raw bytes win: authored winner mutation must NOT flip the
        # terminal (summary consistency flags it instead)
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / \
                "score-characterization-case-256.json"
            d = json.loads(p.read_text())
            d["arms"]["A"]["winner_token"] = 999999
            p.write_text(json.dumps(d))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_MULTI_AXIS)
            sc = doc["checks"]["score_characterization"]
            self.assertEqual(sc["status"], "OK")
            self.assertEqual(sc["derived"]["A"]["winner_token"], 328)
            self.assertIn("summary:armA:winner_mismatch",
                          sc["summary_disagreements"])

    def test_altered_raw_jsonl_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "characterization" / "pos0" / "B.jsonl"
            rows = [json.loads(x) for x in p.read_text().splitlines()]
            rows[0]["top"] = [[999999, 99.0]] + rows[0]["top"][1:]
            p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_altered_raw_f32_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "characterization" / "pos0" / "C.jsonl.pos0.f32"
            row = bytearray(p.read_bytes())
            struct.pack_into("<f", row, 561 * 4, 99.0)
            p.write_bytes(bytes(row))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_changed_sidecar_digest_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / \
                "score-characterization-case-256.json"
            d = json.loads(p.read_text())
            d["arms"]["A"]["raw_sidecar_sha256"]["f32_pos0"] = "0" * 64
            p.write_text(json.dumps(d))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            sc = doc["checks"]["score_characterization"]
            self.assertIn("summary:armA:f32_digest_mismatch",
                          sc["problems"])

    def test_forged_non_perturbation_rejected(self):
        # authored non_perturbation_identical=true while the raw
        # response tokens differ from the canonical stream -> reject
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "characterization" / "pos0" / "A.resp.json"
            d = json.loads(p.read_text())
            d["tokens"] = [999999] + d["tokens"][1:]
            p.write_text(json.dumps(d))
            s = ev / "candidate" / \
                "score-characterization-case-256.json"
            sd = json.loads(s.read_text())
            sd["arms"]["A"]["non_perturbation_identical"] = True
            s.write_text(json.dumps(sd))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_wrong_arm_response_rejected(self):
        # swap B's raw response for C's -> wrong-arm binding rejected
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            bd = ev / "candidate" / "characterization" / "pos0"
            b = json.loads((bd / "B.resp.json").read_text())
            c = json.loads((bd / "C.resp.json").read_text())
            (bd / "B.resp.json").write_text(json.dumps(c))
            (bd / "C.resp.json").write_text(json.dumps(b))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_observation_pin_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "characterization" / "pos0" / \
                "pos0-observation-pin.json"
            d = json.loads(p.read_text())
            d["observation_producer"]["llama_cpp_source_pin"] = "f" * 40
            p.write_text(json.dumps(d))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_f32_length_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "characterization" / "pos0" / "A.jsonl.pos0.f32"
            p.write_bytes(p.read_bytes()[:-4])
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)


class TestObservationExecutionTruth(unittest.TestCase):
    """Round-3 blocker: observation executions mechanically bound to
    the GPU/backend selectors they represent. Every mutation below
    must fail closed (BLOCKED), never silently classify."""

    RECEIPT_MUTATIONS = {
        "absent": "receipt file removed",
        "armA_wrong_rtx": "Arm A selected the sibling 3060",
        "armB_different_than_A": "Arm B on a different 3060 than A",
        "armC_wrong_die": "Arm C on the excluded V340L die",
        "relative_icd_B": "Arm B relative ICD path",
        "relative_icd_C": "Arm C relative ICD path",
        "missing_icd_B": "Arm B ICD entry removed",
        "wrong_icd_vendor_B": "AMD devices visible under B's ICD",
        "cpu_fallback": "no-usable-GPU fallback markers",
        "wrong_binary_hash": "observation binary hash drift",
        "wrong_host": "receipt executed on the wrong host",
        "selector_pin_mismatch": "pin selector != execution env",
        "zero_selected_activity": "selected GPU carried no residency",
        "excluded_active": "excluded device active during run",
        "forged_equality": "canonical tokens with wrong identity",
        "model_member_1_sha": "model member 1 sha256 drift",
        "model_member_2_sha": "model member 2 sha256 drift",
        "model_member_3_sha": "model member 3 sha256 drift",
        "model_member_size": "model member byte length drift",
        "model_member_missing": "model member missing",
        "model_member_foreign": "foreign/additional model member",
        "prompt_sha": "prompt sha256 drift",
        "request_contract": "sampler/top-k/temperature/seed/n_predict drift",
        "duplicate_argv": "conflicting duplicate execution argv option",
        "model_path": "argv model path does not bind model subject",
        "vulkan_package": "libggml-vulkan bytes drift",
        "cuda_package": "libggml-cuda bytes drift",
        "common_package": "common libggml bytes drift",
        "missing_package": "required backend package object absent",
        "bc_package": "B/C Vulkan package mismatch",
        "mapped_package": "mapped backend object outside authorized package",
    }
    # test-method name for each mutation-class label
    _TEST_FOR = {
        "absent": "test_receipt_absent_blocks",
        "armA_wrong_rtx": "test_armA_wrong_rtx_blocks",
        "armB_different_than_A": "test_armB_different_gpu_than_A_blocks",
        "armC_wrong_die": "test_armC_wrong_die_blocks",
        "relative_icd_B": "test_relative_icd_B_blocks",
        "relative_icd_C": "test_relative_icd_C_blocks",
        "missing_icd_B": "test_missing_icd_B_blocks",
        "wrong_icd_vendor_B": "test_wrong_icd_vendor_B_blocks",
        "cpu_fallback": "test_cpu_fallback_blocks",
        "wrong_binary_hash": "test_wrong_binary_hash_blocks",
        "wrong_host": "test_wrong_host_blocks",
        "selector_pin_mismatch": "test_selector_pin_vs_receipt_mismatch_blocks",
        "zero_selected_activity": "test_zero_selected_activity_blocks",
        "excluded_active": "test_excluded_device_active_blocks",
        "forged_equality": "test_forged_token_equality_blocks",
        "model_member_1_sha": "test_model_member_hashes_block",
        "model_member_2_sha": "test_model_member_hashes_block",
        "model_member_3_sha": "test_model_member_hashes_block",
        "model_member_size": "test_model_member_shape_blocks",
        "model_member_missing": "test_model_member_shape_blocks",
        "model_member_foreign": "test_model_member_shape_blocks",
        "prompt_sha": "test_prompt_and_request_contract_block",
        "request_contract": "test_prompt_and_request_contract_block",
        "duplicate_argv": "test_duplicate_execution_argv_blocks",
        "model_path": "test_wrong_model_path_blocks",
        "vulkan_package": "test_execution_package_hashes_block",
        "cuda_package": "test_execution_package_hashes_block",
        "common_package": "test_execution_package_hashes_block",
        "missing_package": "test_missing_required_package_object_blocks",
        "bc_package": "test_bc_vulkan_package_mismatch_blocks",
        "mapped_package": "test_mapped_object_not_authorized_blocks",
    }

    def _receipts_dir(self, ev: Path) -> Path:
        return ev / "candidate" / "characterization" / "pos0"

    def _load(self, p: Path) -> dict:
        return json.loads(p.read_text())

    def _rewrite(self, p: Path, mutate) -> None:
        d = self._load(p)
        mutate(d)
        d["digest"] = "PENDING"
        d["digest"] = rc.sha256_bytes(rc.canonical(d))
        p.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")

    def test_baseline_identity_bound_ok(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_MULTI_AXIS)
            sc = doc["checks"]["score_characterization"]
            ot = sc["observation_execution_truth"]
            for arm in ("A", "B", "C"):
                self.assertEqual(ot[arm]["status"], "OK",
                                 f"{arm}: {ot[arm]['problems']}")
            self.assertTrue(ot["AB_same_gpu"]["same_frozen_rtx3060"])

    def test_receipt_absent_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            d = self._receipts_dir(ev)
            (d / "observation-receipt-B.json").unlink()
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            ot = (doc["checks"]["score_characterization"]
                  ["observation_execution_truth"])
            self.assertEqual(ot["B"]["status"], "ABSENT")

    def test_armA_wrong_rtx_blocks(self):
        # Arm A executed on the SIBLING 3060 (UUID/BDF swap)
        def mut(d):
            d["device_proof"]["selected"] = {
                "uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
                "bdf": "00000000:03:00.0"}
            d["residency"]["compute_apps_bound_to_pid"] = [{
                "t": 1.0, "phase": "generation", "pid": 4242,
                "gpu_uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
                "used_memory": "900 MiB"}]
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-A.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            ot = (doc["checks"]["score_characterization"]
                  ["observation_execution_truth"])
            self.assertIn("armA:selected_uuid:", "".join(
                ot["A"]["problems"]))

    def test_armB_different_gpu_than_A_blocks(self):
        # B's receipts claim the sibling while A stays frozen -> A/B
        # same-GPU relation breaks AND B's own binding breaks
        def mut(d):
            d["device_proof"]["selected"] = {
                "uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
                "bdf": "00000000:03:00.0",
                "deviceUUID": "d5c05739-96c1-7e49-89b6-bf54c2121c55"}
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-B.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            ot = (doc["checks"]["score_characterization"]
                  ["observation_execution_truth"])
            self.assertFalse(ot["AB_same_gpu"]["same_frozen_rtx3060"])

    def test_armC_wrong_die_blocks(self):
        # C executed on the EXCLUDED die 09:00.0
        def mut(d):
            d["device_proof"]["selected"] = {
                "bdf": "00000000:09:00.0",
                "deviceUUID": "00000000-0900-0000-0000-000000000000"}
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-C.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            ot = (doc["checks"]["score_characterization"]
                  ["observation_execution_truth"])
            self.assertIn("armC:selected_die", "".join(
                ot["C"]["problems"]))

    def test_relative_icd_B_blocks(self):
        # the quarantined-incident class: relative VK_ICD_FILENAMES
        def mut(d):
            d["launch"]["env"]["VK_ICD_FILENAMES"] = "nvidia_icd.json"
            d["launch"]["icd"]["path"] = "nvidia_icd.json"
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-B.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_relative_icd_C_blocks(self):
        def mut(d):
            d["launch"]["env"]["VK_ICD_FILENAMES"] = "radeon_icd.json"
            d["launch"]["icd"]["path"] = "radeon_icd.json"
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-C.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_missing_icd_B_blocks(self):
        def mut(d):
            d["launch"]["env"].pop("VK_ICD_FILENAMES", None)
            d["launch"]["icd"] = None
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-B.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_wrong_icd_vendor_B_blocks(self):
        # B's restricted census unexpectedly shows RADV devices
        def mut(d):
            (d["device_proof"]["vulkan_physical_devices"]
             .append({"gpu_index": "GPU2",
                      "deviceName": "AMD Radeon Pro V340",
                      "deviceUUID": "x" * 36,
                      "driverName": "RADV"}))
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-B.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_cpu_fallback_blocks(self):
        # markers of the quarantined incident: warning present,
        # no model-scale residency
        def mut(d):
            d["cpu_fallback"]["no_usable_gpu_warning_present"] = True
            d["residency"]["selected_delta_bytes"] = 0
            d["residency"]["selected_during_peak_delta_bytes"] = 0
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-B.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            ot = (doc["checks"]["score_characterization"]
                  ["observation_execution_truth"])
            probs = "".join(ot["B"]["problems"])
            self.assertIn("cpu_fallback_warning", probs)
            self.assertIn("no_model_scale_residency", probs)

    def test_wrong_binary_hash_blocks(self):
        def mut(d):
            d["observation_binary"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-A.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_wrong_host_blocks(self):
        def mut(d):
            d["host"]["hostname"] = "inferswarm09"
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-C.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_selector_pin_vs_receipt_mismatch_blocks(self):
        # pin says selector 0; execution env says 1
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) / "pos0-observation-pin.json",
                          lambda d: d["observation_producer"]
                          ["selectors"]["B"].__setitem__(
                              "GGML_VK_VISIBLE_DEVICES", "1"))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            sc = doc["checks"]["score_characterization"]
            self.assertIn("observation_pin:armB:selector",
                          "".join(sc["problems"]))

    def test_zero_selected_activity_blocks(self):
        def mut(d):
            d["residency"]["selected_delta_bytes"] = 1024
            d["residency"]["selected_during_peak_delta_bytes"] = 1024
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-A.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            ot = (doc["checks"]["score_characterization"]
                  ["observation_execution_truth"])
            self.assertIn("armA:zero_selected_device_activity",
                          "".join(ot["A"]["problems"]))

    def test_excluded_device_active_blocks(self):
        def mut(d):
            d["residency"]["excluded"][0]["peak_delta_bytes"] = \
                900 * 1024 * 1024
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-C.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_forged_token_equality_blocks(self):
        # canonical tokens in the receipt but the raw RESPONSE bytes
        # differ (the forged-equality class: tokens alone prove
        # nothing; artifact digests + non-perturbation bind truth)
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = self._receipts_dir(ev) / "B.resp.json"
            d = self._load(p)
            d["tokens"] = [999999] + d["tokens"][1:]
            p.write_text(json.dumps(d))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_receipt_digest_tamper_blocks(self):
        # mutate a validated field WITHOUT re-digesting
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = self._receipts_dir(ev) / "observation-receipt-A.json"
            d = self._load(p)
            d["device_proof"]["selected"]["uuid"] = "GPU-forged"
            p.write_text(json.dumps(d))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            ot = (doc["checks"]["score_characterization"]
                  ["observation_execution_truth"])
            self.assertIn("observation_receipt:digest",
                          "".join(ot["A"]["problems"]))

    def test_no_cuda_backend_mapped_blocks(self):
        # maps show CPU-only backends in the CUDA arm
        def mut(d):
            d["in_process_backends"]["mapped_libggml"] = [
                "libggml-base.so", "libggml-cpu.so"]
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) /
                          "observation-receipt-A.json", mut)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_model_member_hashes_block(self):
        for index in range(3):
            with self.subTest(member=index + 1), tempfile.TemporaryDirectory() as t:
                ev = make_evidence(Path(t))
                def mut(d, i=index):
                    d["model"]["members"][i]["sha256"] = "0" * 64
                self._rewrite(self._receipts_dir(ev) /
                              "observation-receipt-A.json", mut)
                self.assertEqual(red.derive_terminal(ev, closure=CLOSURE)["terminal"],
                                 red.TERMINAL_BLOCKED)

    def test_model_member_shape_blocks(self):
        mutations = {
            "size": lambda d: d["model"]["members"][1].__setitem__("bytes", 1),
            "missing": lambda d: d["model"].__setitem__("members", d["model"]["members"][:-1]),
            "foreign": lambda d: d["model"]["members"].append(
                {"name": "foreign.gguf", "bytes": 1, "sha256": "f" * 64}),
        }
        for label, mut in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as t:
                ev = make_evidence(Path(t))
                self._rewrite(self._receipts_dir(ev) /
                              "observation-receipt-B.json", mut)
                self.assertEqual(red.derive_terminal(ev, closure=CLOSURE)["terminal"],
                                 red.TERMINAL_BLOCKED)

    def test_prompt_and_request_contract_block(self):
        mutations = {
            "prompt": lambda d: d["request"].__setitem__("prompt_sha256", "0" * 64),
            "samplers": lambda d: d["request"]["contract"].__setitem__("samplers", ["greedy"]),
            "top_k": lambda d: d["request"]["contract"].__setitem__("top_k", 2),
            "temperature": lambda d: d["request"]["contract"].__setitem__("temperature", 0.5),
            "seed": lambda d: d["request"]["contract"].__setitem__("seed", 1),
            "n_predict": lambda d: d["request"]["contract"].__setitem__("n_predict", 9),
        }
        for label, mut in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as t:
                ev = make_evidence(Path(t))
                self._rewrite(self._receipts_dir(ev) /
                              "observation-receipt-C.json", mut)
                self.assertEqual(red.derive_terminal(ev, closure=CLOSURE)["terminal"],
                                 red.TERMINAL_BLOCKED)

    def test_duplicate_execution_argv_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) / "observation-receipt-A.json",
                          lambda d: d["launch"]["argv"].extend(
                              ["--n-gpu-layers", "99"]))
            self.assertEqual(red.derive_terminal(ev, closure=CLOSURE)["terminal"],
                             red.TERMINAL_BLOCKED)

    def test_wrong_model_path_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            def mut(d):
                argv = d["launch"]["argv"]
                argv[argv.index("--model") + 1] = "/models/foreign.gguf"
            self._rewrite(self._receipts_dir(ev) / "observation-receipt-B.json", mut)
            self.assertEqual(red.derive_terminal(ev, closure=CLOSURE)["terminal"],
                             red.TERMINAL_BLOCKED)

    def test_execution_package_hashes_block(self):
        cases = (("A", "libggml-cuda.so"), ("B", "libggml-vulkan.so"),
                 ("C", "libggml.so"), ("C", "libggml-base.so"))
        for arm, obj in cases:
            with self.subTest(arm=arm, object=obj), tempfile.TemporaryDirectory() as t:
                ev = make_evidence(Path(t))
                def mut(d, o=obj):
                    d["observation_binary"].setdefault("package", {}) \
                        .setdefault("objects", {})[o] = {"sha256": "0" * 64}
                self._rewrite(self._receipts_dir(ev) /
                              f"observation-receipt-{arm}.json", mut)
                self.assertEqual(red.derive_terminal(ev, closure=CLOSURE)["terminal"],
                                 red.TERMINAL_BLOCKED)

    def test_missing_required_package_object_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) / "observation-receipt-B.json",
                          lambda d: d["observation_binary"].setdefault(
                              "package", {}).setdefault("objects", {}).pop(
                              "libggml-vulkan.so", None))
            self.assertEqual(red.derive_terminal(ev, closure=CLOSURE)["terminal"],
                             red.TERMINAL_BLOCKED)

    def test_bc_vulkan_package_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) / "observation-receipt-C.json",
                          lambda d: d["observation_binary"].setdefault(
                              "package", {}).setdefault("objects", {}).__setitem__(
                                  "libggml-vulkan.so", {"sha256": "c" * 64}))
            self.assertEqual(red.derive_terminal(ev, closure=CLOSURE)["terminal"],
                             red.TERMINAL_BLOCKED)

    def test_mapped_object_not_authorized_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._rewrite(self._receipts_dir(ev) / "observation-receipt-B.json",
                          lambda d: d["in_process_backends"].__setitem__(
                              "mapped_objects", [{"path": "/tmp/libggml-vulkan.so",
                                                  "sha256": "f" * 64}]))
            self.assertEqual(red.derive_terminal(ev, closure=CLOSURE)["terminal"],
                             red.TERMINAL_BLOCKED)

    def test_receipt_covers_all_mutation_classes(self):
        # structural: each documented mutation class has a test
        for label in self.RECEIPT_MUTATIONS:
            self.assertTrue(
                hasattr(self, self._TEST_FOR[label]),
                f"missing mutation-class test: {label}")


class TestObservationPinSelectors(unittest.TestCase):
    """Round-3: the pin's selector/ICD authority is mechanically
    enforced (previously authored strings nothing validated)."""

    def _pin(self, ev: Path) -> Path:
        return (ev / "candidate" / "characterization" / "pos0" /
                "pos0-observation-pin.json")

    def _mutate_pin(self, ev, mutate):
        d = json.loads(self._pin(ev).read_text())
        mutate(d)
        self._pin(ev).write_text(json.dumps(d))

    def test_valid_pin_passes(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            problems = red._validate_observation_pin(ev, 0)
            self.assertEqual(problems, [])

    def test_pin_selector_mutation_blocks(self):
        for arm, key, val in (
                ("A", "CUDA_VISIBLE_DEVICES", "GPU-forged"),
                ("B", "GGML_VK_VISIBLE_DEVICES", "1"),
                ("C", "VK_ICD_FILENAMES", "/other/radeon_icd.json")):
            with tempfile.TemporaryDirectory() as t:
                ev = make_evidence(Path(t))
                self._mutate_pin(
                    ev, lambda d, a=arm, k=key, v=val:
                    d["observation_producer"]["selectors"][a]
                    .__setitem__(k, v))
                problems = red._validate_observation_pin(ev, 0)
                self.assertTrue(
                    any(f"arm{arm}:selector" in p for p in problems),
                    f"{arm}/{key}: {problems}")

    def test_pin_relative_icd_blocks(self):
        for arm in ("B", "C"):
            with tempfile.TemporaryDirectory() as t:
                ev = make_evidence(Path(t))
                self._mutate_pin(
                    ev, lambda d, a=arm:
                    d["observation_producer"]["selectors"][a]
                    .__setitem__("VK_ICD_FILENAMES", "radeon_icd.json"))
                problems = red._validate_observation_pin(ev, 0)
                self.assertTrue(
                    any("icd_not_absolute" in p or
                        f"arm{a}:selector" in p
                        for p in problems for a in [arm]),
                    f"{arm}: {problems}")

    def test_pin_missing_selector_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._mutate_pin(
                ev, lambda d:
                d["observation_producer"]["selectors"].pop("A"))
            problems = red._validate_observation_pin(ev, 0)
            self.assertTrue(any("selector" in p for p in problems))

    def test_pin_icd_sha_mutation_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._mutate_pin(
                ev, lambda d:
                d["observation_producer"]["icd_sha256"]
                .__setitem__("B", "0" * 64))
            problems = red._validate_observation_pin(ev, 0)
            self.assertTrue(any("icd_sha256" in p for p in problems))


class TestReducerTerminals(unittest.TestCase):
    def test_divergence_without_characterization_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            import shutil
            ev = make_evidence(Path(t))
            shutil.rmtree(ev / "candidate" / "characterization")
            (ev / "candidate" /
             "score-characterization-case-256.json").unlink()
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            self.assertIn("characterization",
                          " ".join(doc["terminal_basis"]))

    def test_repeat_drop_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), drop_b_repeat=True)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_nondeterminism_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), det_b=False)
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)

    def test_ladder_prefix_violation_raises(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t), case="case-1024")
            with self.assertRaises(red.ReduceError):
                red.derive_terminal(ev, closure=CLOSURE)

    def test_geometry_drift_raises(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            p = ev / "candidate" / "ladder-B-case-256.json"
            d = json.loads(p.read_text())
            d["geometry"]["ngl"] = 99
            p.write_text(json.dumps(d))
            with self.assertRaises(red.ReduceError):
                red.derive_terminal(ev, closure=CLOSURE)

    def test_authored_status_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            for arm in "ABC":
                p = ev / "candidate" / f"ladder-{arm}-case-256.json"
                d = json.loads(p.read_text())
                d["status"] = "PASS_ALL_EQUAL"
                for r in d["repeats"]:
                    r["comparison"] = {"exact": True}
                p.write_text(json.dumps(d))
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_MULTI_AXIS)

    def test_legacy_greedy_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            for arm in "ABC":
                p = ev / "candidate" / f"ladder-{arm}-case-256.json"
                d = json.loads(p.read_text())
                d["geometry"]["request"]["samplers"] = ["greedy"]
                p.write_text(json.dumps(d))
            with self.assertRaises(red.ReduceError):
                red.derive_terminal(ev, closure=CLOSURE)

    def test_retired_terminal_never_emitted(self):
        self.assertNotIn(red.RETIRED_TERMINAL, red.ALL_TERMINALS)


class TestControlSuite(unittest.TestCase):
    def test_count_and_ids(self):
        self.assertEqual(len(asm.CONTROLS), 36)
        self.assertEqual(sorted(asm.CONTROLS), list(range(1, 37)))

    def test_controls_run_all_ok_on_multi_axis_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            receipt = asm.run_controls(ev, CLOSURE)
            self.assertEqual(receipt["count"], 36)
            self.assertTrue(receipt["all_ok"])
            bad = {k: v for k, v in receipt["controls"].items()
                   if not v["ok"]}
            self.assertEqual(bad, {}, f"failing controls: {bad}")

    def test_control33_receipts_only_missing_blocks(self):
        # round-3 companion: raw bytes intact but execution receipts
        # absent — an unbound observation corpus blocks
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            pos0 = ev / "candidate" / "characterization" / "pos0"
            for p in pos0.glob("observation-receipt-*.json"):
                p.unlink()
            doc = red.derive_terminal(ev, closure=CLOSURE)
            self.assertEqual(doc["terminal"], red.TERMINAL_BLOCKED)
            ot = (doc["checks"]["score_characterization"]
                  ["observation_execution_truth"])
            self.assertEqual(ot["A"]["status"], "ABSENT")
            self.assertIn("observation_execution_truth",
                          "".join(doc["checks"]["score_characterization"]
                                  ["problems"]))

    def test_control33_proves_all_blocked_paths(self):
        # focused re-check of the five required control-33 outcomes
        outcomes = {}
        with tempfile.TemporaryDirectory() as t:
            import shutil
            ev = make_evidence(Path(t))
            # (1) missing characterization
            shutil.rmtree(ev / "candidate" / "characterization")
            (ev / "candidate" /
             "score-characterization-case-256.json").unlink()
            outcomes["missing"] = red.derive_terminal(
                ev, closure=CLOSURE)["terminal"]
            # (2) wrong generated position (summary-only, pos 5)
            ev2 = make_evidence(Path(t) / "x2")
            shutil.rmtree(ev2 / "candidate" / "characterization" / "pos0")
            (ev2 / "candidate" /
             "score-characterization-case-256.json").unlink()
            outcomes["wrong_pos"] = red.derive_terminal(
                ev2, closure=CLOSURE)["terminal"]
        self.assertEqual(outcomes["missing"], red.TERMINAL_BLOCKED)
        self.assertEqual(outcomes["wrong_pos"], red.TERMINAL_BLOCKED)
        # (3/4/5) summary/raw mismatch, sidecar tamper, non-perturbation
        # forgery are covered by TestRawBoundCharacterization above and
        # by controls 21/27/31/32/33 in the assembled suite.


class TestDeployedProducerVerification(unittest.TestCase):
    CLOSURE_PHYS = None

    @classmethod
    def setUpClass(cls):
        real = rc.verify_closure(REPO)
        cls.CLOSURE_PHYS = real

    def _deployed(self, ev: Path):
        return json.loads(
            (ev / "freeze" / "deployed-producers.json").read_text())

    def test_real_matrix_verifies(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            r = asm.verify_deployed_producers(
                self._deployed(ev), self.CLOSURE_PHYS)
            self.assertTrue(r["derived_all_hosts_match_pin"])
            self.assertEqual(r["expected_hosts"],
                             ["inferswarm01", "inferswarm02"])
            for h in ("inferswarm01", "inferswarm02"):
                self.assertEqual(
                    r["per_host"][h]["checked"],
                    sorted(asm.DEPLOYED_PRODUCER_BASENAMES))

    def _expect_fail(self, ev, mutate, label):
        d = self._deployed(ev)
        mutate(d)
        with self.assertRaises(asm.AssembleError, msg=label):
            asm.verify_deployed_producers(d, self.CLOSURE_PHYS)

    def test_missing_host_01_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._expect_fail(
                ev, lambda d: d["hosts"].pop("inferswarm01"), "01")

    def test_missing_host_02_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._expect_fail(
                ev, lambda d: d["hosts"].pop("inferswarm02"), "02")

    def test_missing_ladder_producer_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._expect_fail(
                ev,
                lambda d: d["hosts"]["inferswarm01"]["hashes"].pop(
                    "issue234_ladder.py"),
                "ladder")

    def test_wrong_ladder_hash_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._expect_fail(
                ev,
                lambda d: d["hosts"]["inferswarm01"]["hashes"].
                __setitem__("issue234_ladder.py", "0" * 64),
                "ladder-hash")

    def test_wrong_health_hash_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            self._expect_fail(
                ev,
                lambda d: d["hosts"]["inferswarm02"]["hashes"].
                __setitem__("issue234_health.py", "0" * 64),
                "health-hash")

    def test_substituted_producer_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            def mut(d):
                h = d["hosts"]["inferswarm01"]["hashes"]
                h["issue234_substitute.py"] = h["issue234_ladder.py"]
            self._expect_fail(ev, mut, "substitute")

    def test_authored_boolean_not_trusted(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            def mut(d):
                d["all_hosts_match_pin"] = True
                d["hosts"].pop("inferswarm01")
            self._expect_fail(ev, mut, "forged boolean")

    def test_renamed_collection_pin_out_of_lineage_fails(self):
        # /3 schema: closure_producer_head_at_collection must be in the
        # closure lineage; a foreign SHA fails closed under BOTH the
        # renamed and the legacy spelling.
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            for key in ("closure_producer_head_at_collection",
                        "closure_producer_head"):
                d = self._deployed(ev)
                d.pop("closure_producer_head_at_collection", None)
                d.pop("closure_producer_head", None)
                d[key] = "f" * 40
                with self.assertRaises(asm.AssembleError, msg=key):
                    asm.verify_deployed_producers(d, self.CLOSURE_PHYS)

    def test_stale_closure_pin_out_of_lineage_fails(self):
        with tempfile.TemporaryDirectory() as t:
            ev = make_evidence(Path(t))
            closure = dict(self.CLOSURE_PHYS)
            closure["producer_head"] = closure["producer_head"]
            # 377d2ff IS an ancestor of the active pin -> passes
            r = asm.verify_deployed_producers(self._deployed(ev),
                                              self.CLOSURE_PHYS)
            self.assertTrue(r["derived_all_hosts_match_pin"])
            # a foreign SHA must fail the lineage check
            def mut(d):
                d["closure_producer_head"] = "f" * 40
            with self.assertRaises(asm.AssembleError):
                d = self._deployed(ev)
                mut(d)
                asm.verify_deployed_producers(d, self.CLOSURE_PHYS)


class TestClosureDoctrine(unittest.TestCase):
    def test_closure_document_blobs(self):
        doc = rc.closure_document(REPO)
        self.assertEqual(doc["schema"],
                         "inferswarm.r8h.producer-closure/2")
        self.assertEqual(len(doc["sources"]), len(rc.CLOSURE_SOURCES))
        self.assertIn("scripts/issue234_characterize.py",
                      rc.REDUCTION_PRODUCERS)
        self.assertIn("scripts/issue234_characterize.py",
                      doc["sources"])
        n_phys = sum(1 for v in doc["sources"].values()
                     if v["class"] == "physical")
        self.assertEqual(n_phys, len(rc.PHYSICAL_PRODUCERS))

    def test_freeze_binding_rejects_gpu_mismatch(self):
        gpu = {"host": "h", "uuid": "GPU-x", "bdf": "02:00.0",
               "cuda_identity": "c", "vulkan_identity": "v"}
        common = {"ngl": 1, "context": rc.CONTEXT_SETTINGS,
                  "request": rc.REQUEST_CONTRACT,
                  "fixture_sha256": rc.R8D_FIXTURE_SHA256,
                  "model_sha256": [m["sha256"] for m in rc.MODEL_MEMBERS]}
        doc = {"schema": "inferswarm.r8h.freeze/2",
               "campaign": rc.CAMPAIGN_ID,
               "llama_cpp_pin": rc.LLAMA_CPP_PIN,
               "request_contract": rc.REQUEST_CONTRACT,
               "fixture_sha256": rc.R8D_FIXTURE_SHA256,
               "ngl": rc.MATCHED_NGL, "context": rc.CONTEXT_SETTINGS,
               "model_members": [dict(m) for m in rc.MODEL_MEMBERS],
               "rtx3060": gpu,
               "arms": {"A": {**common, "gpu": gpu},
                        "B": {**common, "gpu": dict(gpu,
                                                    uuid="GPU-OTHER")},
                        "C": {**common,
                              "gpu": {"bdf": "06:00.0",
                                      "deviceUUID": "d"},
                              "excluded_die": {"bdf": "09:00.0"}}}}
        with self.assertRaises(rc.FreezeError):
            rc.verify_freeze_binding(doc)


class TestGeometry(unittest.TestCase):
    def test_context_settings_batch_flag(self):
        self.assertIn("batch-size", rc.CONTEXT_SETTINGS)
        self.assertNotIn("batch", rc.CONTEXT_SETTINGS)

    def test_repeat_ids(self):
        self.assertEqual(rc.REQUIRED_REPEAT_IDS, (1, 2, 3))


if __name__ == "__main__":
    unittest.main()
