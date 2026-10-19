# Strata as an InferSwarm vehicle: feasibility, modularity and dense-model transfer

> **Status: investigation only.** This is evidence in, not a decision out (see
> [README](README.md)). It changes no ADR, Fabric Doctrine section, gate,
> accepted result or execution authority. No hardware was touched and no Strata
> code was built or run to write it. It was written on 2026-10-19 from a static
> reading of [`Zutfen-LLC/Strata`](https://github.com/Zutfen-LLC/Strata) at
> `e88ee39` (a fork of upstream `Niko1221/Strata`, app version 0.2.0-beta,
> engine 0.1.45.3) and of this repository at `5a28198`.

**How numbers are labelled.** The labels are the ones in
[BENCHMARKING.md](../../BENCHMARKING.md): MEASURED, CALCULATED, ESTIMATED and
SPECULATIVE. Two more tags are used here:

- **STRATA-REPORTED**: Strata's maintainers or community measured the number on
  their own hardware. It is MEASURED for that hardware only. For the InferSwarm
  fleet it is at best ESTIMATED. The source file is named each time.
- **EXTERNAL**: prior art from outside both repositories, with a link. A claim
  marked *background* comes from general knowledge and was not re-checked for
  this document.

Code facts are cited as `path:line` in the Strata repository unless a path
starts with `docs/` or `inferswarm/` in this one.

---

## 1. Bottom line

1. **Inside one PC, Strata already does most of what InferSwarm wants to do
   across PCs, but only for one model.** It treats VRAM, RAM, CPU, PCIe and SSD
   as tiers. It keeps all of them busy at the same moment, and it checks several
   tokens per pass. It also has a multi-GPU layer split. The boundary between two
   stages of that split is one small tensor, handed over once per verify window.
   That boundary is the natural seam to stretch over Ethernet.
2. **For Qwen3.8-Flash-Next, Strata probably moves the single-node baseline so
   far that the current distributed result is no longer the interesting
   comparison.** On UD-IQ1_S, InferSwarm's accepted two-host llama.cpp path
   measured 3.925 tok/s, against 4.411 tok/s on one host (MEASURED, #255).
   Strata reports about 59 tok/s on a single RTX 3060 with IQ3_XXS
   (STRATA-REPORTED). With Strata alone, inferswarm01 (125 GiB RAM, two RTX
   3060) is ESTIMATED at tens of tok/s. If a measurement confirms that, one node
   already answers "can we run Flash-Next at all?". For this model the
   capability question then moves to bigger quants, bigger models and nodes
   short on RAM. **Measure this first: it is cheap, and it changes how every
   later step is read.**
3. **A networked layer split ("stage servers") is the most feasible way to adapt
   Strata. Feasibility is high and the effort is moderate.** The hand-off is
   51,216 B per token (CALCULATED from code), about 200 KiB per 4-token window,
   or about 1.75 ms on the measured 1 GbE path. That is a few percent of a
   35-50 ms window (ESTIMATED). Each host keeps the experts, KV cache and
   recurrent state of its own layers, so no state moves during decode. Each host
   also runs its own engine build. A CUDA host and a HIP host can therefore be
   stages of one request. Strata refuses that combination inside one process.
4. **Expert parallelism over Ethernet ("remote experts") works, but latency
   limits it.** It costs 48 synchronous round trips per window, about 13-33 ms
   extra (ESTIMATED). It is worth having only as a tier for a stage that is short
   on RAM, where it beats a SATA SSD. It should not be the main way to
   distribute work.
5. **Modularity is the largest engineering cost.** Strata's kernels are compiled
   for Flash-Next's shapes. The constants are `H=2560`, `FF=640` and `NE=512` in
   `include/strata/kernels/cpu/expert.hpp:36-38`, and more are fixed in
   `src/prefill/prefill.cpp:130`. The second model Strata supports,
   Qwen3.6-35B-A3B, needed its own engine path of about 5,200 lines
   (`src/qwen35`). Some abstraction already exists: `ModelGeometry`,
   `ModelFamily` and the GGUF layout tables. The component recommended here is a
   **model pack**, which is the concrete form of InferSwarm's Model Execution
   Strategy. It has five parts: a descriptor, a tier runtime, block kernels, a
   speculation provider and a partition contract. Port one second model family
   through it before generalizing further.
6. **For dense models, the literal mechanism does not carry over: there are no
   experts to cache. Five principles do carry over.**
   - Put the bytes that are read every token in the fastest memory you can pool.
     For a dense model that means VRAM, pooled across hosts by a pipeline.
   - Cross an expensive link once per window, never once per layer.
   - Verify several tokens per pass.
   - Fill the idle time in the pipeline ("bubbles").
   - Plan in bytes against measured bandwidth.

   With these, a 70B Q4 model spread over the fleet's GPUs is ESTIMATED at
   7-9 tok/s plain and 14-18 tok/s with speculation. On inferswarm01's RAM alone
   it would run at about 1.2 tok/s. That difference is the "usable" bar the
   project has set.
7. **Outside work supports this shape.**
   [prima.cpp](https://arxiv.org/abs/2504.08791) (ICLR 2026) reports running 70B
   models on four home devices. [PipeInfer](https://arxiv.org/abs/2407.11798)
   (SC24) and [SpecPipe](https://arxiv.org/html/2504.04104v2) combine
   speculation with pipelines. [PowerInfer](https://arxiv.org/abs/2312.12456) is
   the dense counterpart of hot and cold experts (EXTERNAL). None of them has
   InferSwarm's discipline for correctness, attribution and planning, which
   remains the project's own contribution.

---

## 2. Primer: three ways to split one model across machines

A model is a stack of layers. Each token passes through every layer in order.
There are three basic ways to share that work between machines. They differ in
what crosses the link, and how often.

| Split | What crosses the link | Crossings per verify window (Flash-Next, 48 layers) | Fit for ordinary 1 GbE |
|---|---|---|---|
| **Layer / pipeline** (machine A runs layers 0-23, B runs 24-47) | One residual vector per token at each stage boundary | 1 per boundary, plus a few bytes back | **Good.** Bandwidth is small and latency is paid once. |
| **Tensor** (every layer is cut in half across A and B) | Partial results, which must be summed (all-reduce) | About 2 per layer, so about 100 | **Poor.** About 100 network latencies per window. |
| **Expert** (A owns half of every layer's experts, B the other half) | The token's activation to the expert's owner, and the result back | 1 round trip per MoE layer, so 48 | **Fair.** Bandwidth is small, but 48 latencies per window. |

Over commodity Ethernet, the cost that dominates is **how many times you wait
for the network per token**, not how many bytes you send. That one fact drives
most of this document.

---

## 3. What Strata is, and how it compares to FreeToken and llama.cpp RPC

### 3.1 Strata in one page

Strata is a C++/CUDA engine, with HIP, SYCL and Metal ports, written for **one
model**: Qwen3.8-Flash-Next. That model has 125 billion parameters in total, of
which 6 billion are active per token. It has 48 layers. Of these, 36 use Gated
DeltaNet and 12 use sparse attention. Every layer has 512 experts and the router
picks 10 per token. Strata's paper, `docs/paper/Strata-Paper.pdf`, explains the
design. It places each kind of byte where it pays:

| Part of the model (Q2_0 file) | Stored | Read per token | Where Strata keeps it |
|---|---:|---:|---|
| Routed experts (48 layers x 512) | 34.0 GB | 0.66 GB (2%) | All in pinned RAM, plus a VRAM cache of the ~4,500 most-used |
| Mixers, attention, shared experts, routers | 1.8 GB | 1.8 GB | VRAM |
| Gated residual (hyper-connections) | 1.3 GB | 1.3 GB | VRAM |
| Output head | 0.44 GB | 0.44 GB | VRAM |
| N-gram embedding table | 28.8 GB | ≤ 23 KB | SSD and the OS page cache |
| MTP draft layer | 0.8 GB | per draft | VRAM |

*Source: paper Table 1 (STRATA-REPORTED).*

The mechanisms InferSwarm cares about are:

- **One layer, three workers at once.** The GPU runs the mixer and the router,
  then writes the 10 chosen expert IDs into pinned host memory (the
  "doorbell"). A CPU thread spins on the doorbell and splits the experts three
  ways. Experts already in the VRAM cache run on the GPU. A share of the misses
  is copied to the GPU by DMA. The rest run on the CPU, in place in RAM. The
  next layer waits for whichever is slower. The whole 48-layer pass is one
  captured CUDA graph per window size (paper section 3.2).
- **Guess, then check.** The model's own MTP layer drafts up to 3 tokens. One
  pass through all 48 layers checks them, giving 2.4-3.2 tokens per pass. The
  output is identical, token for token, to plain greedy decoding (paper
  section 3.3, STRATA-REPORTED).
- **An expert cache that follows the conversation.** A profile recorded on other
  prompts fills the cache at start. Every four rounds, up to 96 experts are
  swapped in. On a 12 GB card the hit rate goes from 0.50 to 0.72 (paper
  finding 4, STRATA-REPORTED).
- **A layer split across GPUs in one PC.** Each card owns a contiguous range of
  layers and the expert cache for those layers. "A token crosses from one card
  to the next once per verify window ... not twice per layer"
  (`docs/MULTI_GPU.md`).
- **Low-RAM file tier.** On a PC whose RAM cannot hold every expert, the experts
  are memory-mapped from the model files. RAM keeps only what the GPU does not
  hold. A 16 GB box with a 12 GB card still runs, more slowly
  (`docs/MODELS.md`, "A big graphics card and little RAM").
- **A balanced engine.** At 4K context with Q2_0, a verify window takes about
  34 ms. About 14.6 ms of that is the GPU's share and 13.4 ms the CPU's share of
  missed experts. No single upgrade doubles the speed (paper Table 5, finding 1,
  STRATA-REPORTED).

Strata's philosophy, in its own words: *"Strata is an inference engine written
for this one model"* (paper abstract). That is the source of both its speed and
the modularity problem discussed in section 6.

### 3.2 Side by side

| | **Strata** | **FreeToken** (the current research vehicle) | **llama.cpp + RPC** (the current operator path) |
|---|---|---|---|
| Language and stack | C++/CUDA, plus HIP, SYCL and Metal; hand-written kernels | Python/PyTorch with custom kernels | C/C++ ggml; broad backend set, including Vulkan |
| Models | Flash-Next (and its fine-tunes) and Qwen3.6-35B-A3B | Several, including Qwen3.6, DeepSeek-V4-Flash and GLM-5.2 ([feasibility study](multi_gpu_moe_feasibility.md)) | Very broad |
| MoE offload | Pinned arena; adaptive VRAM cache; CPU computes misses in place; DMA share of misses | LRU offload cache; hybrid CPU executor; calibrated fetch fraction ("q*") | `-cmoe` / `-ot` put experts on CPU; no adaptive cache |
| Speculation | The model's own MTP layer; prompt lookup; exact greedy | Not studied here | Draft models in `llama-server` |
| Multiple GPUs | Layer split in one PC, same vendor only | Tensor parallel (NCCL) across similar GPUs | Layer split, including across hosts |
| Across hosts | None | Research-internal Coordinator (R4-R5B) | RPC backend, accepted (#255, #268) |
| What it offers InferSwarm | The best single-node mechanism for this model class; a ready in-process stage seam | Accepted evidence lineage and a multi-model engine | Model breadth, Vulkan and AMD reach, an existing operator path |

FreeToken and Strata belong to the same family of ideas: MoE expert offload with
hybrid CPU/GPU execution. Strata is the hand-tuned, single-model end of that
family, and it has the features FreeToken's study listed as missing:
conversation-adaptive caching, overlap with the copy engine, and MTP
verification.

---

## 4. First question: what does one fleet node do with Strata?

InferSwarm's capability claim is *"infeasible under a declared single-resource
envelope, feasible with more resources"* (README, "Two capacity claims"). Which
single-node engine sets the baseline matters, so this comes first.

### 4.1 Fleet against Strata's requirements

Strata's requirements:

- an x86-64 CPU with AVX2 (`docs/INSTALL.md:26` in Strata);
- an NVIDIA card of RTX 20 series or newer, or an AMD card reached through
  **ROCm/HIP**, not Vulkan. Setup builds the HIP backend for gfx1100, gfx1101,
  gfx1200, gfx1201 and gfx1030. Hand builds documented in Strata cover RDNA1
  (gfx1010/1011/1012) and wave64 gfx906 (`docs/AMD_HIP.md` and
  `docs/OLDER_GPUS.md` in Strata). See section 4.3 for the fleet's AMD cards;
- RAM of at least the expert size plus about 10 GB, or the low-RAM mode instead.

| Host | What it has (from [pcie-slot-ledger](../hardware/pcie-slot-ledger.md) and the cited records) | Strata on this host alone |
|---|---|---|
| inferswarm01 | HP Z440. Xeon E5-2683 v3 (14 cores, Haswell, AVX2, no AVX-512). 125 GiB RAM (R8-B freeze). 2x RTX 3060 12 GB on PCIe 3.0 x16. | Every Flash-Next size fits in RAM, including Unsloth's UD-IQ4_XS (about 72 GB). Layer split across both 3060s. **ESTIMATED: tens of tok/s decode.** |
| inferswarm03 | Tiger Lake-H. About 15 GiB RAM. 2x RTX 3060, the second at x4. 2.5 GbE. | Low-RAM mode, with most expert misses read from the SSD. It runs, but slower. **SPECULATIVE: single-digit to low tens of tok/s.** |
| inferswarm04 | Haswell desktop. RTX 3090 24 GB in a PCIe Gen2 slot. RAM not recorded in this repository. | The large VRAM gives a high cache hit rate. The Gen2 link slows prompt reading, which streams experts over PCIe. The result depends on RAM, which is unknown. |
| Valinor | B550 board with a Zen 2-class CPU (inferred from the root-complex name). RX 6800 XT 16 GB (gfx1030). RAM not recorded. | For gfx1030, Strata says the RX 6800 series "builds and runs too, reported by a community machine and not yet validated by the maintainers" (Strata `docs/AMD_HIP.md:7`). |
| inferswarm05 | HP Z440. 125.6 GiB RAM. V340L (gfx900, two 8 GB dies) and a GTX 1060 3 GB. | **Possible, untested.** gfx900 is not on Strata's list, but Strata's wave64 build for gfx906 (Vega 20) is a close fit for this Vega 10 card (section 4.3). The 1060 3 GB is below the 4 GB floor in Strata's card-selection rule. If the gfx900 build works, this host combines the largest RAM pool in the fleet with 16 GB of HBM2. |
| inferswarm02 | Celeron G3900 (2 cores). 16 GiB RAM. V340L on an x1 link. | Weak even if the gfx900 build works. Two CPU cores are too few to compute missed experts at a useful speed (ESTIMATED), and the x1 link starves prompt reading. |

**Why "tens of tok/s" for inferswarm01 (ESTIMATED).** The nearest measured
machine had the same GPU but a much newer CPU. On the Strata maintainers' RTX
3060 box, Strata reports about 59 tok/s with IQ3_XXS and the experts resident in
RAM. That box is a 20-core desktop, named a Core Ultra 7 265 elsewhere in the
same file. The figure is STRATA-REPORTED, from `docs/DETAILS.md:229`, `:1908`
and `:1810` in Strata. A separate community run on an RTX 3060 with a Core
i7-12700 and 64 GB of DDR4-3200 is in Strata's
`bench/results/2026-10-09-community-rtx-3060-0141/`. inferswarm01 differs as
follows:

- Its memory bandwidth is probably lower. Quad-channel DDR4-2133 gives
  68 GB/s theoretical. That CPU platform uses DDR5 (background).
- Each CPU core is much slower. i-quant experts are limited by CPU arithmetic,
  so they run slower on it (paper finding 7).
- Its PCIe 3.0 link is slower than PCIe 4.0.
- Its second 3060 roughly doubles the VRAM cache through the layer split, which
  removes CPU work.

**A closer match: the same CPU class and the same RAM size.** Strata has a
community benchmark (STRATA-REPORTED) from a near-twin of inferswarm01's
platform:

- Hardware: a Xeon E5-2666 v3 (Haswell, 10 cores, AVX2), 125.7 GiB of RAM, and
  one 16 GB Radeon Pro VII (gfx906) on PCIe 3.0 x16.
- Build: Strata's wave64 gfx906 build, on the distribution's ROCm 6.2.
- Result with Flash-Next IQ2_XS at 128K context: **about 24 tok/s decode**,
  steady from 4K to 128K prompts, and **284-350 tok/s prompt reading**.

Source: Strata `bench/results/2026-10-09-community-radeon-pro-vii-16gb/`.
inferswarm01 has 4 more cores and 24 GB of VRAM across two 3060s instead of
16 GB on one card. Its VRAM bandwidth per card is lower (360 GB/s against about
1 TB/s).

The net effect for inferswarm01 is ESTIMATED at roughly **20-35 tok/s decode**.
This has to be measured; section 9, Step 0 covers it.

### 4.2 What this does to InferSwarm's Flash-Next story

Here is the comparison as it can be stated today:

| Path | Quant | Decode |
|---|---|---|
| #255 single host, llama.cpp (inferswarm01) | UD-IQ1_S | 4.411 tok/s (MEASURED) |
| #255 two hosts, llama.cpp RPC (01 + 04) | UD-IQ1_S | 3.925 tok/s (MEASURED) |
| Strata, 1x RTX 3060, 20-core desktop (Core Ultra 7 265) | IQ3_XXS, experts resident | ~59 tok/s (STRATA-REPORTED) |
| Strata, 1x RTX 5070, Ryzen 5 7600, 64 GB | Q2_0 | 94.6 tok/s at 4K (STRATA-REPORTED, paper Table 3) |

Three caveats keep this fair:

- The quants differ. IQ1_S is not one of Strata's supported files.
- #255 and #268 used a deliberately conservative placement (`-ngl 8 -cmoe`), so
  their numbers are not llama.cpp's ceiling either.
- The Strata rows come from other machines.

Even with those caveats, the gap is an order of magnitude. That points to two
conclusions:

- **For Flash-Next, one node running Strata is the baseline to beat.**
  Same-request pooling across hosts would have to beat it, or would have to run
  something that one node cannot run without streaming weights from the SSD.
- **Flash-Next is therefore a weak subject for a whole-model feasibility claim**
  unless the declared envelope excludes weights streamed from the SSD. Strata's
  low-RAM mode makes the model run, slowly, even on 16 GB boxes.

Stronger candidates for the capability claim:

- **Flash-Next Q8_0.** It needs about 136 GB of RAM (Strata `docs/MODELS.md`,
  STRATA-REPORTED), which is more than any single host's 125 GiB. RAM pooled
  across 01 and 05 would hold it. 05 can be a Strata stage only if the untested
  gfx900 build for its V340L works (section 4.3).
- **Larger MoE models.** DeepSeek-V4-Flash has about 137 GB of experts at FP4,
  and GLM-5.2 about 407 GB (CALCULATED and CODE in
  [multi_gpu_moe_feasibility.md](multi_gpu_moe_feasibility.md)).
- **Dense 70B-class models**, covered in section 7.

### 4.3 The fleet's AMD cards: Strata uses ROCm/HIP, not Vulkan

InferSwarm has driven its AMD cards through llama.cpp's Vulkan backend. Strata
does not use Vulkan. It reaches AMD through **ROCm/HIP**: the CUDA engine is
compiled for AMD through a small compatibility layer. Whether a card can be a
Strata stage therefore turns on two questions:

1. Does a ROCm runtime and BLAS library exist for the card's instruction set?
2. Do Strata's kernels compile and run for that instruction set?

It is not about Vulkan.

Strata has two AMD builds:

- **The wave32 backend** (`STRATA_ENABLE_HIP`) covers RDNA1, RDNA2, RDNA3 and
  RDNA4.
- **A separate opt-in wave64 build** (`STRATA_HIP_GFX906`) covers the older
  GCN-style cards. It runs each CUDA warp of 32 lanes as one half of a 64-lane
  AMD wavefront (Strata `docs/AMD_HIP.md`, "gfx906").

| Card | ISA | Strata path | Status in Strata | What it would take | Verdict |
|---|---|---|---|---|---|
| RX 6800 XT (Valinor) | gfx1030, RDNA2, wave32 | Standard HIP backend; `setup.sh --backend hip`; ROCm 7 (system ROCm 7 is the tested route; the `gfx103X-all` wheels are unvalidated) | "Builds and runs too", community-reported, not maintainer-validated | Setup only | **Ready to test** |
| RX 5600 XT 6 GB (named in #281) | gfx1010, RDNA1, wave32 | Standard HIP backend built by hand: `-DCMAKE_HIP_ARCHITECTURES=gfx1010`, on ROCm 7.14's `gfx101X-dgpu` wheels | Listed: "RX 5700 and the 6 GB RX 5600 ... the same build". Measured on an RX 5700 XT (Strata `docs/OLDER_GPUS.md:29-31`) | A hand build | **Runs, but small.** Strata says 6 GB "leaves ~50 expert slots" and expects the RX 5500 XT's range (15.3 tok/s on that 8 GB card, STRATA-REPORTED). More useful as a pipeline stage holding a few layers than on its own. |
| Radeon Pro V340L (inferswarm05; two 8 GB HBM2 dies) | gfx900, Vega 10 (GCN5), wave64 | Not listed. The closest path is the wave64 gfx906 build (Vega 20, the same GCN5 family) compiled with `-DCMAKE_HIP_ARCHITECTURES=gfx900` | **Untested on gfx900** | (a) A ROCm runtime plus rocBLAS/hipBLAS with gfx900 kernels. AMD's current ROCm ships neither gfx900 nor gfx906, and gfx906 users rely on a community ROCm image or an older distribution ROCm. (b) The compile. The one gfx906-only instruction the compatibility layer uses, the 8-bit dot product `sdot4`, already falls back to a portable byte-wise version on other targets (`include/strata/platform/hip_compat/strata_hip.h:233-240` in Strata). That is correct but slower for the i-quant kernels. | **Plausible, SPECULATIVE.** A compile-and-parity test is cheap. The two dies are two 8 GB devices, so a layer split across them is the natural layout, and Strata supports layer splits on AMD. |
| RX 580 8 GB (named in #281) | gfx803, Polaris (GCN4), wave64 | None | Not listed | InferSwarm already showed that the packaged ROCm runtime exposes no device on gfx803 (`NATIVE_BACKEND_UNAVAILABLE`, [vulkan-v0-a](vulkan-v0-a/RESULTS.md)). It would need a community gfx803 ROCm build plus the wave64 build compiled for gfx803. GCN4 also lacks GCN5's packed FP16 math. | **Lowest priority.** Keep it on llama.cpp/Vulkan. |

Strata's gfx906 community results are relevant beyond the V340L question. They
show the wave64 build serving Flash-Next on older AMD hardware attached to
Haswell Xeon hosts:

- one Radeon Pro VII 16 GB: about 24 tok/s with IQ2_XS (section 4.1);
- 2x MI50 16 GB: about 50 tok/s with the Coder IQ1_M, all experts in VRAM
  across both cards (Strata `docs/OLDER_GPUS.md:33`).

Both are STRATA-REPORTED.

Either way, mixing AMD and NVIDIA *within one request* still needs Option A's
networked split (section 5.1). Strata refuses mixed vendors inside one engine
process.

---

## 5. Adapting Strata to InferSwarm: the options

### 5.1 Option A: networked layer split ("stage servers"). **Recommended.**

**Idea.** Run one Strata engine per host. Each engine owns a contiguous range of
layers and does all of Strata's tiering for that range: VRAM cache, CPU misses,
DMA, and its own KV and recurrent state. Today, two stages in one PC pass the
residual through mapped pinned memory. In this option, adjacent stages pass the
same buffer over TCP.

**What already exists.** These are code facts:

- `Verifier::set_stage(layer_begin, layer_end, handoff_in, handoff_out)`
  (`include/strata/core/verify.hpp:166-175`). A stage that does not start at
  layer 0 takes its residual from `handoff_in`. A stage that does not end at the
  last layer writes to `handoff_out` and has no head.
- The hand-off buffers live in host memory. They are "mapped pinned memory,
  portable when the stages are on two devices" (`verify.hpp:171`). The bytes
  already pass through host RAM, which is the right place to hand them to a
  socket.
- The split is designed to be bit-exact: "the split is bit-exact"
  (`verify.hpp:170`). A self-check runs both stages on one card:
  `--layer-split K --split-device 0` (Strata `docs/MULTI_GPU.md`).
- Ready flags let the next stage wait on a published hand-off instead of a host
  sync (`STRATA_SPLIT_OVERLAP`, `verify.hpp:182-189`).
- A batch pipeline across stages exists, in which "stage k can then run group g
  while stage k+1 runs group g-1" (`verify.hpp:228-233`). An overlapped mode for
  a single sequence with drafts also exists (`verify.hpp:264-270`). These are
  in-process forms of the bubble-filling that section 7.3 asks for across hosts.
- Each stage carves session state only for its own layers
  (`include/strata/core/session.hpp:50`).
- An automatic split planner already exists. It prices a decode window, puts the
  faster card last, requires a minimum number of layers per card, and sizes each
  card's share by its room for experts (Strata `docs/MULTI_GPU.md`). This is a
  small, real heterogeneous planner.

**Size of what crosses the link (CALCULATED).** `handoff_floats(g) = hc*n_embd +
n_embd + hc` (`verify.hpp:194`). For Flash-Next that is 4x2560 + 2560 + 4 =
12,804 fp32 values, or **51,216 B per token**. The link time uses about
934 Mb/s, the measured goodput of the 1 GbE path. This is CALCULATED from R4's
747.12 Mb/s limit, which applied an 80% margin; see
[ARCHITECTURE.md](../../ARCHITECTURE.md).

| Tokens in the window | Hand-off | 1 GbE serialization | 2.5 GbE serialization |
|---:|---:|---:|---:|
| 1 | 50 KiB | 0.44 ms | 0.17 ms |
| 4 (typical verify window) | 200 KiB | 1.75 ms | 0.70 ms |
| 8 (`--batch 8` rows) | 400 KiB | 3.51 ms | 1.39 ms |

One extra stage boundary therefore costs about 2-3 ms per window on 1 GbE,
including the small message back and a LAN round trip of about 0.1-0.3 ms
(ESTIMATED). Compared with a 35-50 ms window, that is **about 5-8% per
boundary** (ESTIMATED). The structure also matches R4's accepted finding that
link capacity was not the limit for a contiguous-block boundary
(`R4_1GBE_PRIMITIVE_CAPACITY_VIABLE`).

**What has to be built:**

1. **Transport.** One message per window per boundary:
   `{plan epoch, window id, positions, T x 12,804 fp32}`. One message comes back
   with the accepted count and the next tokens or drafts. The last stage owns
   the head, the MTP draft layer and sampling. Send the bytes unchanged (fp32,
   no conversion) to keep the hand-off exact.
2. **A stage-server mode.** This is an engine started with a layer range, no
   tokenizer, and no head unless it is the last stage. It listens for windows
   and commits.
3. **Commit and rollback across stages.** Rejected drafts must roll back
   recurrent (GDN) state on every stage. In-process, `run` and `commit` already
   continue into the next stage (`verify.hpp:190-191`). Over the network, that
   becomes a commit message sent to every stage.
4. **Per-layer n-gram rows.** The n-gram table is read per token, at no more
   than 23 KB per token (STRATA-REPORTED). Either each stage host keeps its own
   copy on its own SSD, or stage 0 reads the rows and forwards them. Before
   choosing, confirm how the table is sliced by layer.
5. **Epoch and failure semantics.** If a stage is lost, the request fails, and
   InferSwarm's plan epochs decide what to do next. Strata's per-conversation
   snapshots (`src/core/conversation_snapshot.cpp`) are a possible basis for
   resuming at a safe boundary later.
6. **Planner input.** Use Strata's own fit arithmetic
   (`strata_control/gpu_fit.py`, which "keeps its constants equal" to the app's
   `fitOn`) as the strategy's memory model for a candidate layer range.

**Correctness gate that comes almost for free.** inferswarm01 and inferswarm03
each have two RTX 3060 cards (sm_86). Two runs can be compared:

- an **in-process split** on 01's two 3060s;
- a **networked split** from one 3060 on 01 to one on 03, using the same build.

If the transport copies the fp32 hand-off byte for byte, the two should produce
**identical token IDs** (SPECULATIVE; strongly suggested by `verify.hpp:170`).
That is a crisp check for ADR 0010 layer 1 (exact integrity) and layer 3 (exact
tokens), and it needs no tolerance.

**Mixed vendors.** Each host runs its own build: CUDA on 01, 03 and 04, and HIP
on Valinor. The boundary is fp32 in host memory, so the transport does not care
which vendor is on either side. That avoids Strata's in-process rule that it
"never splits a model across NVIDIA and AMD cards". Numerics will differ, so
this case calls for ADR 0010 qualification, not a bitwise check.

**Verdict.** Feasibility: **HIGH**. Effort: **moderate**. A transport, a
stage-server mode and commit messages, all added to code that already has the
in-process version. Main risk (SPECULATIVE): the in-process split may assume
shared pointers, events or a single host thread across stages in more places
than the headers show. Untangling that could be larger than it looks.

### 5.2 Option B: remote experts over the network

**Idea.** A host that is short on RAM sends missed experts' activations to a
host that holds those experts in RAM, and gets the results back. This is
Strata's in-PC "helper GPU" pattern (`docs/SECOND_GPU.md`;
`src/core/remote_experts.cpp`) stretched over Ethernet. Note that in Strata
today, "remote experts" means CUDA1-3 in the same PC, not another host.

**Cost (CALCULATED from H=2560 and the 934 Mb/s path, plus an ESTIMATED 0.15 ms
RTT).** For each MoE layer, the activation goes out in fp16 and the result comes
back in fp32.

| Tokens in window | Per layer | Serialization + RTT | x 48 layers per window |
|---:|---:|---:|---:|
| 1 | 15 KiB | 0.28 ms | 13.5 ms |
| 4 | 60 KiB | 0.68 ms | 32.5 ms |

That is comparable to a whole window's compute. It is still cheaper than a SATA
SSD as the tier behind RAM. A SATA SSD reads 1.3-2.3 MB expert blobs at about
450 MB/s, which is 3-5 ms per expert (CALCULATED from figures STRATA-REPORTED in
`docs/DETAILS.md` and paper finding 8). One network round trip, by contrast,
covers every missed expert of a layer.

**Verdict.** It works, but latency limits it. **Low priority.** Build it only if
Option A leaves a stage that is short on RAM and has no better choice.

### 5.3 Option C: Strata as an opaque engine on each node, under the Coordinator

This needs no engine change. InferSwarm's Coordinator decides which node serves
which model or request: placement and replicas, not pooling within one request.
Strata already offers what such a node agent needs:

- OpenAI- and Anthropic-compatible APIs;
- a management bridge using stdin/stdout JSON (`docs/MANAGEMENT_PROTOCOL.md` in
  Strata);
- Prometheus metrics and telemetry fields;
- elastic VRAM (`POST /v1/vram`).

This does not satisfy same-request pooling. It is still the cheapest way to make
the fleet *useful* soon, and it exercises the management-plane half of the
doctrine.

### 5.4 How Strata maps onto the Fabric Doctrine

| Doctrine concept | Strata counterpart |
|---|---|
| Compute Unit | GPU (CUDA/HIP device); CPU pool (`kernels/cpu/pool`) |
| Memory Resource | VRAM (dense part, expert cache, KV); pinned RAM arena; OS page cache |
| Backing/Source | GGUF shards on SSD; the n-gram table (Strata reads it directly as a tier, which the doctrine leaves as a "future question" for storage) |
| Cache vs. residency | The expert cache is a true **cache**. It can be evicted, refilled and adapted, and correctness never depends on it. The RAM arena is **residency**. |
| Logical State Unit | (layer, expert) pairs; per-layer KV/QSA state; per-layer GDN recurrent state |
| Legal boundary | The contiguous layer range of `set_stage` |
| Link boundary state | The 12,804-float hand-off per token |
| Mutable-state authority | Each stage owns the KV and recurrent state of its own layers. Commit and rollback act on accepted drafts. |
| Planner | `--layer-split auto` (prices a window, puts the faster card last, sizes by room for experts) and `gpu_fit.py` |
| Correctness evidence | Bit-exact split self-check; teacher-forced KL against references; interleaved A/B pairs (Strata `docs/BENCHMARK_PROTOCOL.md`) |

### 5.5 Process fit

- **Follow the ADR 0002 pattern.** Keep `Zutfen-LLC/Strata` `main` tracking
  upstream. Put the stage-server work on an `inferswarm-research` integration
  branch, and preserve evidence branches by SHA. Naming Strata as a second
  runtime vehicle, beside FreeToken and llama.cpp, would take an ADR. This
  document does not decide that.
- **License.** Strata is MIT, as is ggml in `third_party`. InferSwarm is
  Apache-2.0. MIT code can be included. Each model file keeps its own license.
- **Contribution culture.** The two projects are compatible here. Strata
  requires that new features are opt-in, that the default path stays
  byte-identical, and that defaults change only with measurements
  (`AGENTS.md`/`CONTRIBUTING.md` in Strata). That matches InferSwarm's evidence
  discipline. An upstream contribution of a networked split is plausible if it
  is opt-in.

---

## 6. Modularity: a model pack, so the product is not tied to Flash-Next

### 6.1 What is specific to Flash-Next in Strata today

- **Kernel shapes are compile-time constants.** Examples:
  - `H=2560, FF=640, NE=512` (`include/strata/kernels/cpu/expert.hpp:36-38`);
  - `N=2560, HC=4, LR=320, K=10, NE=512` (`src/prefill/prefill.cpp:130`);
  - `H` and `FF` again in `src/core/remote_experts.cpp:19-20` and
    `src/kernels/cuda/s2_expert_grouped.cu:40-41`.

  The guard `compiled_geometry_mismatch` refuses any file whose shapes differ
  from these (`include/strata/core/family_layout.hpp`, header comment). The
  guard is a good thing, because it refuses rather than mis-runs.
- **Layer types and residual style are specific to this model**: 36 GDN layers,
  12 sparse-attention (QSA) layers with an indexer, hyper-connections (`hc=4`),
  and the per-layer n-gram embedding table.
- **The speculation source is specific to this model.** The MTP head is fetched
  from the BF16 checkpoint and uses a reduced draft vocabulary.
- **Expert-usage profiles ship per model** and fill the cache at start.
- **The second model got its own engine path.** `model_family_runs` returns
  true only for `Qwen4Exp` (`include/strata/artifact/model_family.hpp`).
  Qwen3.6-35B-A3B runs on `src/qwen35`: `q36_engine.cu` (3,976 lines),
  `q36ref.cu` (832) and `q36_kernels.cuh` (399, with `NE=256, K=8` fixed at
  `:314`). That model is a close cousin, with the same tokenizer and the same
  3:1 GDN/attention pattern, and it still took a parallel engine.

The parts that are already generic, or nearly so:

- the GGUF reader;
- `ModelGeometry`, filled from metadata (`include/strata/core/geometry.hpp:23`);
- per-family tensor layout tables;
- quant kernels (i-quants, Q8, Q4_K and others; ggml's CPU backend is linked for
  i-quants);
- the CPU pool, the pinned arena and DMA batching;
- the expert-cache bookkeeping;
- the server, API, CLI and app;
- the vision helper (llama.cpp `mtmd`);
- the benchmark protocol and tooling.

Scale, for calibration: `src/` is about 135k lines and `sycl/` about 154k lines
(CALCULATED by line count). Most of the bulk is backend-specific kernels.

### 6.2 The proposed component: a model pack (Model Execution Strategy)

The aim is for Strata's *mechanism* to be generic while each model's *math*
plugs in. The pieces line up with InferSwarm's Model Execution Strategy: the
strategy constrains, and the planner chooses.

```text
Model pack (one per model family)
 ├─ 1. Descriptor      geometry + tensor layout + block graph
 │                     (per layer: mixer kind, MoE params, residual style, state kind)
 │                     read from GGUF metadata; refuses unknown shapes
 ├─ 2. Tier runtime    GENERIC, parameterized by expert shape, count, top-k, quant:
 │                     pinned arena, VRAM expert cache + adaptive swap, doorbell,
 │                     CPU pool split, DMA share, file tier, demand profile capture
 ├─ 3. Block kernels   per family: attention kinds (GQA, MLA, sliding window, sparse),
 │                     recurrent mixers (GDN, Mamba), norms, RoPE variants, routers
 │                     (top-k, grouped top-k), residual (plain, hyper-connections)
 ├─ 4. Speculation     MTP head if the model has one; else a draft model; else
 │     provider        prompt-lookup/suffix drafts. Same exact verify window either way
 └─ 5. Partition       legal cut points (layer boundaries), hand-off tensor shape and
       contract        dtype, per-stage state ownership, commit/rollback messages,
                       memory model per candidate range (for the InferSwarm planner)
```

Notes on each part:

- **Part 2 is where Strata's value lives, and it is the most portable.** The
  expert cache, the arena, the doorbell and the CPU/GPU/DMA split are
  bookkeeping over `(layer, expert)` IDs and byte sizes. Paper finding 8 says to
  size the cache in bytes, not slots, and Strata already does. Turning
  `H/FF/NE/K` from `constexpr` into runtime values here is mostly mechanical.
- **Part 3 is where the hard work is.** Strata's speed comes from kernels tuned
  to one shape. There are two workable routes:
  1. Template-instantiate a small table of supported `(H, FF, quant)` shapes.
  2. Fall back to ggml kernels for shapes without a tuned kernel. These are
     slower but correct, and Strata already links ggml's CPU backend.

  Do 2 first, then 1 for the families that earn it.
- **Part 5 is what InferSwarm adds.** Strata has the in-process version
  (section 5.1), and the pack makes it explicit and model-independent.

### 6.3 Which MoE models suit the Strata pattern

The pattern pays when four things hold:

1. the always-read dense part fits on one GPU with room to spare;
2. the experts are many and small, with top-k much smaller than the expert
   count, so routing is skewed and a cache can exploit it;
3. the expert bytes per token are low enough for CPU RAM bandwidth;
4. there is a draft source.

*Model figures marked "background" are from general knowledge as of mid-2026.
Confirm them from each model's `config.json` before planning.*

| Model family | Total / active | Experts, top-k | What it adds to the engine | Fleet relevance |
|---|---|---|---|---|
| Qwen3.8-Flash-Next | 125B / 6B (paper) | 512, top-10 | (supported) | One node (section 4) |
| Qwen3.6-35B-A3B | 35B / 3B (Strata docs) | 256, top-8 | (supported, separate path) | Fits on one 3090 |
| Qwen3-235B-A22B (background) | 235B / 22B | 128, top-8 | GQA attention, plain residual; no MTP, so it needs a draft model | Fits 125 GiB at about 3-4 bit; a single-node stretch |
| gpt-oss-120b (background) | ~117B / ~5B | 128, top-4 | Sliding/full attention, attention sinks, native MXFP4 | Fits one node; a good second family to port |
| GLM-4.5-Air (background) | ~106B / ~12B | 128, top-8 | GQA; MTP layer in some releases | Fits one node |
| DeepSeek-V4-Flash | ~285B (CALC in [FreeToken study](multi_gpu_moe_feasibility.md)) | (see study) | MLA attention, DS-FP4 experts | **137 GB of experts**: needs pooled RAM, so a genuine InferSwarm target |
| GLM-5.2 | (see study) | (see study) | DSA attention | **~407 GB of experts** (CODE, from the study): multi-node only |
| Mixtral / Llama 4 Scout (background) | 47B / 13B; 109B / 17B | 8 top-2; 16 top-1 | A few very large experts | Weak fit: caching is coarse and there is little skew to exploit |

**Recommended sequence.**

1. Make the tier runtime's expert shape runtime-parameterized.
2. Port **one** family with a *different* attention type, such as gpt-oss-120b
   or GLM-4.5-Air, through the descriptor and the ggml-fallback kernels. Measure
   it against llama.cpp on the same box. This is the proving case for the
   seam.
3. Only then extract the partition contract and run a networked stage with the
   second family.

**An alternative to weigh honestly.** Leave long-tail models to llama.cpp as a
generic engine. Apply Strata-style specialization only to the families that
justify it, which is what Strata itself does by linking ggml for i-quants. In
InferSwarm terms, a "Strata strategy" and a "llama.cpp strategy" sit behind the
same planner. Keep one engine per request pipeline at first. Mixing engines
inside one request is possible in principle, but tensor layouts and numerics
differ (SPECULATIVE, high risk).

---

## 7. Dense models in a distributed setting: what transfers

### 7.1 Why the literal mechanism does not carry over

In a dense model, every weight is read for every token. Nothing is routed, so
there is no "hot 2%" to cache. The core of Strata's speed, an expert cache with
the CPU computing misses in place, has no direct counterpart.

### 7.2 The physics

Decode time per token is roughly the bytes read per token divided by the
bandwidth of the memory they sit in, plus the latency of every hop between
places. Nominal bandwidths (vendor specification, ESTIMATED as upper bounds):

| Where the bytes live | Bandwidth |
|---|---:|
| RTX 3090 VRAM | 936 GB/s |
| RX 6800 XT VRAM | 512 GB/s |
| RTX 3060 VRAM | 360 GB/s |
| Quad-channel DDR4-2133 (inferswarm01/05) | 68 GB/s theoretical |
| PCIe 3.0 x16 | ~16 GB/s |
| 1 GbE (measured path) | ~0.117 GB/s |

A 70B model at Q4 is about 42 GB (ESTIMATED). On inferswarm01's RAM alone that
gives **about 1.2 tok/s** (CALCULATED at an effective 50 GB/s). With the same
bytes spread across the fleet's VRAM, the per-token weight reads add up as
follows (CALCULATED):

- 18 GB on the 3090: about 19 ms;
- 6 GB on each of four 3060s: about 17 ms each.

That is about 86 ms in total, an **ideal ceiling of about 11.6 tok/s**. At
60-75% kernel efficiency, plus three Ethernet hops of about 0.5 ms each, the
estimate is **7-9 tok/s**. Two hosts (01's 3060s plus the 3090 on 04, 48 GB of
VRAM) give about 8 tok/s, if KV and buffers fit (ESTIMATED).

A dense pipeline over 1 GbE has little to send: a 70B model with hidden size
8192 hands off 16 KiB per token in fp16, or 0.14 ms (CALCULATED). The cost that
dominates is the stages running one after another. It is not the network.

### 7.3 The principles that transfer, and how

1. **Keep the bytes read every token in the fastest memory you can pool.** For a
   dense model, every byte is read every token. "Pool VRAM" then means a
   pipeline whose layer ranges are sized to each card's capacity and bandwidth.
   The slowest stage sets the pace. That makes Strata's lesson from its own
   split directly applicable: "the 3060's 360 GB/s of memory bandwidth against
   the 4060 Ti's 288 counts for more than its SMs" (Strata `docs/MULTI_GPU.md`,
   #2644). Spilling layers to a node's RAM is legal, but that stage becomes the
   bottleneck.
2. **Cross an expensive link once per window, never once per layer.** Use a
   pipeline (layer split) across hosts. Use tensor parallelism only inside a
   host, and only when it is measured to pay. Strata's paper finding 5 points
   the same way: splitting a window more finely "did not pay".
3. **Verify several tokens per pass. This is the most important principle for
   distributed dense inference.** Each pass pays the weight reads *and* every
   network hop. Accepting 2-3 tokens per pass divides both by 2-3. Draft sources
   are a small same-tokenizer model on the head node, an EAGLE/MTP-style head,
   or prompt lookup, which Strata finds worth 6-11% on code edits. With 2.5
   tokens per pass at about 1.2x the cost of a pass, the 70B estimate goes from
   7-9 to **about 14-18 tok/s** (ESTIMATED). Prior art:
   [PipeInfer](https://arxiv.org/abs/2407.11798) runs asynchronous speculation
   through a pipeline and reports up to 2.15x over standard speculative
   inference; [SpecPipe](https://arxiv.org/html/2504.04104v2) does similar work
   (EXTERNAL). Strata's exactness discipline carries over unchanged: greedy
   output with drafts must equal greedy output without them.
4. **Fill pipeline bubbles.** With a single request, only one stage works at a
   time. There are two ways to fill the idle time:
   - run several requests at once (batch slots), so that stage k runs group g
     while stage k+1 runs group g-1, which is Strata's in-process batch
     pipeline;
   - run speculative windows into the pipeline ahead of time, as PipeInfer
     does.

   Under the doctrine's "useful service" ranking, total throughput across
   requests is a legitimate objective even when single-stream speed is flat.
5. **Plan in bytes, measure the hardware, refuse instead of mis-running.**
   Strata's habits match the doctrine directly:
   - sizing by bytes;
   - putting the fastest card last, because it runs the head and the verify;
   - requiring a minimum number of layers per card;
   - asking for a split sweep once on unequal pairs;
   - interleaved A/B measurement;
   - the `compiled_geometry_mismatch` refusal.

   prima.cpp's Halda scheduler is a worked, published heterogeneous layer
   assigner that solves the same problem for home clusters
   ([arXiv 2504.08791](https://arxiv.org/abs/2504.08791), EXTERNAL).

Two more principles are worth a research lane but should not come first:

6. **Hot/cold within dense layers (activation sparsity).**
   [PowerInfer](https://arxiv.org/abs/2312.12456) splits dense models into hot
   neurons, kept on the GPU, and cold neurons, computed on the CPU. It reports up
   to 11.69x over llama.cpp on a single RTX 4090, mostly on models with ReLU
   activations (EXTERNAL). Modern SwiGLU models are much less sparse by nature.
   Training-free activation sparsification such as TEAL (background) recovers
   some sparsity at a measurable quality cost. That cost would need
   qualification under ADR 0010 and ADR 0012.
7. **Disk as a planned tier with prefetch.** Strata's file tier and prima.cpp's
   mmap prefetch both treat storage as a tier read ahead of use. The doctrine
   currently limits storage to verified backing. Using it as a weight tier is a
   "future question", and these two systems are the evidence that would inform
   it.

### 7.4 Which engine to use for dense work

Strata has no dense path. For dense models the practical vehicle is
**llama.cpp**: it already layer-splits dense models across hosts over RPC, has
draft-model speculation, and reaches AMD through Vulkan. The #268 operator path
is the natural place to add the transferable pieces:

- placement sized by measured bandwidth;
- a draft model on the head node;
- multiple slots to fill bubbles.

prima.cpp, which is built on llama.cpp, is worth a bounded evaluation as a
second candidate. Its authors report 674 ms/token for a 70B model on four
consumer devices, 26 tok/s for a 32B model with speculation, and 5-17x lower
time per token than llama.cpp, exo and dllama. These are the authors' own
numbers, and no independent reproduction was found (EXTERNAL).

---

## 8. The landscape at a glance

| System | What it is | What to borrow | Role for InferSwarm |
|---|---|---|---|
| **Strata** | Single-model MoE engine: VRAM/RAM/CPU/SSD tiers, MTP verification | Tier runtime, doorbell, adaptive cache, in-process stage seam, measurement discipline | MoE stage server (Option A); single-node baseline |
| **FreeToken** | PyTorch multi-model engine with MoE offload | Accepted R-series lineage; multi-model breadth | Existing research vehicle; evidence continuity |
| **llama.cpp RPC** | General engine with remote backends | Model breadth, Vulkan, existing operator path | Dense and long-tail vehicle |
| **prima.cpp** (EXTERNAL, verified) | llama.cpp-based home-cluster engine; pipelined-ring parallelism with disk prefetch; Halda scheduler | Heterogeneous layer assignment; prefetch design | Candidate for a bounded evaluation on dense 30-70B |
| **PipeInfer / SpecPipe** (EXTERNAL, verified) | Speculation through pipelines | Asynchronous speculation and early cancellation | Design input for principle 3 |
| **PowerInfer** (EXTERNAL, verified) | Hot/cold neuron split, GPU plus CPU | The dense counterpart of expert caching | Research lane (principle 6) |
| **KTransformers** (background; cited by Strata) | CPU/GPU hybrid MoE | Expert placement heuristics | Reference |
| **exo, distributed-llama** (background) | Heterogeneous device clusters (exo: pipeline by memory share; dllama: tensor parallel on CPUs) | Ease of joining devices; dllama's evidence that tensor parallelism is latency-sensitive | References and baselines |
| **Petals** (background) | Pipeline over the internet with volunteer servers | Fault-tolerant stage routing, "usable not fast" serving | Reference for elasticity and failure semantics |

---

## 9. Recommended path: feasibility first

Run Steps 0-2 as bounded engineering observations under the experiment-first
review standard in [AGENTS.md](../../AGENTS.md), not as acceptance campaigns.
Promote a result to accepted evidence once it is worth defending.

| Step | Question | Hardware | Success looks like | Relative cost |
|---|---|---|---|---|
| **0. Single-node baseline** | What does Strata alone do on the fleet? | 01 (2x3060, 125 GiB); 04 (3090); 03 (low-RAM mode) | Decode and prompt tok/s per node and quant, with the cache hit rate, recorded as MEASURED for this fleet | Small (install and benchmark; Strata ships `BENCH`) |
| **1. Networked split, same GPU model** | Does Option A work, and is it exact? | 01 → 03 (3060 → 3060), then 01 → 04 | Same token IDs as the in-process split on 01; boundary overhead per window MEASURED | Moderate (transport, stage mode, commit messages in a fork branch) |
| **2. Capacity that one node lacks** | Can stages hold what no single host can without SSD streaming? | 03 + 04 (+ Valinor). Small-RAM hosts whose combined VRAM may hold a whole Q2_0 model | The model GPU-resident across hosts. Compare with Step 0's low-RAM single-node result on the same hosts. **This is GPU-residency expansion, not whole-model feasibility, unless the envelope excludes SSD streaming** | Small once Step 1 exists |
| **3. Mixed vendor** | Can a HIP stage join CUDA stages? Can the V340L be one? | Valinor RX 6800 XT (gfx1030) with an NVIDIA host. Separately, a compile-and-parity test of the wave64 build for gfx900 on inferswarm05's V340L | ADR 0010 qualification passes on a frozen subject. The gfx900 build passes Strata's parity tests on the card | Moderate (qualification work); the gfx900 test is small but needs a ROCm with gfx900 libraries |
| **4. Model pack** | Is the product separable from Flash-Next? | Any node | A second MoE family through the descriptor and tier runtime; parity with llama.cpp on the same box | Large |
| **Parallel track: dense** | Is distributed dense usable? | 01 + 04 (48 GB VRAM), then add 03 | 70B Q4 MEASURED at "usable" with speculation and bandwidth-sized placement through the llama.cpp operator path | Moderate |

**The one decision this document asks for:** whether to run Step 0. It takes no
new architecture, it uses hardware already in hand, and its result decides how
much weight Flash-Next should carry in InferSwarm's capability claim.

---

## 10. Risks and open questions

- **Upstream pace.** Every commit in the fork's (shallow) history is by the
  upstream maintainer, and the engine changes often. Keep the stage seam narrow and opt-in, and
  propose it upstream, to avoid a deep fork. That is the ADR 0002 lesson.
- **Coupling inside the in-process split.** The split may share more state than
  the headers show: events, pointers, a single host thread (SPECULATIVE). This
  is the main schedule risk for Option A.
- **CPUs.** Strata's fastest CPU kernel (Q2_0) uses AVX-512 VNNI. inferswarm01
  and 05 are Haswell with AVX2 only, so the CPU half of each window will be
  slower. Tiger Lake-H (03) has AVX-512 (background), but only about 15 GiB of
  RAM.
- **AMD coverage depends on ROCm, not Vulkan** (section 4.3). Card by card:
  - The RX 6800 XT (gfx1030) is supported through setup, though not
    maintainer-validated.
  - The RX 5600 XT (gfx1010) runs from a documented hand build, but its 6 GB
    leaves little room for experts.
  - The V340L (gfx900) needs an untested compile of the wave64 build and a ROCm
    with gfx900 libraries. AMD's current releases do not ship these.
  - The RX 580 (gfx803) has no ROCm runtime on the fleet's packaged stack. It
    stays a llama.cpp/Vulkan participant.
- **inferswarm05's RAM** is the largest pool in the fleet. Whether that host can
  be a Strata stage depends on the gfx900 build. Without it, the host would need
  a CPU-only stage mode, which Strata does not have (SPECULATIVE effort), or a
  supported GPU.
- **Links.** inferswarm04's GPU sits in a PCIe Gen2 slot, which slows Strata's
  prompt path because experts stream over PCIe. 1 GbE latency jitter matters
  more than its bandwidth.
- **Sampling.** Strata's exactness guarantees are for greedy decoding. Sampled
  decoding has opt-in rejection sampling that is exact in distribution, not
  bitwise (Strata `docs/DETAILS.md:1445`). ADR 0010's semantic profiles would
  need to cover this.
- **Measurement and attribution.** InferSwarm's observer and attribution
  machinery would need hooks in Strata. Strata's telemetry fields and Prometheus
  output (`docs/TERMINAL_TELEMETRY_FIELDS.md` in Strata) are the starting point.
- **What this document did not do.** It ran no code and touched no hardware. It
  did not read FreeToken's source; the FreeToken facts come from
  [multi_gpu_moe_feasibility.md](multi_gpu_moe_feasibility.md). It did not
  measure LAN round-trip time. Every fleet-performance number above is ESTIMATED
  or SPECULATIVE until Step 0 and Step 1 run.

---

## Appendix: source pointers

Strata (`Zutfen-LLC/Strata` at `e88ee39`):

- Design and measurements: `docs/paper/Strata-Paper.pdf`, `docs/HOW_IT_WORKS.md`,
  `docs/DETAILS.md` ("How it works", line 2165 onward).
- Layer split: `docs/MULTI_GPU.md`; `include/strata/core/verify.hpp:166-194`,
  `:228-270`; `include/strata/core/session.hpp:50`.
- Secondary-GPU experts: `docs/SECOND_GPU.md`; `src/core/remote_experts.cpp`,
  `src/core/peer_experts.cpp`.
- Model coupling: `include/strata/kernels/cpu/expert.hpp:36-38`;
  `src/prefill/prefill.cpp:130`; `include/strata/core/geometry.hpp:23-63`;
  `include/strata/core/family_layout.hpp`;
  `include/strata/artifact/model_family.hpp`; `src/qwen35/`.
- Low-RAM mode and file tier: `docs/MODELS.md` ("Will it fit?"),
  `docs/DETAILS.md:284-320`.
- Fit arithmetic: `strata_control/gpu_fit.py`.

InferSwarm (this repository at `5a28198`):

- Fleet: [docs/hardware/pcie-slot-ledger.md](../hardware/pcie-slot-ledger.md);
  [R8-B topology freeze](qwen38-flash-next-r8-b/TOPOLOGY-FREEZE.md) (RAM on
  inferswarm01).
- Accepted distributed results: README "What the research has established"
  (#255, #268); [two-host MVP report](../implementation/two-host-mvp-255/product-report.md).
- FreeToken internals: [multi_gpu_moe_feasibility.md](multi_gpu_moe_feasibility.md).
- Doctrine: [Fabric Doctrine](../architecture/fabric-doctrine.md), ADR 0002,
  0003, 0007, 0008 and 0010.

External (checked 2026-10-19):

- prima.cpp: <https://arxiv.org/abs/2504.08791> (ICLR 2026:
  <https://iclr.cc/virtual/2026/poster/10008093>)
- PipeInfer: <https://arxiv.org/abs/2407.11798>
- SpecPipe: <https://arxiv.org/html/2504.04104v2>
- PowerInfer: <https://arxiv.org/abs/2312.12456>
