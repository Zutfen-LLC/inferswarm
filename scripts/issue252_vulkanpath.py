#!/usr/bin/env python3
"""Issue 252 Phase-0: source-only, fail-closed Vulkan execution-path ledger.

No Vulkan import, model load, network access, or GPU execution. All cited line
numbers are resolved from the authenticated pinned source at derivation time.
A cited `what` is an exact substring of its cited source line, not a paraphrase.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess


# TODO-252: keep these local until sibling issue252_constants.py is landed.
PIN_HEAD = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
PIN_TREE = "950999fe62b7fe55f44ab5b7394e3c8542f37f12"
DEFAULT_SOURCE = Path("/home/zutfen/llama.cpp-252")
OUTPUT_REL = Path("docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism/evidence/phase0/vulkan-path.json")
REF_REL = Path("docs/investigations/qwen38-flash-next-r8-i3b-ref-runtime-boundary/evidence/phase0/phase0-analysis.json")
REF_METHODOLOGY = Path("docs/investigations/qwen38-flash-next-r8-i3b-ref-runtime-boundary/METHODOLOGY.md")
VK = "ggml/src/ggml-vulkan/ggml-vulkan.cpp"
SHADER = "ggml/src/ggml-vulkan/vulkan-shaders/mul_mat_vec_base.glsl"


def verify_source(source: Path, expected_head: str = PIN_HEAD, expected_tree: str = PIN_TREE) -> dict:
    """Authenticate BOTH commit and tree before reading source, including overrides."""
    source = Path(source)
    try:
        actual = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD", "HEAD^{tree}"],
            text=True, stderr=subprocess.PIPE,
        ).splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"source is not a readable git tree: {source}") from exc
    if actual != [expected_head, expected_tree]:
        raise ValueError(f"source identity mismatch: HEAD/tree {actual!r}")
    # HEAD^{tree} alone says nothing about unstaged/staged edits to source.
    try:
        clean = subprocess.run(["git", "-C", str(source), "diff", "--quiet", "HEAD", "--"], check=False, stderr=subprocess.PIPE)
    except OSError as exc:
        raise ValueError("unable to inspect pinned tree modifications") from exc
    if clean.returncode != 0:
        raise ValueError("pinned source has tracked modifications")
    return {"head": actual[0], "tree": actual[1]}


class Source:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.lines: dict[str, list[str]] = {}

    def read(self, relative: str) -> list[str]:
        if relative not in self.lines:
            p = Path(relative)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(f"unsafe source path: {relative}")
            self.lines[relative] = (self.root / p).read_text(encoding="utf-8").splitlines()
        return self.lines[relative]

    def cite(self, relative: str, needle: str, *, nth: int = 0) -> dict:
        """Find an exact literal on a source line; fail on ambiguous anchors."""
        matches = [i for i, line in enumerate(self.read(relative), 1) if needle in line]
        if not matches or nth >= len(matches):
            raise ValueError(f"missing anchor {relative}: {needle!r}")
        # When repeated, select the first source occurrence deterministically.
        # `what` and its precise line remain in the artifact for independent
        # line-by-line validation (no nearest-line or prose-only citations).
        return {"path": relative, "lines": [matches[nth]], "what": needle}


def verify_citations(doc: dict, source: Path) -> bool:
    """Re-read exact targets, not a best-effort nearest-line search."""
    files = Source(source)
    for item in doc["path_trace"]:
        if not item["files"]:
            raise ValueError(f"uncited path topic {item['topic']}")
        for citation in item["files"]:
            p, needle = citation["path"], citation["what"]
            for lineno in citation["lines"]:
                lines = files.read(p)
                if not isinstance(lineno, int) or isinstance(lineno, bool) or not (1 <= lineno <= len(lines)) or needle not in lines[lineno - 1]:
                    raise ValueError(f"invalid citation {p}:{lineno} {needle!r}")
    for control in doc["controls"]:
        for citation in control["proven"]:
            lines = files.read(citation["path"])
            n = citation["lines"][0]
            if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= len(lines)) or citation["what"] not in lines[n-1]:
                raise ValueError(f"invalid control citation {citation!r}")
    for candidate in doc["nondeterminism_candidates"]:
        for citation in candidate["source_basis"]:
            lines = files.read(citation["path"])
            n = citation["lines"][0]
            if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= len(lines)) or citation["what"] not in lines[n-1]:
                raise ValueError(f"invalid candidate citation {citation!r}")
    return True


# A source-code getter census, not a list of imagined upstream flags.  This pin
# handles these names in ggml-vulkan.cpp (the loader's VK_ICD_FILENAMES is
# external Vulkan-loader configuration, not a GGML_VK_* variable).
ENV_GETTER = re.compile(r'\bgetenv\s*\(\s*"(GGML_VK_[A-Z0-9_]+)"\s*\)')
ENV_EFFECTS = {
    "GGML_VK_PREFER_HOST_MEMORY": "Prefer coherent host-visible allocation before device-local.",
    "GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM": "Prefer device-local-only allocation instead of host-visible VRAM.",
    "GGML_VK_ALLOW_SYSMEM_FALLBACK": "Allow coherent system-memory fallback on device allocation failure.",
    "GGML_VK_DISABLE_GRAPH_OPTIMIZE": "Disable Vulkan graph optimization/reordering.",
    "GGML_VK_DISABLE_COOPMAT": "Disable KHR cooperative-matrix feature detection.",
    "GGML_VK_DISABLE_COOPMAT2": "Disable NV cooperative-matrix2 feature detection.",
    "GGML_VK_DISABLE_COOPMAT2_DECODE_VECTOR": "Disable NV cooperative-matrix2 decode-vector extension.",
    "GGML_VK_DISABLE_INTEGER_DOT_PRODUCT": "Disable accelerated integer-dot shader branch.",
    "GGML_VK_DISABLE_BFLOAT16": "Disable BF16 extension branch.",
    "GGML_VK_DISABLE_DOT2": "Disable mixed-float dot2 feature branch.",
    "GGML_VK_ENABLE_MEMORY_PRIORITY": "Opt into EXT memory priority for allocations.",
    "GGML_VK_DISABLE_ASYNC": "Turn off backend asynchronous interface support.",
    "GGML_VK_FORCE_MAX_ALLOCATION_SIZE": "Override queried maximum allocation size (integer bytes).",
    "GGML_VK_FORCE_MAX_BUFFER_SIZE": "Override queried maximum buffer size (integer bytes).",
    "GGML_VK_SUBALLOCATION_BLOCK_SIZE": "Override suballocation block size (integer bytes).",
    "GGML_VK_MAX_NODES_PER_SUBMIT": "Override batching threshold (minimum one node).",
    "GGML_VK_DISABLE_F16": "Disable FP16 storage/compute feature use.",
    "GGML_VK_ALLOW_GRAPHICS_QUEUE": "Allow a graphics-capable compute queue instead of avoiding it.",
    "GGML_VK_DISABLE_OCP_FP4": "Disable optional OCP FP4 feature branch.",
    "GGML_VK_DISABLE_MULTI_ADD": "Disable multi-add optimization.",
    "GGML_VK_ASYNC_USE_TRANSFER_QUEUE": "Use transfer queue for asynchronous transfers if available.",
    "GGML_VK_SERIALIZE_SUBMISSIONS": "Submit compute work with a fence rather than unfenced batching.",
    "GGML_VK_DISABLE_FUSION": "Disable Vulkan op fusion, including add/RMS fusion.",
    "GGML_VK_DISABLE_MMVQ": "Force off matrix-vector quantized-activation route.",
    "GGML_VK_FORCE_MMVQ": "Force matrix-vector quantized-activation route when available.",
    "GGML_VK_DEBUG_MARKERS": "Enable debug-utils object/command labels if extension available.",
    "GGML_VK_PERF_LOGGER": "Enable Vulkan performance logging and fence/wait instrumentation.",
    "GGML_VK_PERF_LOGGER_CONCURRENT": "Select concurrent performance-logging grouping.",
    "GGML_VK_SYNC_LOGGER": "Log synchronization and graph nodes.",
    "GGML_VK_MEMORY_LOGGER": "Enable Vulkan allocation logging.",
    "GGML_VK_PIPELINE_STATS": "Select pipeline-statistics logging filter.",
    "GGML_VK_PERF_LOGGER_FREQUENCY": "Override performance logger frequency (integer).",
    "GGML_VK_VISIBLE_DEVICES": "Filter/reorder Vulkan enumerated device indices.",
}


def enumerate_env_controls(source: Path) -> dict[str, list[dict]]:
    """Census every literal GGML_VK_ getenv call in tracked source files."""
    src = Source(source)
    paths = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"], stderr=subprocess.PIPE).split(b"\0")
    result: dict[str, list[dict]] = {}
    for raw in paths:
        if not raw:
            continue
        rel = os.fsdecode(raw)
        # Match source, not prose describing possible flags or compiled artifacts.
        if Path(rel).suffix not in {".cpp", ".c", ".cc", ".h", ".hpp", ".py", ".sh"}:
            continue
        for n, line in enumerate(src.read(rel), 1):
            for match in ENV_GETTER.finditer(line):
                name = match.group(1)
                result.setdefault(name, []).append({"path": rel, "lines": [n], "what": match.group(0)})
    return dict(sorted(result.items()))


def derive(source: Path = DEFAULT_SOURCE, repo: Path | None = None) -> dict:
    source = Path(source)
    repo = Path(repo) if repo is not None else Path(__file__).resolve().parents[1]
    identity = verify_source(source)
    s = Source(source)
    ref = json.loads((repo / REF_REL).read_text(encoding="utf-8"))
    if ref["llama_pin"]["tree"] != identity["tree"] or ref["reconstruction"]["R5_vulkan_at_ngl1"]["summary"].find("OUTPUT layer") < 0:
        raise ValueError("#250 predecessor tree/placement mismatch")
    # The committed #250 summary carries a *39-character* SHA (missing one
    # nibble); preserve this malformed historical literal rather than repairing
    # it or treating it as a valid lookup. The pinned source is authenticated
    # independently against the 40-character HEAD and the corroborating tree.
    predecessor_head = ref["llama_pin"]["commit"]
    predecessor_head_discrepancy = (predecessor_head != identity["head"])
    method = (repo / REF_METHODOLOGY).read_text(encoding="utf-8").splitlines()
    proof_lines = [i for i, x in enumerate(method, 1) if "Reference arm B: NVIDIA RTX 3060" in x]
    if len(proof_lines) != 1 or "610.57.04" not in method[proof_lines[0]+1]:
        raise ValueError("#250 reference device identity missing")

    def item(topic: str, narrative: str, *anchors: tuple[str, str]) -> dict:
        return {"topic": topic, "files": [s.cite(p, needle) for p, needle in anchors], "narrative": narrative}

    trace = [
        item("device_selection", "Vulkan loader (external VK_ICD_FILENAMES from accepted #250 env) supplies physical devices; ggml filters GGML_VK_VISIBLE_DEVICES indices. There is no VulkanExtension symbol at this pin. Physical-device extensions/features then gate coopmat, integer dot and subgroup; compute queue prefers non-graphics, transfer queue prefers transfer-only. Context owns a command pool/queue, not an independently enumerated device.",
             (VK, "vk::enumerateInstanceVersion()"), (VK, "vk_instance.instance = vk::createInstance"), (VK, 'getenv("GGML_VK_VISIBLE_DEVICES")'), (VK, "enumeratePhysicalDevices();"), (VK, "ggml_vk_find_queue_family_index(std::vector"), (VK, "ggml_vk_create_context(ggml_backend_vk_context * ctx")),
        item("output_projection", "Accepted #250 R5 proves ngl=1 places output head (full-vocabulary MUL_MAT) on Vulkan and embedding/repeating blocks on CPU; #250 R2 says first divergent row comes from last prompt ubatch. File-type IQ1_S family does NOT prove the specific output tensor quantization; exact variant is conditional on tensor type, activation type, shape, capability and compiled shaders. FQ/flash attention does not execute in this output projection.",
             ("src/llama-model.cpp", "const int i_gpu_start = std::max(n_layer_all + 1 - n_gpu_layers, 0);"), ("src/llama-model.cpp", "pimpl->dev_output = get_layer_buft_list(n_layer_all);"), (VK, "static void ggml_vk_mul_mat(ggml_backend_vk_context")),
        item("buffer_allocation", "Tensor buffers choose host-visible/coherent device-local (ReBAR) if possible, otherwise device-local; memory types come from driver's requirements and available heaps, retried on failure. Output weight bytes must be loaded via set_tensor, direct mapped host-visible memcpy or host-coherent staging/copyBuffer with a fence. Device-buffer creation maps/binds but does not zero memory.",
             (VK, "ggml_vk_find_memory_properties(const"), (VK, "buf->device_memory = device->device.allocateMemory({ mem_req.size"), (VK, "static vk_buffer ggml_vk_create_buffer_device"), (VK, "static void ggml_backend_vk_buffer_set_tensor"), (VK, "ggml_vk_ensure_sync_staging_buffer(dst->device, staging_size);")),
        item("buffer_initialization", "init_tensor only validates a view and returns success; NO blanket zero-fill. Explicit memset_tensor/clear uses vkCmdFillBuffer and waits for its fence; CPU memcpy for mapped memory or staging memcpy before submit initialize only written spans. Uninitialized allocation/padding is a conditional candidate, NOT proof that output GEMM reads uninitialized data.",
             (VK, "static enum ggml_status ggml_backend_vk_buffer_init_tensor"), (VK, "return GGML_STATUS_SUCCESS;"), (VK, "static void ggml_backend_vk_buffer_memset_tensor"), (VK, "subctx->s->buffer->buf.fillBuffer(dst->buffer, offset, size, c);"), (VK, "ggml_vk_submit(subctx, dst->device->fence);")),
        item("submission", "Command buffer records and ends, queue.submit accepts multiple ordered submissions with timeline waits/signals. Default graph submits unfenced chunks; a final synchronize submits a fence and waits. max_nodes_per_submit defaults to 100 and flops/almost-ready/end-node thresholds also submit. Multiple chunks can be in flight; NVIDIA serializes concurrent host queue submissions under queue_submit_mutex (not GPU command execution). Transfer queue is normally separate/aliased as driver permits, with timeline dependency.",
             (VK, "static void ggml_vk_submit(vk_context& ctx"), (VK, "ctx->p->q->handle->submit(submit_infos, fence);"), (VK, "device->max_nodes_per_submit = 100;"), (VK, "ctx->device->serialize_submissions) {"), (VK, "device->queue_submit_mutex"), (VK, "ctx->device->compute_queue->handle->submit({}, ctx->fence);")),
        item("host_device_sync", "ggml_vk_sync_buffers emits shader-read/write and transfer-read/write pipelineBarrier. Host-to-GPU pinned or staging writes use copyBuffer and submit; non-UMA reads use staging and fence, outgoing memcpy after completion. Async transfers can signal timeline semaphores; default async interface is supported on NVIDIA unless disabled.",
             (VK, "static void ggml_vk_sync_buffers"), (VK, "subctx->s->buffer->buf.pipelineBarrier("), (VK, "subctx->s->buffer->buf.copyBuffer(staging_buffer->buffer, dst->buffer, slices);"), (VK, "ctx->transfer_semaphore.value++;"), (VK, "static void ggml_vk_synchronize(ggml_backend_vk_context * ctx)")),
        item("shader_dispatch", "Output GGML_OP_MUL_MAT: vector path when <= mul_mat_vec_max_cols activation rows (e.g. one-token decode); otherwise matmul path. Vector IQ1_S may dispatch IQ1_S/Q8_1 integer-dot (if capability and MMVQ heuristic) or IQ1_S/F32/F16 dequant vector shader with subgroup/hybrid/shared-memory reduction; GEMM chooses quantized Q8_1 when possible then quantized F16/F32 map, finally dequantize-to-F16 fallback. Coopmat1/2 versus scalar is extension/build dependent, not established from #250's device label alone. Tile-selector, subgroup and workgroup dispatch all read device properties. Embedded SPIR-V is loaded; GLSL compiler is not invoked by this runtime path.",
             (VK, "ggml_vk_mul_mat_vec_q_f16(ctx, subctx, cgraph, node_idx);"), (VK, "ggml_vk_mul_mat_q_f16(ctx, subctx, src0, src1, dst, false);"), (VK, "ggml_vk_should_use_mmvq(ctx->device, ne01, ne11, ne10, src0->type)"), (VK, "pipeline_dequant_mul_mat_vec_q8_1_f32[w][GGML_TYPE_IQ1_S][i]"), (VK, "pipeline_dequant_mul_mat_vec_f32_f32[w][GGML_TYPE_IQ1_S][i]"), (VK, "pipeline_dequant_mul_mat_vec_f16_f32[w][GGML_TYPE_IQ1_S][i]"), (VK, "ggml_vk_guess_matmul_pipeline_map(ctx, *mmp_map, ne01, ne11, aligned, false)"), (VK, "X(GGML_TYPE_IQ1_S,   iq1_s)"), (VK, "FOR_EACH_LUT_TYPE_NONFP4(X_CM2)"), (VK, "FOR_EACH_LUT_TYPE_NONFP4(X_CM1)"), (VK, "FOR_EACH_LUT_TYPE(X_SG)"), (VK, "FOR_EACH_LUT_TYPE(X_SG_FP32)"), (VK, "device->matmul_tile_selector = [](uint32_t m, uint32_t n"), (VK, "ggml_vk_create_pipeline_func(vk_device& device")),
        item("pipeline_cache", "Pipelines are per-process vk_pipeline objects with compiled flag and compile mutex/CV; lazy compile once per requested variant. Vulkan createComputePipeline receives VK_NULL_HANDLE (NO application-managed vk::PipelineCache); no GGML_VK_PIPELINE_CACHE or GGML_VK_SHADER_CACHE getenv and no backend disk persistence path. Driver's own implicit cache is outside source proof: a cache hit cannot select another app-level variant; driver compilation behavior is not proven bitwise equivalent across processes.",
             (VK, "if (!pipeline->compiled)"), (VK, "compile_cv"), (VK, "createComputePipeline(VK_NULL_HANDLE"), (VK, "ggml_vk_load_shaders(device);")),
        item("descriptor_reuse", "Descriptor sets expand in per-context pools; each dispatch increments descriptor_set_idx and rewrites its bindings. Graph cleanup resets the index for next graph but keeps pools/sets until backend cleanup. Overlapping tensor buffer ranges are detected by buffer identity and offsets before barriers; prealloc_x/y/split_k scratch is shared/reused with explicit barriers. Pointer identity controls reuse but is not itself a floating arithmetic input.",
             (VK, "ggml_pipeline_allocate_descriptor_sets(ggml_backend_vk_context"), (VK, "ctx->descriptor_sets[ctx->descriptor_set_idx++]"), (VK, "ctx->descriptor_set_idx = 0;"), (VK, "if (a_buf == o_buf)"), (VK, "ctx->prealloc_y_last_tensor_used != src1")),
        item("reduction_order", "IQ1_S vector shader includes subgroupAdd or shared-memory/hybrid sum and a device/shape-selected workgroup. Matmul tiles fix per-work-item accumulation order via specialization dimensions; split-K is chosen from K, tile count, shader core count when K>=2048 and uses a second ordered reduction pass. These can CHANGE arithmetic across distinct paths/geometries but no source proof says identical inputs/device/shape choose a different path per fresh process; split-K is not a presumed cause.",
             (SHADER, "temp[j][n] = subgroupAdd(temp[j][n]);"), (SHADER, "temp[j][n] += tmpsh[j][n][s];"), (SHADER, "tmpsh[j][n][tid] += tmpsh[j][n][tid + s];"), (VK, "SHADER_REDUCTION_MODE_HYBRID"), (VK, "static uint32_t ggml_vk_guess_split_k"), (VK, "if (k >= 2048)"), (VK, "pipeline_matmul_split_k_reduce, { split_k_buffer, d }"), (VK, "device->subgroup_size = subgroup_props.subgroupSize;")),
        item("rng_scope", "rand() calls exist only inside GGML_VULKAN_RUN_TESTS/ GGML_VULKAN_CHECK_RESULTS test helpers, not the production output GEMM path. This is a source-scoped exclusion, not a statement about driver internal randomness.",
             (VK, "#if defined(GGML_VULKAN_CHECK_RESULTS)"), (VK, "x[i] = (rand() / (float)RAND_MAX)"), (VK, "#if defined(GGML_VULKAN_RUN_TESTS)")),
    ]

    env = enumerate_env_controls(source)
    if set(env) != set(ENV_EFFECTS):
        raise ValueError(f"unreviewed or missing GGML_VK_ getter(s): {sorted(set(env) ^ set(ENV_EFFECTS))}")
    controls = [{"name": name, "kind": "env", "proven": env[name], "effect": ENV_EFFECTS[name]} for name in sorted(env)]
    controls += [
        {"name": "vk::PipelineCache / GGML_VK_PIPELINE_CACHE", "kind": "code_absent", "proven": [s.cite(VK, "createComputePipeline(VK_NULL_HANDLE")], "effect": "No application cache-control env variable or persistent pipeline cache; creation passes null cache."},
        {"name": "GGML_VK_FORCE_SCALAR / GGML_VK_SUBGROUP_SIZE / GGML_VK_DETERMINISTIC", "kind": "code_absent", "proven": [s.cite(VK, "device->subgroup_size = subgroup_props.subgroupSize;")], "effect": "None of these upstream-sounding toggles is handled by a getenv in this pin; disable coopmat and integer dot separately instead."},
        {"name": "backend n_threads", "kind": "code", "proven": [s.cite(VK, "static void ggml_vk_mul_mat(ggml_backend_vk_context")], "effect": "No n_threads parameter in Vulkan MUL_MAT dispatch; CPU -t/-tb can alter host computation feeding Vulkan, not a Vulkan shader thread count."},
    ]
    def candidate(rank: int, mechanism: str, why: str, gemm: bool, *anchors: tuple[str, str]) -> dict:
        return {"rank": rank, "mechanism": mechanism, "source_basis": [s.cite(p, n) for p, n in anchors], "why_it_can_differ_across_fresh_processes": why, "affects_output_layer_gemm": gemm}
    candidates = [
        candidate(1, "GPU input or scratch content/padding not initialized before read (unproven)", "Allocations are not zeroed; if a quantization/padding/buffer-reuse path reads unwritten bytes, fresh allocations could contain different data. Requires a concrete read-before-write proof; weights are explicitly loaded and ordinary destinations fully written.", True, (VK, "static enum ggml_status ggml_backend_vk_buffer_init_tensor"), (VK, "ctx->prealloc_y_last_k_padded")),
        candidate(2, "cross-queue synchronization or aliasing gap (unproven)", "Fresh-process queue timing could expose a missing dependency if source's barrier/overlap tracking misses a real alias. Explicit barriers, semaphores and final fence argue against treating async alone as a proven race.", True, (VK, "if (a_buf == o_buf)"), (VK, "ctx->transfer_semaphore.value++;")),
        candidate(3, "driver-reported memory type/capability or allocation fallback varies", "Memory pressure and driver heap/type ordering can change device-local vs mapped/staging paths or selected subgroup/coopmat paths. Must inspect actual device/feature/log path per process; a fixed device/driver does not establish variation.", True, (VK, "for (auto mtype_it = memory_type_indices.begin()"), (VK, "device->subgroup_size = subgroup_props.subgroupSize;")),
        candidate(4, "driver compile or implicit driver shader cache", "createComputePipeline has null application cache and consumes embedded SPIR-V; driver-internal compilation/cache is implementation-defined and not evidenced as changing numerical results. There is no runtime glslang/dxc random seed or app cache key.", True, (VK, "createComputePipeline(VK_NULL_HANDLE"), (VK, "vk::ShaderModuleCreateInfo shader_module_create_info")),
        candidate(5, "shape-sensitive reduction, MMVQ, cooperative matrix and split-K", "Output prompt-ubatch shape can choose a different floating accumulation tree, but for identical shape/capabilities selection is deterministic. K>=2048 alone does not imply split-K; tiling/occupancy gate must also pass.", True, (VK, "if (k >= 2048)"), (VK, "ggml_vk_should_use_mmvq(ctx->device, ne01, ne11, ne10, src0->type)"), (SHADER, "temp[j][n] = subgroupAdd(temp[j][n]);")),
        candidate(6, "ASLR/pointer-keyed reuse and submission timeline values", "Fresh processes have different pointer addresses and command/timeline histories; pointers appear in cache/alias predicates and counters in synchronization, but the source has no address-to-FP-value operation or RNG in output GEMM. Only a latent alias bug could turn this into numeric variance.", False, (VK, "ctx->prealloc_y_last_tensor_used != src1"), (VK, "ctx->transfer_semaphore.value++;")),
    ]
    doc = {
        "schema": "inferswarm.issue252.vulkan-path.phase0/1",
        "source_identity": {**identity, "pinned_repository": "llama.cpp", "verification": "git rev-parse HEAD HEAD^{tree}", "predecessor_250_reported_commit_literal": predecessor_head, "predecessor_250_commit_literal_mismatch": predecessor_head_discrepancy, "predecessor_250_tree_match": True},
        "device_identity_ref": {"host": "inferswarm01", "gpu": "NVIDIA RTX 3060", "bdf": "00000000:03:00.0", "gpu_uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55", "driver": "610.57.04", "icd": "nvidia", "vulkan": "1.4.341", "comparator_sha256": ref["llama_pin"]["binaries"]["comparator"], "authority": f"{REF_METHODOLOGY}:21-23; {REF_REL}:108-116,239-255", "placement": "ngl=1 output head Vulkan, input embedding and all repeating blocks CPU; R5 accepted #250", "scope": "offline pinned-source inference only; no physical execution"},
        "path_trace": trace,
        "controls": controls,
        "nondeterminism_candidates": candidates,
        "limitations": ["No runtime shader variant, per-tensor output quant type, driver features, allocation path, queue depth, race, or numerical root cause is proven by static source alone.", "VulkanExtension is not a symbol in the pinned source tree; vk::enumerateInstanceExtensionProperties and physical device extension enumeration are the actual path.", "VK_ICD_FILENAMES and CUDA_VISIBLE_DEVICES are external launch/environment controls from #250, not GGML_VK_ backend getters.", "No backend RNG or address-based arithmetic located in the output GEMM dispatch path; absence is scoped to source code, not the driver."],
    }
    verify_citations(doc, source)
    return doc


def encode(doc: dict) -> bytes:
    return (json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def main() -> None:
    source = Path(os.environ.get("LLAMA_SRC", str(DEFAULT_SOURCE)))
    repo = Path(__file__).resolve().parents[1]
    output = repo / OUTPUT_REL
    payload = encode(derive(source, repo))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    print(output)


if __name__ == "__main__":
    main()
