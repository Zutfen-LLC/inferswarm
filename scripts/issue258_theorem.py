#!/usr/bin/env python3
"""#258 prospective arm-set theorem: mechanically explicit terminal capability.

Repository-only derivation, frozen BEFORE any further physical execution.
This module re-derives the R8-I3C localization/non-localization arm-set law
after the accepted A3 (variable, mechanism-capable) and A5
(A5_OBSERVATIONALLY_CAPABLE_NONTERMINAL, #257) physical findings.

It grants NO physical execution authority and reads NO evidence root. It is
pure source-derived law consumed by scripts/issue252_terminal.py (the
retained-byte reducer) so that terminal derivation no longer conditions any
terminal on the mere execution of a named arm.

Grounding (all citations at the frozen llama.cpp pin b29c606e, tree
950999fe, file ggml/src/ggml-vulkan/ggml-vulkan.cpp; verified read-only
2026-10-02 in /home/zutfen/llama.cpp-252 which carries exactly that
commit/tree):

- Every #252 arm control is an environment-variable PRESENCE gate:
  :6553-6554 prefer_host_memory, :6556-6557 disable_host_visible_vidmem,
  :6724 support_async (&& getenv(...) == nullptr),
  :7435 serialize_submissions. Presence (not value) selects the branch.

TERMINAL CAPABILITY, per arm, derived from retained-observable existence at
the pin (NOT from arm names, and NOT from whether an arm was executed):

- A1 (GGML_VK_SERIALIZE_SUBMISSIONS): NON_TERMINAL_CAPABLE. The serialized
  wait path (:18105 waitForFences) emits no retained observable that
  distinguishes a serialized submission from an unfenced batch
  (issue252_mechanism.NON_TERMINAL_CAPABLE["A1"], unchanged).
- A2 (GGML_VK_DISABLE_COOPMAT): DEAD_CONTROL on the frozen subject. The
  gate touches only KHR cooperative-matrix detection (:6600); the frozen
  RTX 3060 / NV_coopmat2 subject selects coopmat2 (:7678-7679) which the
  gate does not remove, so family stays NV_coopmat2 with the control live.
  A2 cannot change the selected shader family on THIS subject: executing
  it adds a negative-control fact only, never terminal information.
- A3 (GGML_VK_DISABLE_ASYNC): TERMINAL_CAPABLE and physically variable
  (accepted round-7: first mismatch at unit 002). Retained observable: the
  exact async-disabled stderr line (:6727) plus producer-attested placement
  (AMENDMENT-005).
- A4 (GGML_VK_PREFER_HOST_MEMORY): NON_TERMINAL_CAPABLE. No retained
  observable binds an allocation line to the prefer_host_memory branch
  (issue252_mechanism.NON_TERMINAL_CAPABLE["A4"], unchanged).
- A5 (GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM): NON_TERMINAL_CAPABLE at this
  pin WITHOUT new instrumentation. Accepted #257 classification
  A5_OBSERVATIONALLY_CAPABLE_NONTERMINAL: the control is attested live and
  staging activity is authentic, but no retained observable uniquely
  discriminates the selected model-buffer memory type / upload path
  relative to the no-A5 branch (both overloads of the staging marker,
  eDeviceLocal reachable from both branches, no property flags logged).

HYPOTHESIS-CLASS COVERAGE (frozen #252 hypothesis matrix):

- H1 (uninitialized read), H4 (driver shader cache), H6 (ASLR/pointer
  reuse): discriminator_arm = None at freeze. No single-factor control
  exists; they are OUTSIDE any arm-provable coverage and therefore outside
  terminal closure. Their existence is exactly why the terminal vocabulary
  keeps an UNRESOLVED state: absence of a discriminator is not negative
  evidence.
- H2 (cross-queue sync / aliasing): discriminator arm A1 — nonterminal.
- H3 (memory-type / allocation fallback): discriminator arm A4 —
  nonterminal (A5 shares the mechanism family and is also nonterminal).
- H5 (shape-sensitive path selection): discriminator arm A2 — dead control
  on this subject.

THE NEW THEOREM (AMENDMENT-006). Terminal T of the R8-I3C reduction is
derived under capability-explicit laws:

1. LOCALIZED(_FIX_VALIDATED / _FIX_NOT_VALIDATED, unchanged strings): some
   arm X with TERMINAL_CAPABLE[X] is True has a valid deterministic
   retained population AND X's frozen mechanism contract holds on the
   retained bytes. (Determinism contrast alone under any arm never
   localizes.)
2. NON_LOCALIZED (new string, see constants): EVERY frozen hypothesis
   class whose discriminator_arm is not None is covered by at least one
   terminal-capable arm, every terminal-capable arm has an admissible
   retained population, and every such population is variable (no
   deterministic correction). I.e., the complete set of discriminators
   that COULD have restored determinism each demonstrably failed, and no
   discriminator-less mechanism family is claimed excluded.
3. UNRESOLVED (unchanged string): admissible retained evidence exists but
   the coverage precondition of (2) does not hold — at least one frozen
   hypothesis class with a discriminator arm has no terminal-capable arm
   that has produced an admissible population (absent, blocked, or
   nonterminal-only), or only nonterminal arms executed.

Under the CURRENT frozen pin/subject the coverage precondition of (2) is
provably FALSE (H2->A1 nonterminal, H3->A4/A5 nonterminal, H5->A2 dead):
the honest terminal for any admissible all-variable state — including the
accepted A3+variable plus A5+variable physical state — is UNRESOLVED, and
executing A1/A2/A4 or re-executing A5 under unchanged instrumentation
cannot change the terminal. Only new prospective instrumentation that
makes a currently-nonterminal arm terminal-capable (with its own exact-head
reviewed freeze) can reopen NON_LOCALIZED.

That is the exact withdrawal of the old complete-named-arm-set law: the
old reducer demanded set(states) == set(A.ARMS) — the execution of all
five NAMED arms — for any non-localization-family terminal, including
arms that provably cannot change any terminal. "Ran every named arm" is
not a logical theorem; coverage by terminal-CAPABLE discriminators is.
"""
from __future__ import annotations

# Mechanically explicit terminal-capability law, consumed by the reducer.
# Values are frozen facts with their authority; tests pin them.
TERMINAL_CAPABLE = {
    "A1": False,
    "A2": False,   # dead control on the frozen NV_coopmat2 subject
    "A3": True,
    "A4": False,
    "A5": False,   # A5_OBSERVATIONALLY_CAPABLE_NONTERMINAL (#257)
}
CAPABILITY_REASON = {
    "A1": "no retained submission-serialization observable exists at pin "
          "b29c606e; the serialized wait path emits no distinguishable "
          "retained bytes",
    "A2": "dead control on the frozen RTX 3060 / NV_coopmat2 subject: the "
          "KHR-only coopmat disable does not remove the subject's selected "
          "coopmat2 family, so the control cannot change the selected path",
    "A3": "terminal-capable at pin b29c606e: the exact async-disabled line "
          "(:6727) plus producer-attested placement (AMENDMENT-005) "
          "uniquely prove the intervention was live",
    "A4": "no retained observable at pin b29c606e binds an allocation line "
          "to the prefer_host_memory branch",
    "A5": "A5_OBSERVATIONALLY_CAPABLE_NONTERMINAL (#257): control attested "
          "live and staging authentic, but no retained observable uniquely "
          "discriminates the selected model-buffer memory type / upload "
          "path at this pin",
}
# Hypothesis-class -> discriminator-arm coverage map (frozen #252 matrix).
HYPOTHESIS_DISCRIMINATORS = {
    "H1": None, "H2": "A1", "H3": "A4", "H4": None, "H5": "A2", "H6": None,
}
# Arms sharing the H3 memory-type/allocation-fallback mechanism family.
H3_FAMILY_ARMS = ("A4", "A5")


def capability_matrix() -> dict[str, dict[str, object]]:
    """Machine-readable A1-A5 capability matrix (Phase-1 deliverable)."""
    import issue252_arms as A

    matrix = {}
    for arm, spec in A.ARMS.items():
        control = spec["control"]
        capable = TERMINAL_CAPABLE[arm]
        matrix[arm] = {
            "control": control["name"],
            "control_kind": control["kind"],
            "intended_mechanism": spec["one_factor"],
            "hypothesis_class": next(
                (h for h, a in HYPOTHESIS_DISCRIMINATORS.items() if a == arm),
                None),
            "terminal_capable": capable,
            "capability_reason": CAPABILITY_REASON[arm],
            "dead_control_on_frozen_subject": arm == "A2",
            "reducer_treatment": (
                "mechanism validator admissible for localization"
                if capable else
                "never required for terminal completion; never grants "
                "terminal authority from determinism contrast or evidence "
                "presence"),
        }
    return matrix


def hypothesis_coverage() -> dict[str, object]:
    """Coverage fact for the NON_LOCALIZED precondition (theorem clause 2).

    Returns {"covered": bool, "gaps": [...]} where each gap names a frozen
    hypothesis class with a discriminator arm that has NO terminal-capable
    arm. A class is covered iff at least one terminal-capable arm maps to
    it (directly, or through the H3 memory-type family sharing).
    """
    gaps = []
    for hyp, arm in HYPOTHESIS_DISCRIMINATORS.items():
        if arm is None:
            continue  # no discriminator exists: outside arm-provable scope
        candidates = [arm]
        if arm == "A4":
            candidates = list(H3_FAMILY_ARMS)
        if not any(TERMINAL_CAPABLE.get(a, False) for a in candidates):
            gaps.append({
                "hypothesis": hyp,
                "discriminator_arm": arm,
                "reason": CAPABILITY_REASON[arm],
            })
    return {"covered": not gaps, "gaps": gaps}


def terminal_capable(arm: str) -> bool:
    """Frozen terminal-capability fact for one arm (fail-closed)."""
    return TERMINAL_CAPABLE.get(arm, False)


def terminal_capable_arms() -> list[str]:
    """Existing terminal-capable arms, sorted (inventory fact only).

    This is NOT a closure set: terminal-capable is a per-arm property
    (retained-observable existence at the pin), independent of whether
    non-localization coverage is satisfiable. Closure additionally
    requires hypothesis coverage (see terminal_closure()).
    """
    return sorted(a for a, capable in TERMINAL_CAPABLE.items() if capable)


def terminal_closure() -> dict[str, object]:
    """Structured terminal-closure fact (fail-closed).

    Returns {"closure_possible": bool, "required_arms": [...],
    "coverage_gaps": [...]}. required_arms is non-empty ONLY when every
    discriminator-bearing frozen hypothesis class is covered by at least
    one terminal-capable arm; while coverage is impossible at the current
    freeze (gaps non-empty) closure is not possible and the required-arm
    set is [] — an existing terminal-capable arm (A3) is never a
    sufficient closure set on its own.
    """
    coverage = hypothesis_coverage()
    possible = coverage["covered"]
    return {
        "closure_possible": possible,
        "required_arms": terminal_capable_arms() if possible else [],
        "coverage_gaps": coverage["gaps"],
    }


def required_arms() -> list[str]:
    """Physical arms required for NON_LOCALIZED closure, IF closure is
    possible at all.

    Fail-closed: returns [] while hypothesis coverage is incomplete at
    the current freeze — which it provably is (H2/H3/H5 gaps) — because
    no set of existing-arm executions can make NON_LOCALIZED reachable
    then. The terminal-capable inventory (A3 today) is a per-arm fact
    exposed separately by terminal_capable_arms(); it is NOT by itself a
    closure claim (AMENDMENT-006 §4).
    """
    if not hypothesis_coverage()["covered"]:
        return []
    return terminal_capable_arms()


def validate_theorem() -> list[str]:
    """Structural self-check of the frozen law (fail-closed)."""
    import issue252_arms as A

    problems = []
    if set(TERMINAL_CAPABLE) != set(A.ARMS):
        problems.append("TERMINAL_CAPABLE does not cover the frozen arm set")
    if set(CAPABILITY_REASON) != set(TERMINAL_CAPABLE):
        problems.append("CAPABILITY_REASON arms differ from TERMINAL_CAPABLE")
    for hyp, arm in HYPOTHESIS_DISCRIMINATORS.items():
        if arm is not None and arm not in TERMINAL_CAPABLE:
            problems.append(f"{hyp} names unknown discriminator arm {arm}")
    covered = hypothesis_coverage()
    if covered["covered"] and not any(TERMINAL_CAPABLE.values()):
        problems.append("coverage claimed with zero terminal-capable arms")
    return problems


def main() -> int:
    import json
    import sys

    problems = validate_theorem()
    if problems:
        print("invalid theorem: " + "; ".join(problems))
        return 1
    print(json.dumps({
        "schema": "inferswarm.issue258.capability-matrix/1",
        "capability_matrix": capability_matrix(),
        "hypothesis_coverage": hypothesis_coverage(),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
