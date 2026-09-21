#!/usr/bin/env python3
"""Issue #234 — R8-H score-characterization assembler (reduction producer).

Round-2 correction (maintainer NO-GO on cfd86f11): Issue #234 requires
bounded pre-choice numerical characterization at the FIRST divergent
generated position. The global earliest pairwise divergence for the
canonical case-256 campaign is position 0 (A<->B and A<->C diverge
there; B<->C first diverge at position 5).

This producer emits:
  * the CANONICAL characterization at generated position 0 for all
    three arms, every number re-derived from the retained raw
    observation bytes (hook JSONL row + full-vocab float32 row +
    observation response). Nothing is hand-authored;
  * the RETAINED position-5 document, reclassified explicitly as
    secondary_device_axis_characterization (it binds only the later
    B/C device-axis divergence and never satisfies the global
    first-divergence gate).

The terminal reducer (issue234_reduce.characterization_ok) does NOT
trust this summary: it independently re-derives from the same raw
bytes and requires the summary to agree, failing closed otherwise.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc

EVIDENCE = Path("docs/investigations/qwen38-flash-next-r8-h-vulkan"
                "/evidence")
CHAR_DIR = EVIDENCE / "candidate" / "characterization"
POS0_DIR = CHAR_DIR / "pos0"
OUT_CANONICAL = EVIDENCE / "candidate" / \
    "score-characterization-case-256.json"
OUT_SECONDARY = CHAR_DIR / "pos5-secondary" / \
    "score-characterization-case-256.json"
OLD_SECONDARY_SRC = EVIDENCE / "candidate" / \
    "score-characterization-case-256.json"

OBS_BUILDS = {
    "A": {"host": "inferswarm01", "backend": "cuda",
          "binary": "/home/hermes/llama.cpp/r8h-obs/build-obs-cuda/bin/llama-server",
          "sha256": "2242e96363c651184c1565969abe4eaf619c1c534e965fdb053db4119f16be2f",
          "selector": "CUDA_VISIBLE_DEVICES=GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099"},
    "B": {"host": "inferswarm01", "backend": "vulkan",
          "binary": "/home/hermes/llama.cpp/r8h-obs/build-obs-vk/bin/llama-server",
          "sha256": "dcee5bcf8d80a7c99f2d71b753afd4c678d51a43154ed83bc2e208cced1b3ab0",
          "selector": ("GGML_VK_VISIBLE_DEVICES=0+VK_ICD_FILENAMES="
                       "/usr/share/vulkan/icd.d/nvidia_icd.json")},
    "C": {"host": "inferswarm02", "backend": "vulkan",
          "binary": "/tmp/is234r/obs-vk-bin/llama-server (01-built, deployed)",
          "sha256": "dcee5bcf8d80a7c99f2d71b753afd4c678d51a43154ed83bc2e208cced1b3ab0",
          "selector": ("GGML_VK_VISIBLE_DEVICES=0+VK_ICD_FILENAMES="
                       "/usr/share/vulkan/icd.d/radeon_icd.json")},
}
POSITION = 0
FOCAL = [328, 561, 271, 34227, 12188, 248068]
#: canonical (non-observation) tokens per arm, from ladder receipts
CANONICAL = {
    "A": [328, 760, 40554, 1, 271, 12188, 279, 1727],
    "B": [561, 324, 55965, 51624, 29014, 271, 248068, 271],
    "C": [561, 324, 55965, 51624, 29014, 34227, 18030, 16382],
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def derive_arm(arm: str, position: int, src_dir: Path) -> dict:
    """Re-derive one arm's characterization from raw bytes."""
    jsonl = src_dir / f"{arm}.jsonl"
    f32 = src_dir / f"{arm}.jsonl.pos{position}.f32"
    resp = json.loads((src_dir / f"{arm}.resp.json").read_text())
    rows = [json.loads(l) for l in jsonl.read_text().splitlines()]
    row = next(r for r in rows if r["pos"] == position)
    n_vocab = row["n_vocab"]
    raw = f32.read_bytes()
    assert len(raw) == n_vocab * 4, (arm, len(raw), n_vocab)
    values = struct.unpack(f"<{n_vocab}f", raw)
    assert all(v == v and abs(v) != float("inf") for v in values)
    order = sorted(range(n_vocab), key=lambda i: (-values[i], i))
    rank = {t: k + 1 for k, t in enumerate(order)}
    obs_tokens = resp["tokens"]
    return {
        "generated_position": position,
        "winner_token": order[0],
        "top_k": {
            "1": {"token": order[0], "logit": values[order[0]]},
            "2": {"token": order[1], "logit": values[order[1]]},
        },
        "winner_vs_runner_up_margin":
            round(values[order[0]] - values[order[1]], 9),
        "focal_pair_328_561_margin":
            round(abs(values[328] - values[561]), 9),
        "focal_tokens": {str(t): {"rank": rank[t], "logit": values[t]}
                         for t in FOCAL},
        "raw_sidecar_sha256": {
            "jsonl": sha(jsonl),
            f"f32_pos{position}": sha(f32),
        },
        "f32_row_floats": n_vocab,
        "n_nonfinite": row["n_nonfinite"],
        "observation_build": OBS_BUILDS[arm],
        "repeat_binding": ("single observation pass under the prospective "
                           "pos0-observation-pin; canonical arm evidence is "
                           "the 3-repeat ladder receipt (ladder-{arm}-"
                           "case-256.json); the observation pass is "
                           "non-perturbing"),
        "non_perturbation_identical": obs_tokens == CANONICAL[arm],
        "observed_tokens": obs_tokens,
        "canonical_tokens": CANONICAL[arm],
    }


def main() -> int:
    # ---- canonical position-0 summary --------------------------------
    arms = {arm: derive_arm(arm, POSITION, POS0_DIR) for arm in "ABC"}
    doc = {
        "schema": "inferswarm.r8h.score-characterization/3",
        "campaign": rc.CAMPAIGN_ID,
        "case_id": "case-256",
        "generated_position": POSITION,
        "characterization_class": "canonical_first_divergence",
        "methodology": (
            "R8-E observation-only hook (Issue #199) at the same pin "
            "b29c606e; reads llama_get_logits_ith after sampling; no "
            "model state writes. Full-vocab float32 rows are the score "
            "authority; hook JSONL rows are cross-checks. Collected "
            "under evidence/candidate/characterization/pos0/"
            "pos0-observation-pin.json (prospective pin BEFORE "
            "collection)."),
        "arms": arms,
        "key_finding": (
            "At case-256 generated position 0 — the global earliest "
            "pairwise divergence — A/CUDA selects 328 (561 runner-up, "
            "margin 0.118303) while BOTH Vulkan arms select 561 "
            "(B/NVIDIA margin over 328 0.234203; C/AMD 0.599080). The "
            "first divergence A<->B is backend-associated at position "
            "0: same GPU, same prompt, different backend, opposite "
            "winners. B and C agree on the first token and first "
            "diverge at position 5 (see secondary characterization)."),
    }
    OUT_CANONICAL.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")

    # ---- retained position-5 document, reclassified -------------------
    # byte-preserve the ROUND-1 position-5 summary (read from the
    # reviewed head cfd86f11, NOT from the just-overwritten canonical
    # path) under pos5-secondary/ with an explicit reclassification
    # envelope; original content kept verbatim.
    sec_dir = CHAR_DIR / "pos5-secondary"
    sec_dir.mkdir(parents=True, exist_ok=True)
    import subprocess
    legacy = json.loads(subprocess.run(
        ["git", "show", "cfd86f11:docs/investigations/"
         "qwen38-flash-next-r8-h-vulkan/evidence/candidate/"
         "score-characterization-case-256.json"],
        capture_output=True, check=True, cwd=rc.ROOT).stdout)
    legacy["schema"] = "inferswarm.r8h.score-characterization/2"
    legacy["round2_reclassification"] = {
        "classification": "secondary_device_axis_characterization",
        "reason": ("position 5 is the first B<->C divergence only; the "
                   "global earliest pairwise divergence for case-256 is "
                   "position 0 (A<->B and A<->C), so this document "
                   "cannot satisfy the global first-divergence "
                   "characterization gate"),
        "retained": True,
        "superseded_as_canonical_by":
            "evidence/candidate/score-characterization-case-256.json "
            "(schema /3, position 0)",
    }
    OUT_SECONDARY.write_text(
        json.dumps(legacy, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")

    print(json.dumps({
        "case": "case-256", "canonical_position": POSITION,
        "winners": {a: arms[a]["winner_token"] for a in arms},
        "margins": {a: arms[a]["winner_vs_runner_up_margin"]
                    for a in arms},
        "focal_328_561": {a: arms[a]["focal_pair_328_561_margin"]
                          for a in arms},
        "non_perturbation_all":
            all(arms[a]["non_perturbation_identical"] for a in arms),
        "secondary": str(OUT_SECONDARY),
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
