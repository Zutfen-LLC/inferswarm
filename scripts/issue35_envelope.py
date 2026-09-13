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

Coarse-concurrent classification — CORRECTED (terminal-semantics
round): the classification consumes the per-attempt DISTRIBUTION,
never a median alone. With two highly separated attempts the median
is not a steady-state measurement and must not be presented as one;
the basis is the per-attempt states against the matched control, the
median ratio is retained only because the frozen stop rules record
it, and NO causal mechanism (e.g. pipeline compilation) is asserted
for a cold first attempt unless it is demonstrated by retained
evidence.

Terminal derivation — CORRECTED (terminal-semantics round): the
campaign terminal is DERIVED from the classifications and marginal
facts by ``derive_terminal`` (and checkable by ``validate_terminal``),
never a manually maintained status string. The issue's own terminal
definitions are implemented mechanically:

* X1_MINIMUM_VIABLE_PARTICIPANT_ENVELOPE_ESTABLISHED — utility is
  characterized across the declared roles well enough to distinguish
  capacity-only versus throughput-useful placements and define
  measured requirements for future resource economics. This does NOT
  require every tested throughput role to be positive.
* X1_PARTICIPANT_ONLY_CAPACITY_USEFUL — only when the bounded tested
  roles establish real capacity utility but NO throughput-neutral or
  throughput-positive serving role under current supported semantics.
  A retained THROUGHPUT_POSITIVE (or capacity-positive
  throughput-neutral) supported serving role FORBIDS this terminal.

Fail-closed: missing inputs raise ``EnvelopeError``; nothing defaults.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import issue35_residency_facts

SCHEMA = "inferswarm.issue35.utility-envelope/3"
NEUTRAL_BAND = 0.05

TERMINAL_ENVELOPE_ESTABLISHED = (
    "X1_MINIMUM_VIABLE_PARTICIPANT_ENVELOPE_ESTABLISHED")
TERMINAL_CAPACITY_ONLY = "X1_PARTICIPANT_ONLY_CAPACITY_USEFUL"
TERMINAL_NOT_USEFUL = "X1_PARTICIPANT_NOT_USEFUL_ON_TESTED_SUBSTRATE"
TERMINAL_INSUFFICIENT = "X1_EVIDENCE_INSUFFICIENT"

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


def dispersion_ratio(values: list[float]) -> float:
    """CALCULATED: max/min separation of an attempt-value list.

    A two-attempt arm whose values differ by an order of magnitude is
    highly dispersed; its median is not a steady-state measurement.
    """
    if not values:
        raise EnvelopeError("no attempt values retained")
    lo, hi = min(values), max(values)
    if lo <= 0:
        raise EnvelopeError(f"non-positive attempt value: {values}")
    return hi / lo


def classify_concurrent_arm(arm: dict, control: dict) -> dict:
    """Classify the corrected concurrent coarse arm against its
    workload-matched concurrent control.

    CORRECTED (terminal-semantics round): the classification consumes
    the per-attempt DISTRIBUTION, never the median alone. The retained
    split arm has two highly separated attempts (large first-versus-
    second-attempt dispersion) while the matched control is stable, so
    the median of the split arm is not presented as representative
    steady-state performance and the classification does not rest on
    the unstable median ratio. The reasoning recorded in the basis is:

    * every retained per-attempt state is compared against the stable
      control state: an attempt inside the neutral band demonstrates
      no improvement beyond the band, and an attempt decisively below
      the control demonstrates degradation;
    * no retained attempt demonstrates throughput improvement beyond
      the declared neutral band;
    * the role contributes no separate capacity benefit in this
      workload (capacity_positive is False on measured facts);
    therefore NOT_USEFUL_FOR_TESTED_ROLE. The per-attempt ratios and
    the dispersion are recorded; the median ratio is retained only
    because the frozen stop rules record medians, and is explicitly
    NOT treated as a stable steady-state ratio. No causal mechanism
    (e.g. pipeline compilation) is asserted for the cold first
    attempt unless demonstrated by retained evidence (none is).
    """
    arm_dist = arm["aggregate_throughput_tokens_per_s"]
    control_dist = control["aggregate_throughput_tokens_per_s"]
    if not arm.get("all_attempts_all_correct"):
        return {
            "role_id": arm["arm_id"],
            "classification": "EVIDENCE_INSUFFICIENT",
            "basis": "not every concurrent request matched the frozen "
                     "reference semantics",
            "label": "MEASURED",
        }
    control_values = control_dist["values"]
    control_rate = control_dist["median"]
    # The control's own per-attempt values anchor the comparison: use
    # each retained control attempt as the matched state.
    arm_values = arm_dist["values"]

    # Per-attempt ratios: every arm attempt against every control
    # attempt would overcount; pair them in retained order (the freeze
    # fixes attempt counts per arm), else against the control median.
    per_attempt = []
    for i, value in enumerate(arm_values):
        matched_control = (control_values[i]
                           if i < len(control_values) else control_rate)
        per_attempt.append({
            "attempt": i + 1,
            "arm_rate": value,
            "control_rate": matched_control,
            "ratio_vs_control_attempt": round(value / matched_control, 4),
        })
    ratios = [p["ratio_vs_control_attempt"] for p in per_attempt]
    arm_dispersion = dispersion_ratio(arm_values)
    control_dispersion = dispersion_ratio(control_values)
    highly_dispersed = arm_dispersion > 1.0 + NEUTRAL_BAND
    control_stable = control_dispersion <= 1.0 + NEUTRAL_BAND

    # State-based reasoning. A stable arm (attempts agree within the
    # band) is characterized by its median as before. A highly
    # dispersed arm cannot be characterized by its median at all; the
    # retained per-attempt states carry the classification:
    #   * no retained attempt improves beyond the neutral band ->
    #     NOT_USEFUL_FOR_TESTED_ROLE (no demonstrated benefit; any
    #     decisively-below attempt is recorded as degradation);
    #   * every retained attempt improves beyond the band ->
    #     THROUGHPUT_POSITIVE (improvement in every retained state);
    #   * mixed states -> EVIDENCE_INSUFFICIENT for a steady-state
    #     characterization (the distribution does not establish one;
    #     no third run is mandated by the frozen stop rules).
    median_ratio = arm_dist["median"] / control_rate
    if not highly_dispersed:
        if median_ratio > 1.0 + NEUTRAL_BAND:
            classification = "THROUGHPUT_POSITIVE"
        else:
            # Inside or below the band with no separate capacity
            # contribution: no measured benefit justifies the added
            # participation for this role shape.
            classification = "NOT_USEFUL_FOR_TESTED_ROLE"
    elif not any(r > 1.0 + NEUTRAL_BAND for r in ratios):
        classification = "NOT_USEFUL_FOR_TESTED_ROLE"
    elif all(r > 1.0 + NEUTRAL_BAND for r in ratios):
        classification = "THROUGHPUT_POSITIVE"
    else:
        classification = "EVIDENCE_INSUFFICIENT"
    def state_words(p):
        r = p["ratio_vs_control_attempt"]
        if r < 1.0 - NEUTRAL_BAND:
            return (f"attempt {p['attempt']}: {p['arm_rate']} vs control "
                    f"{p['control_rate']} t/s ({r}x, decisively below "
                    f"the control)")
        if r > 1.0 + NEUTRAL_BAND:
            return (f"attempt {p['attempt']}: {p['arm_rate']} vs control "
                    f"{p['control_rate']} t/s ({r}x, above the neutral "
                    f"band)")
        return (f"attempt {p['attempt']}: {p['arm_rate']} vs control "
                f"{p['control_rate']} t/s ({r}x, inside the declared "
                f"±{int(NEUTRAL_BAND * 100)}% neutral band)")

    states = "; ".join(state_words(p) for p in per_attempt)
    if classification == "NOT_USEFUL_FOR_TESTED_ROLE":
        state_basis = (
            f"no retained attempt demonstrates throughput improvement "
            f"beyond the neutral band"
            + ("; " + states if states else "")
            + f"; the role contributes no separate capacity benefit in "
              f"this workload")
    elif classification == "THROUGHPUT_POSITIVE":
        state_basis = (
            f"every retained attempt improves beyond the neutral band "
            f"({states}); the first-attempt states are NOT attributed to "
            f"any causal mechanism without retained evidence")
    else:
        state_basis = (
            f"the retained states are mixed ({states}); the distribution "
            f"does not establish a steady-state characterization")
    basis = (
        f"genuinely concurrent four-request workload matched in both "
        f"arms; per-attempt aggregate states: {states}. "
        + (f"The retained split-arm distribution is highly dispersed "
           f"(max/min {arm_dispersion:.3f}) while the matched control "
           f"is stable (max/min {control_dispersion:.3f}), so the "
           f"attempt median ratio {median_ratio:.4f} is recorded per "
           f"the frozen stop rules but is NOT representative "
           f"steady-state performance and does not carry the "
           f"classification. " if highly_dispersed else
           f"The arm attempts agree within the neutral band "
           f"(max/min {arm_dispersion:.3f}); median ratio "
           f"{median_ratio:.4f}. ")
        + f"Mechanical basis: {state_basis}. "
        + (f"A first-attempt initialization/cold-state effect is "
           f"observed (large first-versus-second-attempt dispersion); "
           f"causal attribution is not established by this issue (no "
           f"retained evidence demonstrates a specific mechanism). "
           if highly_dispersed and per_attempt
           and per_attempt[0]["arm_rate"] == min(arm_values) else "")
        + f"Classification: {classification}.")
    return {
        "role_id": arm["arm_id"],
        "classification": classification,
        "throughput_ratio_vs_control": round(median_ratio, 4),
        "role_rate": arm_dist["median"],
        "control_rate": control_rate,
        "per_attempt_states": per_attempt,
        "attempt_dispersion": {
            "arm_max_over_min": round(arm_dispersion, 4),
            "control_max_over_min": round(control_dispersion, 4),
            "arm_highly_dispersed": highly_dispersed,
            "control_stable": control_stable,
        },
        "median_is_steady_state": not highly_dispersed,
        "steady_state_note": (
            "median of two highly separated attempts; NOT "
            "representative steady-state performance"
            if highly_dispersed else
            "attempts agree within the neutral band"),
        "workload_shape": "4 concurrent requests vs 4 concurrent requests",
        "capacity_positive": False,
        "basis": basis,
        "label": "CALCULATED",
    }


def derive_terminal(classifications: list[dict],
                    marginal_views: dict | None = None,
                    link_vs_device: dict | None = None) -> dict:
    """CALCULATED: derive the campaign terminal from the retained
    classifications and marginal facts, per the issue's own terminal
    definitions — never a manually maintained status string.

    * X1_MINIMUM_VIABLE_PARTICIPANT_ENVELOPE_ESTABLISHED — utility is
      characterized across the declared roles well enough to
      distinguish capacity-only versus throughput-useful placements
      and define measured requirements for future resource economics.
      This does NOT require every tested throughput role to be
      positive.
    * X1_PARTICIPANT_ONLY_CAPACITY_USEFUL — only when the bounded
      tested roles establish real capacity utility but NO
      throughput-neutral/positive serving role under current
      supported semantics.
    * X1_PARTICIPANT_NOT_USEFUL_ON_TESTED_SUBSTRATE — no capacity
      utility and no throughput-useful supported role.
    * X1_EVIDENCE_INSUFFICIENT — an effective (non-superseded) role
      still lacks sufficient evidence.

    ``classifications`` must be the EFFECTIVE set: superseded
    diagnostics retained for honesty (their insufficiency resolved by
    a corrected arm, not left open) are excluded by the caller.
    """
    if not classifications:
        raise EnvelopeError("no classifications retained")
    # Superseded diagnostics (retained for honesty, their insufficiency
    # resolved by a corrected arm) are excluded HERE, mechanically —
    # the derivation must not depend on the caller pre-filtering.
    effective = [c for c in classifications if not c.get("superseded_by")]
    if not effective:
        raise EnvelopeError("no effective classifications retained")
    by_class: dict[str, list[dict]] = {}
    for entry in effective:
        by_class.setdefault(entry["classification"], []).append(entry)

    unresolved = by_class.get("EVIDENCE_INSUFFICIENT", [])
    if unresolved:
        return {
            "value": TERMINAL_INSUFFICIENT,
            "label": "CALCULATED",
            "basis": ("effective roles without sufficient evidence: "
                      + ", ".join(sorted(c["role_id"] for c in unresolved))),
        }

    capacity_roles = [c for c in effective if c.get("capacity_positive")]
    serving_roles = [c for c in effective
                     if c["classification"] in ("THROUGHPUT_POSITIVE",
                                                "CAPACITY_POSITIVE_"
                                                "THROUGHPUT_NEUTRAL")]
    not_useful = by_class.get("NOT_USEFUL_FOR_TESTED_ROLE", [])

    capacity_real = bool(capacity_roles)
    serving_real = bool(serving_roles)

    if capacity_real and serving_real:
        # The measured envelope distinguishes capacity-only versus
        # throughput-useful placements (both axes characterized with
        # matched evidence) and carries the measured requirements
        # (transport facts; anchor-relative crossover input).
        distinctions = []
        distinctions.append(
            "decisive capacity/residency utility on measured memory-fit "
            "facts ("
            + "; ".join(f"{c['role_id']} ratio "
                        f"{c.get('throughput_ratio_vs_control')} vs the "
                        f"pressured control"
                        for c in capacity_roles) + ")")
        if marginal_views:
            for role_id, views in marginal_views.items():
                if isinstance(views, dict) and "adding_peer_to_subject" in views \
                        and "adding_subject_to_peer" in views:
                    distinctions.append(
                        f"conditional single-sequence throughput utility "
                        f"depending on anchor compute strength "
                        f"({role_id}: {views['adding_peer_to_subject']['ratio']}x "
                        f"adding the stronger participant to the weaker "
                        f"anchor vs "
                        f"{views['adding_subject_to_peer']['ratio']}x adding "
                        f"the weaker participant to the stronger anchor)")
        for entry in not_useful:
            if entry.get("workload_shape") == ("4 concurrent requests vs "
                                               "4 concurrent requests"):
                distinctions.append(
                    "no demonstrated benefit for the corrected "
                    "four-concurrent-request coarse role ("
                    + entry.get("steady_state_note", "per-attempt states "
                                "retained") + ")")
            else:
                distinctions.append(
                    f"unsupported finer split shape on this substrate "
                    f"({entry['role_id']}: fails closed under current "
                    f"supported semantics)")
        if link_vs_device and "single_subject_compute" in link_vs_device:
            compute = link_vs_device["single_subject_compute"]
            distinctions.append(
                "device/backend compute rate as an explicit crossover "
                "input (device-local ratio "
                f"{compute.get('device_local_ratio_nv_over_amd')}), not an "
                "x1/vendor special case")
        return {
            "value": TERMINAL_ENVELOPE_ESTABLISHED,
            "label": "CALCULATED",
            "basis": ("utility characterized across the declared roles "
                      "well enough to distinguish capacity-only versus "
                      "throughput-useful placements; the measured "
                      "envelope distinguishes: "
                      + "; ".join(distinctions)
                      + ". ENVELOPE_ESTABLISHED does not require every "
                        "tested throughput role to be positive."),
            "supports_capacity_only": False,
            "capacity_roles": sorted(c["role_id"] for c in capacity_roles),
            "serving_roles": sorted(c["role_id"] for c in serving_roles),
        }
    if capacity_real and not serving_real:
        return {
            "value": TERMINAL_CAPACITY_ONLY,
            "label": "CALCULATED",
            "basis": ("real capacity utility established on measured "
                      "memory-fit facts, but no throughput-neutral or "
                      "throughput-positive serving role under current "
                      "supported semantics"),
            "supports_capacity_only": True,
            "capacity_roles": sorted(c["role_id"] for c in capacity_roles),
            "serving_roles": [],
        }
    if serving_real and not capacity_real:
        return {
            "value": TERMINAL_ENVELOPE_ESTABLISHED,
            "label": "CALCULATED",
            "basis": ("throughput-useful supported serving roles "
                      "characterized ("
                      + ", ".join(sorted(c["role_id"] for c in serving_roles))
                      + "); no measured capacity contribution retained, so "
                        "the capacity axis is characterized by its absence "
                        "on the tested roles; the envelope distinguishes "
                        "the two placement kinds for the tested substrate"),
            "supports_capacity_only": False,
            "capacity_roles": [],
            "serving_roles": sorted(c["role_id"] for c in serving_roles),
        }
    return {
        "value": TERMINAL_NOT_USEFUL,
        "label": "CALCULATED",
        "basis": ("no measured capacity contribution and no "
                  "throughput-useful supported serving role on the tested "
                  "substrate"),
        "supports_capacity_only": False,
        "capacity_roles": [],
        "serving_roles": [],
    }


def validate_terminal(declared_terminal: str, classifications: list[dict],
                      marginal_views: dict | None = None,
                      link_vs_device: dict | None = None) -> dict:
    """Fail-closed consistency check between a declared terminal (e.g.
    the STATUS.json string) and the classifications it must derive from.

    Raises ``EnvelopeError`` on any inconsistency, including the
    specific mechanical contradiction of declaring
    X1_PARTICIPANT_ONLY_CAPACITY_USEFUL while retained supported
    serving-role evidence contains a throughput-positive (or
    capacity-positive throughput-neutral) role.
    """
    derived = derive_terminal(classifications, marginal_views,
                              link_vs_device)
    if declared_terminal == TERMINAL_CAPACITY_ONLY and \
            derived["value"] != TERMINAL_CAPACITY_ONLY:
        serving = derived.get("serving_roles") or []
        if serving:
            raise EnvelopeError(
                f"terminal {TERMINAL_CAPACITY_ONLY} is not permitted: "
                f"retained supported serving-role evidence contains "
                f"throughput-neutral/positive roles ({', '.join(serving)})")
    if declared_terminal != derived["value"]:
        raise EnvelopeError(
            f"declared terminal {declared_terminal} does not match the "
            f"terminal derived from the retained classifications "
            f"({derived['value']})")
    return derived


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
        # coarse evidence; workload shape recorded for honesty. It is
        # SUPERSEDED by the corrected concurrent arm — retained for
        # honesty but excluded from terminal derivation (its
        # insufficiency is resolved, not open).
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
            "superseded_by": "x1p-coarse4-split",
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

    link_vs_device = {
        "label": "CALCULATED",
        "note": (
            "Both narrow-link subjects negotiate the same link class "
            "under load (see transport summaries). Observations consistent "
            "across both subjects are plausibly link/role dominated; "
            "device-local compute differences are carried explicitly "
            "from the single-subject controls and are not attributed to "
            "the link."),
        "single_subject_compute": {
            "amd_a_median_tps": amd_single["median"],
            "nv_a_median_tps": nv_single["median"],
            "device_local_ratio_nv_over_amd": round(
                nv_single["median"] / amd_single["median"], 4),
        },
    }

    # Terminal derivation (terminal-semantics round): the terminal is
    # DERIVED from the effective classifications and marginal facts —
    # never a manually maintained status string. Superseded
    # diagnostics are excluded inside derive_terminal (retained for
    # honesty, insufficiency resolved by a corrected arm, they do not
    # force EVIDENCE_INSUFFICIENT).
    terminal = derive_terminal(
        classifications,
        marginal_views=marginal_views,
        link_vs_device=link_vs_device)

    return {
        "schema": SCHEMA,
        "neutral_band": NEUTRAL_BAND,
        "taxonomy": list(TAXONOMY),
        "classifications": classifications,
        "terminal": terminal,
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
        "link_vs_device_separation": link_vs_device,
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
        "terminal": envelope["terminal"]["value"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
