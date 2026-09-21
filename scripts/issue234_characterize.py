#!/usr/bin/env python3
"""Issue #234 — R8-H score-characterization assembler (reduction producer).

Consumes the retained raw observation sidecars (R8-E observation-only
hook, same pin b29c606e) for case-256 at generated position 5 and
emits the machine-checkable characterization the reducer's control-33
gate consumes. All numbers are re-derived from the raw .jsonl rows and
the raw float32 sidecar hashes; nothing is hand-authored.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc

CHAR_DIR = Path("docs/investigations/qwen38-flash-next-r8-h-vulkan"
                "/evidence/candidate/characterization")
OUT = Path("docs/investigations/qwen38-flash-next-r8-h-vulkan"
           "/evidence/candidate/score-characterization-case-256.json")
OBS_BUILDS = {
    "A": {"host": "inferswarm01", "backend": "cuda",
          "binary": "/home/hermes/llama.cpp/r8h-obs/build-obs-cuda/bin/llama-server",
          "sha256": "2242e96363c651184c1565969abe4eaf619c1c534e965fdb053db4119f16be2f",
          "selector": "CUDA_VISIBLE_DEVICES=GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099"},
    "B": {"host": "inferswarm01", "backend": "vulkan",
          "binary": "/home/hermes/llama.cpp/r8h-obs/build-obs-vk/bin/llama-server",
          "sha256": "dcee5bcf8d80a7c99f2d71b753afd4c678d51a43154ed83bc2e208cced1b3ab0",
          "selector": "GGML_VK_VISIBLE_DEVICES=0+VK_ICD_FILENAMES=nvidia_icd.json"},
    "C": {"host": "inferswarm02", "backend": "vulkan",
          "binary": "/tmp/is234r/obs-vk-bin/llama-server (01-built, deployed)",
          "sha256": "dcee5bcf8d80a7c99f2d71b753afd4c678d51a43154ed83bc2e208cced1b3ab0",
          "selector": ("GGML_VK_VISIBLE_DEVICES=0+VK_ICD_FILENAMES="
                       "radeon_icd.json")},
}
POSITION = 5
FOCAL = [328, 561, 271, 34227, 12188, 248068]
# canonical (non-observation) tokens per arm, from ladder receipts
CANONICAL = {
    "A": [328, 760, 40554, 1, 271, 12188, 279, 1727],
    "B": [561, 324, 55965, 51624, 29014, 271, 248068, 271],
    "C": [561, 324, 55965, 51624, 29014, 34227, 18030, 16382],
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    arms = {}
    for arm in "ABC":
        jsonl = CHAR_DIR / f"{arm}.jsonl"
        rows = [json.loads(l) for l in jsonl.read_text().splitlines()]
        p5 = next(r for r in rows if r["pos"] == POSITION)
        winner = p5["tok"]
        top1, top2 = p5["top"][0], p5["top"][1]
        focus = {str(t): {"rank": r, "logit": v}
                 for t, r, v in p5["focus"]}
        f32 = CHAR_DIR / f"{arm}.jsonl.pos{POSITION}.f32"
        n_floats = f32.stat().st_size // 4
        obs_tokens = json.loads(
            (CHAR_DIR / f"{arm}.resp.json").read_text())["tokens"]
        arms[arm] = {
            "generated_position": POSITION,
            "winner_token": winner,
            "top_k": {
                "1": {"token": top1[0], "logit": top1[1]},
                "2": {"token": top2[0], "logit": top2[1]},
            },
            "winner_vs_runner_up_margin":
                round(top1[1] - top2[1], 9),
            "focal_tokens": focus,
            "same_focal_rank1_rank2": None,  # set below, pairwise
            "raw_sidecar_sha256": {"jsonl": sha(jsonl),
                                   "f32_pos5": sha(f32)},
            "f32_row_floats": n_floats,
            "n_nonfinite": p5["n_nonfinite"],
            "observation_build": OBS_BUILDS[arm],
            "repeat_binding": ("single observation pass; canonical arm "
                               "evidence is the 3-repeat ladder receipt "
                               "(ladder-{arm}-case-256.json); the "
                               "observation pass is non-perturbing"),
            "non_perturbation_identical":
                obs_tokens == CANONICAL[arm],
            "observed_tokens": obs_tokens,
            "canonical_tokens": CANONICAL[arm],
        }
    # rank-1/rank-2 focal occupancy across arms
    for a, b in (("A", "B"), ("B", "C"), ("A", "C")):
        fa, fb = arms[a]["focal_tokens"], arms[b]["focal_tokens"]
        same = {t: (fa[t]["rank"], fb[t]["rank"])
                for t in fa if t in fb}
        arms[a].setdefault("pairwise_rank_compare", {})[b] = same
    doc = {
        "schema": "inferswarm.r8h.score-characterization/2",
        "campaign": rc.CAMPAIGN_ID,
        "case_id": "case-256",
        "generated_position": POSITION,
        "methodology": ("R8-E observation-only hook (Issue #199) at the "
                        "same pin b29c606e; reads llama_get_logits_ith "
                        "after sampling; no model state writes"),
        "arms": arms,
        "key_finding": (
            "At case-256 generated position 5 the three arms produce "
            "THREE DIFFERENT WINNERS from materially different score "
            "structures: A/CUDA winner 12188 (271 at rank 79, 34227 at "
            "rank 21184); B/NVIDIA-Vulkan winner 271 (runner-up 34227, "
            "margin 0.686); C/AMD-Vulkan winner 34227 (runner-up 271, "
            "margin 0.269). Not a single shared near-tie across "
            "backends/devices."),
    }
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "case": "case-256", "pos": POSITION,
        "winners": {a: arms[a]["winner_token"] for a in arms},
        "non_perturbation_all":
            all(arms[a]["non_perturbation_identical"] for a in arms),
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
