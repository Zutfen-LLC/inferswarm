# Frozen numerical reducer

The reducer identity is
`host-float64/full-domain/nearest-rank-higher-p99/per-case-family-max/1`.

## Tensor reduction

Hash each source tensor in its native bytes and dtype before conversion. Reject
a shape or semantic-dtype mismatch. Reject NaN and Inf.

Convert reference and candidate elements to host IEEE-754 binary64. For the
complete declared domain, calculate `e_i = abs(reference_i - candidate_i)`.

- Maximum absolute difference is `max(e_i)`.
- RMS difference is `sqrt(fsum(e_i * e_i) / N)`.
- P99 absolute error sorts all `e_i` in ascending numerical order. It uses
  one-based rank `ceil(0.99 * N)`. This is the nearest-rank/higher rule. It does
  not interpolate.

The sort key is the binary64 numerical value. Equal values are equivalent. The
selected value is deterministic even if the stable order of equal values
changes.

## Case-family reduction

For one prompt and one family, collect every declared checkpoint and replay
position. Reduce each tensor first. For each metric, take the largest value
across those checkpoint reductions. The prompt contributes exactly one summary
to each of the 15 envelopes.

## Calibration limit

For one envelope, take the largest summary from the 576 statistical cases.
Take the largest summary from the eight selected stress cases. The inclusive
limit is the larger of those values. A candidate satisfies the envelope when
`observed <= limit`.

Serialize every derived value with an exact hexadecimal binary64 string. Do not
round or edit it.
