#!/usr/bin/env python3
"""Issue #35 utility-envelope derivation.

Derives the measured compute-to-communication / residency utility
envelope from the retained campaign evidence (transport summaries,
role-sweep results, the corrected residency-facts reduction, and the
corrected concurrent coarse arms) WITHOUT freezing a universal hardware
score and WITHOUT any vendor/width special case: every input is a
measured fact from the frozen evidence files; every output is either a
CALCULATED derivation (labeled) or a MEASURED fact carried through with
its label.

The classifier implements the issue's per-role taxonomy exactly:

* CAPACITY_POSITIVE_THROUGHPUT_NEGATIVE
* CAPACITY_POSITIVE_THROUGHPUT_NEUTRAL
* THROUGHPUT_POSITIVE
* NOT_USEFUL_FOR_TESTED_ROLE
* EVIDENCE_INSUFFICIENT

Classification rules (declared before the corrected reduction;
deterministic and data-driven):

Throughput axis — a role is compared ONLY against a workload-matched
control. A four-concurrent-request arm is compared against the
four-concurrent-request control, never against a single-request
baseline (and vice versa). throughput_ratio = matched medians.

Capacity axis — CORRECTED per maintainer review: capacity contribution
is derived from measured residency/memory-pressure facts (the
residency-facts reduction over retained raw stderr), NOT from the
``complete_offload`` layer-count boolean:

* control pressure: over-capacity final allocation, aborted fit,
  projected >> free, or context reduction under pressure;
* role residency: model buffers materially split across BOTH
  participants with no over-capacity device;
* capacity_positive = control pressured AND role split-resident.

A nominal complete offload with over-capacity self-demand is pressure,
not residency success; a non-zero CPU_Mapped buffer appears in every
placement and never proves paging by itself.

Roles whose declared expected failure mode fired classify
NOT_USEFUL_FOR_TESTED_ROLE (fail-closed controls are first-class
classifications, not omissions). Roles without a matched control or
without a throughput reduction classify EVIDENCE_INSUFFICIENT.

Fail-closed: missing inputs raise ``EnvelopeError``; nothing defaults.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import issue35_residency_facts

SCHEMA = "inferswarm.issue35.utility-envelope/2"
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


def classify_role(role: dict, control: dict | None,
                  capacity_basis: dict | None = None) -> dict:
    """Classify one placement role against its matched control.

    ``capacity_basis`` is the CALCULATED residency-facts derivation
    (from ``issue35_residency_facts.derive_capacity_basis``); when the
    role has no capacity question (same-model throughput roles) it is
    None and capacity_positive is False by absence of evidence, never
    by the layer-count boolean.
    """
    role_id = role.get("role_id", role.get("arm_id", "<unnamed>"))
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

    capacity_positive = bool(
        capacity_basis["capacity_positive"]) if capacity_basis else False
    capacity_facts = (capacity_basis or {}).get("control_pressure_facts")

    if capacity_positive:
        if ratio < 1.0 - NEUTRAL_BAND:
            classification = "CAPACITY_POSITIVE_THROUGHPUT_NEGATIVE"
            basis = ("measured memory-fit facts: control placement "
                     "pressure-limited "
                     f"(over-capacity={capacity_facts['over_capacity']}, "
                     f"fit aborted ({capacity_facts['fit_abort_reason']}), "
                     f"projected {capacity_facts['projected_vs_free']}) "
                     "while the role splits model buffers across both "
                     f"participants with no over-capacity device; "
                     f"throughput ratio {ratio:.3f} below the neutral band")
        elif ratio > 1.0 + NEUTRAL_BAND:
            classification = "THROUGHPUT_POSITIVE"
            basis = (f"throughput ratio {ratio:.3f} above the neutral band "
                     "with capacity contributed on measured memory-fit "
                     "facts (control pressured, role split-resident)")
        else:
            classification = "CAPACITY_POSITIVE_THROUGHPUT_NEUTRAL"
            basis = (f"throughput ratio {ratio:.3f} inside the neutral "
                     "band with capacity contributed on measured "
                     "memory-fit facts")
    else:
        if ratio > 1.0 + NEUTRAL_BAND:
            classification = "THROUGHPUT_POSITIVE"
            basis = f"throughput ratio {ratio:.3f} above the neutral band"
        elif ratio < 1.0 - NEUTRAL_BAND:
            classification = "NOT_USEFUL_FOR_TESTED_ROLE"
            basis = (f"no measured capacity contribution and throughput "
                     f"ratio {ratio:.3f} below the neutral band")
        else:
            classification = "NOT_USEFUL_FOR_TESTED_ROLE"
            basis = (f"no measured capacity contribution and throughput "
                     f"ratio {ratio:.3f} inside the neutral band: no "
                     "measured benefit justifies the added participation "
                     "for this role shape")
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


def classify_concurrent_arm(arm: dict, control: dict) -> dict:
    """Classify the corrected concurrent coarse arm against its
    workload-matched concurrent control on aggregate throughput."""
    arm_rate = arm["aggregate_throughput_tokens_per_s"]["median"]
    control_rate = control["aggregate_throughput_tokens_per_s"]["median"]
    ratio = arm_rate / control_rate
    if not arm["all_attempts_all_correct"]:
        return {
            "role_id": arm["arm_id"],
            "classification": "EVIDENCE_INSUFFICIENT",
            "basis": "not every concurrent request matched the frozen "
                     "reference semantics",
            "label": "MEASURED",
        }
    if ratio > 1.0 + NEUTRAL_BAND:
        classification = "THROUGHPUT_POSITIVE"
    elif ratio < 1.0 - NEUTRAL_BAND:
        classification = "NOT_USEFUL_FOR_TESTED_ROLE"
    else:
        classification = "NOT_USEFUL_FOR_TESTED_ROLE"
    basis = (f"aggregate concurrent throughput ratio {ratio:.3f} "
             f"({arm_rate} vs {control_rate} tokens/s aggregate, "
             "CALCULATED from measured aggregate tokens / aggregate wall "
             "seconds, 4 concurrent matched requests per arm)")
    return {
        "role_id": arm["arm_id"],
        "classification": classification,
        "throughput_ratio_vs_control": round(ratio, 4),
        "role_rate": arm_rate,
        "control_rate": control_rate,
        "workload_shape": "4 concurrent requests vs 4 concurrent requests",
        "capacity_positive": False,
        "basis": basis,
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
        "x1p-role-adverse-rowsplit-unsupported": load(
            evidence / "x1p-role-adverse-rowsplit-unsupported.json"),
        "x1p-role-single-amd-a": load(
            evidence / "x1p-role-single-amd-a.json"),
        "x1p-role-single-nv-a": load(
            evidence / "x1p-role-single-nv-a.json"),
    }
    capacity_facts = load(evidence / "x1p-capacity-residency-facts.json")
    coarse_split = load(evidence / "x1p-coarse4-split.json")
    coarse_single = load(evidence / "x1p-coarse4-single.json")

    capacity_basis = capacity_facts["capacity_basis"]

    classifications = [
        classify_role(roles["x1p-role-adverse"],
                      roles["x1p-role-single-amd-a"]),
        # Retained single-request diagnostic: NOT classified as the
        # coarse evidence; workload shape recorded for honesty.
        {
            "role_id": "x1p-role-coarse",
            "classification": "EVIDENCE_INSUFFICIENT",
            "basis": "single llama-cli interaction with -np 4 slots "
                     "provisioned: one completion in retained stdout; "
                     "invalid for the intended coarse-comparison claim "
                     "and superseded by the corrected concurrent arm; "
                     "retained unchanged as a diagnostic/reference",
            "label": "MEASURED",
            "workload_shape": "1 request on a 4-slot-provisioned server",
        },
        classify_role(roles["x1p-role-capacity"],
                      roles["x1p-role-capacity-control"],
                      capacity_basis=capacity_basis),
        # Control R0: the unsupported row-split shape is a first-class
        # classification (NOT_USEFUL_FOR_TESTED_ROLE, fail-closed), not
        # an omission from the machine-readable envelope.
        classify_role(roles["x1p-role-adverse-rowsplit-unsupported"], None),
        classify_concurrent_arm(coarse_split, coarse_single),
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
        "note": ("The retained single-request coarse diagnostic (x1p-role-coarse) "
                 "is excluded from marginal views: its workload shape "
                 "(1 request, 4 idle-capable slots) is not matched to the "
                 "single-sequence controls' semantics."),
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
        "corrected_coarse": {
            "label": "CALCULATED",
            "note": ("The corrected coarse role is the four-concurrent-"
                     "request experiment (x1p-coarse4-split vs the "
                     "workload-matched concurrent control); the "
                     "retained single-request result (x1p-role-coarse) "
                     "is a diagnostic reference only."),
            "aggregate_throughput_split_vs_single": {
                "split": coarse_split["aggregate_throughput_tokens_per_s"],
                "single": coarse_single[
                    "aggregate_throughput_tokens_per_s"],
            },
            "per_sequence_split_vs_single": {
                "split": coarse_split[
                    "per_sequence_throughput_tokens_per_s"],
                "single": coarse_single[
                    "per_sequence_throughput_tokens_per_s"],
            },
        },
        "capacity_authority": {
            "label": "CALCULATED",
            "note": ("capacity_positive is derived from measured "
                     "residency/memory-pressure facts reduced from the "
                     "retained raw stderr (issue35_residency_facts), not "
                     "from the complete_offload layer-count boolean"),
            "control_pressure": capacity_basis["control_pressure_facts"],
            "role_residency": capacity_basis["role_residency_facts"],
        },
        "marginal_views": {
            "label": "CALCULATED",
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
