#!/usr/bin/env python3
"""Build Issue #115 RAW-EVIDENCE-RETENTION.json (Phase A manifest).

Pure stdlib; reads node inventory records gathered in this session and
derives every classification from the retention policy.  The generated
manifest is deterministic: same inputs -> same bytes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # repo root

ARCHIVE_OBJECT_MANIFEST_SHA = "15e1e437ecb8d505cbc7f29cdd5f91332e10b99ecfc6e525ce78e7a32e777ac2"
ARCHIVE_OBJECTS = 516
ARCHIVE_BYTES = 460854709

AUTHORITY = {
    "issue": 115,
    "cleanup_authority": "maintainer-accepted issue #115 (storage-cleanup-only) + accepted issue #110",
    "accepted_main": "546ff9d44c727b6eba5abf3c8b40669b0b9b0b76",
    "accepted_pr114_evidence_head": "47d9d78f645886e8d4199cfc885dd3ac8dded7a1",
    "terminal_adjudication_sha256": "f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70",
    "freetoken_merge": "b05564a7f3f7ca1b141d54842357ff2624dc6a19",
    "calibration_producer": "7e5c852163afd9aadfccc406be267e8d060e79ef",
    "holdout_producer": "924cd22ea081f6d4ed471016faf01d427fc5b0d2",
    "methodology": "bc6f0ec657d025702d5928771bf8f51aa563a8be",
    "terminal_disposition": "V5_QUALIFICATION_PASS (immutable; not reinterpreted by this cleanup)",
    "holdout_state": "h109 CONSUMED (single-use, permanent)",
}

# Verified node inventories (du -B1 --apparent-size, this campaign).
INVENTORY = {
    "inferswarm01:/srv/models/issue110": {
        "reference-copy": 133603070785,
        "candidate-laststage-copy": 237742009264,
        "candidate": 27308670274,
        "holdout-candidate (whole)": 2528567447,
        "holdout-candidate/reference": 2092071051,
        "holdout-candidate/<24 h109 case dirs>": 436494628,
        "holdout-candidate/logs": 1768,
        "holdout-candidate/index-hcand109.json": None,
        "holdout-candidate-laststage": 3822863704,
        "holdout-adjudication (whole)": 397582,
        "holdout-adjudication/observations": 178423,
        "holdout-adjudication-run2": 117174,
        "adjudication": 6555466,
        "observations": 10661996,
        "cpu-tools": 136904,
        "top-level files (corpus/pool/selection/scripts)": None,
    },
    "inferswarm01:/srv/inferswarm/state/issue110": {
        "calibration-corpus.json": 1042766,
        "stress-pool.json": 33119,
        "manifests/holdout-corpus.json": 17533,
    },
    "inferswarm03:/srv/models/issue110": {
        "candidate-laststage": 237742015982,
        "holdout-candidate-laststage": 3822870427,
        "case-list.txt": 21352,
    },
    "inferswarm04:/srv/inferswarm/state/issue110": {
        "reference (whole)": 133603308747,
        "reference/<case trees>": 133603070785,
        "reference/logs": 237962,
        "holdout-reference": 2092071051,
        "manifests/holdout-corpus.json": 17533,
        "calibration-corpus.json": 1042766,
        "stress-pool.json": 33119,
    },
    "inferswarm04:/srv/models/issue110": {"reference-copy (empty)": 0},
    "orchestrator": {
        "~/is110 (campaign scratch)": 63948049,
        "~/.local/share/inferswarm/issue109-holdout-v5-custody": 2553,
    },
    "inferswarm00": {
        "~/.local/share/inferswarm/issue109-holdout-v5-corrected-final": 2553,
    },
}

# Exact expunge targets (path-specific; never a coarse campaign root).
EXPUNGE = [
    # ---- inferswarm01: bulk calibration/stress reference + candidate copies ----
    {"host": "inferswarm01", "path": "/srv/models/issue110/reference-copy",
     "bytes": 133603070785,
     "reason": "duplicate calibration+stress reference materialization; the complete per-case compact evidence is committed (a2 calibration-summary) and the provenance-defining raw rows are durably archived"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/candidate-laststage-copy",
     "bytes": 237742009264,
     "reason": "candidate calibration/stress last-stage capture bundles + rows; compact per-case reducers committed; provenance rows archived"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/candidate",
     "bytes": 27308670274,
     "reason": "candidate chain stage1/stage2 capture bundles + duplicate reference tree; all correctness-bearing content in committed compact evidence + archive"},
    # ---- inferswarm01: holdout bulk after 384-row archive ----
    {"host": "inferswarm01", "path": "/srv/models/issue110/holdout-candidate/reference",
     "bytes": 2092071051,
     "reason": "h109 reference rows+case jsons (archived, producer-pin verified) + capture bundles (envelope content committed in b/holdout-rows.json)"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/holdout-candidate/<24 case dirs>",
     "bytes": 436494628,
     "reason": "h109 candidate stage1/stage2 bundles + case records (rows archived from laststage; case records archived)"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/holdout-candidate/logs",
     "bytes": 1768, "reason": "run log; identity content retained in archived run metadata"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/holdout-candidate/index-hcand109.json",
     "bytes": 4603, "reason": "run index; identity fields retained via archived case records + committed b/ artifacts"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/holdout-candidate-laststage",
     "bytes": 3822863704,
     "reason": "h109 candidate last-stage bundles + rows; all 192 candidate rows archived (producer-pin verified)"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/holdout-adjudication/observations",
     "bytes": 178423,
     "reason": "duplicate observation copies; identical content archived in h109-rows/<case>/observation.json"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/holdout-adjudication/assemble.log",
     "bytes": 1350, "reason": "assembly log; result committed (assembly-index 24/0)"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/holdout-adjudication-run2",
     "bytes": 117174,
     "reason": "byte-identical duplicate adjudication outputs (sha-verified equal to committed b/ artifacts)"},
    # ---- inferswarm01: derivations represented by committed compact evidence ----
    {"host": "inferswarm01", "path": "/srv/models/issue110/adjudication",
     "bytes": 6555466,
     "reason": "calibration-summary + semantic-accounting working copies; byte-equal content committed (a2) modulo canonicalization; scripts retained in git history and cpu-tools copy"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/observations",
     "bytes": 10661996,
     "reason": "per-case calibration observations; complete compact content committed in a2 calibration-summary (1424 cases)"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/cpu-tools",
     "bytes": 136904,
     "reason": "frozen-methodology script copies; byte-identical scripts live in the repository (scripts/) and the accepted producer history"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/assemble_calibration.py",
     "bytes": 9821, "reason": "orchestration script copy; retained in git history (accepted producer tree)"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/calib-case-ids.json",
     "bytes": 25488, "reason": "derived case-id list; derivable from committed corpus"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/calibration-corpus.json",
     "bytes": 1042766, "reason": "duplicate of committed public corpus (sha b35f1915…)"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/stress-pool.json",
     "bytes": 33119, "reason": "duplicate of committed stress pool (sha e54b10ae…)"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/selected-stress-eighth.json",
     "bytes": 6953, "reason": "duplicate of committed selection (sha 86ab5f0f…)"},
    {"host": "inferswarm01", "path": "/srv/models/issue110/stress-case-ids.json",
     "bytes": 136, "reason": "derived case-id list"},
    {"host": "inferswarm01", "path": "/srv/inferswarm/state/issue110/manifests/holdout-corpus.json",
     "bytes": 17533,
     "reason": "duplicate derived execution corpus (plaintext-derived); plaintext diagnostic copy retained restricted; corpus sha recorded"},
    # ---- inferswarm03 ----
    {"host": "inferswarm03", "path": "/srv/models/issue110/candidate-laststage",
     "bytes": 237742015982,
     "reason": "candidate calibration/stress last-stage bundles + rows; compact evidence committed; provenance rows archived"},
    {"host": "inferswarm03", "path": "/srv/models/issue110/holdout-candidate-laststage",
     "bytes": 3822870427,
     "reason": "h109 candidate last-stage bundles + rows; all 192 candidate rows archived"},
    {"host": "inferswarm03", "path": "/srv/models/issue110/case-list.txt",
     "bytes": 21352, "reason": "derived case list"},
    # ---- inferswarm04 ----
    {"host": "inferswarm04", "path": "/srv/inferswarm/state/issue110/reference",
     "bytes": 133603308747,
     "reason": "primary calibration+stress reference tree (rows+bundles); compact evidence committed; provenance rows archived"},
    {"host": "inferswarm04", "path": "/srv/inferswarm/state/issue110/holdout-reference",
     "bytes": 2092071051,
     "reason": "h109 reference tree; all 192 reference rows + case records archived (producer-pin verified)"},
    {"host": "inferswarm04", "path": "/srv/inferswarm/state/issue110/manifests/holdout-corpus.json",
     "bytes": 17533, "reason": "duplicate derived execution corpus (plaintext-derived)"},
    {"host": "inferswarm04", "path": "/srv/inferswarm/state/issue110/calibration-corpus.json",
     "bytes": 1042766, "reason": "duplicate of committed public corpus"},
    {"host": "inferswarm04", "path": "/srv/inferswarm/state/issue110/stress-pool.json",
     "bytes": 33119, "reason": "duplicate of committed stress pool"},
    {"host": "inferswarm04", "path": "/srv/models/issue110/reference-copy",
     "bytes": 0, "reason": "empty leftover directory"},
    # ---- orchestrator ----
    {"host": "orchestrator", "path": "/home/zutfen/is110",
     "bytes": 63948049,
     "reason": "campaign orchestration scratch (scripts mirrored in git history; a2/b artifacts committed; holdout-staging plaintext duplicated in the restricted diagnostic copy)"},
    # ---- custody secrets (holdout consumed; no fresh decrypt may remain possible) ----
    {"host": "orchestrator", "path": "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-custody/recipient-key.pem",
     "bytes": 2488,
     "reason": "V5 holdout recipient PRIVATE KEY copy; h109 permanently consumed; issue #115 preferred terminal state: no surviving material can freshly decrypt holdout.cms; public cert/ciphertext/commitments remain committed; issue #115 secret lifecycle"},
    {"host": "orchestrator", "path": "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-custody/secret-seed.txt",
     "bytes": 65,
     "reason": "V5 holdout SECRET SEED copy; destruction prevents regeneration of the consumed h109 cases; generator + public commitments remain committed; issue #115 secret lifecycle"},
    {"host": "inferswarm00", "path": "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-corrected-final/recipient-key.pem",
     "bytes": 2488, "reason": "custodian private-key copy (issue #115 secret lifecycle)"},
    {"host": "inferswarm00", "path": "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-corrected-final/secret-seed.txt",
     "bytes": 65, "reason": "custodian secret-seed copy (issue #115 secret lifecycle)"},
    {"host": "inferswarm01", "path": "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-corrected-final/recipient-key.pem",
     "bytes": 2488, "reason": "custodian private-key copy (issue #115 secret lifecycle)"},
    {"host": "inferswarm01", "path": "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-corrected-final/secret-seed.txt",
     "bytes": 65, "reason": "custodian secret-seed copy (issue #115 secret lifecycle)"},
]

# Objects that remain (kept) with classification.
RETAINED = {
    "retain_durable_raw_archive": {
        "description": "Content-addressed two-copy archive of every acceptance-bearing raw object",
        "layout": "/srv/inferswarm/archive/issue110-v5/sha256/<digest>",
        "copies": [
            {"host": "inferswarm01", "path": "/srv/inferswarm/archive/issue110-v5",
             "storage": "root SSD / (ext4)", "verified": "516/516 object sha256 exact, digest==filename"},
            {"host": "inferswarm03", "path": "/srv/inferswarm/archive/issue110-v5",
             "storage": "1.9 TB local SSD /srv/models-boundary disk (ext4, /dev/sda1)", "verified": "516/516 object sha256 exact, byte-identical to copy 1"},
        ],
        "object_manifest": "OBJECT-MANIFEST.json",
        "object_manifest_sha256": ARCHIVE_OBJECT_MANIFEST_SHA,
        "object_count": ARCHIVE_OBJECTS,
        "total_bytes": ARCHIVE_BYTES,
        "contents": {
            "h109-rows/<case>/{ref,cand}-decision-0..7.f32": "24 x 8 x 2 = 384 full-vocabulary FP32 consumer-logit rows (1 MiB each)",
            "h109-rows/<case>/reference-case-href109.json": "reference producer case record (row hashes, prefixes, trajectory, device identity)",
            "h109-rows/<case>/chain-case-hcand109.json": "candidate producer case record",
            "h109-rows/<case>/observation.json": "assembled per-case observation (reducers, domains, verdict inputs)",
            "threshold-provenance/<case>/...": "both arms x 8 decisions for c109-04-02-024, c109-02-03-030, p109-03-03-01 + case records",
            "run-metadata/": "calibration-summary, semantic-accounting, holdout-adjudication, holdout-rows, telemetry-reference-bands (byte-equal to committed a2/b artifacts)",
        },
        "independent_reverification": {
            "method": "recompute from archive rows only, frozen scripts @ accepted main 546ff9d, pure stdlib",
            "max_abs": "0x1.b480000000000p+3",
            "rms": "0x1.44dcfa4242a7ap+1",
            "decision_local_e_d": "0x1.4900000000000p+3",
            "semantic_accounting": "192/192 SEMANTIC_PASS reconstructed (unstable 192, zero failures of every class)",
            "threshold_provenance": "c109-04-02-024 -> statistical max-abs 0x1.d2p+4 + E_D 0x1.d2p+4; c109-02-03-030 -> statistical rms 0x1.7790ef6766a33p+3; p109-03-03-01 -> stress maxima 0x1.81p+3 / 0x1.007ddb6e479b5p+1 / 0x1.5ep+3 (all reproduced from raw rows)",
        },
    },
    "retain_private_diagnostic": {
        "description": "ONE restricted non-repository copy of the consumed h109 plaintext + derived execution corpus",
        "host": "orchestrator",
        "path": "/home/zutfen/.local/share/inferswarm/issue110-h109-consumed-diagnostic",
        "directory_mode": "0700",
        "file_mode": "0600",
        "marking": "CONSUMED_DIAGNOSTIC_ONLY (STATUS.txt); permanently ineligible as future calibration/stress/holdout evidence",
        "files": {
            "holdout-plaintext.json": {"sha256": "46abbd201dd007d8d6822b14e3b08879c8eac47c955b282cf3db5bd4e7703fc8", "bytes": 20270},
            "holdout-corpus.json": {"sha256": "5b0a5c8b560fd353d0fe20b21f73233bf7df9bac792b6de66fc0a49bd6d284fb", "bytes": 17533},
            "STATUS.txt": {"sha256": "68bd7c7dab71a4d7680ae28f6aab36938d0e7d7cdd9f2c1cc9c6e8931318d03b"},
        },
    },
    "retain_compact_derivation": {
        "description": "All accepted committed evidence/tooling on main (immutable); never an expungement target",
        "paths": [
            "docs/qualification/gemma4-12b-it-v5-campaign-110/ (a1, a2, preflight, b)",
            "docs/qualification/gemma4-12b-it-v5/ (frozen methodology, manifests, schemas, sealed ciphertext)",
            "scripts/ (frozen methodology implementations incl. issue109_v5_methodology.py, issue95_v4_methodology.py)",
            "benchmarks/ producer trees in Zutfen-LLC/FreeToken @ b05564a (calibration 7e5c852, holdout 924cd22)",
        ],
    },
    "fail_closed_keeps (unclassified)": [
        {"host": "inferswarm01", "path": "/srv/models/issue110/holdout-adjudication/{holdout-adjudication.json,holdout-rows.json,telemetry-reference-bands.json}",
         "reason": "byte-identical to committed b/ artifacts (sha f024f8b3… verified) — kept as in-place second copy until maintainer accepts the PR; not needed for retention"},
        {"host": "inferswarm01", "path": "/srv/inferswarm/state/issue110/manifests (dir)",
         "reason": "campaign root top-level manifests dir; its only file is separately classified"},
    ],
}

manifest = {
    "schema": "inferswarm.issue115.raw-evidence-retention/1",
    "authority": AUTHORITY,
    "node_inventory_bytes": INVENTORY,
    "classification_counts": {
        "RETAIN_DURABLE_RAW": f"{ARCHIVE_OBJECTS} archive objects ({ARCHIVE_BYTES} bytes) on 2 independent copies",
        "RETAIN_PRIVATE_DIAGNOSTIC": "3 files (orchestrator, 0700/0600)",
        "RETAIN_COMPACT_DERIVATION": "all committed repository evidence (never deleted)",
        "SAFE_TO_EXPUNGE_AFTER_ACCEPTANCE": f"{len(EXPUNGE)} path-specific targets",
        "UNCLASSIFIED_STOP": "2 fail-closed keeps",
    },
    "retained": RETAINED,
    "safe_to_expunge_after_acceptance": EXPUNGE,
    "expected_reclaim": {
        "inferswarm01": None,  # filled below
        "inferswarm03": None,
        "inferswarm04": None,
        "orchestrator": 63948049,
        "inferswarm00": 2553,
    },
    "notes": [
        "Sizes are du -B1 --apparent-size at classification time (2026-09-07).",
        "Deletion is path-specific only; /srv/models/issue110 and /srv/inferswarm/state/issue110 roots themselves are NEVER deletion targets.",
        "holdout-candidate/<24 case dirs> resolves to exactly the 24 enumerated h109-* directories; index-hcand109.json and logs are separately listed.",
        "All 384 h109 rows + all 48 provenance rows were verified against producer row_f32_sha256 pins before classification.",
        "Zero model/CUDA execution, zero evidence regeneration occurred in this cleanup.",
    ],
}

per_host = {}
for t in EXPUNGE:
    per_host[t["host"]] = per_host.get(t["host"], 0) + (t["bytes"] or 0)
manifest["expected_reclaim"].update({
    "inferswarm01": per_host.get("inferswarm01", 0),
    "inferswarm03": per_host.get("inferswarm03", 0),
    "inferswarm04": per_host.get("inferswarm04", 0),
    "orchestrator": per_host.get("orchestrator", 0),
    "inferswarm00": per_host.get("inferswarm00", 0),
    "total_bytes": sum(per_host.values()),
})

out = ROOT / "docs/qualification/gemma4-12b-it-v5-campaign-110/cleanup/RAW-EVIDENCE-RETENTION.json"
out.parent.mkdir(parents=True, exist_ok=True)
text = json.dumps(manifest, indent=1, sort_keys=True) + "\n"
out.write_text(text)
print("wrote", out)
print("bytes", len(text.encode()))
print("sha256", hashlib.sha256(text.encode()).hexdigest())
print("expected reclaim total:", per_host)
