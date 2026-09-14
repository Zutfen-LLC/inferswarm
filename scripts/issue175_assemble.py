#!/usr/bin/env python3
"""Issue #175 — Arm-D reduction-part assembler (CPU-only, stdlib).

Re-derives EVERY retained reduction part from the retained raw bytes
under the evidence bundle, fail-closed:

- fence parts: compare_fences + gpu_fence over the retained inventory
  records and the frozen kill lists (embedded, matching the launch
  logs' recorded PIDs);
- strace parts: reduce_strace over the retained raw traces with the
  authorized cache-alias byte map;
- cache parts: reduce_cache_hits over the strace parts cross-checked
  against the retained last-stage ready witnesses;
- equality parts: reduce_equality (restart 1 canonical vs accepted
  #172) and the sentinel reduction (restart 2 vs accepted #172 +
  within-restart determinism), all from raw records;
- gpu parts: the post-kill inventory records.

Idempotent: re-running over an unchanged bundle reproduces identical
parts. This is the committed derivation the terminal reducer consumes,
so the PASS token is reproducible from git alone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue175_campaign_pins as P  # noqa: E402
import issue175_reduce as R  # noqa: E402

#: authorized model-weight byte map: the verified cache shards (the
#: 01-side model-view symlinks resolve to the stage-1/2 shards; sizes
#: from the retained inventory records, re-read at run time)
ALIAS_BYTES = {
    "/srv/inferswarm/state/arm-c/model-view/stage-1.safetensors":
        9256843520,
    "/srv/inferswarm/state/arm-c/model-view/stage-2.safetensors":
        7278967984,
    "/srv/inferswarm/materialized/issue117/dense.6171f32b4413"
    ".stage-3/armb-participant.safetensors": 9292241800,
}

#: frozen kill lists (from the retained launch/death logs; PIDs of the
#: processes each restart terminated, per host)
KILL_LISTS = {
    1: {"00": [305140, 305137],
        "01": [2755024, 2755972, 2755973, 2755020],
        "03": [2324042, 2324038]},
    2: {"00": [306460, 306457],
        "01": [2760541, 2760628, 2760629, 2760538],
        "03": [2329793, 2329790]},
}

E172 = (P.EVIDENCE_172 / "physical-execution")


def write_canonical(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle",
                        default=str(P.EVIDENCE_DIR / "physical-execution"))
    args = parser.parse_args()
    bundle = Path(args.bundle)
    inv = bundle / "inventories"
    raw = bundle / "strace-raw"
    parts = bundle / "reduction-parts"
    wit = bundle / "witnesses"

    for restart in (1, 2):
        # --- strace parts ---
        for side, trace in (("node", f"strace-{restart}-node-agent"
                                        ".strace"),
                            ("last", f"strace-{restart}-last-stage"
                                     ".strace")):
            lines = (raw / trace).read_text(errors="replace").splitlines()
            reduction = R.reduce_strace(lines, ALIAS_BYTES)
            rec = {"schema": "inferswarm.issue175.arm-d."
                             "strace-reduction/1",
                   "restart": restart, "side": side,
                   "source_trace": f"strace-raw/{trace}",
                   "source_trace_sha256": sha256_file(raw / trace),
                   **reduction}
            write_canonical(parts / f"strace-{restart}-{side}.json", rec)

        # --- fence parts ---
        for host in ("00", "01", "03"):
            pre = json.loads(
                (inv / f"inventory-{host}-pre{restart}.json").read_text())
            post = json.loads(
                (inv / f"inventory-{host}-postkill{restart}.json")
                .read_text())
            fence = R.compare_fences(
                pre, post, killed_pids=KILL_LISTS[restart][host])
            gpu = R.gpu_fence(post["gpus"], P.FROZEN_GEOMETRY_UUIDS,
                              host=f"inferswarm{host}")
            rec = {"schema": P.FENCE_SCHEMA, "campaign_id": P.CAMPAIGN_ID,
                   "restart": restart, "host": f"inferswarm{host}",
                   "killed_pids": KILL_LISTS[restart][host],
                   "fence": fence, "gpu_fence": gpu,
                   "pre_record": f"inventories/inventory-{host}-"
                                 f"pre{restart}.json",
                   "post_record": f"inventories/inventory-{host}-"
                                  f"postkill{restart}.json"}
            write_canonical(parts / f"fence-{restart}-{host}.json", rec)
        write_canonical(parts / f"killed-pids-{restart}.json",
                        {"pids": sorted(set(
                            sum(KILL_LISTS[restart].values(), [])))})

        # --- gpu parts (post-kill inventory records) ---
        for host in ("01", "03"):
            post = json.loads(
                (inv / f"inventory-{host}-postkill{restart}.json")
                .read_text())
            write_canonical(parts / f"gpu-{restart}-{host}.json", post)

        # --- cache parts ---
        strace_parts = []
        for side in ("node", "last"):
            strace_parts.append(json.loads(
                (parts / f"strace-{restart}-{side}.json").read_text()))
        ready = [json.loads((wit / f"last-stage-ready-restart{restart}"
                             ".json").read_text())]
        cache = R.reduce_cache_hits(strace_parts, ready)
        rec = {"schema": "inferswarm.issue175.arm-d.cache-reduction/1",
               "restart": restart, **cache}
        write_canonical(parts / f"cache-{restart}.json", rec)

    # --- equality part (restart 1) ---
    post_campaign = json.loads(
        (bundle / "restart1-canonical/ordinary-campaign.json").read_text())
    post_report = json.loads(
        (bundle / "serving-report-restart1.json").read_text())
    acc_campaign = json.loads(
        (E172 / "ordinary-canonical/ordinary-campaign.json").read_text())
    acc_report = json.loads(
        (E172 / "serving-report-canonical.json").read_text())
    corpus = json.loads(P.CORPUS_172_PATH.read_text())
    equality = R.reduce_equality(post_campaign, post_report,
                                 acc_campaign, acc_report,
                                 corpus["cases"])
    rec = {"schema": P.EQUALITY_SCHEMA, "campaign_id": P.CAMPAIGN_ID,
           "restart": 1,
           "comparison": "post-restart ordinary vs accepted #172 "
                         "canonical", **equality}
    write_canonical(parts / "equality-1.json", rec)

    # --- sentinel part (restart 2) ---
    r2 = json.loads(
        (bundle / "restart2-sentinels/ordinary-campaign.json").read_text())
    acc_s = json.loads(
        (E172 / "ordinary-sentinels/ordinary-campaign.json").read_text())
    rows = []
    for record in r2["records"]:
        accepted = [x for x in acc_s["records"]
                    if x["case_id"] == record["case_id"]
                    and x["repeat"] == record["repeat"]][0]
        rows.append({
            "case": record["case_id"], "repeat": record["repeat"],
            "equal": record["response"]["choices"][0]["message"][
                "content"] == accepted["response"]["choices"][0][
                "message"]["content"]})
    determinism = all(
        len(set(r["response"]["choices"][0]["message"]["content"]
                for r in r2["records"] if r["case_id"] == cid)) == 1
        for cid in {r["case_id"] for r in r2["records"]})
    sent_pass = (all(x["equal"] for x in rows) and determinism
                 and len(rows) == len(P.SENTINEL_IDS) * P.SENTINEL_REPEATS)
    rec = {"schema": P.EQUALITY_SCHEMA, "campaign_id": P.CAMPAIGN_ID,
           "restart": 2,
           "comparison": "post-restart sentinels vs accepted #172 "
                         "sentinels + within-restart determinism",
           "rows": rows, "row_count": len(rows),
           "equal_count": sum(1 for x in rows if x["equal"]),
           "within_restart_determinism": determinism,
           "passed": sent_pass}
    write_canonical(parts / "equality-2.json", rec)

    print(json.dumps({
        "parts": sorted(p.name for p in parts.glob("*.json")),
        "equality_1": equality["equal_count"],
        "equality_2_rows": len(rows),
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
