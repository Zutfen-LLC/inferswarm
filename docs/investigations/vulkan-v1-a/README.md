# V1-A reusable internal execution participant

Status: physical campaign complete on `inferswarm02` through the generalized seam; terminal candidate `V1A_REUSABLE_VULKAN_PARTICIPANT_PASS`, recorded in draft PR #156 pending acceptance.

This additive investigation generalizes the accepted V0-C S2 control-plane seam. The generic internal participant accepts opaque Node, Compute Unit, Memory Resource, physical identity, execution contract, implementation, evidence, strategy-unit, representation, feature, integrity, economics, candidate, plan, and adapter-validated canonical-proof inputs. It intentionally does not expose a public plugin or backend API.

The generic participant is `scripts/v1a_execution_participant.py`: no vendor token, model-specific layer count, backend runtime field, or proving-resource default. Node identity and the execution contract are bound into candidate identity, frozen plans, capability qualification, adapter-sealed canonical proofs, canonical observations, and receipts; a contract-A observation cannot be enriched into a contract-B capability and a contract-A proof cannot satisfy a contract-B plan. `scripts/v1a_vulkan_adapter.py` is the backend-local boundary. `scripts/v1a_runner.py` orchestrates the campaign locally without SSH, reusing the accepted V0-C accounting reducer and byte-exact correctness comparator unchanged.

Campaign evidence: fresh qualification `v1a-amd-a-qualification-01` (37/37 offload, no fallback, clean exit, contract sealed), mixed-resource generic plan `v1a-amd-a-plan-01` (AMD/Vulkan participant selected from opaque facts; NVIDIA/native pressure excluded `EXECUTION_CONTRACT_UNSUPPORTED`), canonical reproduction `v1a-amd-a-canonical-01` (accounting 0/0/0, byte-exact visible output equal to the accepted reference). The prospective physical authority (`PHYSICAL-AUTHORITY.json`) was frozen and pushed before physical output; two superseded pre-freeze probes are recorded in `FINAL-TERMINAL.json`.

The earlier `V1A_EVIDENCE_BLOCKED` SSH condition was a withdrawn session assumption: the session ran locally on the proving node. No public API, production-support claim, or preferred/default-backend policy is introduced.
