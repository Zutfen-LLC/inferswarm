#!/usr/bin/env python3
"""Issue #210 — build the two prospective V2-B campaign authorities.

Pure data authoring: every fact is copied from the fresh reviewed
discovery artifacts and the accepted V2-A predecessor identities
(runtime/model/prompt/reference reused byte-identically). No fact is
invented here; the v2a_authority_v3 loader re-verifies everything at
load time on the proving node.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = "vulkan-v2-b-v340l"
AREA = ROOT / "docs/investigations" / NS
INV_SHA = hashlib.sha256((AREA / "DISCOVERY-INVENTORY-R3.json").read_bytes()).hexdigest()
BIND_SHA = hashlib.sha256((AREA / "DISCOVERY-BINDINGS-R3.json").read_bytes()).hexdigest()
INV = json.loads((AREA / "DISCOVERY-INVENTORY-R3.json").read_text())
BIND = json.loads((AREA / "DISCOVERY-BINDINGS-R3.json").read_text())
REF = json.loads((ROOT / "docs/investigations/vulkan-v2-a/AUTHORITY-AMD-A-R3.json").read_text())
R3F = REF["frozen"]

MEASURED = INV["measured_utc"]
REVIEWED = BIND["reviewed_utc"]

def binding(selector: str) -> dict:
    for b in BIND["bindings"]:
        if b["selector"] == selector:
            return b
    raise SystemExit(f"selector {selector} not in bindings")

def build(die: str, selector: str, cu: str, mr: str, impl: str, bdf: str,
          plan_id: str, qual_id: str, canon_id: str, cap_id: str) -> dict:
    b = binding(selector)
    assert b["binding_status"] == "BOUND" and b["pci_bdf"] == bdf, b
    inv_dev = next(d for d in INV["devices"] if d["selector"] == selector)
    frozen = {
        "canonical_execution_evidence_id": canon_id,
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
        "qualification_evidence_id": qual_id,
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
    return {
        "accepted_source_pins": REF["accepted_source_pins"],
        "authority_state": (
            "prospective prephysical V2-B authority frozen and pushed before any V2-B "
            "correctness-bearing physical output; binds the selector/BDF pair to the "
            "FRESH V2-B reviewed discovery artifacts mechanically (loader v3 "
            "stale-inventory fail-closed contract); runtime/model/prompt/reference "
            "reused byte-identically from the accepted V2-A R3 authority"),
        "capability_completion": {
            "integrity_status": "QUALIFIED",
            "representations": [R3F["required_representation"]],
            "required_features": ["compute"],
        },
        "correctness": dict(REF["correctness"]),
        "discovery_binding": {
            "binding_proof_sha256": b["binding_proof_sha256"],
            "binding_status": "BOUND",
            "bindings_path": f"docs/investigations/{NS}/DISCOVERY-BINDINGS-R3.json",
            "bindings_sha256": BIND_SHA,
            "discovery_hostname": INV["hostname"],
            "discovery_runtime_executable_sha256": INV["runtime_executable_sha256"],
            "inventory_measured_utc": MEASURED,
            "inventory_path": f"docs/investigations/{NS}/DISCOVERY-INVENTORY-R3.json",
            "inventory_sha256": INV_SHA,
            "pci_bdf": bdf,
            "reviewed_utc": REVIEWED,
            "selector": selector,
        },
        "evidence": {
            "capability_evidence_id": cap_id,
            "evidence_namespace": NS,
            "plan_evidence_id": plan_id,
        },
        "frozen": frozen,
        "issue": "#210",
        "nonclaims": list(REF["nonclaims"]) + [
            "no concurrent dual-die execution, throughput scaling, or shared-x1 contention claim",
            "no SR-IOV VF, ROCm/HIP, or mixed-vendor claim",
            "no Qwen3.8/DeepSeek V4.1 model qualification",
        ],
        "physical_identity": {
            "compute_unit_id": cu,
            "device_local_vram_capacity_bytes": inv_dev["device_local_vram_bytes"],
            "driver_runtime_identity": (
                "Vulkan loader 1.4.309 (re-measured); RADV Mesa 25.0.7-2+deb13u1; "
                f"{selector} selector re-measured via llama-cli --list-devices; BDF {bdf} "
                "re-measured via lspci and the runtime's own selected-device line "
                "(identity probe, zero generated tokens); upstream root-port 00:1d.0 "
                "negotiated 8.0 GT/s x1 (Gen3 x1) proven in the Phase-1 freeze"),
            "gpu_name": ("AMD Radeon Pro V340 (RADV VEGA10) — one of two identically-named "
                         "Vega 10 dies on the V340L board; the name-join ambiguity is recorded "
                         "inventory fact, and the selector-to-BDF binding is verified "
                         "mechanically by the runtime's own selected-device execution line"),
            "gpu_pci_id": "1002:6864",
            "hostname": "inferswarm02",
            "memory_resource_bytes": inv_dev["device_local_vram_bytes"],
            "memory_resource_id": mr,
            "node_id": "node-inferswarm02",
            "upstream_topology": {
                "gpu_to_switch_link": "PCIe Gen3 x16 (LnkSta 8.0 GT/s x16 at the endpoint)",
                "pm8533_switch": "Microchip PM8533 (11f8:8533) fanout switch",
                "root_port": "0000:00:1d.0 Intel 200-series PCH Root Port #9",
                "root_port_negotiated": "PCIe Gen3 x1 (8.0 GT/s, width 1)",
            },
        },
        "predecessors": {
            "v2a_merge": "e38ebe91a0604fb666397ddae675248e9f819f60",
            "v2a_terminal": "V2A_REUSABLE_DEVICE_QUALIFICATION_HARNESS_PASS",
            "v2a_amd_r3_authority": "docs/investigations/vulkan-v2-a/AUTHORITY-AMD-A-R3.json",
            "campaign_main_at_start": "267b983de1249cad9c516e5c5c3cf86ed4a5a252",
        },
        "repeatability_inheritance": dict(REF["repeatability_inheritance"]),
        "runtime_model_reuse": {
            "basis": "exact reuse of the accepted V2-A R3 runtime/model/prompt/configuration",
            "drift_check": ("executable sha256, model sha256/bytes, llama.cpp source commit, "
                            "Vulkan loader identity re-measured on this host at freeze; the "
                            "previous AMD-A subject (RX 580 pair) was physically replaced by "
                            "the V340L, so the selector/BDF/driver facts are FRESH V2-B "
                            "measurements, not inherited"),
        },
        "schema": "inferswarm.v2a.campaign-authority/3",
        "source_freeze": {
            "campaign_branch": "issue-210-v2b-v340l",
            "discovery_head": "c26746c719e4f60fc6c5f85482e40483de5aa9ec",
            "harness_sources_reused_unchanged": True,
        },
    }

def pressure(die: str, cu: str, mr: str, bdf: str, ev: str) -> dict:
    """The other V340L die as a static pressure resource in the snapshot.

    Mirrors the accepted V2-A pattern (authority data only; the planner
    sees a second, contract-mismatched CU and must still select the
    campaign's own subject). Integrity/identity facts are the fresh
    V2-B discovery facts for the sibling die.
    """
    return {
        "capabilities": [{
            "bound_compute_unit_id": cu,
            "bound_execution_unit_id": R3F["execution_unit_id"],
            "bound_memory_resource_id": mr,
            "bound_node_id": "node-inferswarm02",
            "economics": {"objective_value": 1.0},
            "evidence_fresh": True,
            "evidence_id": ev,
            "execution_contract_id": "contract-native-opaque-v1",
            "implementation_id": f"impl-static-{die}",
            "integrity_status": "QUALIFIED",
            "physical_device_bdf": bdf,
            "qualification_digest": f"static-{die}-not-eligible-contract-mismatch",
            "qualification_evidence_id": ev,
            "representations": [R3F["required_representation"]],
            "required_features": ["compute"],
            "runtime_identity": {"binary_sha256": f"static-{die}"},
        }],
        "compute_unit_id": cu,
        "memory_resource": {
            "bytes": None,  # filled by the caller from fresh discovery facts
            "memory_resource_id": mr,
        },
        "node_id": "node-inferswarm02",
        "physical_device_bdf": bdf,
    }

DIE_A = build("A", "Vulkan1", "cu-v340l-die-a", "mr-v340l-die-a-vram",
              "impl-portable-v340l-die-a", "06:00.0",
              "v2b-v340l-a-plan-01", "v2b-v340l-a-qualification-01",
              "v2b-v340l-a-canonical-01", "v2b-v340l-a-capability-01")
DIE_B = build("B", "Vulkan2", "cu-v340l-die-b", "mr-v340l-die-b-vram",
              "impl-portable-v340l-die-b", "09:00.0",
              "v2b-v340l-b-plan-01", "v2b-v340l-b-qualification-01",
              "v2b-v340l-b-canonical-01", "v2b-v340l-b-capability-01")

# Each die's authority carries its sibling as the static pressure resource.
DIE_A["physical_identity"]["ontology_pressure_resource"] = pressure(
    "v340l-die-b", "cu-v340l-die-b", "mr-v340l-die-b-vram", "09:00.0",
    "v2b-static-die-b-pressure-01")
DIE_B["physical_identity"]["ontology_pressure_resource"] = pressure(
    "v340l-die-a", "cu-v340l-die-a", "mr-v340l-die-a-vram", "06:00.0",
    "v2b-static-die-a-pressure-01")
# pressure memory bytes: fresh discovery fact for the sibling die
INV_BY_BDF = {d.get("candidate_bdfs") and b or d.get("pci_bdf"): d
              for d in INV["devices"] for b in (d.get("candidate_bdfs") or [d.get("pci_bdf")])}
for doc, sib_bdf in ((DIE_A, "09:00.0"), (DIE_B, "06:00.0")):
    doc["physical_identity"]["ontology_pressure_resource"]["memory_resource"]["bytes"] = \
        next(d["device_local_vram_bytes"] for d in INV["devices"]
             if sib_bdf in (d.get("candidate_bdfs") or [d.get("pci_bdf")]))


for name, doc in (("AUTHORITY-V340L-A.json", DIE_A), ("AUTHORITY-V340L-B.json", DIE_B)):
    out = AREA / name
    out.write_bytes(json.dumps(doc, indent=2, sort_keys=True).encode() + b"\n")
    print(name, hashlib.sha256(out.read_bytes()).hexdigest())
