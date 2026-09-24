#!/usr/bin/env python3
"""Issue #241 — comparator/2 continuous canonical-reference-prefix
observer seam (R8-I3).

The comparator/2 observer is an EXACT-SOURCE-DERIVED patch on llama.cpp
pin b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 applied ON TOP of the
accepted R8-E observation patch (retained verbatim, proving coexistence
and non-perturbation of the accepted path). This module carries the
exact patch text, applies it to a clean checkout, and is the single
source of truth for the observer source identity frozen in
docs/qualification/qwen38-vulkan-v2-rx580/.

Physical semantics (frozen prospectively before ANY retained capture):

  Reference arm — one continuous request:
    LLAMA_OBSERVE_CAPTURE=<n>   capture the first n generated positions'
                                full-vocabulary FP32 consumer rows
    (the sampled greedy winner IS the reference winner; it is appended
    to live state naturally by the sampler)

  Candidate arm — one continuous request:
    LLAMA_OBSERVE_FORCE=t0,t1,… teacher-force these REFERENCE tokens
                                AFTER each row is captured; the live
    state evolves continuously per the candidate implementation while
    every acceptance-bearing decision is evaluated on the same
    reference token prefix.

Inert when LLAMA_OBSERVE_CAPTURE is unset/zero: no file writes, no
forcing, no deviation from the pinned behavior.

Forcing happens after capture and before common_sampler_accept, so the
candidate prefix equals the reference canonical prefix exactly while the
recurrent state evolves continuously; the captured row is the untouched
consumer row for that prefix.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

LLAMA_CPP_PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
TARGET = "tools/server/server-context.cpp"

R8E_ACCEPTED_PATCH_REL = (
    "docs/investigations/qwen38-flash-next-r8-e/evidence/instrumentation/"
    "applied-source.patch")
R8E_ACCEPTED_PATCH_SHA256 = (
    "058674419daa1189b25b80e99278001e437827a97c9a2d68ed7e24f03df0d659")

HOOK_FUNCTION = r'''
// ---------------------------------------------------------------------------
// R8-I3 comparator/2 continuous observation seam (Issue #241).
// Inert unless LLAMA_OBSERVE_CAPTURE is set to a positive count.
// Captures the first <n> per-request generated positions'
// full-vocabulary FP32 consumer rows in ONE continuous request;
// optionally teacher-forces the frozen REFERENCE prefix AFTER each row
// is captured (LLAMA_OBSERVE_FORCE, candidate arm). Reads only the
// logits row the sampler just consumed (same read pattern as the
// accepted R8-E hook).
// Single-request capture session: requests are strictly sequential.
// ---------------------------------------------------------------------------
static llama_token r8i3_capture_and_force(struct llama_context * ctx,
                                          const int idx,
                                          const int gen_pos,
                                          const llama_token sampled) {
    static const int capture_count = []() {
        const char * c = std::getenv("LLAMA_OBSERVE_CAPTURE");
        if (!c || !c[0]) { return 0; }
        try { return std::stoi(c); } catch (...) { return 0; }
    }();
    static const std::string out_path =
        std::getenv("LLAMA_OBSERVE_OUT") ? std::getenv("LLAMA_OBSERVE_OUT") : "";
    static const std::vector<llama_token> force_tokens = []() {
        std::vector<llama_token> v;
        if (const char * f = std::getenv("LLAMA_OBSERVE_FORCE")) {
            std::istringstream is(f);
            std::string item;
            while (std::getline(is, item, ',')) {
                try { v.push_back((llama_token) std::stoi(item)); } catch (...) {}
            }
        }
        return v;
    }();
    if (capture_count <= 0 || out_path.empty()) { return sampled; }
    if (gen_pos < 0 || gen_pos >= capture_count) { return sampled; }

    const float * logits = nullptr;
    try { logits = llama_get_logits_ith(ctx, idx); } catch (...) { logits = nullptr; }
    if (!logits) { return sampled; }  // fail closed: no row, no force
    const int n_vocab =
        llama_vocab_n_tokens(llama_model_get_vocab(llama_get_model(ctx)));

    llama_token forced = sampled;
    bool did_force = false;
    if (gen_pos < (int) force_tokens.size()) {
        forced = force_tokens[gen_pos];
        did_force = true;
    }

    {
        std::string dst = out_path + ".row" + std::to_string(gen_pos) + ".f32";
        std::string tmp = dst + ".tmp";
        {
            std::ofstream f(tmp, std::ios::binary);
            f.write((const char *) logits,
                    (std::streamsize) n_vocab * sizeof(float));
        }
        std::filesystem::rename(tmp, dst);
    }
    {
        std::ofstream m(out_path + ".meta.json", std::ios::app);
        m << "{\"pos\": " << gen_pos
          << ", \"sampled_winner\": " << sampled
          << ", \"forced_token\": " << (did_force ? (long long) forced : -1)
          << ", \"n_vocab\": " << n_vocab << "}\n";
    }
    return forced;
}
'''

WIRE_OLD = """                id = common_sampler_sample(slot.smpl.get(), slot.ctx_tgt, tok_idx);
                // R8-E observation-only (Issue #199): reads the same
                // logits row the sampler consumed; no state writes.
                r8e_observe_logits(slot.ctx_tgt, tok_idx,
                                   (int) slot.stats.n_gen, id);
            }"""

WIRE_NEW = """                id = common_sampler_sample(slot.smpl.get(), slot.ctx_tgt, tok_idx);
                // R8-E observation-only (Issue #199): reads the same
                // logits row the sampler consumed; no state writes.
                r8e_observe_logits(slot.ctx_tgt, tok_idx,
                                   (int) slot.stats.n_gen, id);
                // R8-I3 comparator/2 observer (Issue #241): capture the
                // untouched row BEFORE any forcing, then teacher-force
                // the REFERENCE token for this decision (candidate arm).
                id = r8i3_capture_and_force(slot.ctx_tgt, tok_idx,
                                            (int) slot.stats.n_gen, id);
            }"""

INCLUDE_ANCHOR = "#include <fstream>\n"
INCLUDE_NEW = ("#include <fstream>\n"
               "#include <filesystem>\n"
               "#include <vector>\n")


def validate_capture_force_order(hook_function: str = HOOK_FUNCTION,
                                 wire: str = WIRE_NEW) -> None:
    """Fail closed unless the untouched consumer row is written before force."""
    capture = hook_function.find("f.write((const char *) logits")
    force = hook_function.find("return forced;")
    if capture < 0 or force < 0 or capture > force:
        raise RuntimeError("capture must precede force")
    sample_at = wire.find("common_sampler_sample")
    observe_at = wire.find("r8e_observe_logits")
    force_at = wire.find("r8i3_capture_and_force")
    if (min(sample_at, observe_at, force_at) < 0 or
            not sample_at < observe_at < force_at or
            wire.count("r8i3_capture_and_force") != 1):
        raise RuntimeError("observer call order must be sample, observe, capture/force")


def apply(r8e_patched_source: str) -> str:
    """Apply the R8-I3 seam to source that already carries the accepted
    R8-E patch. Idempotent; fails closed on anchor drift."""
    if "r8i3_capture_and_force" in r8e_patched_source:
        raise RuntimeError("R8-I3 hook already present (double apply)")
    validate_capture_force_order(HOOK_FUNCTION, WIRE_NEW)
    src = r8e_patched_source
    if src.count(INCLUDE_ANCHOR) != 1:
        raise RuntimeError("include anchor drift")
    src = src.replace(INCLUDE_ANCHOR, INCLUDE_NEW, 1)
    hook_at = src.find("// fix problem with std::min and std::max")
    if hook_at < 0:
        raise RuntimeError("hook insertion anchor drift")
    src = src[:hook_at] + HOOK_FUNCTION + "\n" + src[hook_at:]
    if src.count(WIRE_OLD) != 1:
        raise RuntimeError("wire anchor drift")
    src = src.replace(WIRE_OLD, WIRE_NEW, 1)
    return src


def patched_source_sha256(r8e_patched_source: str) -> str:
    return hashlib.sha256(apply(r8e_patched_source).encode()).hexdigest()


def verify_r8e_patch(patch_path: Path) -> None:
    data = patch_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != R8E_ACCEPTED_PATCH_SHA256:
        raise RuntimeError(
            f"R8-E accepted patch drift: {digest} != {R8E_ACCEPTED_PATCH_SHA256}")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--source", type=Path, required=True,
                    help="server-context.cpp already carrying the R8-E patch")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    src = args.source.read_text()
    out = apply(src)
    args.out.write_text(out)
    print(f"patched source written: {args.out}")
    print(f"patched source sha256: {hashlib.sha256(out.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
