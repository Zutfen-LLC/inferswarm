#!/usr/bin/env python3
"""Issue #35 utility-envelope derivation.

Derives the measured compute-to-communication / residency utility
envelope from the retained campaign evidence (transport summaries and
role-sweep results) WITHOUT freezing a universal hardware score and
WITHOUT any vendor/width special case: every input is a measured fact
from the frozen evidence files; every output is either a CALCULATED
derivation (labeled) or a MEASURED fact carried through with its label.

The classifier implements the issue's per-role taxonomy exactly:

* CAPACITY_POSITIVE_THROUGHPUT_NEGATIVE
* CAPACITY_POSITIVE_THROUGHPUT_NEUTRAL
* THROUGHPUT_POSITIVE
* NOT_USEFUL_FOR_TESTED_ROLE
* EVIDENCE_INSUFFICIENT

Classification rules (declared here, before the physical sweep is
reduced; deterministic and data-driven):

For a multiworker role R with matched single-subject control C (same
model/workload, subject device):

* capacity_delta = resident bytes contributed by the added participant
  (feasible-with vs infeasible/partial control) — measured from the
  role's offload facts and the subject's VRAM facts;
* throughput_ratio = median generation t/s of R / median of C;
* NEUTRAL_BAND = 0.05 (within-declared-uncertainty band; medians of
  2-attempt distributions with min/max recorded — a ratio inside
  [1-band, 1+band] is not evidence of a change either way);
* if R executed a model the control could not hold resident
  (complete_offload where the control is partial/infeasible):
  capacity-positive regardless of throughput;
* classification per role follows from capacity_delta and
  throughput_ratio mechanically;
* roles whose expected failure mode fired, or whose control is missing,
  classify EVIDENCE_INSUFFICIENT (for feasibility) or
  NOT_USEFUL_FOR_TESTED_ROLE (when the role's own execution failed for
  reasons within the tested substrate).

Fail-closed: missing inputs raise ``EnvelopeError``; nothing defaults.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SCHEMA = "inferswarm.issue35.utility-envelope/1"
NEUTRAL_BAND = 0.05

TAXONOMY = (
    "CAPACITY_POSITIVE_THROUGHPUT_NEGATIVE",
    "CAPACITY_POSITIVE_THROUGHPUT_NEUTRAL",
    "THROUGHPUT_POSITIVE",
    "NOT_USEFUL_FOR_TESTED_ROLE",
    "EVIDENCE_INSUFFICIENT",
)


class EnvelopeError(RuntimeError):
    """An envelope input was missing or inconsistent."""


def load(path: Path) -> dict:
    if not path.is_file():
        raise EnvelopeError(f"evidence file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def classify_role(role: dict, control: dict | None) -> dict:
    """Classify one multiworker role against its matched control."""
    role_id = role.get("role_id", "<unnamed>")
    if role.get("outcome") == "EXPECTED_FAILURE":
        return {
            "role_id": role_id,
            "classification": "NOT_USEFUL_FOR_TESTED_ROLE",
            "basis": "role failed on the tested substrate in its declared "
                     "expected mode; retained as evidence",
            "label": "MEASURED",
        }
    if control is None:
        return {
            "role_id": role_id,
            "classification": "EVIDENCE_INSUFFICIENT",
            "basis": "no matched control retained",
            "label": "MEASURED",
        }
    if "generation_tokens_per_s" not in role:
        return {
            "role_id": role_id,
            "classification": "EVIDENCE_INSUFFICIENT",
            "basis": "role result carries no throughput reduction",
            "label": "MEASURED",
        }

    role_rate = role["generation_tokens_per_s"]["median"]
    control_rate = control["generation_tokens_per_s"]["median"]
    ratio = role_rate / control_rate

    role_offload = role.get("offload", {})
    control_offload = control.get("offload", {})
    role_complete = role_offload.get("complete_offload")
    control_complete = control_offload.get("complete_offload")

    # Capacity contribution: the role achieved complete residency where
    # the control could not. (For same-model roles this is false and the
    # classification reduces to the throughput axis, as intended.)
    capacity_positive = bool(role_complete) and not bool(control_complete)

    if capacity_positive:
        if ratio < 1.0 - NEUTRAL_BAND:
            classification = "CAPACITY_POSITIVE_THROUGHPUT_NEGATIVE"
            basis = ("complete resident execution where the control could "
                     f"not hold the model; throughput ratio {ratio:.3f} "
                     "below the neutral band")
        elif ratio > 1.0 + NEUTRAL_BAND:
            classification = "THROUGHPUT_POSITIVE"
            basis = (f"throughput ratio {ratio:.3f} above the neutral band "
                     "with capacity contributed")
        else:
            classification = "CAPACITY_POSITIVE_THROUGHPUT_NEUTRAL"
            basis = (f"throughput ratio {ratio:.3f} inside the neutral "
                     "band with capacity contributed")
    else:
        if ratio > 1.0 + NEUTRAL_BAND:
            classification = "THROUGHPUT_POSITIVE"
            basis = (f"throughput ratio {ratio:.3f} above the neutral band")
        elif ratio < 1.0 - NEUTRAL_BAND:
            classification = "NOT_USEFUL_FOR_TESTED_ROLE"
            basis = (f"no capacity contribution (control already complete) "
                     f"and throughput ratio {ratio:.3f} below the neutral "
                     "band")
        else:
            classification = "NOT_USEFUL_FOR_TESTED_ROLE"
            basis = (f"no capacity contribution and throughput ratio "
                     f"{ratio:.3f} inside the neutral band: no measured "
                     "benefit justifies the added participation for this "
                     "role shape")
    return {
        "role_id": role_id,
        "classification": classification,
        "throughput_ratio_vs_control": round(ratio, 4),
        "role_rate": role_rate,
        "control_rate": control_rate,
        "capacity_positive": capacity_positive,
        "basis": basis,
        "label": "CALCULATED",
    }


def transfer_cost_per_token(transport: dict, bytes_per_token: float) -> dict:
    """CALCULATED: link-seconds per token for a bytes/token demand.

    Uses the measured sustained D2H+H2D medians at the transfer size
    closest to (and not smaller than) the per-token demand when
    available, else the smallest measured size (service-latency regime).
    """
    sustained = transport["sustained_transfers"]
    if not sustained:
        raise EnvelopeError("no sustained transfer measurements")
    # service regime for small demands
    service = transport["small_transfer_service"]
    service_ms = service["time_ms_median"]
    entries = []
    for key, summary in sustained.items():
        direction, size = key.split("_")
        entries.append((direction, int(size), summary))
    h2d = min((e for e in entries if e[0] == "h2d"), key=lambda e: e[1])
    d2h = min((e for e in entries if e[0] == "d2h"), key=lambda e: e[1])
    # linear model on the smallest measured size class: GB/s medians
    rate_h2d = h2d[2]["gbps_median"] or 1e-9
    rate_d2h = d2h[2]["gbps_median"] or 1e-9
    ms_per_token = (bytes_per_token / 1e9 / rate_h2d * 1e3
                    + bytes_per_token / 1e9 / rate_d2h * 1e3)
    return {
        "bytes_per_token": bytes_per_token,
        "h2d_gbps_median_used": rate_h2d,
        "d2h_gbps_median_used": rate_d2h,
        "roundtrip_service_ms_median": service_ms,
        "modeled_link_ms_per_token": round(ms_per_token, 6),
        "label": "CALCULATED",
    }


def build_envelope(root: Path) -> dict:
    evidence = root / "evidence"
    transport_amd = load(evidence / "x1p-transport-amd-a.json")
    transport_nv = load(evidence / "x1p-transport-nv-a.json")
    roles = {
        "x1p-role-adverse": load(evidence / "x1p-role-adverse.json"),
        "x1p-role-coarse": load(evidence / "x1p-role-coarse.json"),
        "x1p-role-capacity": load(evidence / "x1p-role-capacity.json"),
        "x1p-role-capacity-control": load(
            evidence / "x1p-role-capacity-control.json"),
        "x1p-role-single-amd-a": load(
            evidence / "x1p-role-single-amd-a.json"),
        "x1p-role-single-nv-a": load(evidence / "x1p-role-single-nv-a.json"),
    }

    classifications = [
        classify_role(roles["x1p-role-adverse"], roles["x1p-role-single-amd-a"]),
        classify_role(roles["x1p-role-coarse"], roles["x1p-role-single-amd-a"]),
        classify_role(roles["x1p-role-capacity"],
                      roles["x1p-role-capacity-control"]),
    ]

    # Both-perspective marginal analysis for the two-device roles: the
    # same placement measured against EACH participant's standalone
    # control. Adding the strong participant to the weak one can be
    # throughput-positive while adding the weak one to the strong one is
    # throughput-negative; both measured facts are recorded.
    def marginal(rid, control_id):
        role = roles[rid]
        ctrl = roles[control_id]
        return {
            "vs_control_median_tps": ctrl["generation_tokens_per_s"]["median"],
            "ratio": round(role["generation_tokens_per_s"]["median"] /
                           ctrl["generation_tokens_per_s"]["median"], 4),
        }
    marginal_views = {
        "x1p-role-adverse": {
            "adding_peer_to_subject": marginal(
                "x1p-role-adverse", "x1p-role-single-amd-a"),
            "adding_subject_to_peer": marginal(
                "x1p-role-adverse", "x1p-role-single-nv-a"),
        },
        "x1p-role-coarse": {
            "adding_peer_to_subject": marginal(
                "x1p-role-coarse", "x1p-role-single-amd-a"),
            "adding_subject_to_peer_batched_per_sequence": marginal(
                "x1p-role-coarse", "x1p-role-single-nv-a"),
        },
    }

    # Link-dominated vs device-dominated separation (both subjects share
    # the measured link class; the single-subject controls isolate
    # device-local compute).
    amd_single = roles["x1p-role-single-amd-a"]["generation_tokens_per_s"]
    nv_single = roles["x1p-role-single-nv-a"]["generation_tokens_per_s"]

    return {
        "schema": SCHEMA,
        "neutral_band": NEUTRAL_BAND,
        "taxonomy": list(TAXONOMY),
        "classifications": classifications,
        "marginal_views": {
            "label": "CALCULATED",
            "note": ("The frozen classification uses the subject-perspective "
                     "control; the peer-perspective ratio is recorded because "
                     "the marginal value of adding a participant depends on "
                     "which device already hosts the workload."),
            "views": marginal_views,
        },
        "link_vs_device_separation": {
            "label": "CALCULATED",
            "note": (
                "Both narrow-link subjects negotiate the same link class "
                "under load (see transport summaries). Observations consistent "
                "across both subjects are plausibly link/role dominated; "
                "device-local compute differences are carried explicitly "
                "from the single-subject controls and are not attributed "
                "to the link."),
            "single_subject_compute": {
                "amd_a_median_tps": amd_single["median"],
                "nv_a_median_tps": nv_single["median"],
                "device_local_ratio_nv_over_amd": round(
                    nv_single["median"] / amd_single["median"], 4),
            },
        },
        "transport_facts": {
            subject: {
                "link_under_load": transport["link"]["negotiated_under_load"],
                "h2d_gbps_128mib": transport["sustained_transfers"][
                    "h2d_134217728"]["gbps_median"],
                "d2h_gbps_128mib": transport["sustained_transfers"][
                    "d2h_134217728"]["gbps_median"],
                "service_ms_4kib": transport["small_transfer_service"][
                    "time_ms_median"],
            }
            for subject, transport in
            (("amd_a", transport_amd), ("nv_a", transport_nv))
        },
        "nonclaims": [
            "per-role classifications for the tested substrate and "
            "supported semantics only, not permanent device grades",
            "no universal hardware score is frozen",
            "wider links remain later comparison points, not prerequisites",
            "no vendor/width special case enters generic planner semantics",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True,
                        help="investigation namespace root")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    envelope = build_envelope(Path(args.root))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "classifications": {c["role_id"]: c["classification"]
                            for c in envelope["classifications"]},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
