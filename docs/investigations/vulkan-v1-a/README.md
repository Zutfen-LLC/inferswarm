# V1-A reusable internal execution participant

Status: CPU-only seam correction is pending the required full CPU gate; physical qualification and canonical reproduction are not yet authorized.

This additive investigation generalizes the accepted V0-C S2 control-plane seam. The generic internal participant accepts opaque Node, Compute Unit, Memory Resource, physical identity, execution contract, implementation, evidence, strategy-unit, representation, feature, integrity, economics, candidate, plan, and adapter-validated canonical-proof inputs. It intentionally does not expose a public plugin or backend API.

The generic participant is `scripts/v1a_execution_participant.py`. It contains no vendor or accelerator-runtime selection token, model-specific layer count, backend runtime field, or proving-resource default. Node identity is bound into candidate identity, frozen plans, capability qualification, and canonical receipt attribution. `scripts/v1a_vulkan_adapter.py` is the backend-local boundary: it parses runtime proof, rejects fallback or incomplete offload, validates the selected physical device, and seals an opaque canonical proof from raw runtime bytes. A qualification observation cannot substitute for that proof.

`COUPLING-AUDIT.json` mechanically classifies physical-authority facts, generic contract inputs, and backend-local details. CPU controls exercise a synthetic complete 12/12 observation, 11/12 rejection at the adapter boundary, Node identity absence/mismatch, frozen-plan substitution, forged mapping rejection, qualification-proof substitution, and cross-node canonical proof rejection.

No V1-A physical output is retained in this repository yet. The proving host is local to this session (`inferswarm02`), so no SSH host key was accepted or used. No synthetic CPU control is presented as physical qualification, and this directory does not claim `V1A_REUSABLE_VULKAN_PARTICIPANT_PASS`.
