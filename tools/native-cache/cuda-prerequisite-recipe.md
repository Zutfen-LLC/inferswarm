# Bounded CUDA prerequisite recipe (two steps, #311/#313/#315)

Recipe for later explicit physical dispatch — not execution authority. Targets
inferswarm05 as full-source CPU coordinator and inferswarm03 GPU0 (x16 link)
as the single-CUDA worker; GPU1 (x4) stays outside this experiment and no
hardware move is needed. Every step below is read-only or owned-build only
until its own dispatch is accepted.

## Step A — builds and no-model discovery (record identities for review)

Access prerequisite for the operator: existing SSH aliases for inferswarm05
and inferswarm03 plus the retained pinned source archive
(sha256 `03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723`,
llama.cpp `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`). No new credentials,
persistent access or security-policy changes; flag any gap to the maintainer
instead of working around it.

1. Read-only host inventory first (no service interruption): RAM headroom,
   GPU identity/health via `nvidia-smi --query-gpu`, driver/toolkit versions,
   PCIe `LnkSta` width for GPU0 (x16 expected; idle-downgraded speed is not
   link width), `/srv/models` mount and free space, current listeners by
   owning process. Prior x4-link and occupied-RPC observations are historical
   and must be re-verified, not assumed.
2. Coordinator (05): run the CPU recipe unchanged into a fresh owned
   directory — `operator-build.py` builds `llama-server` + `ggml-rpc-server`
   CPU/RPC in minutes. Record `build.json` plus both
   `*.build-manifest.json`, the absolute source/output prefix, resolved C/C++
   compiler paths and complete version output, CMake version and build logs.
   These are **candidate CPU receipts**, not a promise of identical hashes:
   the unchanged composer embeds absolute source paths into CMake input before
   hashing it, and the accepted rows record `c++ (GCC) 16.2.1 20260810`.
   A fresh path or different toolchain can therefore change the manifest even
   with the same verified archive and overlay.
   Compare both manifests with the accepted CPU rows and retain every mismatch
   for separate maintainer review; do not retry into a match, edit the bound
   CPU recipe, overwrite accepted rows, or authorize a candidate from its receipt.
3. Worker (03): run the additive CUDA recipe into a fresh owned directory:
   `python3 tools/native-cache/operator-build-cuda.py --archive <pin.tar.gz>
   --output /srv/models-owned/cuda-worker-build --arch 86` (RTX 3060 is
   sm_86). Budget 45-60 minutes for the nvcc phase at two jobs; do not
   prescribe a 30-minute window. The build never touches the GPU; bind
   device-facing checks to `CUDA_VISIBLE_DEVICES=<expected UUID>` with a
   separate `nvidia-smi` UUID/PCI snapshot when discovery runs.
4. No-model discovery only: verify the worker binary starts and enumerates
   exactly GPU0 (`--list-devices` or equivalent), refuses nothing unexpected,
   and that the manifest closure contains `libggml-cuda.a`. No model weights,
   no inference, no cache writes.
5. Post the CPU build receipts and comparison + the candidate
   `cuda-worker-receipt.json` (executable/library closure hashes, compiler,
   nvcc, arch, resolved real driver path+sha) for maintainer review. STOP.
   The follow-up [explicit build pair](step-a-build-pair/README.md) preserves
   these historical instructions and their candidate/acceptance distinction.
   It selects both uploaded Step A manifests together; adding a CUDA worker
   while silently replacing the historical CPU client is insufficient.
   Review of that coding change does not dispatch Step B.

## Step B — selective backing and GPU readback

Future separately authorized physical dispatch only. Select
`strategy_options.build_pair: "step-a-cpu05-cuda03"`, the selective
`source_contract`, enabled cache and per-role observer paths together.
The historical CPU pair remains the default. Keep the one-GPU client-mediated
route; server-local copy remains refused. Ordinary full-Qwen one-GPU planning
still includes a remote CPU layer partition and unresolved observer/fit gates:
**do not run that full-model placement on the small worker**. This compact
fixture uses the existing preparation/native-loader/readback infrastructure,
without model construction or a performance/inference request.

1. **Bind the actual deployment.** Coordinator inferswarm05 has approximately
   125 GiB RAM and the full pinned source already on SSD; keep its complete
   source, GGUF/header authentication, reads/hashes and largest-tensor loader
   work explicit. Worker inferswarm03 has approximately 15 GiB RAM. Reconfirm
   UUID `GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176` at PCI `01:00.0` and the
   x16 link using `nvidia-smi` UUID/PCI and `lspci` negotiated-width snapshots.
   Set worker `CUDA_VISIBLE_DEVICES` to that UUID, independently verify the
   resulting native selector and bind the owned PID to that physical GPU.
   The second x4 GPU stays unused. Recheck health/listeners/headroom; do not
   interrupt another service. Use existing source/build/owned-process checks
   to compare both deployed manifests in full, actual executable hashes and
   dependency/static-library hashes. Capture resolved dependency/link evidence,
   exact argv/environment and masked discovery at execution. If a compact
   `is311-loader` helper is used, also bind its own host-retained executable
   and closure: its bytes are not identified by the llama-server manifest.
   Missing proof is a STOP, not a reason to rebuild historical binaries.
2. **Freeze a compact whole-tensor assignment.** Choose a small set of complete
   immutable tensors from the pinned Q8 subject on 05 (including a Q8 tensor),
   each greater than 10 MiB for the unchanged native hash-hit threshold. Record
   names, member offsets, lengths, types/shapes, SHA-256/FNV and exact ownership;
   use one offset-zero whole-tensor SET per destination. No expert slicing,
   partial/view/duplicate uploads or small-tensor zero-payload claim. Freeze a
   10-minute execution timeout and numerical criterion **byte-exact readback**.
   Assigned destination plus metadata, backend overhead, verification GET and
   bounded staging must fit **<=10 GiB owned host RAM**, leave **>=4 GiB host
   headroom**, and fit **measured free VRAM minus >=512 MiB reserve** throughout.
   Include existing GET/loader whole-tensor buffers when sizing the fixture;
   the 1 MiB cache scratch alone is not the peak. Shrink the planned fixture
   before dispatch if these bounds cannot be established; never change it
   after a failed run to convert that result into PASS.
3. **Prepare assigned SSD backing with the worker stopped.** Use
   `prepare_q8_participant` with the existing #99/#101 authority, verified
   inventory, epoch/missing-only delta and #317 streaming cache view. Only the
   assigned immutable ranges and small exact metadata go to 03's owned SSD
   directory; no complete source members are acquired there. Freeze
   `DiskBudget(limit_bytes,min_free_bytes,reserve_bytes)` including existing
   history and the required `D + L + 16384*(N+1)` native repair reserve.
   Source requests remain <=64 KiB, verification/native scratch <=1 MiB.
   Record cold acquisition separately from metadata/control and GET traffic.
4. **Load once, then restart once with unchanged backing.** Use the existing
   owned lifecycle, assigned upload guards and compact pinned-loader fixture,
   selecting only the masked CUDA device. Observe actual PID/UUID and VRAM
   residency during load, plus timestamped cgroup/process host memory, free
   headroom, swap and cleanup. Require exact readback of every declared tensor.
   Reconstruct Node/preparation, revalidate the same durable objects and restart
   the owned worker: require **zero missing-weight acquisition payload and zero
   unchanged weight SET payload**, with exact readback again. Count verified
   acknowledgements/cache consumption; upload-attempt events alone prove neither.
   Report source hashing/local reads on 05, acquisition, weight SET, metadata,
   control and verification GET separately. Readback proves transfer/loading
   integrity, not GPU arithmetic or inference correctness.
5. **Stop and preserve.** On timeout, integrity failure, OOM, swap growth,
   <4 GiB host headroom or <512 MiB VRAM reserve, >10 GiB owned host
   peak, physical/build/assignment drift, unexpected placement or incomplete
   observer/cleanup evidence, stop owned processes and retain originals/logs
   and the failed result. No retry-until-PASS, deletion of old evidence, full
   model CPU partition on 03, second GPU, new performance run, service
   interruption, credentials or policy change. The Step A sampling/link gaps
   are stated in the [provenance note](step-a-build-pair/README.md), never filled
   with assumptions. #311/#313/#315/#300 stay open; this coding PR stops for
   maintainer review and dispatches neither hardware nor Final CPU Validation.
