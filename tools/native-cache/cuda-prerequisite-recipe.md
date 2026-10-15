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
   If the deployed CPU client matches its accepted row, CUDA qualification
   still requires a maintainer-reviewed `remote-cuda` row in a separate change.
   If the CPU receipts differ, a separate maintainer decision and reviewed
   follow-up must establish the deployable CPU identities while preserving the
   historical accepted pair; adding only a CUDA row is insufficient. This PR
   adds no mechanism for selecting another CPU pair. Until that decision is
   implemented, ordinary runtime admission and Step B remain blocked. Receipts
   themselves grant nothing; Step A ends with their review, not qualification.

## Step B — after identities are accepted: selective backing + GPU load/readback

Only after the complete deployed CPU/CUDA pair's identities are reviewed in,
and Step B receives its own physical dispatch. Compact whole-tensor fixture
first; this is a selective-loading/cache test, not an inference claim, and the
full-model baseline's CPU layer assignment must NOT be reused on 03 without a
separately proven fit.

1. Freeze the fixture: a small set of immutable whole-tensor ranges from the
   pinned Q8 subject, each a single offset-zero whole-tensor SET (the native
   guard refuses partial/view/duplicate boundaries), sized so assigned weights
   + metadata + scratch fit 03's ~15 GiB host RAM and 12 GiB VRAM with
   measured headroom (record measured free VRAM before load; target well
   under, e.g. ≤8 GiB resident). No expert slicing beyond whole tensors.
2. 05 keeps the complete source model and serves as coordinator; 03 acquires
   only assigned immutable bytes onto its mounted `/srv/models` SSD through
   the existing #317 preparation adapter with an explicit DiskBudget.
3. Measure three byte counts separately:
   - acquisition bytes (preparation, cold);
   - warm-restart weight-upload bytes (worker restart reusing local backing —
     unchanged weights must be 0; an upload-observer event is an attempted
     send before acknowledgment, not proof of completion — count verified
     reuse, not events);
   - completion readback bytes (verification GET), also separately from
     control/metadata traffic.
4. Record actual GPU identity, host memory peak and VRAM residency at load
   (timestamped `nvidia-smi --query-compute-apps` mid-phase, not post-hoc).
   Tensor readback proves loading integrity only — it does not establish
   inference correctness or physical GPU computation; state that in the
   record. Sampled util ≤ a few percent is not idle evidence in either
   direction.
5. Stop conditions: integrity failure, OOM/swap, headroom breach, identity
   drift, unexpected placement. Preserve a failed result; never retry it into
   a PASS.

No model downloads beyond declared assigned bytes, no inference request, no
service interruption, no credential/policy change. #311/#313/#315/#300 stay
open; maintainer review of Step A's identities is the stopping point of this
recipe's first dispatch.
