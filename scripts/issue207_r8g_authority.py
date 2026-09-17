"""Issue #207 R8-G: frozen authority constants for the bounded earliest
layer/state-boundary localization campaign (case-4096 primary, case-256
contrast ONLY; no requalification, no repair).

Accepted predecessors (immutable, consumed, never rewritten):
  R8-D:  Issue #195 / PR #197, merged f142a0d9b693f999685960c641b2a8fe362c4e1e
         (reviewed head ca7e159929190a04cabd059042def1b6bd4c2467),
         terminal R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL.
  R8-E:  Issue #199 / PR #205, merge 8a3681b28c6c7e1797f7dd7f5b6efcde31d83b6c,
         terminal R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED.
  R8-F:  Issue #200 / PR #206, merge affa26cc358159b9e73aa460ad4327c0fe139c39
         (evidence namespace docs/implementation/r8-f-local-backing-source-policy-200/),
         terminal R8F_LOCAL_VERIFIED_BACKING_PASS (per Issue #207 preamble).

This campaign is diagnostic localization ONLY: it determines the earliest
semantically meaningful runtime boundary at which the accepted reference
and the accepted five-device RPC candidate cease to agree for the residual
case-4096 divergence (bounded case-256 contrast). It does NOT repair
llama.cpp, does NOT requalify R8-D, does NOT change topology/sampler/
placement, and does NOT create or execute a runtime-repair successor.
"""

# Starting point (Issue #207: "Start from exact origin/main@affa26c...")
START_MAIN = "affa26cc358159b9e73aa460ad4327c0fe139c39"  # PR #206 merge (R8-F)
BRANCH = "issue-207-r8g-runtime-boundary-localization"
ISSUE = 207

# ---------------------------------------------------------------------------
# Accepted predecessor identity (pins identical to accepted R8-E authority;
# the runtime subject is UNCHANGED from R8-D/R8-E)
# ---------------------------------------------------------------------------
R8D_V2_DIR = "docs/investigations/qwen38-flash-next-r8-d-v2"
R8D_V2_MANIFEST = R8D_V2_DIR + "/MANIFEST.sha256"
R8D_V2_TERMINAL = "R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL"
R8D_V2_REVIEWED_HEAD = "ca7e159929190a04cabd059042def1b6bd4c2467"
R8D_V2_MERGE = "f142a0d9b693f999685960c641b2a8fe362c4e1e"

R8E_DIR = "docs/investigations/qwen38-flash-next-r8-e"
R8E_MANIFEST = R8E_DIR + "/MANIFEST.sha256"
R8E_MERGE = "8a3681b28c6c7e1797f7dd7f5b6efcde31d83b6c"
R8E_TERMINAL = "R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED"
# R8-E retained decision rows bound by this campaign's non-perturbation
# cross-check (case-4096 generated position 0; per-arm repeat-stable).
R8E_POS0_ROW_SHA256 = {
    "reference": "e79a8490e33d25bc",   # prefix; full sha loaded below
    "candidate": "d4a0a88fff3a4214",
}
R8E_CASE4096_TOKENS = {
    "reference": [328, 760, 324, 55965, 51624, 29014, 34227, 18030],
    "candidate": [248046],
}

R8F_DIR = "docs/implementation/r8-f-local-backing-source-policy-200"
R8F_MERGE = "affa26cc358159b9e73aa460ad4327c0fe139c39"
R8F_TERMINAL = "R8F_LOCAL_VERIFIED_BACKING_PASS"

# Runtime authority (identical to accepted R8-D/R8-E pins; NO runtime
# byte changes for execution — see DIAGNOSTIC below)
LLAMA_CPP_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
ACCEPTED_BINARY_SHA256 = {
    "llama-server": "de3a8a545e2f5995f80ff23f60776fedc30edca67f0e09f3bc47c845156e3411",
    "ggml-rpc-server": "a897f908add3305658e6b4f996880033d07ede0800fff71dbc46e90230acdfe9",
}
BIN_DIR = "/home/hermes/llama.cpp/build-v041/bin"

# Model authority (accepted R8-A pins, unchanged)
MODEL_DIR_01 = "/srv/models/qwen38-ud-iq1-s"
SPLIT_SHA256 = {
    "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf":
        "88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf":
        "3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf":
        "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a",
}
SPLIT_TOTAL_BYTES = 72546461344

# Frozen topology (accepted R8-D v2 / R8-E; re-verified fresh at R8-G freeze)
TOPOLOGY = {
    "client": {"host": "inferswarm01", "ip": "10.0.0.141", "gpus": [
        {"bdf": "0000:02:00.0", "uuid": "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099"},
        {"bdf": "0000:03:00.0", "uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55"},
    ]},
    "rpc1": {"host": "inferswarm03", "ip": "10.0.0.219", "gpus": [
        {"bdf": "0000:01:00.0", "uuid": "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176"},
        {"bdf": "0000:03:00.0", "uuid": "GPU-a57bd3fb-c072-67ed-166c-ce52cf504ac0"},
    ]},
    "rpc2": {"host": "inferswarm04", "ip": "10.0.0.204", "gpus": [
        {"bdf": "0000:01:00.0", "uuid": "GPU-ecda1aaa-0c66-857b-8218-3d511dc75c03"},
    ]},
}
CANDIDATE_RPC_ENDPOINTS = ["10.0.0.219:50052", "10.0.0.219:50053",
                           "10.0.0.204:50052"]
REFERENCE_PORT = 8341   # R8-G observation arm, inferswarm01 loopback
CANDIDATE_PORT = 8343   # R8-G observation arm client, inferswarm01 loopback

# Request contract — IDENTICAL to accepted R8-D v2 / R8-E (canonical
# true-greedy); the boundary hook observes, never alters, request semantics.
REQUEST_CONTRACT = {
    "samplers": ["top_k"],
    "top_k": 1,
    "temperature": 0.0,
    "seed": 0,
    "cache_prompt": False,
    "stream": False,
    "return_tokens": True,
    "n_predict": 8,
}
FORBIDDEN_REQUEST_KEYS = ("n_probs", "probs", "min_p", "top_p", "typical_p")

# Decision inputs are loaded MECHANICALLY from the accepted R8-D v2
# retained run bytes via issue199_r8e_authority.load_decision_inputs()
# (same loader, same hard identity assertions — never hand-copied).
R8D_RUN_RECORDS = {
    "reference": R8D_V2_DIR + "/evidence/reference/ref-run-1.json",
    "candidate": R8D_V2_DIR + "/evidence/candidate/cand-run-1.json",
}
CASE256_PREFIX = [561, 324, 55965, 51624, 29014]
CASE256_REF_TOKEN = 271
CASE256_CAND_TOKEN = 34227
CASE4096_REF_TOKEN = 328
CASE4096_CAND_TOKEN = 248046

# ---------------------------------------------------------------------------
# Model structure — derived from the EXACT pinned model metadata + source
# (GGUF qwen4exp.* keys read from the accepted split member 1 on
# inferswarm01, 2026-09-16; src/models/qwen4exp.cpp @ b29c606e). These are
# NOT assumed from general model knowledge.
# ---------------------------------------------------------------------------
N_LAYER = 48                       # qwen4exp.block_count
N_EMBD = 2560                      # qwen4exp.embedding_length
HC_MULT = 4                        # qwen4exp.hyper_connection.count
FULL_ATTENTION_INTERVAL = 4        # qwen4exp.full_attention_interval
PLE_LAYER = 0                      # qwen4exp.ple.layers = [0]
N_VOCAB = 248320                   # observed f32 row width (R8-E rows)

def is_full_attention_layer(il):
    # load_arch_hparams: is_recr_impl[i] = (i < n_layer) && ((i+1) % interval != 0)
    # -> NOT recurrent (full attention) exactly when (i+1) % 4 == 0
    return ((il + 1) % FULL_ATTENTION_INTERVAL) == 0

FULL_ATTENTION_LAYERS = [il for il in range(N_LAYER)
                         if is_full_attention_layer(il)]  # [3,7,...,47]

# ---------------------------------------------------------------------------
# PROSPECTIVELY FROZEN observation boundary set (Phase 0 freeze, BEFORE any
# new physical observation). Boundary identity = (node name, occurrence
# ordinal within one graph execution) where node names are the runtime names
# assigned by llama_context::graph_get_cb() at src/llama-context.cpp:2526
# (ggml_format_name("%s-%d") for il>=0, plain name for il==-1) from the
# cb() call sites in src/models/qwen4exp.cpp. Ordered by graph construction
# order = execution order.
#
# Derivation (per graph execution, occurrence ordinals counted over ALL
# occurrences of the same name in the graph):
#   - embedding:      "model.input_embed" (1 occurrence)
#   - per layer il:   "hc_mixed-<il>" occurs 2x (attn-side then ffn-side;
#                      qwen4exp.cpp:389, 437), "l_last-<il>" 1x (:441),
#                      "hc_combine-<il>" 2x (:419, :443)
#   - head:           "result_norm" 1x, "result_output" 1x
#
# COARSE SET (Phase 2; 18 boundaries — every 3rd layer output + anchors):
#   idx 0  model.input_embed          (embedding application)
#   idx 1  l_last-2                   (after layer 2: GDN block outputs)
#   idx 2  l_last-5                   (after layer 5)
#   idx 3  l_last-8
#   idx 4  l_last-11
#   idx 5  l_last-14
#   idx 6  l_last-17
#   idx 7  l_last-20
#   idx 8  l_last-23
#   idx 9  l_last-26
#   idx 10 l_last-29
#   idx 11 l_last-32
#   idx 12 l_last-35
#   idx 13 l_last-38
#   idx 14 l_last-41
#   idx 15 l_last-44
#   idx 16 l_last-47                  (last layer output; layer 47 is FULL
#                                      ATTENTION — the only full-attn
#                                      boundary in the coarse set besides
#                                      the interval crossings between)
#   idx 17 result_norm                (final hyper-connection head mixer)
#   ("result_output" is additionally retained as a SEAM ANCHOR: its decode-0
#    row must byte-match the accepted R8-E pos-0 logits row — internal
#    consistency of the observation seam, not a localization boundary.)
#
# REFINEMENT RULE (Phase 3, frozen prospectively):
#   If the coarse pass yields matching boundary i and differing boundary
#   j = first differing, refine ONLY inside (i, j]:
#   R1. If j - i == 1 and boundary i is l_last-a, boundary j is l_last-b
#       with b = a+1: observe INTRA-layer ordered sub-boundaries of layer b
#       (frozen list, see REFINEMENT_SUBLIST below) — first differing
#       sub-boundary is the earliest divergent boundary; if all sub-boundary
#       states match while l_last-b differs, report the interval
#       localized to (sub-boundary list exhausted -> layer-b aggregate
#       effect) with the blocker "no finer runtime-native boundary without
#       an invasive seam".
#   R2. If j - i > 1: bisect (midpoint of the ordered coarse interval) and
#       repeat; valid because layer outputs are ordered and divergence at a
#       coarser boundary implies divergence at every finer-superset point
#       AFTER onset — BUT the refinement must re-verify the last-matching
#       boundary at every step (reconvergence check, see R3).
#   R3. If ANY boundary observed at ordinal k differs while a LATER
#       observed boundary k' > k matches again, the divergence structure is
#       NON-MONOTONIC inside the frozen interval: STOP bisecting, scan the
#       complete frozen coarse set (already observed) + the frozen
#       sub-boundary list of the layers inside the affected interval, and
#       emit R8G_NONMONOTONIC_RUNTIME_DIVERGENCE_CHARACTERIZED.
#
# REFINEMENT_SUBLIST (intra-layer ordered sub-boundaries, frozen; names as
# emitted by graph_get_cb from the cb() call sites in build_layer_attn,
# build_layer_attn_linear, build_layer_ffn, build_ple of qwen4exp.cpp):
#   For a GDN (linear attention) layer il:
#     1. "linear_attn_qkv_mixed-<il>"   (qkv projection of the token mixer)
#     2. "conv_output_silu-<il>"        (conv state transition output)
#     3. "final_output-<il>"            (gated-normalized recurrent attn out)
#     4. "linear_attn_out-<il>"         (mixer output projection)
#     5. "ffn_moe_out-<il>"             (MoE expert combine)
#     6. "ffn_out-<il>"                 (after shared-expert add)
#   For a FULL ATTENTION layer il:
#     1. "Qcur-<il>"                    (q projection + norm; pre-rope)
#     2. "attn_pregate-<il>"            (attention output pre gate)
#     3. "attn_gated-<il>"              (post sigmoid gate)
#     4. "attn_output-<il>"             (mixer output projection)
#     5. "ffn_moe_out-<il>"
#     6. "ffn_out-<il>"
#   For the PLE layer (0), prepended before the GDN list:
#     0. "ple_conv_out-0"               (PLE n-gram conv output)
#   (Sub-boundary identity likewise = (name, occurrence ordinal); each
#    listed name occurs once per layer in graph order except where a layer
#    hosts two hc_mix halves — hc_mixed/hc_combine are NOT in the sublist;
#    the sublist brackets the token mixer and FFN, the semantically
#    meaningful per-layer state transitions.)
#
# CASE-256 CONTRAST SET (Phase 4, frozen prospectively per Issue #207):
#   the case-4096 localized boundary, its immediately adjacent accepted
#   boundaries, plus at most one additional frozen checkpoint
#   ("l_last-23") to distinguish shared-vs-case-specific onset.
CASE256_CONTRAST_EXTRA = "l_last-23"

COARSE_BOUNDARIES = (
    ("model.input_embed", 0),
    ("l_last-2", 0), ("l_last-5", 0), ("l_last-8", 0), ("l_last-11", 0),
    ("l_last-14", 0), ("l_last-17", 0), ("l_last-20", 0), ("l_last-23", 0),
    ("l_last-26", 0), ("l_last-29", 0), ("l_last-32", 0), ("l_last-35", 0),
    ("l_last-38", 0), ("l_last-41", 0), ("l_last-44", 0), ("l_last-47", 0),
    ("result_norm", 0),
)
SEAM_ANCHOR_BOUNDARY = ("result_output", 0)   # row cross-check vs R8-E bytes

def gdn_sublist(il):
    sub = []
    if il == PLE_LAYER:
        sub.append(("ple_conv_out-%d" % il, 0))
    sub += [
        ("linear_attn_qkv_mixed-%d" % il, 0),
        ("conv_output_silu-%d" % il, 0),
        ("final_output-%d" % il, 0),
        ("linear_attn_out-%d" % il, 0),
        ("ffn_moe_out-%d" % il, 0),
        ("ffn_out-%d" % il, 0),
    ]
    return tuple(sub)

def full_attn_sublist(il):
    return (
        ("Qcur-%d" % il, 0),
        ("attn_pregate-%d" % il, 0),
        ("attn_gated-%d" % il, 0),
        ("attn_output-%d" % il, 0),
        ("ffn_moe_out-%d" % il, 0),
        ("ffn_out-%d" % il, 0),
    )

def layer_sublist(il):
    return full_attn_sublist(il) if is_full_attention_layer(il) \
        else gdn_sublist(il)

# Frozen comparison contract: at every boundary, states are compared as
# exact float32 bytes per position; equality contract = byte identity.
# (Runtime float32 tensors are bit-stable across identical executions on
# identical binaries/devices — repeat-stability is PROVEN per capture
# before any cross-arm comparison is trusted; a boundary whose repeats are
# not byte-identical is UNOBSERVABLE under this contract and reported as
# such, never compared.)
COMPARISON_CONTRACT = "exact-f32-bytes-per-position"
REPEATS = 2

# ---------------------------------------------------------------------------
# Evidence namespace (fresh, additive)
# ---------------------------------------------------------------------------
R8G_DIR = "docs/investigations/qwen38-flash-next-r8-g"
R8G_EV = R8G_DIR + "/evidence"

CAMPAIGN_ID = "issue207-r8g-boundary-localization"
OBS_SCHEMA = "inferswarm.issue207.boundary-observation/1"
RED_SCHEMA = "inferswarm.issue207.reduction/1"

# Diagnostic instrumentation (Phase 1). Observation-only diagnostic build
# from the EXACT accepted source b29c606e (same policy as accepted R8-E:
# separately named binary; accepted binaries UNCHANGED for all
# token-equality proofs).
DIAGNOSTIC_NAME = "llama-server-r8g"
DIAGNOSTIC_SOURCE_BASE = "/home/hermes/llama.cpp"
DIAGNOSTIC_WORKTREE = "/home/hermes/llama.cpp/r8g-obs"
DIAGNOSTIC_BUILD_DIR = "build-r8g"
# The R8-G hook reuses the accepted R8-E sampling-seam hook semantics and
# ADDS the scheduler eval-callback boundary observer (native
# ggml_backend_sched_set_eval_callback seam; callback reads tensor bytes
# after compute+sync, sets no state, changes no split/placement).

# Terminals (exactly one)
TERMINAL_LOCALIZED = "R8G_EARLIEST_RUNTIME_BOUNDARY_LOCALIZED"
TERMINAL_INTERVAL = "R8G_RUNTIME_DIVERGENCE_INTERVAL_LOCALIZED"
TERMINAL_NONMONOTONIC = "R8G_NONMONOTONIC_RUNTIME_DIVERGENCE_CHARACTERIZED"
TERMINAL_BLOCKED = "R8G_LOCALIZATION_EVIDENCE_BLOCKED"
TERMINALS = (TERMINAL_LOCALIZED, TERMINAL_INTERVAL,
             TERMINAL_NONMONOTONIC, TERMINAL_BLOCKED)

# Producers whose bytes are pinned at the R8-G authority freeze
R8G_PRODUCERS = (
    "scripts/issue207_r8g_authority.py",
    "scripts/issue207_r8g_launch.py",
    "scripts/issue207_r8g_capture.py",
    "scripts/issue207_r8g_reduce.py",
    "scripts/issue207_r8g_negative_controls.py",
    "scripts/issue207_r8g_manifest.py",
)

# ---------------------------------------------------------------------------
# Loaders (mechanical, fail-closed)
# ---------------------------------------------------------------------------

def load_decision_inputs(repo_root):
    """Exact case prompts + accepted generated tokens from the accepted
    R8-D v2 retained run bytes, via the accepted R8-E loader (same hard
    identity assertions; never hand-copied)."""
    import importlib.util
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "issue199_r8e_authority.py")
    spec = importlib.util.spec_from_file_location("r8e_authority", p)
    r8e = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r8e)
    return r8e.load_decision_inputs(repo_root)


def r8d_v2_manifest_ok(repo_root):
    import importlib.util
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "issue199_r8e_authority.py")
    spec = importlib.util.spec_from_file_location("r8e_authority", p)
    r8e = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r8e)
    return r8e.r8d_v2_manifest_ok(repo_root)


def r8e_manifest_ok(repo_root):
    """Accepted R8-E evidence byte-preserved (every manifest row verifies).
    WRONG predecessor identity must fail closed."""
    import hashlib
    import os
    p = os.path.join(repo_root, R8E_MANIFEST)
    if not os.path.exists(p):
        return False, "manifest missing"
    n = 0
    for line in open(p):
        line = line.strip()
        if not line:
            continue
        digest, name = line.split("  ", 1)
        fp = os.path.join(repo_root, name)
        if not os.path.exists(fp):
            return False, name + " missing"
        got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
        if got != digest:
            return False, name + " digest mismatch"
        n += 1
    if n < 70:
        return False, "suspiciously small manifest (%d rows)" % n
    return True, "ok (%d rows)" % n


def load_r8e_pos0_row_sha(repo_root, arm):
    """Full 64-hex sha of the accepted R8-E case-4096 pos-0 float32 row,
    read from the retained R8-E capture record (never hand-copied)."""
    import glob
    import json
    import os
    pats = os.path.join(repo_root, R8E_DIR, "evidence", "observations",
                        "capture-case-4096-%s-obs1.json" % arm)
    with open(pats) as fh:
        d = json.load(fh)
    assert d["case"] == "case-4096" and d["arm"] == arm
    assert d["generated_position_observed"] == 0
    assert d["f32_row_sha256"].startswith(R8E_POS0_ROW_SHA256[arm]), \
        "R8-E pos-0 row sha drift for arm %s" % arm
    return d["f32_row_sha256"]


def serialize_request(prompt_ids, n_predict=8):
    """Deterministic canonical request serialization (identical rules to
    the accepted R8-D v2 / R8-E producers)."""
    import json
    body = dict(REQUEST_CONTRACT)
    body["prompt"] = list(prompt_ids)
    body["n_predict"] = n_predict
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode()


def producer_pins_ok(repo_root):
    import hashlib
    import json
    import os
    pins_p = os.path.join(repo_root, R8G_DIR, "producer-hashes.json")
    if not os.path.exists(pins_p):
        return False, "producer-hashes.json missing"
    pins = json.load(open(pins_p))
    for rel, want in pins.items():
        p = os.path.join(repo_root, rel)
        if not os.path.exists(p):
            return False, rel + " missing"
        got = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if got != want:
            return False, rel + " digest mismatch"
    return True, "ok"
