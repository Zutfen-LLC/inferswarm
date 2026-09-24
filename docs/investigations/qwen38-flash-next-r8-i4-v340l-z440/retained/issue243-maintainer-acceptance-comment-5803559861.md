## Maintainer decision — GO for closure work

Decision report comment #5803481831 is accepted for the Issue #243 engineering decision point.

Accepted disposition:

`R8I4_V340_Z440_PRACTICAL_SINGLE_DIE_AND_DUAL_RESOURCE`

Proceed with **closure work only** under the issue contract:

- add the minimal durable investigation/evidence record;
- add/update the evidence manifest and focused verification needed by repository doctrine;
- update the PCIe ledger for **inferswarm05** from the freshly retained topology;
- open exactly one PR and leave it **OPEN / UNMERGED** for exact-head maintainer review;
- do not execute `c237-*` predictive calibration, derive R8-J thresholds, access/decrypt the sealed holdout, or claim #239 is unblocked;
- do not rewrite #240 historical evidence.

Two precision requirements for the durable record:

1. **PCIe topology:** preserve the complete `lspci -PP` path and distinguish each die's Gen3 x16 endpoint/downstream link from the card/system's shared upstream/root-port path. Do not imply two independent x16 host uplinks merely because both die endpoints report x16.

2. **Campaign projection:** replace the equal-four-regime approximation with the frozen realized regime counts when recording the durable projection: 338 / 366 / 363 / 349 for ~256 / ~1024 / ~3072 / ~4096. Using the reported representative walls (13.6 / 24.7 / 63.9 / 81.3 s) gives ~18.11 h sequential before any additional comparator/observer overhead. Keep the ~9 h dual-die figure explicitly an engineering throughput projection, not R8-J qualification authority.

Thermal language must remain scoped to the **bounded retained Qwen workload / temporary 140 mm cooling arrangement**. The retained <=55 C result is strong evidence for this campaign, but it is not a full-TDP or universal V340L cooling qualification.

Current `origin/main` was rechecked at maintainer review and remains `3aa59aed74df7f00302a6a2eb84640623b7cc14b`. Re-fetch before closure work and reconcile normally if it advances.

After the closure PR is open and CI is green, STOP and report the exact PR head for maintainer review. Do not create/execute the V340L comparator/2 numerical successor in the same session.