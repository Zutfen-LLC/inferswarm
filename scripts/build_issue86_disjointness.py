#!/usr/bin/env python3
"""Build the v3 mechanical disjointness proof and print frozen identities."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from issue74_methodology import canonical_json_bytes, sha256_bytes

V1 = ROOT / "docs/qualification/gemma4-12b-it-v1"
V2 = ROOT / "docs/qualification/gemma4-12b-it-v2"
V3 = ROOT / "docs/qualification/gemma4-12b-it-v3"


def hashes(cases):
    return ({c["prompt_sha256"] for c in cases}, {c["token_ids_sha256"] for c in cases})


v3cal = json.loads((V3 / "manifests/calibration-corpus.json").read_text())
v3pool = json.loads((V3 / "manifests/stress-pool.json").read_text())
assert len(v3cal["cases"]) == 576 and all(c["case_id"].startswith("c86-") for c in v3cal["cases"])
assert len(v3pool["cases"]) == 48 and all(c["case_id"].startswith("p86-") for c in v3pool["cases"])

prior = {
    "c74-calibration-corpus": json.loads((V1 / "manifests/calibration-corpus.json").read_text())["cases"],
    "p74-v1-stress-pool": json.loads((V1 / "manifests/margin-stress-pool.json").read_text())["cases"],
    "p76-v2-stress-pool": json.loads((V2 / "manifests/margin-stress-pool.json").read_text())["cases"],
    "h74-holdout-public-commitment": json.loads((V1 / "manifests/sealed-holdout-commitment.json").read_text())["cells"],
}

report = {
    "schema": "inferswarm.issue86.v3-disjointness-proof/1",
    "contract_id": "inferswarm.gemma4-heterogeneous-numerical-equivalence/1",
    "method": "set intersection of prompt_sha256 and token_ids_sha256 against each listed public artifact; empty intersection required for both hash kinds",
    "v3_artifacts": ["c86-* 576-case calibration corpus", "p86-* 48-case stress pool"],
    "checked_against": [
        {"artifact": name, "case_count": len(cases),
         "prompt_sha256_overlap": 0, "token_ids_sha256_overlap": 0}
        for name, cases in prior.items()
    ],
}
v3calh, v3poolh = hashes(v3cal["cases"]), hashes(v3pool["cases"])
rows = []
for name, cases in prior.items():
    p, t = hashes(cases)
    for label, (pp, tt) in (("c86-calibration", v3calh), ("p86-stress-pool", v3poolh)):
        rows.append((name, label, len(p & pp), len(t & tt)))
for r in rows:
    assert r[2] == 0 and r[3] == 0, f"OVERLAP: {r}"
assert not (v3calh[0] & v3poolh[0]) and not (v3calh[1] & v3poolh[1]), "v3 internal overlap"
report["v3_internal_disjoint"] = True
report["verdict"] = "MECHANICALLY_DISJOINT"
(V3 / "manifests/disjointness-proof.json").write_bytes(canonical_json_bytes(report))

cal_ids = sorted(c["case_id"] for c in v3cal["cases"])
pool_ids = sorted(c["case_id"] for c in v3pool["cases"])
print("cal_corpus_sha", sha256_bytes(canonical_json_bytes(v3cal)))
print("pool_sha", sha256_bytes(canonical_json_bytes(v3pool)))
print("cal_case_ids_sha", sha256_bytes(canonical_json_bytes(cal_ids)))
print("cal_case_identities_sha", sha256_bytes(canonical_json_bytes(
    [{"case_id": c["case_id"], "case_sha256": c["case_sha256"]}
     for c in sorted(v3cal["cases"], key=lambda c: c["case_id"])])))
print("pool_case_ids_sha", sha256_bytes(canonical_json_bytes(pool_ids)))
print("pool_case_identities_sha", sha256_bytes(canonical_json_bytes(
    [{"case_id": c["case_id"], "case_sha256": c["case_sha256"]}
     for c in sorted(v3pool["cases"], key=lambda c: c["case_id"])])))
