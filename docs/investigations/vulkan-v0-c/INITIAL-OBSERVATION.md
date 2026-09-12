# V0-C initial physical observation

Classification: `V0C_EVIDENCE_BLOCKED`

This is an initial physical observation, not a V0-C pass. It is retained so the
next attempt cannot silently reinterpret the result.

## Observed facts

The run used the Phase-0 source identity and executable hash, the frozen model
hash and size, selector `Vulkan1`, BDF `02:00.0`, `-ngl 99`, and the frozen
prompt/sampling values. It exited 0. The retained backend stderr proves:

- `using device Vulkan1 ... (0000:02:00.0)`;
- `offloaded 37/37 layers to GPU`.

The visible deterministic response matches the accepted V0-A AMD-A Vulkan
response. It reported 243.6 prompt tokens/s and 44.1 generation tokens/s.
Those are one-run observations, not a performance claim or comparison.

## Why this does not pass V0-C

The command was an adapter substrate smoke, not a realization driven by the
new generic frozen-plan implementation. It therefore cannot prove the required
end-to-end sequence of generic planning, frozen-plan realization, observed
state reconciliation, and result attribution. It also records process-level
output only; it does not provide direct materialization accounting sufficient
to establish zero unexplained persistent host mirror bytes.

No fallback-free V0-C architectural pass, numerical-equivalence claim,
performance claim, or preferred-backend policy is made.

## Retained raw files

- `raw/v0c-amd-a-01/stdout.txt` — SHA-256
  `3f9ebfffc8cec1ee6f62df17d6c5c22134c86a7bf2fe5e8719f050dd74e9691a`;
- `raw/v0c-amd-a-01/stderr.txt` — SHA-256
  `ec070eaa29c3910436f92dad51a021dceae97879f3ffed6f6e87d1697a69d1bc`;
- `raw/v0c-amd-a-01/exit-code.txt` — SHA-256
  `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`.
