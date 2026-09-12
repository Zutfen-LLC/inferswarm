# V1-A reusable internal execution participant

Status: CPU-only seam implementation complete; physical qualification and canonical reproduction pending authenticated access to the proving host.

This additive investigation generalizes the accepted V0-C S2 control-plane seam. The generic internal participant accepts opaque node, Compute Unit, Memory Resource, physical identity, execution contract, implementation, evidence, strategy-unit, representation, feature, integrity, economics, candidate, plan, materialization, observation, and receipt inputs. It intentionally does not expose a public plugin or backend API.

The generic participant is `scripts/v1a_execution_participant.py`. It contains no vendor or accelerator-runtime selection token. `scripts/v1a_vulkan_adapter.py` is the backend-local boundary that parses runtime proof and binds it to opaque inputs.

`COUPLING-AUDIT.json` records the V0-C-specific identifiers and their permitted locations. The CPU tests exercise a second opaque resource/implementation, generic tie/ranking, binding mismatches, stale evidence, absent capability, plan/observation attribution, physical identity absence, and adapter full-offload/fallback rejection.

No V1-A physical output is retained in this repository yet. No synthetic CPU control is presented as physical qualification, and this directory does not claim `V1A_REUSABLE_VULKAN_PARTICIPANT_PASS`.
