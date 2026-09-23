#!/usr/bin/env python3
"""Bounded Phase-3 host/server comparator collector; CPU fake-runner tested."""
from __future__ import annotations
import hashlib, json, os, re, signal, subprocess, threading, time, urllib.request, urllib.error
from pathlib import Path
from typing import Any, Callable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_comparator as comparator
import issue241_constants as C
import issue241_census as census_mod
import issue241_dispatch as dispatch
import issue241_placement as placement
import issue241_placement_producer as phase2_producer

PHASE2_SCHEMA = phase2_producer.SCHEMA

def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def _bdf(text: str) -> str:
    m = re.fullmatch(r"([0-9a-fA-F]{4,8}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])", text)
    if not m: raise ValueError(f"malformed BDF {text!r}")
    return f"{int(m[1],16):08x}:{m[2].lower()}:{m[3].lower()}.{m[4]}"

def _command(argv: list[str], env: dict[str, str] | None = None) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, check=True,
                            timeout=15, env=env)
    if not result.stdout.strip(): raise ValueError(f"empty device observation: {argv}")
    return result.stdout

def _nvidia() -> dict[str, dict[str, Any]]:
    rows = {}
    for line in _command(["nvidia-smi", "--query-gpu=uuid,pci.bus_id,memory.used",
                          "--format=csv,noheader,nounits"]).splitlines():
        fields = [v.strip() for v in line.split(",")]
        if len(fields) != 3: raise ValueError("malformed NVIDIA device row")
        bdf = _bdf(fields[1])
        if bdf in rows: raise ValueError("duplicate NVIDIA BDF")
        rows[bdf] = {"gpu_uuid": fields[0], "used_mib": int(fields[2])}
    return rows

def _amd(bdf: str) -> dict[str, Any]:
    dev = Path("/sys/bus/pci/devices") / (f"{int(bdf[:8],16):04x}" + bdf[8:])
    cards = sorted(dev.glob("drm/card[0-9]*"))
    if len(cards) != 1: raise ValueError(f"no unique AMD DRM card for {bdf}")
    used = int((cards[0] / "device/mem_info_vram_used").read_text().strip())
    vendor = (dev / "vendor").read_text().strip().removeprefix("0x").lower()
    device = (dev / "device").read_text().strip().removeprefix("0x").lower()
    return {"pci_id": f"{vendor}:{device}", "used_mib": used / (1024 * 1024)}

def _device_identity(arm: str, env: dict[str, str]) -> dict[str, Any]:
    cfg = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    bdf = cfg["bdf"]
    text = _command(["vulkaninfo", "--summary"], env=env)
    gpus: list[dict[str, str]] = []
    for line in text.splitlines():
        s = line.strip()
        if re.fullmatch(r"GPU\d+:", s): gpus.append({})
        elif gpus and "=" in s:
            k, _, v = s.partition("="); gpus[-1][k.strip()] = v.strip()
    if len(gpus) != 1 or not gpus[0].get("deviceName"):
        raise ValueError("ICD must expose exactly one named Vulkan GPU")
    gpu = gpus[0]
    result = {"bdf": bdf, "vulkan_device_name": gpu["deviceName"],
              "vulkan_device_uuid": gpu.get("deviceUUID"),
              "vulkan_api_version": gpu.get("apiVersion"),
              "vulkan_driver_name": gpu.get("driverName"),
              "vulkan_driver_info": gpu.get("driverInfo"),
              "vulkan_summary": text}
    if arm == "B":
        nv = _nvidia()
        if bdf not in nv: raise ValueError("reference BDF absent from NVIDIA observation")
        result["gpu_uuid"] = nv[bdf]["gpu_uuid"]
    else:
        amd = _amd(bdf)
        uuid = gpu.get("deviceUUID", "").replace("-", "")
        if len(uuid) != 32 or not re.fullmatch(r"[0-9a-fA-F]{32}", uuid):
            raise ValueError("RADV deviceUUID absent or malformed")
        mapped = _bdf(f"{uuid[:8]}:{uuid[8:10]}:{uuid[10:12]}.{int(uuid[12:14],16)&7}")
        if mapped != bdf: raise ValueError("RADV UUID does not map to selected BDF")
        result.update(pci_id=amd["pci_id"])
    return result

def _device_sample(arm: str, stage: str) -> dict[str, Any]:
    bdf = next(iter(C.EXCLUDED_BY_ARM[arm]))
    info = _amd(bdf) if arm == "B" else _nvidia()[bdf]
    return {"stage": stage, "timestamp": time.time(),
            "residency_mib": {bdf: info["used_mib"]}, "device": info}

def _process_attribution(pid: int) -> dict[str, Any]:
    root = Path(f"/proc/{pid}")
    argv = [part.decode(errors="replace") for part in (root / "cmdline").read_bytes().split(b"\0") if part]
    env = {}
    for part in (root / "environ").read_bytes().split(b"\0"):
        if b"=" in part:
            k, _, v = part.partition(b"=")
            key = k.decode(errors="replace")
            if key in {"GGML_VK_VISIBLE_DEVICES", "CUDA_VISIBLE_DEVICES", "VK_ICD_FILENAMES", "LLAMA_OBSERVE_CAPTURE", "LLAMA_OBSERVE_OUT", "LLAMA_OBSERVE_LOG", "LLAMA_OBSERVE_FORCE"}:
                env[key] = v.decode(errors="replace")
    if not argv or not env: raise ValueError("live /proc argv/env missing")
    return {"server_pid": pid, "server_argv": argv, "server_env": env,
            "server_exe_sha256": _file_sha(root / "exe")}

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _validate_authority(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict) or doc.get("schema") != dispatch.AUTHORITY_SCHEMA:
        raise ValueError("exact dispatch authority required")
    if not dispatch.SHA40.fullmatch(str(doc.get("head_sha", ""))):
        raise ValueError("dispatch authority head is malformed")
    if doc.get("dispatch_phrase") != dispatch.DISPATCH_PHRASE:
        raise ValueError("dispatch authority phrase mismatch")
    if not isinstance(doc.get("review_id"), int) or isinstance(doc.get("review_id"), bool) or not doc.get("reviewer"):
        raise ValueError("dispatch authority reviewer/review identity missing")
    return doc

def _phase2(doc: Any) -> int:
    if not isinstance(doc, dict) or doc.get("schema") != PHASE2_SCHEMA or doc.get("campaign") != C.CAMPAIGN_ID:
        raise ValueError("full Phase-2 producer receipt required")
    if not isinstance(doc.get("authority"), dict):
        raise ValueError("Phase-2 authority missing")
    ladder = list(C.LADDER_NGLS)
    rungs, receipts = doc.get("rungs"), doc.get("rung_receipts")
    if not isinstance(rungs, dict) or set(rungs) != {"B", "C"}:
        raise ValueError("Phase-2 receipt must contain both B/C rung sets")
    for arm in ("B", "C"):
        rows = rungs[arm]
        if not isinstance(rows, list) or [r.get("ngl") for r in rows] != ladder:
            raise ValueError(f"Phase-2 {arm} ladder does not match frozen ordered rungs")
        if any(r.get("arm") != arm or r.get("schema") != placement.RUNG_SCHEMA for r in rows):
            raise ValueError(f"Phase-2 {arm} rung identity/schema mismatch")
    if not isinstance(receipts, list) or len(receipts) != 2 * len(ladder):
        raise ValueError("Phase-2 ordered raw rung receipts incomplete")
    expected_order = [(n, a) for n in ladder for a in ("C", "B")]
    if [(r.get("ngl"), r.get("arm")) for r in receipts] != expected_order:
        raise ValueError("Phase-2 raw rung receipts have wrong execution order")
    for r in receipts:
        if not isinstance(r.get("raw_log_sha256"), str) or len(r["raw_log_sha256"]) != 64 or not r.get("raw_log"):
            raise ValueError("Phase-2 rung receipt lacks raw-log identity")
    selected = placement.select_matched_rung(rungs)
    if doc.get("selected") != selected or selected.get("placement_blocked") or type(selected.get("matched_ngl")) is not int:
        raise ValueError("Phase-2 selected result is invalid or inconsistent with both ladders")
    return selected["matched_ngl"]

def _real_runner(*, argv: list[str], env: dict[str, str], arm: str, mode: str,
                 request: dict[str, Any], prompt: str, output_dir: Path,
                 timeout_s: int) -> dict[str, Any]:
    """Launch server, send the frozen request, preserve raw logs and observer output."""
    port = int(argv[argv.index("--port") + 1]); log_path = Path(env["LLAMA_OBSERVE_LOG"])
    process_env = {**os.environ, **env}
    identity = _device_identity(arm, process_env)
    samples = [_device_sample(arm, "before")]
    t0 = time.monotonic(); deadline = t0 + timeout_s
    with log_path.open("wb") as log:
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                env=process_env, start_new_session=True)
        try:
            while time.monotonic() < min(deadline, t0 + 300):
                if proc.poll() is not None: raise RuntimeError(f"server exited early ({proc.returncode})")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as health:
                        if health.status == 200: break
                except (OSError, urllib.error.URLError): time.sleep(.2)
            else: raise TimeoutError("server readiness deadline exceeded")
            attribution = _process_attribution(proc.pid)
            samples.append(_device_sample(arm, "during"))
            body = {**request, "prompt": prompt}
            # llama.cpp completion endpoint consumes n_predict/temperature/top_k;
            # the observer hook sees these same request tokens and prompt.
            req = urllib.request.Request(f"http://127.0.0.1:{port}/completion",
                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            # Keep sampling the excluded device throughout the blocking HTTP request.
            stop = threading.Event(); errors: list[Exception] = []
            def sample_loop() -> None:
                while not stop.wait(1):
                    try: samples.append(_device_sample(arm, "during"))
                    except Exception as exc:
                        errors.append(exc); return
            thread = threading.Thread(target=sample_loop, daemon=True); thread.start()
            try:
                with urllib.request.urlopen(req, timeout=max(.1, deadline-time.monotonic())) as response:
                    if response.status != 200: raise RuntimeError("completion HTTP status != 200")
                    raw_response = response.read(1024 * 1024)
            finally:
                stop.set(); thread.join(timeout=2)
            if errors: raise RuntimeError("device sampling failed during completion") from errors[0]
            samples.append(_device_sample(arm, "after"))
            response = json.loads(raw_response)
            return {"returncode": 0, "response": response, "response_raw": raw_response,
                    "pid": proc.pid, "process_attribution": attribution,
                    "device_identity": identity, "device_samples": samples,
                    "log_path": str(log_path), "started_monotonic": t0}
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL); proc.wait(timeout=5)

def run_phase3_producer(repo_root: Path, out_root: Path, server: Path,
                        selected_receipt: dict[str, Any], authority: dict[str, Any],
                        runner: Callable[..., Any] | None = None,
                        revalidate_authority: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                        timeout_s: int = 3600, canonical_server: Path | None = None) -> dict[str, Any]:
    """Execute all four historical cases, both arms, repeats and inertness controls.

    The supplied Phase-2 value is the complete phase2-producer receipt, not a
    per-case selected object. The revalidator is called immediately before
    every server run. No physical run is performed unless this API is invoked.
    """
    repo, out = Path(repo_root).resolve(strict=True), Path(out_root)
    binary = Path(server).resolve(strict=True)
    ngl = _phase2(selected_receipt)
    authority = _validate_authority(authority)
    canonical = Path(canonical_server).resolve(strict=True) if canonical_server is not None else None
    if canonical is None or canonical == binary or not canonical.is_file():
        raise ValueError("distinct canonical no-hook server binary is required for inertness controls")
    if not callable(revalidate_authority): raise ValueError("revalidation callback required before every run")
    if selected_receipt.get("authority") != authority: raise ValueError("Phase-2 authority differs from current dispatch authority")
    out.mkdir(parents=True, exist_ok=True)
    fixtures = C.load_fixtures(repo); execute = runner or _real_runner
    binary_sha = _file_sha(binary); canonical_sha = _file_sha(canonical)
    if canonical_sha != C.ACCEPTED_CANONICAL_VK_SERVER_SHA256:
        raise ValueError("accepted canonical no-hook server SHA mismatch")
    if binary_sha == canonical_sha: raise ValueError("canonical server bytes must differ from patched server")
    model_hashes = {_name: _file_sha(C.MODEL_DIR / _name) for _name in C.MODEL_MEMBERS}
    if model_hashes != C.MODEL_MEMBER_SHA256:
        raise ValueError("actual model member hashes differ from frozen model")
    all_pairs=[]; all_determinism=[]; all_inertness=[]; timings={"B":{},"C":{}}

    def run(case: str, arm: str, mode: str, forced: list[int] | None = None) -> dict[str, Any]:
        nonlocal authority
        authority = _validate_authority(revalidate_authority(authority))
        cfg = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
        case_dir = out / case; case_dir.mkdir(parents=True, exist_ok=True)
        tag=f"{case}-{arm}-{mode}"; log_path=case_dir/f"{tag}.server.log"
        observer = mode in ("baseline", "candidate", "repeat", "disabled")
        env={**cfg["selector"], "VK_ICD_FILENAMES":cfg["icd"],
             "LLAMA_OBSERVE_CAPTURE":"8" if observer and mode!="disabled" else "0",
             "LLAMA_OBSERVE_OUT":str(case_dir/tag), "LLAMA_OBSERVE_LOG":str(log_path),
             "LLAMA_OBSERVE_FORCE":"" if forced is None else ",".join(map(str,forced))}
        run_binary = canonical if mode == "canonical" else binary
        argv=[str(run_binary),"--model",str(C.MODEL_DIR/C.MODEL_MEMBERS[0]),"-ngl",str(ngl),
              "--ctx-size","8192","--batch-size","512","--host","127.0.0.1",
              "--port",str(19000+(arm=="C"))]
        request=dict(C.REQUEST_CONTRACT)
        start=time.monotonic()
        result=execute(argv=argv,env=env,arm=arm,mode=mode,request=request,
                       prompt=fixtures[case]["prompt_text"],output_dir=case_dir,timeout_s=timeout_s)
        wall=time.monotonic()-start
        if not isinstance(result,dict) or result.get("returncode") not in (0,None): raise ValueError(f"{tag}: server execution failed")
        pa = result.get("process_attribution")
        if not isinstance(pa, dict) or type(pa.get("server_pid")) is not int or pa["server_pid"] <= 0 or not isinstance(pa.get("server_argv"), list) or not isinstance(pa.get("server_env"), dict):
            raise ValueError(f"{tag}: actual process attribution required")
        if pa["server_argv"] != argv or any(pa["server_env"].get(k) != v for k, v in env.items()):
            raise ValueError(f"{tag}: observed process attribution differs from launch")
        if pa.get("server_exe_sha256") != (canonical_sha if mode == "canonical" else binary_sha):
            raise ValueError(f"{tag}: executed server /proc/exe hash differs from selected binary")
        identity = result.get("device_identity")
        if not isinstance(identity, dict) or identity.get("bdf") != cfg["bdf"] or (arm == "B" and identity.get("gpu_uuid") != cfg["gpu_uuid"]) or (arm == "C" and identity.get("pci_id") != cfg["pci_id"]):
            raise ValueError(f"{tag}: observed device identity differs from frozen BDF/UUID/PCI")
        name = identity.get("vulkan_device_name")
        if (arm == "B" and name != "NVIDIA GeForce RTX 3060") or (arm == "C" and (not isinstance(name, str) or "RADV POLARIS10" not in name)):
            raise ValueError(f"{tag}: Vulkan device identity mismatch")
        # Full frozen-subject identity carried through acceptance-bearing
        # execution: subsystem/revision/link/driver/ICD/Vulkan-UUID drift
        # fails closed here too (same predicate as census/Phase-2).
        identity_drift = census_mod.identity_problems(arm, identity)
        if identity_drift:
            raise ValueError(f"{tag}: frozen subject identity drift: {identity_drift}")
        samples = result.get("device_samples")
        if not isinstance(samples, list) or not {"before", "during", "after"}.issubset({s.get("stage") for s in samples if isinstance(s, dict)}):
            raise ValueError(f"{tag}: before/during/after device samples required")
        excluded = {}
        for bdf in C.EXCLUDED_BY_ARM[arm]:
            values = [s.get("residency_mib", {}).get(bdf) for s in samples]
            if any(type(v) not in (int, float) or not (0 <= v < float("inf")) for v in values):
                raise ValueError(f"{tag}: excluded device residency missing or over noise")
            idle = next(s["residency_mib"][bdf] for s in samples if s["stage"] == "before")
            delta = max(0, max(values) - idle)
            if delta > C.EXCLUDED_RESIDENCY_NOISE_MIB:
                raise ValueError(f"{tag}: excluded device residency exceeds idle noise")
            excluded[bdf] = delta
        if result.get("excluded_device_residency_mib") is not None and result["excluded_device_residency_mib"] != excluded:
            raise ValueError(f"{tag}: excluded device summary differs from raw samples")
        response=result.get("response")
        tokens=result.get("tokens")
        if isinstance(response,dict): tokens=response.get("tokens",response.get("tokens_predicted"))
        if not isinstance(tokens,list) or len(tokens)!=C.DECISIONS or any(type(t) is not int for t in tokens): raise ValueError(f"{tag}: exactly 8 integer response tokens required")
        raw_response = result.get("response_raw")
        if not isinstance(raw_response, bytes) or not raw_response:
            raise ValueError(f"{tag}: raw HTTP response required")
        if json.loads(raw_response).get("tokens") != tokens:
            raise ValueError(f"{tag}: HTTP response tokens differ from claimed tokens")
        response_path = case_dir / f"{tag}.response.json"
        with response_path.open("xb") as stream: stream.write(raw_response)
        if not log_path.is_file() and isinstance(result.get("log"),(bytes,str)):
            log_path.write_bytes(result["log"].encode() if isinstance(result["log"],str) else result["log"])
        if not log_path.is_file() or not log_path.stat().st_size: raise ValueError(f"{tag}: raw server log missing")
        rowentries={}; metarows=[]
        metapath = Path(f"{env['LLAMA_OBSERVE_OUT']}.meta.json")
        if observer and mode!="disabled":
            rawrows=result.get("rows")
            if rawrows is None:
                rawrows={}
                for d in range(C.DECISIONS):
                    p=Path(f"{env['LLAMA_OBSERVE_OUT']}.row{d}.f32")
                    if p.is_file() and not p.is_symlink(): rawrows[str(d)]=p.read_bytes()
                if result.get("meta_rows") is None and metapath.is_file() and not metapath.is_symlink():
                    metarows=[json.loads(line) for line in metapath.read_text().splitlines() if line.strip()]
                else:
                    metarows=result.get("meta_rows")
            else:
                metarows=result.get("meta_rows")
            if not isinstance(rawrows,dict) or set(rawrows)!={str(d) for d in range(8)} or not isinstance(metarows,list) or len(metarows)!=8:
                raise ValueError(f"{tag}: observer must provide eight actual raw rows and metadata records")
            if [m.get("pos") for m in metarows] != list(range(C.DECISIONS)) or any(m.get("n_vocab", C.N_VOCAB) != C.N_VOCAB for m in metarows):
                raise ValueError(f"{tag}: observer meta position/vocab drift")
            if not metapath.is_file() or metapath.is_symlink():
                raise ValueError(f"{tag}: raw observer metadata missing")
            raw_meta = metapath.read_bytes()
            if [json.loads(line) for line in raw_meta.splitlines() if line.strip()] != metarows:
                raise ValueError(f"{tag}: raw observer metadata differs from parsed rows")
            for d in range(8):
                raw=rawrows[str(d)]
                if not isinstance(raw,bytes) or len(raw)!=C.ROW_BYTES: raise ValueError(f"{tag}: raw row {d} malformed")
                rel=f"{tag}.row{d}.f32"
                target = case_dir/rel
                if target.is_file():
                    if target.is_symlink() or target.read_bytes() != raw: raise ValueError(f"{tag}: hook row changed before custody")
                else:
                    with target.open("xb") as stream: stream.write(raw)
                rowentries[str(d)]={"path":f"{case}/{rel}","bytes":len(raw),"sha256":_sha(raw)}
        observed_winners=[m.get("sampled_winner") for m in metarows] if observer and mode!="disabled" else result.get("sampled_winners",tokens)
        observed_forced=[m.get("forced_token") for m in metarows if m.get("forced_token")!=-1] if observer and mode!="disabled" else result.get("forced_tokens",forced or [])
        if observer and mode!="disabled" and arm=="C" and observed_forced!=forced:
            raise ValueError(f"{tag}: observer meta does not confirm exact reference force sequence")
        if observer and mode!="disabled" and arm=="B" and observed_forced:
            raise ValueError(f"{tag}: reference observer unexpectedly forced a token")
        if observer and mode!="disabled" and arm=="B" and tokens != observed_winners:
            raise ValueError(f"{tag}: response tokens differ from observed reference winners")
        if observer and mode!="disabled" and arm=="C" and tokens != forced:
            raise ValueError(f"{tag}: response tokens differ from forced reference sequence")
        if mode in ("disabled", "canonical"):
            if metarows or any(Path(f"{env['LLAMA_OBSERVE_OUT']}.{suffix}").exists() for suffix in ["meta.json", *[f"row{d}.f32" for d in range(C.DECISIONS)]]):
                raise ValueError(f"{tag}: disabled/canonical run emitted observer output")
        samples_path = case_dir / f"{tag}.device-samples.json"
        samples_path.write_text(json.dumps({"identity": identity, "samples": samples}, sort_keys=True) + "\n")
        return {"tokens":tokens,"sampled_winners":observed_winners,
                "forced_tokens":observed_forced,"rows":rowentries,
                "meta_rows":metarows,"process_attribution":pa,"device_identity":identity,
                "device_samples": f"{case}/{samples_path.name}", "device_samples_sha256": _file_sha(samples_path),
                "observer_meta": f"{case}/{tag}.meta.json" if observer and mode!="disabled" else None,
                "observer_meta_sha256": _file_sha(metapath) if observer and mode!="disabled" else None,
                "response_path": f"{case}/{response_path.name}", "response_sha256": _file_sha(response_path),
                "log":f"{case}/{log_path.name}","log_sha256":_sha(log_path.read_bytes()),
                "excluded_device_residency_mib":excluded,
                "wall_time_s":wall,"mode":mode,"returncode":result.get("returncode")}

    def make_receipt(case, arm, runrec):
        cfg=C.REFERENCE_ARM if arm=="B" else C.CANDIDATE_ARM
        return {"schema":comparator.RUN_SCHEMA,"campaign":C.CAMPAIGN_ID,"comparator_id":C.COMPARATOR_V2_ID,
            "case_id":case,"host":cfg["host"],"arm":arm,"selector":cfg["selector"],"icd":cfg["icd"],
            "cuda_visible_devices":"-1","bdf":runrec["device_identity"]["bdf"],"gpu_uuid":runrec["device_identity"].get("gpu_uuid"),"pci_id":runrec["device_identity"].get("pci_id"),
            "vulkan_device_name":runrec["device_identity"]["vulkan_device_name"],
            "subject_identity":{k:runrec["device_identity"].get(k) for k in (
                "vendor_id","device_id","subsystem_vendor_id","subsystem_device_id",
                "revision","link_width","max_link_width","max_link_speed",
                "driver_in_use","vulkan_device_uuid","gpu_uuid","pci_id")},
            "ngl":ngl,"fixture_ladder_sha256":C.FIXTURE_LADDER_SHA256,
            "prompt_token_ids":fixtures[case]["prompt_token_ids"],"prompt_len":fixtures[case]["rendered_length"],
            "prompt_text_sha256":_sha(fixtures[case]["prompt_text"].encode()),"model_members":model_hashes,
            "llama_cpp_pin":C.LLAMA_CPP_PIN,"patched_source_sha256":C.OBSERVER_PATCHED_SOURCE_SHA256,
            "server_sha256":binary_sha,"build_flags":C.OBSERVER_BUILD_FLAGS,"request_contract":C.REQUEST_CONTRACT,
            "excluded_device_residency_mib":runrec["excluded_device_residency_mib"],
            "device_samples":runrec["device_samples"],"device_samples_sha256":runrec["device_samples_sha256"],
            "observer_meta":runrec["observer_meta"],"observer_meta_sha256":runrec["observer_meta_sha256"],
            "response_path":runrec["response_path"],"response_sha256":runrec["response_sha256"],
            "process_attribution":runrec["process_attribution"],
            "dispatch_authority":authority,"sampled_winners":runrec["sampled_winners"],
            "forced_tokens":runrec["forced_tokens"],"meta_rows":runrec["meta_rows"],"rows":runrec["rows"],
            "server_log":runrec["log"],"server_log_sha256":runrec["log_sha256"],"wall_time_s":runrec["wall_time_s"]}

    for case in C.FIXTURE_CASES:
        C.assert_historical_only(case)
        b=run(case,"B","baseline"); c=run(case,"C","candidate",b["sampled_winners"])
        br=run(case,"B","repeat"); cr=run(case,"C","repeat",b["sampled_winners"])
        db=run(case,"B","disabled"); nb=run(case,"B","canonical")
        dc=run(case,"C","disabled",b["sampled_winners"]); nc=run(case,"C","canonical",b["sampled_winners"])
        rb=make_receipt(case,"B",b); rc=make_receipt(case,"C",c)
        rb2=make_receipt(case,"B",br); rc2=make_receipt(case,"C",cr)
        reader=comparator.custody_row_reader(out)
        pair=comparator.validate_pair(rb,rc,reader,expected_ngl=ngl)
        det_b=comparator.validate_determinism(rb,rb2,reader); det_c=comparator.validate_determinism(rc,rc2,reader)
        inert_b=comparator.validate_inertness(db["tokens"],nb["tokens"]); inert_c=comparator.validate_inertness(dc["tokens"],nc["tokens"])
        for arm, inert, disabled, canonical_run in (("B", inert_b, db, nb), ("C", inert_c, dc, nc)):
            inert.update(case_id=case, arm=arm,
                         disabled_tokens=disabled["tokens"], canonical_tokens=canonical_run["tokens"],
                         disabled_response_path=disabled["response_path"],
                         disabled_response_sha256=disabled["response_sha256"],
                         canonical_response_path=canonical_run["response_path"],
                         canonical_response_sha256=canonical_run["response_sha256"],
                         patched_server_sha256=binary_sha, canonical_server_sha256=canonical_sha)
        if not pair["validated"] or not det_b["deterministic"] or not det_c["deterministic"] or not inert_b["inert"] or not inert_c["inert"]:
            raise ValueError(f"comparator failed for {case}: {pair['problems']} {det_b['problems']} {det_c['problems']} {inert_b['problems']} {inert_c['problems']}")
        for arm, mode, receipt in (("B", "baseline", rb), ("C", "candidate", rc),
                                   ("B", "repeat", rb2), ("C", "repeat", rc2)):
            target = out / case / f"{arm}-{mode}.run.json"
            if target.exists() or target.is_symlink():
                raise ValueError(f"existing run receipt cannot be replaced: {target}")
            raw = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()
            pending = target.with_name(target.name + ".pending")
            with pending.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            pending.replace(target)
        all_pairs.append(pair); all_determinism.extend((det_b,det_c)); all_inertness.extend((inert_b,inert_c))
        for arm, primary in (("B",b),("C",c)):
            timing={"case_id":case,"arm":arm,"wall_s":primary["wall_time_s"]}
            tp=out/case/f"{arm}-measured-wall.json"; tp.write_text(json.dumps(timing,sort_keys=True)+"\n")
            run_path = out / case / (f"{arm}-baseline.run.json" if arm == "B"
                                     else f"{arm}-candidate.run.json")
            timings[arm][case] = {
                "wall_s": primary["wall_time_s"],
                "run_receipt_path": f"{case}/{run_path.name}",
                "run_receipt_sha256": _sha(run_path.read_bytes()),
                "timing_raw_path": f"{case}/{tp.name}",
                "timing_raw_sha256": _sha(tp.read_bytes())}
    selected_sha = _sha(json.dumps(selected_receipt, sort_keys=True,
                                    separators=(",", ":")).encode())
    measured = {"schema": "inferswarm.issue241.measured-wall-times/1",
                "campaign": C.CAMPAIGN_ID, "matched_ngl": ngl,
                "dispatch_authority": authority,
                "selected_receipt_sha256": selected_sha,
                "measurements": timings}
    measured_path = out / "measured-wall-times.json"
    if measured_path.exists() or measured_path.is_symlink():
        raise ValueError("measured wall-time receipt already exists")
    temp = measured_path.with_name(measured_path.name + ".pending")
    with temp.open("xb") as stream:
        stream.write((json.dumps(measured, sort_keys=True, indent=2) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(measured_path)
    result={"schema":comparator.SCHEMA,"campaign":C.CAMPAIGN_ID,"matched_ngl":ngl,
            "cases":list(C.FIXTURE_CASES),"pairs":all_pairs,"determinism":all_determinism,
            "inertness":all_inertness,"measurements":timings,"server_sha256":binary_sha,
            "canonical_server_sha256":canonical_sha,"authority":authority}
    (out/"phase3.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    return result
