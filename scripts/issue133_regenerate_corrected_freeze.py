#!/usr/bin/env python3
"""Issue #133 corrected-freeze regeneration (Phase-B correction slice).

Executes the exact ordering required by the correction contract:

1. (code/tests already committed by the caller)
2. compute the exact file SHA-256 of every separately deployed
   correctness-bearing byte (the corrected direct driver);
3. mechanically re-derive the final r5a static execution plan via the
   REAL unmocked builder (already done; this script re-verifies);
4. regenerate `execution-freeze.json` (schema /4) from the corrected
   identities;
5. compute its canonical SHA-256;
6. rebind `physical-campaign-authority.json`'s sole campaign
   `execution_freeze_identity` to the regenerated freeze (additive
   supersession lineage is retained INSIDE the freeze document);
7. verify the binding mechanically.

No GPU, no model execution, no participant-state mutation, no
repository-history rewriting. The previous freeze 5af9aee3… is retained
in `superseded_freeze_lineage` as invalidated before physical execution.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue133_arm_c_retry_campaign as camp  # noqa: E402

EV = ROOT / ("docs/implementation/r6-successor-dense-full-integration-117"
             "/evidence/arm-c-retry")
DRIVER = ROOT / "scripts/issue133_arm_c_retry_direct.py"
DRIVER_DEPLOY_PATH = ("/srv/inferswarm/state/arm-c-retry/scripts/"
                      "issue133_arm_c_retry_direct.py")
FREEZE_PATH = EV / "execution-freeze.json"
AUTHORITY_PATH = EV / "physical-campaign-authority.json"
SUPERSEDED_IDENTITY = ("5af9aee314fdd742cdb75d903d47e2f3c43296ee887e50"
                       "7ef335b8f614e7a19e")


def main() -> int:
    import hashlib

    # --- the exact repository commit carrying the corrected bytes ----
    import subprocess
    repo_sha = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()

    # --- 2. exact SHA-256 of every separately deployed byte ----------
    driver_sha = hashlib.sha256(DRIVER.read_bytes()).hexdigest()

    drivers = {
        "direct": {
            "repository_sha": repo_sha,
            "file_sha256": driver_sha,
            "expected_path": DRIVER_DEPLOY_PATH,
            "read_only": True,
        },
    }
    dependencies = {
        "runtime_session_allocator_source": {
            "repository_sha": camp.ISSUE133["accepted_main_merge"],
            "file_sha256": ("388678971eb608741bd7dd4ad31a34e2e63c45fd"
                            "d0807e01065d077d9202805"),
            "expected_path": ("/srv/inferswarm/state/arm-c-retry/scripts/"
                              "r5b_epochs.py"),
            "read_only": True,
        },
    }

    # --- 3/4. regenerate the freeze (real-builder digest is frozen in --
    #         the campaign module and re-proven by the dry run) --------
    record = camp.build_execution_freeze_record(drivers, dependencies)

    # --- 5. canonical identity ---------------------------------------
    identity = camp.execution_freeze_identity(record)
    raw = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
    FREEZE_PATH.write_bytes(raw)
    print(f"regenerated execution-freeze.json: {identity}")

    # --- 6. rebind the authority (sole campaign, same id retained) ---
    authority = json.loads(AUTHORITY_PATH.read_text())
    campaigns = authority["campaigns"]
    assert len(campaigns) == 1
    campaign_id = next(iter(campaigns))
    campaigns[campaign_id]["execution_freeze_identity"] = identity
    authority_raw = (json.dumps(authority, indent=2, sort_keys=True)
                     + "\n").encode()
    AUTHORITY_PATH.write_bytes(authority_raw)
    print(f"rebound authority campaign {campaign_id} -> {identity}")

    # --- 7. verify the binding mechanically --------------------------
    verdict = camp.verify_execution_freeze_binding()
    assert verdict["bound"], verdict
    assert verdict["retained_bytes_sha256"] == identity
    print("freeze<->authority binding VERIFIED mechanically")
    print(json.dumps({
        "campaign_id": campaign_id,
        "execution_freeze_identity": identity,
        "superseded": SUPERSEDED_IDENTITY,
        "driver_repository_sha": repo_sha,
        "driver_file_sha256": driver_sha,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
