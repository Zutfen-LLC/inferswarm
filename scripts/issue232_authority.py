#!/usr/bin/env python3
"""Issue #232 — V2-G immutable intended-identity authority builder.

`build` derives V2-G's authority exclusively from accepted predecessor
bytes (paths/sha/terminal pinned through each predecessor's own
accepted MANIFEST.sha256 rows, every file re-hashed at build — a
hand-copied digest always drifts):

  V2-F (#230/PR #231, merged c21840e) — the immediate predecessor:
    * PLATFORM_STRESS_FAIL terminal (inherited as the REPLAY QUESTION,
      never as permission);
    * the retained whole-boot AER supplementary record — the chronic
      RxErr condition this campaign remediates (its quantification is
      RE-PARSED from the retained gz journal bytes at build time, not
      hand-copied);
    * the accepted V2-F producer closure — the replay producer pin
      (byte-identity requirement for any replay).

Nonclaims: this document authorizes NO physical execution. It binds
intended identity only; every physical observation requires a fresh
census receipt on the current boot, re-derived by switch identity and
bus chaining (historical BDFs never authorize anything after a
power-cycle or slot move).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue232_receipt as rc
import issue232_host as host

ROOT = Path(__file__).resolve().parents[1]

SCHEMA = "inferswarm.v2g.physical-authority/1"

V2F_AREA = "docs/investigations/vulkan-v2-f-v340l-external-memory"
MANIFEST_OF = {
    "v2b": "docs/investigations/vulkan-v2-b-v340l/MANIFEST.sha256",
    "v2c": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/"
            "MANIFEST.sha256"),
    "v2d": ("docs/investigations/vulkan-v2-d-v340l-concurrent/"
            "MANIFEST.sha256"),
    "v2e": ("docs/investigations/vulkan-v2-e-v340l-peer-link/"
            "MANIFEST.sha256"),
    "v2f": f"{V2F_AREA}/MANIFEST.sha256",
}
TERMINALS = {
    "v2b": (f"docs/investigations/vulkan-v2-b-v340l/TERMINAL.json",
            "V2B_V340L_DUAL_DIE_QUALIFICATION_PASS"),
    "v2c": ("docs/investigations/vulkan-v2-c-v340l-platform-stability/"
            "cycles-v2/TERMINAL-V2.json",
            "V2C_V340L_PLATFORM_STABILITY_PASS"),
    "v2d": ("docs/investigations/vulkan-v2-d-v340l-concurrent/"
            "evidence/TERMINAL.json",
            "V2D_V340L_PLATFORM_STRESS_FAIL"),
    "v2e": ("docs/investigations/vulkan-v2-e-v340l-peer-link/"
            "evidence/TERMINAL.json",
            "V2E_EVIDENCE_BLOCKED"),
    "v2f": (f"{V2F_AREA}/evidence/TERMINAL.json",
            "V2F_V340L_PLATFORM_STRESS_FAIL"),
}


class AuthorityError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_manifest_rows(root: Path, rel: str) -> dict[str, str]:
    path = root / rel
    if not path.is_file():
        raise AuthorityError(f"accepted manifest missing: {rel}")
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, path_rel = line.partition("  ")
        rows[path_rel.lstrip()] = digest
    return rows


def _verify_manifest(root: Path, rel: str) -> dict[str, str]:
    """Re-hash EVERY row of an accepted predecessor manifest (#228/#230
    byte-preservation proof, mechanically enforced at every authority
    build/verify)."""
    rows = _load_manifest_rows(root, rel)
    if not rows:
        raise AuthorityError(f"accepted manifest has no rows: {rel}")
    for path_rel, digest in sorted(rows.items()):
        p = root / path_rel
        if not p.is_file():
            raise AuthorityError(
                f"accepted evidence file missing ({rel}): {path_rel}")
        actual = sha256(p.read_bytes())
        if actual != digest:
            raise AuthorityError(
                f"accepted evidence byte drift ({rel}): {path_rel}")
    return rows


def _load(root: Path, rel: str, manifest_rows: dict[str, str]) -> Any:
    if rel not in manifest_rows:
        raise AuthorityError(f"file not pinned by its manifest: {rel}")
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _git_blob(root: Path, rev: str, rel: str) -> bytes:
    import subprocess
    proc = subprocess.run(["git", "-C", str(root), "cat-file", "blob",
                           f"{rev}:{rel}"], capture_output=True)
    if proc.returncode != 0:
        raise AuthorityError(f"git blob unavailable: {rev}:{rel}")
    return proc.stdout


def _is_ancestor(root: Path, rev: str) -> bool:
    import subprocess
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True).stdout.decode().strip()
    proc = subprocess.run(["git", "-C", str(root), "merge-base",
                           "--is-ancestor", rev, head],
                          capture_output=True)
    return proc.returncode == 0


def build_authority(root: Path = ROOT) -> dict[str, Any]:
    source_rows: dict[str, Any] = {}
    terminals: dict[str, Any] = {}

    for gen, rel in MANIFEST_OF.items():
        rows = _verify_manifest(root, rel)
        term_path, term_required = TERMINALS[gen]
        term = _load(root, term_path, rows)
        if term.get("terminal") != term_required:
            raise AuthorityError(
                f"predecessor terminal mismatch ({gen}): "
                f"{term.get('terminal')!r} != {term_required!r}")
        terminals[gen] = {
            "terminal": term["terminal"],
            "path": term_path,
            "campaign_window_utc": term.get("campaign_window_utc"),
        }
        source_rows[gen] = {"manifest": {"path": rel, "rows": len(rows)}}

    if not _is_ancestor(root, "c21840e4a1e5b5c81c366dd23b18ff582f9670b1"):
        raise AuthorityError(
            "V2-F merge commit c21840e4 is not an ancestor of HEAD")

    # --- V2-F replay-producer pin (byte-bound, never hand-copied) ----
    v2f_rows = _load_manifest_rows(root, MANIFEST_OF["v2f"])
    closure_rel = f"{V2F_AREA}/PRODUCER-CLOSURE.json"
    closure = _load(root, closure_rel, v2f_rows)
    if closure.get("producer_head") != rc.REPLAY_PRODUCER_PIN["producer_head"]:
        raise AuthorityError(
            "retained V2-F closure pins a different producer head than "
            "the V2-G replay pin")
    body = {k: v for k, v in closure.items() if k != "closure_digest"}
    recomputed = sha256(rc.canonical(body))
    if closure.get("closure_digest") != recomputed:
        raise AuthorityError("retained V2-F closure digest does not bind")
    transfer_blob = _git_blob(
        root, rc.REPLAY_PRODUCER_PIN["producer_head"],
        rc.REPLAY_PRODUCER_PIN["transfer_source"])
    replay_pin = {
        "campaign": rc.REPLAY_PRODUCER_PIN["campaign"],
        "producer_head": rc.REPLAY_PRODUCER_PIN["producer_head"],
        "closure_rel": closure_rel,
        "closure_digest": closure["closure_digest"],
        "transfer_source": rc.REPLAY_PRODUCER_PIN["transfer_source"],
        "transfer_source_sha256": sha256(transfer_blob),
    }

    # --- chronic-condition baseline (re-parsed from retained bytes) --
    supp_rel = f"{V2F_AREA}/evidence/supplementary/SUPPLEMENTARY-FAULT-BOOT-AER.json"
    supp = _load(root, supp_rel, v2f_rows)
    gz_rel = f"{V2F_AREA}/evidence/supplementary/aer-fault-boot-full.txt.gz"
    if gz_rel not in v2f_rows:
        raise AuthorityError("fault-boot journal not pinned by manifest")
    gz_bytes = (root / gz_rel).read_bytes()
    if sha256(gz_bytes) != supp["source"]["raw_sha256_gz"]:
        raise AuthorityError("fault-boot journal bytes diverge from pin")
    census = host.aer_event_census(
        gzip.decompress(gz_bytes).decode("utf-8", "replace"))
    quant = supp["quantification"]
    chronic = {
        "source": supp_rel,
        "boot_id": supp["source"]["boot_id"],
        "reparsed_from_raw_bytes": {
            "events": census["events"],
            "events_by_source": census["events_by_source"],
            "events_by_type_class": census["events_by_type_class"],
        },
        "retained_quantification": {
            "severity_counts": quant["severity_counts"],
            "by_source_bdf": quant["by_source_bdf"],
            "rate_per_minute": quant["rate_per_minute"],
        },
        "cross_check": {
            "events_correctable_equal":
                census["events"]["Correctable"]
                == quant["severity_counts"]["Correctable"],
            "upstream_events_equal":
                census["events_by_source"]
                .get(rc.HISTORICAL_BDFS["switch_upstream"], {})
                .get("Correctable", -1)
                == quant["by_source_bdf"]
                [rc.HISTORICAL_BDFS["switch_upstream"]],
        },
    }
    if not all(chronic["cross_check"].values()):
        raise AuthorityError(
            "re-parsed fault-boot census diverges from the accepted "
            "quantification — authority refuses to bind a rewritten "
            "baseline")

    # --- historical topology (observation context only) --------------
    historical = dict(rc.HISTORICAL_BDFS)
    historical_note = (
        "observation context ONLY: after any power-cycle or physical "
        "intervention the chain and die BDFs are RE-DERIVED from fresh "
        "census bytes (PM8533 identity + bus chaining + tree "
        "corroboration + UUID join); these literals never authorize")

    doc = {
        "schema": SCHEMA,
        "campaign_id": rc.CAMPAIGN_ID,
        "accepted_sources": sorted(MANIFEST_OF),
        "terminals": terminals,
        "v2f_merge": "c21840e4a1e5b5c81c366dd23b18ff582f9670b1",
        "replay_producer_pin": replay_pin,
        "chronic_condition_baseline": chronic,
        "historical_topology": historical,
        "historical_topology_note": historical_note,
        "gate_definition": {
            "rxerr_max_over_interval": rc.CLEAN_LINK_RXERR_MAX,
            "interval_minutes": rc.GATE_INTERVAL_MINUTES,
            "required_cold_confirmations": rc.GATE_REQUIRED_COLD_CONFIRMATIONS,
            "threshold_basis": (
                "ZERO frozen prospectively (issue Phase 3 prefers zero; "
                "any nonzero threshold must be frozen before observing "
                "the confirmation result — control 10)"),
        },
        "replay_plan": {
            "mechanism": rc.REPLAY_MECHANISM,
            "direction": rc.REPLAY_DIRECTION,
            "ladder": [dict(r) for r in rc.REPLAY_LADDER],
            "stop_conditions": list(rc.REPLAY_STOP_CONDITIONS),
        },
        "nonclaims": [
            "intended identity only: nothing in this document authorizes "
            "physical execution; every observation requires a fresh "
            "census receipt on the current boot",
            "the chronic RxErr condition's causal relationship to the "
            "#216/#230 amdgpu faults is UNKNOWN and stays unclaimed",
            "the inherited V2-F PLATFORM_STRESS_FAIL is the replay "
            "QUESTION, never permission",
        ],
    }
    doc["authority_digest"] = sha256(
        rc.canonical({k: v for k, v in doc.items()
                      if k != "authority_digest"}))
    return doc


def verify_authority(doc: dict[str, Any], root: Path = ROOT) -> bool:
    """Re-derive the authority from predecessor bytes and compare."""
    if doc.get("schema") != SCHEMA:
        raise AuthorityError("bad authority schema")
    if doc.get("campaign_id") != rc.CAMPAIGN_ID:
        raise AuthorityError("bad campaign id")
    rebuilt = build_authority(root)
    if rebuilt != doc:
        raise AuthorityError(
            "authority document does not match a rebuild from accepted "
            "bytes (predecessor drift or hand edit)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    out = ROOT / rc.AREA_REL / "PHYSICAL-AUTHORITY.json"
    if args.verify:
        doc = json.loads(out.read_text(encoding="utf-8"))
        ok = verify_authority(doc)
        print(json.dumps({"verified": ok, "path": str(out)}))
        return 0
    doc = build_authority()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(json.dumps(doc, indent=1, sort_keys=True).encode()
                    + b"\n")
    print(json.dumps({"written": str(out),
                      "authority_digest": doc["authority_digest"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
