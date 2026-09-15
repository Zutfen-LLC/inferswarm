"""Issue #199 R8-E: frozen authority constants for the bounded residual
true-greedy divergence characterization campaign (case-256 / case-4096
decision points ONLY; no requalification).

Accepted predecessor (immutable, never rewritten):
  Issue #195 / PR #197, merged f142a0d9b693f999685960c641b2a8fe362c4e1e
  (reviewed head ca7e159929190a04cabd059042def1b6bd4c2467),
  terminal R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL.

This campaign is diagnostic, not adjudicative: it characterizes the two
residual true-greedy branches immediately before token choice and
answers, per case, margin-inversion vs materially-different score
structure. It does NOT rerun or reinterpret R8-D, does NOT repair
llama.cpp, and does NOT create any successor issue.
"""

# Starting point
START_MAIN = "f142a0d9b693f999685960c641b2a8fe362c4e1e"  # PR #197 merge
BRANCH = "issue-199-r8e-residual-divergence"
ISSUE = 199

# Accepted predecessor identity
R8D_V2_DIR = "docs/investigations/qwen38-flash-next-r8-d-v2"
R8D_V2_MANIFEST = R8D_V2_DIR + "/MANIFEST.sha256"
R8D_V2_TERMINAL = "R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL"
R8D_V2_REVIEWED_HEAD = "ca7e159929190a04cabd059042def1b6bd4c2467"
R8D_V2_MERGE = "f142a0d9b693f999685960c641b2a8fe362c4e1e"

# Runtime authority (identical to accepted R8-D v2 pins; this campaign
# changes NO runtime bytes for execution — see DIAGNOSTIC below)
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

# Frozen topology (accepted R8-D v2; re-verified fresh at R8-E freeze)
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
REFERENCE_PORT = 8331   # R8-E observation arm, inferswarm01 loopback
CANDIDATE_PORT = 8333   # R8-E observation arm client, inferswarm01 loopback

# Frozen placements (identical to accepted R8-D v2 launch semantics)
# reference: single-host llama-server on inferswarm01, NO RPC
# candidate: client llama-server on inferswarm01 + 3 RPC backends
#            (03:50052 CUDA0, 03:50053 CUDA1, 04:50052 CUDA0)

# Request contract — IDENTICAL to accepted R8-D v2 (canonical
# true-greedy). The observation capture uses the same contract; the
# diagnostic hook observes, never alters, the request semantics.
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

# The two bounded decision points (accepted R8-D v2 retained bytes are
# the source of every identity below; loaded mechanically by producers
# via load_decision_inputs() — never hand-copied).
CASES = ["case-256", "case-4096"]
R8D_RUN_RECORDS = {
    "reference": R8D_V2_DIR + "/evidence/reference/ref-run-1.json",
    "candidate": R8D_V2_DIR + "/evidence/candidate/cand-run-1.json",
}
# case-256: prompt + accepted common generated prefix positions 0..4
CASE256_PREFIX = [561, 324, 55965, 51624, 29014]
# case-256 divergence at generated position 5: reference 271 vs candidate 34227
CASE256_REF_TOKEN = 271
CASE256_CAND_TOKEN = 34227
# case-4096: 4097-token prompt, no prefix; first generated token
# reference 328 vs candidate EOS 248046 (<|im_end|>)
CASE4096_REF_TOKEN = 328
CASE4096_CAND_TOKEN = 248046

# Evidence namespace (fresh, additive)
R8E_DIR = "docs/investigations/qwen38-flash-next-r8-e"
R8E_EV = R8E_DIR + "/evidence"

# Repeat contract (observation-path stability; NOT a qualification ladder)
OBSERVATION_REPEATS = 2

# Observation producer contract
TOP_K_OBSERVED = 16          # retained top-16 rows per decision point
FOCUS_TOKENS = {
    "case-256": [271, 34227],
    "case-4096": [328, 248046],
}

# Terminals (exactly one)
TERMINAL_CHARACTERIZED = "R8E_RESIDUAL_DIVERGENCE_CHARACTERIZED"
TERMINAL_LOCALIZATION_JUSTIFIED = "R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED"
TERMINAL_BLOCKED = "R8E_EVIDENCE_BLOCKED"

# Campaign identity
CAMPAIGN_ID = "issue199-r8e-residual-divergence"

# Evidence record schema
OBS_SCHEMA = "inferswarm.issue199.observation/1"

# Producers whose bytes are pinned at the R8-E authority freeze (paths
# relative to repo root).
R8E_PRODUCERS = (
    "scripts/issue199_r8e_authority.py",
    "scripts/issue199_r8e_launch.py",
    "scripts/issue199_r8e_capture.py",
    "scripts/issue199_r8e_terminal_reduction.py",
    "scripts/issue199_r8e_negative_controls.py",
    "scripts/issue199_r8e_manifest.py",
)

# Diagnostic instrumentation (Phase 1). The observation build is a
# separately named binary; the accepted binary is used UNCHANGED for all
# token-equality (non-perturbation) proofs.
DIAGNOSTIC_NAME = "llama-server-obs"
DIAGNOSTIC_BUILD_HOST = "inferswarm01"
DIAGNOSTIC_SOURCE_BASE = "/home/hermes/llama.cpp"
DIAGNOSTIC_BUILD_DIR = "/home/hermes/llama.cpp/build-obs"
# sha256 of the instrumentation patch (patch file itself retained under
# evidence/instrumentation/) — filled by issue199_r8e_capture.py freeze
# step and pinned in evidence/instrumentation/instrumentation.json.


def load_decision_inputs(repo_root):
    """Mechanically load exact case prompts + accepted generated tokens
    from the accepted R8-D v2 retained run bytes (never hand-copied)."""
    import json
    import os
    out = {}
    for arm, rel in R8D_RUN_RECORDS.items():
        with open(os.path.join(repo_root, rel)) as fh:
            d = json.load(fh)
        for r in d["results"]:
            cid = r["case_id"]
            if cid in CASES:
                out.setdefault(cid, {})[arm] = {
                    "prompt_token_ids": r["prompt_token_ids"],
                    "generated_tokens":
                        r["parsed_from_retained_bytes"]["generated_tokens"],
                    "stop_type":
                        r["parsed_from_retained_bytes"]["stop_type"],
                }
    missing = [(c, a) for c in CASES for a in ("reference", "candidate")
               if a not in out.get(c, {})]
    if missing:
        raise RuntimeError("missing accepted run records: %r" % missing)
    # hard identity assertions against the frozen predecessor facts
    c256 = out["case-256"]
    assert c256["reference"]["generated_tokens"][:5] == CASE256_PREFIX
    assert c256["candidate"]["generated_tokens"][:5] == CASE256_PREFIX
    assert c256["reference"]["generated_tokens"][5] == CASE256_REF_TOKEN
    assert c256["candidate"]["generated_tokens"][5] == CASE256_CAND_TOKEN
    assert len(out["case-4096"]["reference"]["prompt_token_ids"]) == 4097
    assert out["case-4096"]["reference"]["generated_tokens"][0] == \
        CASE4096_REF_TOKEN
    assert out["case-4096"]["candidate"]["generated_tokens"][0] == \
        CASE4096_CAND_TOKEN
    assert out["case-4096"]["candidate"]["stop_type"] == "eos"
    return out


def r8d_v2_manifest_ok(repo_root):
    """Accepted R8-D v2 evidence is byte-preserved (every manifest row
    verifies). WRONG predecessor identity must fail closed."""
    import hashlib
    import os
    p = os.path.join(repo_root, R8D_V2_MANIFEST)
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
    if n < 30:
        return False, "suspiciously small manifest (%d rows)" % n
    return True, "ok (%d rows)" % n


def serialize_request(prompt_ids, n_predict=8):
    """Deterministic canonical request serialization (identical rules to
    the accepted R8-D v2 producer: sorted keys, compact separators,
    ASCII) — byte-identical requests across arms and campaigns."""
    import json
    body = dict(REQUEST_CONTRACT)
    body["prompt"] = list(prompt_ids)
    body["n_predict"] = n_predict
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode()


def producer_pins_ok(repo_root):
    """Every R8-E producer file matches its pinned digest (dict source:
    r8-e/producer-hashes.json)."""
    import hashlib
    import json
    import os
    pins_p = os.path.join(repo_root, R8E_DIR, "producer-hashes.json")
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
