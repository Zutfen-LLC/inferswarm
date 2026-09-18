# V2-D producer architecture — rejected design audit record

This campaign's producer architecture is the second design. The first
(PR #218, head 7813e582, branch issue-216-v2d-concurrent-dual-die)
was rejected by an independent read-only exact-worktree audit
(2026-09-17) with a NO-GO verdict before any physical V2-D receipt
existed. PR #218 produced zero physical V2-D receipts and no V2-D
capability claim; it remains retained as historical design evidence
only. The issue body prohibits resurrecting its trust seams.

## Audit findings that this architecture must not repeat

1. Closure drift: physical producers had uncommitted working-tree
   changes while `closure_document()` byte-compared sources against
   Git — every CLI was blocked. Correction: closure sources are read
   through `git show :<path>` (committed bytes), the closure record is
   a committed artifact, and every producer verifies it before
   emitting.
2. CLI output shapes were assembler-inadmissible (fresh-map emitted
   nested fresh_binding; preflight omitted predecessor proof and
   parsed topology; execution omitted the raw fields the reducer
   needed; baselines could never satisfy the 3x2 denominator;
   concurrent output embedded summaries instead of receipt refs;
   transport rows omitted requested/transferred bytes and exit status;
   soak telemetry omitted sequence and fault-state fields).
   Correction: one raw-receipt protocol (scripts/issue216_receipt.py)
   binding raw bytes by content; the assembler derives from bytes via
   accepted parsers and treats collector summaries as cross-checks.
3. Raw bindings were generated summaries, not raw source authority.
   Correction: receipts bind {rel_path, sha256, byte_count} of the
   retained command bytes; the assembler re-hashes and re-parses them.
4. Fresh mapping assigned die labels by BDF sort without proving
   intended-vs-current identity. Correction: fresh-map requires the
   accepted V2-B selector↔BDF correspondence for both dies
   (intended-identity corroboration) plus distinct device UUIDs.
5. Campaign-id mismatch (plan said -v1, envelopes -v2) and
   producer-runtime fallback literals. Correction: single
   CAMPAIGN_ID constant; no fallback runtime identity fields.
6. Reducer denominator checks incomplete (one sample passed
   transport; soak had no duration/cadence denominator).
   Correction: assembler enforces complete denominators per phase
   (3x concurrent repeats minimum, 60-min soak, cadence bounds,
   checkpoint schedule).
7. Tests proved emission seams, not the real CLI path. Correction:
   tests run the real collectors against fixture trees and the real
   assembler as a subprocess (sandbox mutation controls), asserting
   exact terminals.

## Also rejected from #219's rubric (inherited)

- process/wrapper lifetime + shared start gate as overlap authority
  (wrapper overlap does not prove GPU-work overlap);
- polling-based GPU utilization as sole overlap proof;
- GGML_VK_PERF_LOGGER seam (adds per-graph host fence wait).
