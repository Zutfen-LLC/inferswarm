# Arm-C retry methodology

Status: `ISSUE117_ARM_C_RETRY_METHODOLOGY_READY`

This status identifies CPU-only methodology readiness. It is not a physical
Arm-C retry result. It does not authorize physical execution.

## Authority and scope

Issue #129 follows the accepted Arm-C blocker at merge
`718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22`.

The accepted result remains `ISSUE117_ARM_C_EVIDENCE_BLOCKER`. The retained
18/24 comparison and six regime-4 divergences remain diagnostic only. This
methodology does not tune against them.

This work has these limits:

- No GPU execution.
- No model execution.
- No physical Arm-C retry.
- No Arm D or Arm E work.
- No holdout use.
- No change to accepted Arm-B participant state.

## Immutable accepted history

Every path that existed under `evidence/arm-c/` at the accepted merge must
remain byte-exact. Issue #129 must not add a path to that namespace.

The preservation proof compares each accepted blob with the working-tree byte
digest. It also compares the complete current path set with the accepted path
set. The gate fails on a changed path, a missing path, or an additional path.

Issue #129 retains its three additional FreeToken producer inputs under:

`evidence/arm-c-retry/frozen-source/924cd22e/`

The files are:

- `python/freetoken/research/r3_planner.py`
- `python/freetoken/research/r5a_serving.py`
- `benchmarks/inferswarm_r6/strategy.py`

The accepted `r5b_epochs.py`, `xc_strategy.py`, and `coordinator.py` files stay
in their accepted #128 locations. The proof verifies all six files against
their SHA-256 pins before it imports them.

## Frozen real tokenizer

The proof retains five exact non-weight files under
`evidence/arm-c-retry/frozen-tokenizer/assets/`:

| Asset | SHA-256 |
|---|---|
| `chat_template.jinja` | `ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4` |
| `config.json` | `478c46e8d2c52d5c2d85bf67e3b3e8c90e7c9d91086cee27e3c267907e936bd9` |
| `generation_config.json` | `a8349d9bd64cc5841297fcb5002f0fdc4749c473c8f1b10ea337f9ce4ee7014e` |
| `tokenizer.json` | `cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f` |
| `tokenizer_config.json` | `a62f4e85a47c0c136edaaa3a4f591fd6783717299a9def47e5ad03a49f6a5eb9` |

The source repository is `google/gemma-4-12B-it`. The revision is
`707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`. These byte identities also occur
in the accepted checkpoint-authority provenance.

The accepted physical evidence does not retain a Transformers package version.
Issue #129 therefore freezes this explicit retry identity:

- Python 3.12
- `transformers==5.17.0`
- `tokenizers==0.23.2`
- `Jinja2==3.1.6`
- `MarkupSafe==3.0.3`

The proof checks these installed versions. It also checks the retained
`requirements.txt` and `software-identity.json` byte digests. A future physical
retry that uses this methodology must use this software identity. A different
version requires a new accepted methodology freeze.

The proof loads the tokenizer only from the retained directory:

```python
AutoTokenizer.from_pretrained(
    retained_asset_dir,
    local_files_only=True,
    trust_remote_code=False,
)
```

The asset directory must contain exactly the five listed files. A missing file,
an additional file, a symlink, or a byte mismatch fails the gate.

## Real Coordinator ingress proof

The proof extracts the frozen Coordinator `_render_and_tokenize()` and
`_sampling_of()` functions from the pinned `coordinator.py` bytes. It also
verifies the related `handle_chat()` statements.

For each of the 24 retained `c109-*` cases, the proof does these actions:

1. Load the exact retained request body.
2. Verify the request identity and request order.
3. Run the extracted `_render_and_tokenize()` function with the real tokenizer.
4. Compare the result with `evidence/arm-c-retry/prompt-fixture.json`.
5. Verify session allocation, `max_tokens`, and greedy sampling derivation.

The required result is 24/24 exact equality.

The old `FrozenSourceTokenizerStandIn` remains only as a mutation helper. It is
not an input to `ISSUE117_ARM_C_RETRY_METHODOLOGY_READY`.

## Runtime-call equivalence proof

The ordinary arm uses the real frozen planner, `freeze_execution_plan`,
realization reconciliation, and `EpochServingController.serve_tokens`. The
direct arm is an independent comparator.

Both arms use a recording runtime. The runtime is deterministic and CPU-only.
It does not load or execute a model.

For each committed position, both arms must:

1. Set the replay prefix to the prompt IDs plus committed generated IDs.
2. Call `generate()` with `max_new_tokens=2`.
3. Commit only generated step zero.
4. Discard the speculative second token.
5. Repeat until eight tokens are committed.

Each case must produce exactly eight calls. The reducer compares the complete
ordered transcript. The compared fields include:

- case ID;
- call index;
- runtime `session_id`;
- prompt and replay token IDs;
- `max_new_tokens`;
- `on_token` presence;
- returned token IDs;
- committed token ID;
- speculative token ID;
- sampling inputs;
- stopping policy;
- candidate and mapping.

The runtime `session_id` is a model-execution input. The proof derives its
allocator from the pinned `r5b_epochs.py` AST. It compares the exact sequence
for all calls in all 24 cases.

The only excluded fields are listed control-plane fields. They include epoch,
generation, realization, plan-digest value, logical-session, and wall-clock
fields. These fields cannot occur in the recorded `generate()` argument set.

The required result is 24/24 exact transcript equality.

## Tokenizer and Source boundary

The future physical retry can copy the already-proven tokenizer assets to a
dedicated non-Source path before its observation window. The Coordinator must
use that path.

The future contract requires:

- a tokenizer path outside `/srv/models/`;
- the exact five retained asset bytes;
- an exhaustive directory listing;
- the frozen software identity;
- digest verification before the observation window;
- zero file opens under `/srv/models/` during the observation window.

The CPU proof uses an audit hook to test the zero-Source observation rule. The
presence or absence of a Transformers import is not the invariant.

## Deployment identity

Each correctness-bearing driver must record:

- repository SHA;
- file SHA-256;
- expected absolute path;
- read-only deployment state;
- successful pre-launch verification;
- successful post-run verification;
- post-run file SHA-256 equal to the frozen file SHA-256.

A mutable driver, missing pin, changed byte, or missing verification fails
closed.

## Campaign and STOP state machine

Each correctness-bearing attempt must carry:

- `campaign_id`;
- `physical_authorization_id`;
- `methodology_ready_identity` as the accepted methodology SHA;
- `execution_freeze_identity`;
- `attempt_id`.

The attempt also records its observation time and the campaign authority issue
time. The reducer binds one stable authorization identity and one fresh lineage
root to each campaign.

The public physical-evidence reducer loads its campaign-authority registry from
the fixed `evidence/arm-c-retry/physical-campaign-authority.json` path at an
exact accepted Git commit. That commit must be an ancestor of
`refs/remotes/origin/main`. The reducer loads the bytes with `git show`. It
binds the public entry point to the canonical repository root. A caller cannot
provide an alternate repository or `origin/main` authority domain. It
requires canonical JSON, a strict schema, a Git blob identity, a SHA-256, a
methodology-acceptance reference, and a separate physical-execution
authorization reference. The two references must be distinct. A merge does not
imply physical execution authority.
Each campaign record contains all campaign authority fields, including
`physical_retry_authorized`. The reducer compares every attempt with that
accepted record. Attempt facts cannot establish their own methodology or
physical execution authority. No such physical authority record exists in this
PR. The CPU-only self-checks use a private synthetic-record reducer. Its output
is not physical execution authority.

An invalid correctness-bearing observation fires a permanent mandatory STOP
for that campaign. No later attempt in that campaign can clear the STOP. Later
observations can be retained only as disclosed diagnostics. They are never
verdict authority.

`TERMINAL_CAMPAIGN_ATTEMPT` is valid only when the campaign has never fired a
mandatory STOP. A campaign passes only after an authoritative terminal attempt.
A valid nonterminal attempt does not make a campaign pass. A
non-correctness-bearing terminal marker is not authority. An explicitly
disclosed diagnostic is never authority, including in a fresh campaign.

A new campaign after review must have:

- a new `campaign_id`;
- a new `physical_authorization_id`;
- a fresh campaign lineage root;
- a link to the prior stopped campaign and STOP attempt;
- a maintainer review identity and review time;
- a physical authorization issue time after both the STOP and the review.

The reducer rejects a Boolean-only authorization change, an authorization ID
change within one campaign, authorization reuse, lineage-root reuse, a missing
review link, or an authorization that predates the STOP or review. It also
rejects a new campaign when the immediately prior campaign has neither a STOP
nor an authoritative terminal. An intermediate nonterminal campaign cannot
bypass a prior STOP and review boundary. The latest STOP and review time remain
a global authorization watermark for all later campaigns. A successful
intermediate campaign does not remove that watermark.

The positive lineage control keeps campaign A blocked after an invalid
correctness-bearing attempt. It then evaluates a separately constructed
campaign B with a fresh post-review authorization. Campaign B can reach a valid
terminal observation without changing campaign A.

## Fail-closed controls

The test suite covers these runtime and ingress mutations:

1. Single-shot `max_new_tokens=8`.
2. Wrong replay prefix.
3. Changed call count.
4. Speculative token committed.
5. Runtime-session sequence drift.
6. Sampling-input drift.
7. Prompt-token drift.
8. Stopping-policy drift.
9. Control-plane field leakage into runtime inputs.
10. Request-body drift.
11. Chat-template or content mutation.
12. Real rendered IDs different from the frozen fixture.

The suite covers these identity and provenance mutations:

13. Any tokenizer asset byte mutation.
14. Missing tokenizer asset.
15. Additional tokenizer asset.
16. Tokenizer package or version drift.
17. Tokenizer path under `/srv/models/`.
18. Forbidden Source open during the observation window.
19. Mutable or unpinned deployed driver.
20. Changed deployed driver after freeze.
21. Missing inherited producer pin.
22. Mutated frozen producer byte.
23. Changed or missing accepted #128 path.
24. New path in the accepted `evidence/arm-c/` namespace.
25. Stored equality or terminal text used as authority.

The suite covers these campaign mutations:

26. Invalid attempt followed by a terminal attempt in the same campaign.
27. Boolean-only physical authorization change in the same campaign.
28. Authorization ID change without a campaign ID change.
29. Old authorization ID reused for a new campaign.
30. New-campaign authorization issued before the prior STOP or review.
31. Post-STOP diagnostic used as verdict authority.
32. Non-correctness-bearing terminal marker used as authority.
33. Undisclosed correctness-bearing continuation after STOP or terminal.
34. Infrastructure-only or valid nonterminal campaign used as a PASS.
35. Intermediate nonterminal campaign used to bypass a prior STOP and review.
36. Explicit diagnostic disclosure used as verdict authority in a fresh
    campaign.
37. Attempt methodology or execution identity different from the separate
    accepted campaign authority record.
38. Missing accepted campaign authority record.
39. Diagnostic disclosure used to hide missing methodology readiness.
40. Diagnostic disclosure used to hide invalid deployment identity.
41. Attempt facts copied into a caller-supplied authority mapping.
42. Missing fixed-path authority file at an accepted commit.
43. Merge or methodology acceptance used without separate physical execution
    authorization.
44. Successful intermediate campaign used to erase the latest STOP/review
    authorization watermark.
45. Authority commit not present on `refs/remotes/origin/main`.
46. Caller-controlled repository root or `origin/main` authority domain.
47. One reference used as both methodology acceptance and physical execution
    authorization.

## Retained outputs

Issue #129 retains these derived records under `evidence/arm-c-retry/`:

- `prompt-fixture.json`
- `methodology-run.json`
- `authority.json`
- `integrity.json`

The methodology run records the real-tokenizer result, exact runtime-session
comparison, namespace preservation result, state-machine controls, CPU-only
status, and terminal.

Generate authored and derived files first. Generate indexes and hashes next.
Generate manifests last.

## Non-claims

This methodology does not establish an Arm-C ordinary-serving PASS or semantic
FAIL. It does not decide the six regime-4 divergences. It does not authorize a
physical retry. It does not authorize Arm D or Arm E.

STOP for maintainer review.
