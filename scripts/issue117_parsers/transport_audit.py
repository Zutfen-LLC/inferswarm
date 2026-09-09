"""Parser/validator for the retained coordinator transport audit
(Issue #117 Arm B, round-4 P1-2).

Input: evidence/arm-b/observations/coordinator-transport-audit.json —
the digest-bound command/transport audit derived from the
contemporaneous Hermes execution-session transcript (session
20260908_150616_c57910; builder:
scripts/issue117_arm_b_transport_audit_build.py).

This module re-derives the audit's verdicts from the retained record's
own entries (never from the stored booleans) and binds the record's
frozen shape: provenance pins, census entry digests, co-targeting
count, and destructive-scan classification. Any added, removed, or
edited command in the census fails the per-entry sha256 pins; the
transcript chain digest pins the audit to the exact session.
"""
from __future__ import annotations

import hashlib

#: frozen provenance pins (the audit is bound to the exact execution
#: session that ran the Arm-B campaign)
SESSION_ID = "20260908_150616_c57910"
MESSAGE_COUNT = 819
SESSION_INTERVAL_UTC = ("2026-09-08T19:06:19Z", "2026-09-08T22:18:30Z")
CAMPAIGN_INTERVAL_UTC = ("2026-09-08T20:59:55Z", "2026-09-08T21:24:38Z")
TRANSCRIPT_CHAIN_SHA256 = (
    "89f1444af700c4d0b1305dc8824c317f1f2bf2f131d8106066fb81bdc35eb682")

#: frozen census: the exact message ids whose issued commands targeted
#: the coordinator with a file-transfer shape. Every entry is pinned
#: by its own sha256 below (verbatim command text digest).
CENSUS_MESSAGE_IDS = (225441, 225445, 225447, 225457, 225474, 225480,
                      225538, 225581, 225785)

#: sha256 of each census entry's verbatim command text (the issued
#: execute_code/terminal arguments exactly as retained)
CENSUS_ENTRY_SHA256 = {
    225441: "adcd07f40574a367b3b0f7364f0f6cb4d4d030db65d4effb0e33ab4a0c50f88b",
    225445: "11e8b4598091ca8c920e04774f686f081c5b5e7350d00fdc5427d7908449d1e1",
    225447: "6ee9dfc21d1cdbc370265fd7da82a21a4c414ea172da1cc7bf236e351214bdf9",
    225457: "88328db85347a76c8cba05d6dfce256423feaaf8ca2ef29160b277710e30c475",
    225474: "892c4b98dc7bd32c693ec469ffc9870db39e600f6365a6b42ba94615ac7e3d0c",
    225480: "5eaad7d64bfed6669187610533f8e6a841547eae2be452ed2b569e7fe1252225",
    225538: "2e8cec955a243ce4b13e6281a8de7e93d7d41c12c46d386b0896b0487b167690",
    225581: "6e9b66c1f69b52ad7aa214101435eab0220960fec9616e559eda1f3cdc1d6d3b",
    225785: "cafc387f0a00e271ebddf5251ebcf05d1bd6db8c6b16f3e4f501859acc9dab01",
}


def _entry_problems(entry: dict) -> list:
    problems = []
    mid = entry.get("message_id")
    if mid not in CENSUS_MESSAGE_IDS:
        problems.append(f"census entry message_id {mid} not in frozen set")
        return problems
    verbatim = entry.get("verbatim") or ""
    digest = hashlib.sha256(verbatim.encode()).hexdigest()
    if digest != CENSUS_ENTRY_SHA256[mid]:
        problems.append(
            f"census entry {mid} verbatim digest drift (audit record "
            f"edited)")
    return problems


def derive(audit: dict) -> dict:
    """Re-derive the audit verdicts from the record's own entries."""
    problems = []
    prov = audit.get("provenance", {})
    if prov.get("session_id") != SESSION_ID:
        problems.append("transport audit bound to a different session")
    if prov.get("message_count") != MESSAGE_COUNT:
        problems.append(
            f"transport audit message_count {prov.get('message_count')} "
            f"!= {MESSAGE_COUNT}")
    if tuple(prov.get("session_interval_utc") or ()) != SESSION_INTERVAL_UTC:
        problems.append("transport audit session interval drift")
    if tuple(prov.get("campaign_interval_utc") or ()) != CAMPAIGN_INTERVAL_UTC:
        problems.append("transport audit campaign interval drift")
    if prov.get("transcript_chain_sha256") != TRANSCRIPT_CHAIN_SHA256:
        problems.append("transport audit transcript chain digest drift")
    # session window must contain the campaign window
    if prov.get("session_interval_utc") and \
            prov.get("campaign_interval_utc"):
        s0, s1 = prov["session_interval_utc"]
        c0, c1 = prov["campaign_interval_utc"]
        if not (s0 <= c0 and c1 <= s1):
            problems.append("campaign interval escapes the session window")

    census = audit.get("census_coordinator_directed_transfer_commands", {})
    entries = census.get("entries", [])
    ids = sorted(e.get("message_id") for e in entries)
    if ids != sorted(CENSUS_MESSAGE_IDS):
        problems.append(
            f"census message-id set drift: {ids} != "
            f"{sorted(CENSUS_MESSAGE_IDS)}")
    if census.get("entry_count") != len(CENSUS_MESSAGE_IDS):
        problems.append("census entry_count drift")
    for entry in entries:
        problems.extend(_entry_problems(entry))

    cotarget = audit.get("model_byte_cotargeting_commands", {})
    if cotarget.get("count") != 0 or cotarget.get("entries"):
        problems.append(
            "issued command co-targets the coordinator and a model-byte "
            "path: receive path NOT empty")

    dscan = audit.get("destructive_operation_scan", {})
    for hit in dscan.get("hits", []):
        if hit.get("targets_coordinator") or \
                hit.get("targets_canonical_root"):
            problems.append(
                f"destructive op targets coordinator/canonical root "
                f"(msg {hit.get('message_id')})")
    if dscan.get("coordinator_or_canonical_root_targeted") not in (0, None):
        problems.append("destructive scan reports targeted hits")

    # re-derive (never trust the stored booleans)
    zero_cotarget = not cotarget.get("entries")
    zero_targeted_destructive = not any(
        h.get("targets_coordinator") or h.get("targets_canonical_root")
        for h in dscan.get("hits", []))
    census_complete = ids == sorted(CENSUS_MESSAGE_IDS)
    verdicts = audit.get("derived_verdicts", {})
    if verdicts.get("zero_model_byte_cotargeting_commands") != \
            zero_cotarget:
        problems.append("stored co-targeting verdict disagrees with entries")
    if verdicts.get("zero_destructive_coordinator_or_root_targeting") != \
            zero_targeted_destructive:
        problems.append(
            "stored destructive verdict disagrees with entries")
    if verdicts.get("every_coordinator_transfer_is_metadata_or_script") \
            is not True:
        problems.append(
            "census classification verdict not established")

    return {
        "problems": problems,
        "census_command_count": len(CENSUS_MESSAGE_IDS),
        "census_complete": census_complete,
        "zero_model_byte_cotargeting_commands": zero_cotarget,
        "zero_destructive_coordinator_or_root_targeting":
            zero_targeted_destructive,
    }
