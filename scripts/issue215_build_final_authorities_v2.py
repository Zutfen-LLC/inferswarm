#!/usr/bin/env python3
"""Issue #215 — build the two V2-C final-check authorities (data authoring).

Every fact is copied from the fresh final-boot V2-C discovery artifacts and
the accepted V2-B predecessor identities (runtime/model/prompt/reference
reused byte-identically). No fact is invented; the v2a_authority_v3 loader
re-verifies everything at load time on the proving node. Evidence IDs live
in the additive V2-C namespace; #210 evidence is untouched.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = "vulkan-v2-c-v340l-platform-stability"
AREA = ROOT / "docs/investigations" / NS

# Inputs staged from the proving node (final boot):
#   <out>/final-canonical/discovery/DISCOVERY-{INVENTORY,BINDINGS}-R3.json
STAGE = ROOT / "docs/investigations" / NS / "final-boot-staging-v2"
REF = json.loads((ROOT / "docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-A.json").read_text())
R3F = REF["frozen"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def binding(selector: str) -> dict:
    for b in BIND["bindings"]:
        if b["selector"] == selector:
            return b
    raise SystemExit(f"selector {selector} not in bindings")


def build(die: str, selector: str, cu: str, mr: str, impl: str, bdf: str) -> dict:
    b = binding(selector)
    assert b["binding_status"] == "BOUND" and b.get("pci_bdf") == bdf, b
    inv_dev = next(d for d in INV["devices"] if d["selector"] == selector)
    frozen = {
        "canonical_execution_evidence_id": f"v2c-final-{die}-canonical-01",
        "compute_unit_id": cu,
        "correctness_policy": "v0c-byte-exact-visible-output-v2",
        "executable": R3F["executable"],
        "executable_sha256": R3F["executable_sha256"],
        "execution_contract_id": R3F["execution_contract_id"],
        "execution_unit_id": R3F["execution_unit_id"],
        "hostname": "inferswarm02",
        "implementation_id": impl,
        "logical_state_id": R3F["logical_state_id"],
        "memory_bytes": inv_dev["device_local_vram_bytes"],
        "memory_resource_id": mr,
        "model": R3F["model"],
        "model_bytes": R3F["model_bytes"],
        "model_sha256": R3F["model_sha256"],
        "node_id": "node-inferswarm02",
        "objective": "MIN_OBJECTIVE_VALUE",
        "physical_device_bdf": bdf,
        "prompt": R3F["prompt"],
        "qualification_evidence_id": f"v2c-final-{die}-qualification-01",
        "required_features": ["compute"],
        "required_headroom_bytes": R3F["required_headroom_bytes"],
        "required_integrity_status": "QUALIFIED",
        "required_memory_bytes": R3F["required_memory_bytes"],
        "required_representation": R3F["required_representation"],
        "runtime_identity": {
            "binary_sha256": R3F["executable_sha256"],
            "radv_target": "Mesa 25.0.7-2+deb13u1 (RADV VEGA10)",
            "selector": selector,
            "source_commit": R3F["runtime_source_commit"],
            "vulkan_loader": "1.4.309",
            "vulkan_loader_remeasured": INV["vulkan_loader_identity"],
        },
        "runtime_source": R3F["runtime_source"],
        "runtime_source_commit": R3F["runtime_source_commit"],
        "selector": selector,
        "v1a_sources": R3F["v1a_sources"],
    }
    pressure = {
        "node_id": "node-inferswarm02",
        "compute_unit_id": f"cu-v340l-die-{'b' if die == 'a' else 'a'}",
        "physical_device_bdf": "09:00.0" if die == "a" else "06:00.0",
        "memory_resource": {"memory_resource_id": f"mr-v340l-die-{'b' if die == 'a' else 'a'}-vram",
                            "bytes": inv_dev["device_local_vram_bytes"]},
        "capabilities": [],
    }
    return {
        "accepted_source_pins": REF["accepted_source_pins"],
        "authority_state": (
            "prospective prephysical V2-C final-check authority frozen and pushed before "
            "any V2-C final-check correctness-bearing physical output; binds selector/BDF to "
            "the FRESH final-boot V2-C reviewed discovery artifacts mechanically (loader v3 "
            "stale-inventory fail-closed contract); runtime/model/prompt/reference reused "
            "byte-identically from the accepted V2-B authority"
        ),
        "capability_completion": REF["capability_completion"],
        "correctness": REF["correctness"],
        "discovery_binding": {
            "binding_proof_sha256": b.get("binding_proof_sha256"),
            "binding_status": "BOUND",
            "bindings_path": f"docs/investigations/{NS}/final-boot-staging-v2/discovery/DISCOVERY-BINDINGS-R3.json",
            "bindings_sha256": BIND_SHA,
            "discovery_hostname": INV["hostname"],
            "discovery_runtime_executable_sha256": INV["runtime_executable_sha256"],
            "inventory_measured_utc": INV["measured_utc"],
            "inventory_path": f"docs/investigations/{NS}/final-boot-staging-v2/discovery/DISCOVERY-INVENTORY-R3.json",
            "inventory_sha256": INV_SHA,
            "pci_bdf": bdf,
            "reviewed_utc": BIND["reviewed_utc"],
            "selector": selector,
        },
        "evidence": {
            "capability_evidence_id": f"v2c-final-{die}-capability-01",
            "evidence_namespace": NS,
            "plan_evidence_id": f"v2c-final-{die}-plan-01",
        },
        "issue": "#215",
        "nonclaims": REF["nonclaims"],
        "physical_identity": {
            "compute_unit_id": cu,
            "device_local_vram_capacity_bytes": inv_dev["device_local_vram_bytes"],
            "driver_runtime_identity": f"Vulkan loader {INV['vulkan_loader_identity']} (re-measured); RADV Mesa 25.0.7-2+deb13u1",
            "gpu_name": inv_dev["device_name"],
            "gpu_pci_id": "1002:6864",
            "hostname": "inferswarm02",
            "memory_resource_bytes": inv_dev["device_local_vram_bytes"],
            "memory_resource_id": mr,
            "node_id": "node-inferswarm02",
            "ontology_pressure_resource": pressure,
            "upstream_topology": REF["physical_identity"]["upstream_topology"],
        },
        "predecessors": {
            "campaign_main_at_start": "36d0d7a7301230512dbbc2bca65388b6800dec6f",
            "v2b_authority": "docs/investigations/vulkan-v2-b-v340l/AUTHORITY-V340L-A.json",
            "v2b_merge": "f91119d05e7079c780c7b88be6138fed0920b759",
            "v2b_terminal": "V2B_V340L_DUAL_DIE_QUALIFICATION_PASS",
        },
        "repeatability_inheritance": REF["repeatability_inheritance"],
        "runtime_model_reuse": REF["runtime_model_reuse"],
        "schema": "inferswarm.v2a.campaign-authority/3",
        "source_freeze": REF["source_freeze"],
        "frozen": frozen,
    }


if __name__ == "__main__":
    INV_PATH = STAGE / "discovery/DISCOVERY-INVENTORY-R3.json"
    BIND_PATH = STAGE / "discovery/DISCOVERY-BINDINGS-R3.json"
    INV = json.loads(INV_PATH.read_text())
    BIND = json.loads(BIND_PATH.read_text())
    INV_SHA, BIND_SHA = sha(INV_PATH), sha(BIND_PATH)

    dies = {
        "a": dict(selector="Vulkan1", cu="cu-v340l-die-a", mr="mr-v340l-die-a-vram",
                  impl="impl-v2c-final-die-a", bdf="06:00.0"),
        "b": dict(selector="Vulkan2", cu="cu-v340l-die-b", mr="mr-v340l-die-b-vram",
                  impl="impl-v2c-final-die-b", bdf="09:00.0"),
    }
    for die, kw in dies.items():
        doc = build(die, **kw)
        out = AREA / f"AUTHORITY-V2C-V2-FINAL-{die.upper()}.json"
        out.write_bytes(json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
        print(out.name, "bindings bound:", kw["selector"], "->", kw["bdf"])
