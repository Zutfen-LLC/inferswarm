# InferSwarm Security Policy

## Status

InferSwarm is research / proof-of-concept software. No stable release exists;
only the `main` branch is developed, and security fixes land there. There is
no backport policy for pre-alpha software.

## Reporting a vulnerability

We use **GitHub private vulnerability reporting** — the same mechanism other
Zutfen repositories use. Please do not publicly disclose security
vulnerabilities before a fix is available.

To report:

1. Navigate to
   <https://github.com/Zutfen-LLC/inferswarm/security/advisories/new>
2. Create a private security advisory.
3. Provide a clear description, reproduction steps, and impact assessment.

## Current security posture — read this before deploying

The current proof-of-concept code paths involve a host inference engine and
workers on machines you control. **The POC is not suitable for untrusted or
Internet-exposed operation.** Do not expose POC worker endpoints to networks
you do not trust.

## Future concerns for network workers

Distributed execution over a network introduces a real threat model that the
POC does not yet address. Recorded here so it is not lost; none of it is
implemented, and none should be assumed present:

- **Untrusted nodes** — what happens when a worker joins that is not
  controlled by the operator.
- **Authentication** — proving worker and coordinator identity before
  dispatching work or accepting results.
- **Activation confidentiality** — activations can leak input text;
  shipping them across a network has privacy implications.
- **Model-weight confidentiality** — experts resident on a remote worker
  put licensed/proprietary weights on another machine.
- **Control-plane authorization** — who may enroll a worker, contribute
  capacity, or change placement policy.
- **Remote execution boundaries** — any "execute this here" protocol is a
  remote-code-execution surface by definition; it must be scoped tightly.

These concerns will be addressed as network workers move from POC to design;
until then, treat every worker link as a trust boundary you have manually
verified.
