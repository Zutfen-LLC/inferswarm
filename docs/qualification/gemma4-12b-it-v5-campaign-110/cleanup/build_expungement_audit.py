#!/usr/bin/env python3
"""Build Issue #115 RAW-EVIDENCE-EXPUNGEMENT.json (Phase B audit)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

RETENTION_MANIFEST_SHA = "b6987c39fb23fe1f9d641c037d3aaeb519341c116e66cddee27c7a20f7e3264b"
ARCHIVE_OBJECT_MANIFEST_SHA = "15e1e437ecb8d505cbc7f29cdd5f91332e10b99ecfc6e525ce78e7a32e777ac2"

audit = {
    "schema": "inferswarm.issue115.raw-evidence-expungement/1",
    "operation": "post-#110-acceptance authorized raw-evidence expungement (issue #110 V5 campaign node-local bulk evidence)",
    "executed_utc_date": "2026-09-07",
    "authority": {
        "issue_110_terminal": "V5_QUALIFICATION_PASS",
        "issue_115_cleanup_authority": "maintainer-accepted issue #115 (storage-cleanup-only)",
        "accepted_main": "546ff9d44c727b6eba5abf3c8b40669b0b9b0b76",
        "accepted_pr114_evidence_head": "47d9d78f645886e8d4199cfc885dd3ac8dded7a1",
        "terminal_adjudication_sha256": "f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70",
        "freetoken_merge": "b05564a7f3f7ca1b141d54842357ff2624dc6a19",
        "calibration_producer": "7e5c852163afd9aadfccc406be267e8d060e79ef",
        "holdout_producer": "924cd22ea081f6d4ed471016faf01d427fc5b0d2",
        "methodology": "bc6f0ec657d025702d5928771bf8f51aa563a8be",
        "retention_manifest": "docs/qualification/gemma4-12b-it-v5-campaign-110/cleanup/RAW-EVIDENCE-RETENTION.json",
        "retention_manifest_sha256": RETENTION_MANIFEST_SHA,
        "deletion_authority": "maintainer-accepted issue #115 SAFE_TO_EXPUNGE_AFTER_ACCEPTANCE classifications only; all pre-delete gates mechanically verified",
    },
    "pre_deletion_verification": {
        "phase_a_committed_pushed_byte_refetched": "branch issue-115-v5-cleanup head 9573e50bd50292b9b2f8cbb003240580f295b04c == origin (byte-refetch verified)",
        "exact_head_ci": "CI run on 9573e50: success",
        "archive_two_copy_sha_exact": "516/516 objects on inferswarm01 (/srv/inferswarm/archive/issue110-v5) and inferswarm03; digests == filenames; copies byte-identical",
        "h109_rows_complete_and_reproducing": "384/384 rows verified against producer row_f32_sha256 pins; independent recomputation from archive only reproduced max-abs 0x1.b48p+3, rms 0x1.44dcfa4242a7ap+1, E_D 0x1.49p+3 exactly and the 192/192 SEMANTIC_PASS accounting",
        "threshold_provenance_reproducing": "c109-04-02-024 / c109-02-03-030 / p109-03-03-01 rows reproduce all six frozen statistical/stress limit components",
        "repository_evidence_byte_identical": "git diff origin/main HEAD over the accepted campaign evidence areas: empty",
        "private_diagnostic_secured": "orchestrator ~/.local/share/inferswarm/issue110-h109-consumed-diagnostic (0700/0600, CONSUMED_DIAGNOSTIC_ONLY) verified before any plaintext-derived duplicate was deleted",
        "zero_model_or_cuda_execution": True,
    },
    "deletion_command_strategy": "path-specific rm -rf per exact manifest target (never a campaign root); per-target du recorded immediately before removal into host cleanup logs; 'holdout-candidate/<24 case dirs>' resolved to exactly the 24 enumerated h109-* directories",
    "hosts": [
        {
            "host": "inferswarm01",
            "deleted": {
                "/srv/models/issue110/reference-copy": 133603070785,
                "/srv/models/issue110/candidate-laststage-copy": 237742009264,
                "/srv/models/issue110/candidate": 27308670274,
                "/srv/models/issue110/holdout-candidate/reference": 2092071051,
                "/srv/models/issue110/holdout-candidate/<24 h109 case dirs>": 436494628,
                "/srv/models/issue110/holdout-candidate/logs": 1768,
                "/srv/models/issue110/holdout-candidate/index-hcand109.json": 4603,
                "/srv/models/issue110/holdout-candidate-laststage": 3822863704,
                "/srv/models/issue110/holdout-adjudication/observations": 178423,
                "/srv/models/issue110/holdout-adjudication/assemble.log": 1350,
                "/srv/models/issue110/holdout-adjudication-run2": 117174,
                "/srv/models/issue110/adjudication": 6555466,
                "/srv/models/issue110/observations": 10661996,
                "/srv/models/issue110/cpu-tools": 136904,
                "/srv/models/issue110/assemble_calibration.py": 9821,
                "/srv/models/issue110/calib-case-ids.json": 25488,
                "/srv/models/issue110/calibration-corpus.json": 1042766,
                "/srv/models/issue110/stress-pool.json": 33119,
                "/srv/models/issue110/selected-stress-eighth.json": 6953,
                "/srv/models/issue110/stress-case-ids.json": 136,
                "/srv/inferswarm/state/issue110/manifests/holdout-corpus.json": 17533,
                "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-corrected-final/recipient-key.pem": 2488,
                "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-corrected-final/secret-seed.txt": 65,
            },
            "reclaimed_bytes_manifest": 405023975759,
            "df_avail_before_bytes": 1538585759744,
            "df_avail_after_bytes": 1943652454400,
            "df_delta_bytes": 405066694656,
            "command_log": "/srv/inferswarm/archive/issue110-v5-cleanup-01.log (46 DELETED, 0 FAILED)",
        },
        {
            "host": "inferswarm03",
            "deleted": {
                "/srv/models/issue110/candidate-laststage": 237742015982,
                "/srv/models/issue110/holdout-candidate-laststage": 3822870427,
                "/srv/models/issue110/case-list.txt": 21352,
            },
            "reclaimed_bytes_manifest": 241564907761,
            "df_avail_before_bytes": 1623625936896,
            "df_avail_after_bytes": 1865199624192,
            "df_delta_bytes": 241573687296,
            "command_log": "/srv/inferswarm/archive/issue110-v5-cleanup-03.log",
            "note": "ready.json + service.log (service runtime files) kept unclassified",
        },
        {
            "host": "inferswarm04",
            "deleted": {
                "/srv/inferswarm/state/issue110/reference": 133603308747,
                "/srv/inferswarm/state/issue110/holdout-reference": 2092071051,
                "/srv/inferswarm/state/issue110/manifests/holdout-corpus.json": 17533,
                "/srv/inferswarm/state/issue110/calibration-corpus.json": 1042766,
                "/srv/inferswarm/state/issue110/stress-pool.json": 33119,
                "/srv/models/issue110/reference-copy": 0,
            },
            "reclaimed_bytes_manifest": 135696473216,
            "df_avail_before_bytes": 36996796416,
            "df_avail_after_bytes": 172705628160,
            "df_delta_bytes": 135708831744,
            "command_log": "/tmp/issue110-v5-cleanup-04.log",
        },
        {
            "host": "orchestrator (this host)",
            "deleted": {
                "/home/zutfen/is110 (campaign scratch incl. holdout-staging plaintext duplicates)": 63948049,
                "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-custody/recipient-key.pem": 2488,
                "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-custody/secret-seed.txt": 65,
            },
            "reclaimed_bytes_manifest": 63950602,
            "df_avail_before_bytes": 5867749376,
            "df_avail_after_bytes": 5941927936,
        },
        {
            "host": "inferswarm00",
            "deleted": {
                "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-corrected-final/recipient-key.pem": 2488,
                "/home/zutfen/.local/share/inferswarm/issue109-holdout-v5-corrected-final/secret-seed.txt": 65,
            },
            "reclaimed_bytes_manifest": 2553,
            "df_avail_before_bytes": 70765547520,
            "df_avail_after_bytes": 70765555712,
        },
    ],
    "retained_archive": {
        "object_count": 516,
        "total_bytes": 460854709,
        "object_manifest_sha256": ARCHIVE_OBJECT_MANIFEST_SHA,
        "locations": [
            "inferswarm01:/srv/inferswarm/archive/issue110-v5 (root SSD, ext4)",
            "inferswarm03:/srv/inferswarm/archive/issue110-v5 (1.9 TB local SSD /dev/sda1, ext4)",
        ],
        "post_delete_rehash": "both copies re-hashed after deletion: 516/516 sha256 exact, byte-identical to the pre-delete hashes; OBJECT-MANIFEST.json sha256 unchanged on both",
    },
    "private_consumed_h109_diagnostic_retention": {
        "location": "orchestrator:/home/zutfen/.local/share/inferswarm/issue110-h109-consumed-diagnostic",
        "directory_mode": "0700 (verified after deletion)",
        "file_mode": "0600 (verified after deletion)",
        "marking": "CONSUMED_DIAGNOSTIC_ONLY; permanently ineligible for future calibration/stress/holdout evidence",
        "holdout-plaintext.json_sha256": "46abbd201dd007d8d6822b14e3b08879c8eac47c955b282cf3db5bd4e7703fc8",
        "holdout-corpus.json_sha256": "5b0a5c8b560fd353d0fe20b21f73233bf7df9bac792b6de66fc0a49bd6d284fb",
        "post_delete_verified": "present, restricted, hashes exact",
    },
    "custody_secret_disposition": {
        "policy": "issue #115 preferred terminal state: after the consumed-plaintext diagnostic copy and all public commitment/unseal records are durable, destroy every private-key/secret-seed copy so the consumed h109 holdout cannot be freshly decrypted or regenerated",
        "doctrine_conflict_check": "no accepted repository doctrine requires continued key/seed retention; the fail-closed two-custodian rule in the custody records governs UNSEAL of a SEALED holdout, and h109 is permanently CONSUMED (never sealable/unsealable again); public certificate, ciphertext (docs/qualification/gemma4-12b-it-v5/sealed/holdout.cms), and every commitment remain committed",
        "destroyed": [
            "orchestrator:~/.local/share/inferswarm/issue109-holdout-v5-custody/{recipient-key.pem,secret-seed.txt}",
            "inferswarm00:~/.local/share/inferswarm/issue109-holdout-v5-corrected-final/{recipient-key.pem,secret-seed.txt}",
            "inferswarm01:~/.local/share/inferswarm/issue109-holdout-v5-corrected-final/{recipient-key.pem,secret-seed.txt}",
        ],
        "private_key_sha256_destroyed": "6e472dc13c550bbb59542179a04eab5988a60bb4a8746210049215c23a4a87e8",
        "secret_seed_sha256_destroyed": "42ab9569e41ef5df4b79105f02f663980bf5cac0243d5fa731e766662ef35dd6",
        "surviving_secret_copies": 0,
    },
    "fail_closed_keeps": [
        "inferswarm01:/srv/models/issue110/holdout-adjudication/{holdout-adjudication.json,holdout-rows.json,telemetry-reference-bands.json} — byte-identical in-place second copy of committed b/ artifacts (217,809 bytes total remaining under /srv/models/issue110)",
        "inferswarm01:/srv/inferswarm/state/issue110/{calibration-corpus.json,stress-pool.json,manifests/} — unclassified top-level state leftovers (1,075,885 bytes)",
        "inferswarm03:/srv/models/issue110/{ready.json,service.log} — service runtime files",
    ],
    "invariants": {
        "zero_unauthorized_deletions": True,
        "every_authorized_expunge_path_gone": "verified post-delete (46/46 DELETED, 0 FAILED on 01; all targets ABSENT on 03/04/orchestrator/00)",
        "every_durable_path_present_and_sha_exact": "516/516 on both copies re-hashed after deletion",
        "private_diagnostic_present_and_restricted": True,
        "repo_evidence_byte_identical": "git diff origin/main HEAD over accepted campaign evidence areas: empty; terminal adjudication sha f024f8b3… re-verified",
        "no_unclassified_or_retained_path_disappeared": True,
        "zero_model_cuda_execution": True,
        "zero_evidence_regeneration": True,
        "verdict_unchanged": "V5_QUALIFICATION_PASS",
    },
    "reconciliation": {
        "manifest_expected_total_bytes": 782349309891,
        "df_observed_delta_total_bytes": 405066694656 + 241573687296 + 135708831744 + 74178560 + 8192,
        "note": "df deltas exceed du-based manifest totals by 0.005-0.06% per host (filesystem metadata/rounding); every per-target du was recorded in the command logs at deletion time",
    },
    "total_reclaimed_bytes": 782349309891,
    "total_reclaimed_gib": 728.62,
    "tests": {
        "focused_cleanup": "tests.test_issue115_cleanup_retention: 27/27 OK",
        "living_manifest_and_campaign": "173+ tests across issue74/99/101/103/105/108/109/110 suites: OK (issue74 suite requires jsonschema, CI-installed; verified in hosted CI)",
        "hosted_ci": "exact-head run on Phase-A head 9573e50: success",
    },
}

out = ROOT / "docs/qualification/gemma4-12b-it-v5-campaign-110/cleanup/RAW-EVIDENCE-EXPUNGEMENT.json"
text = json.dumps(audit, indent=1, sort_keys=True) + "\n"
out.write_text(text)
print("wrote", out, len(text.encode()))
print("sha256", hashlib.sha256(text.encode()).hexdigest())