# Artifact-locality transition planning — issue #103

Status: **`ARTIFACT_LOCALITY_TRANSITION_PLANNING_PASS`**.

This internal CPU proof ranks an already legal candidate set with frozen
artifact locality and path evidence. Locality is ranking evidence. It is not a
technical feasibility rule or an unconditional candidate preference.

The canonical campaign proves:

| Arm | Transition costs A / B / C | Transition winner | Execution winner |
|---|---:|---|---|
| A | 0.5 / 1.0 / 3.0 seconds | A | B |
| B | 0.5 / 1.0 / 0.0 seconds | C | B |

Arm B changes only verified local inventory on C. The legal candidate set and
technical feasibility remain unchanged. All three required artifacts are four
bytes, for a total of 12 bytes.

The result is a serialized first-order ranking proxy. It is not a production
scheduler and it does not predict physical transfer wall time.

Reproduce the evidence with:

```bash
python3 scripts/issue103_proof.py
python3 -m unittest tests.test_issue103_planner -v
```

The evidence directory contains the frozen strategy, exact requirements,
inventory and source indexes, path evidence, candidate economics,
objective-specific decisions, tie/permutation proof, adversarial controls,
accounting, purity audit, isolation audit, producer hashes, and the integrity
manifest.

No public planner, artifact, path, or wire schema is frozen. No physical
qualification or FreeToken integration is claimed.
