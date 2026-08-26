# Protocols

Design notes for the InferSwarm worker/transport protocol. **The final wire
protocol does not exist yet and is not invented here.** This page records
design goals and constraints so that when the protocol is designed (as the
roadmap's distributed POCs demand it), it starts from stated principles
instead of accidents.

## Design goals

The protocol between a host/coordinator and workers should be:

- **Versioned** — protocol versions negotiated explicitly; workers and
  coordinators can refuse mismatched versions cleanly.
- **Binary-friendly** — activation payloads and results are tensors;
  serialization overhead should not tax every dispatch.
- **Compact** — payloads are small by design (that is the whole premise of
  moving activations instead of weights); framing should stay small too.
- **Transport-independent where practical** — the same message semantics
  over same-machine transports (IPC/shared memory/CUDA IPC) and network
  transports (TCP and up), so a worker behind Ethernet and a GPU next door
  differ in transport, not in protocol shape.
- **Persistent connections** — per-dispatch connection setup would dominate
  latency at 1 GbE scale; connections are established once and reused.
- **Batch by destination** — work for a worker is grouped into one dispatch,
  not one message per expert.

## Dispatch shape

The intended unit of work (aligned with the MoE execution concept in
[../../ARCHITECTURE.md](../../ARCHITECTURE.md)):

- one activation payload per worker per layer, where practical;
- all selected expert IDs / routing information relevant to that worker in
  the same dispatch;
- the worker executes multiple selected experts locally and accumulates;
- the worker returns the smallest practical combined result;
- **avoid a one-network-request-per-expert architecture** — per-expert
  fan-out is the worker's local problem;
- **avoid HTTP/JSON per expert** — request/response per unit of work with
  text serialization is the anti-pattern this design exists to prevent.

## Capability negotiation and correctness

- Support **capability negotiation**: a worker advertises what it can execute
  (formats, expert shapes, resources) at handshake; the coordinator places
  work accordingly (measure, don't stereotype — README principle 8).
- Support **correctness/version checks**: enough interchange metadata
  (format versions, checksums of resident expert data) to detect
  configuration drift between host and workers before it silently corrupts
  outputs.

## Room to grow

The protocol must leave room for:

- same-machine transports (no network hop) and network transports as peers;
- additional resource kinds (RAM-only workers, future storage tiers);
- non-MoE work units (the fabric is model-independent; expert dispatch is
  the first work-unit type, not the only conceivable one).

## The 1 GbE constraint, stated plainly

> 1 GbE viability depends primarily on latency/synchronization behavior
> after activation payloads become small; this remains an experimental
> question.

That sentence is the protocol's driving constraint (ADR 0003). At MoE
activation sizes (kilobytes), a 1 GbE link moves the payload itself in
microseconds; what can kill the design is per-dispatch overhead — round
trips, synchronization stalls, serialization. Hence persistent connections,
destination batching, and binary framing as goals, and hence ROADMAP Phase
4's explicit measurement of latency sensitivity independent of bandwidth.
