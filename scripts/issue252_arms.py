"""Phase-0 hypotheses and frozen, prospective one-factor Vulkan arms (#252)."""
from __future__ import annotations

import json
from pathlib import Path

import issue252_constants as C

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism/evidence/phase0"
VULKAN_PATH = AREA / "vulkan-path.json"
MATRIX_PATH = AREA / "hypothesis-matrix.json"
TERMINAL_VOCABULARY = [C.ACCEPTED_TERMINAL, C.NOT_VALIDATED_TERMINAL, C.UNRESOLVED_TERMINAL]
REPEAT_LAW = {"deterministic_requires": 5, "screening_stability": 3, "first_mismatch": "arm_variable_stop", "selection": "never_select_favorable_repeats"}


def _load_path():
    return json.loads(VULKAN_PATH.read_text(encoding="utf-8"))


def _ref(entry, index=0):
    return f'{entry["path"]}:{entry["lines"][index]}'


def _candidate_rows():
    return sorted(_load_path()["nondeterminism_candidates"], key=lambda row: row["rank"])

# Each item deliberately preserves uncertainty from the source analysis. Candidate
# 1 has no direct single-factor control: toggles cannot prove initialization.
HYPOTHESES = [
    {"id": "H1", "mechanism": "GPU input/scratch content or padding read before initialization (unproven)", "source_basis": ["ggml/src/ggml-vulkan/ggml-vulkan.cpp:16735", "ggml/src/ggml-vulkan/ggml-vulkan.cpp:9665"], "affects_output_layer_gemm": True, "rank": 1, "info_value": "high", "cost": "high", "discriminator_arm": None, "note": "No proven single-factor control establishes or forces initialization; source only shows conditional uninitialized-allocation exposure."},
    {"id": "H2", "mechanism": "Cross-queue synchronization or buffer-aliasing gap (unproven)", "source_basis": ["ggml/src/ggml-vulkan/ggml-vulkan.cpp:16042", "ggml/src/ggml-vulkan/ggml-vulkan.cpp:8572"], "affects_output_layer_gemm": True, "rank": 2, "info_value": "high", "cost": "low", "discriminator_arm": "A1", "note": "Submission serialization is one isolated control; it can screen submission-order sensitivity but does not independently repair/prove alias tracking."},
    {"id": "H3", "mechanism": "Driver-reported memory type/capability or allocation fallback varies (unproven)", "source_basis": ["ggml/src/ggml-vulkan/ggml-vulkan.cpp:3747", "ggml/src/ggml-vulkan/ggml-vulkan.cpp:6760"], "affects_output_layer_gemm": True, "rank": 3, "info_value": "medium", "cost": "medium", "discriminator_arm": "A4", "note": "Host-visible preference changes only the memory-type preference; it is a prospective allocation-path discriminator, not a forced fallback."},
    {"id": "H4", "mechanism": "Driver shader compilation or implicit driver shader cache (unproven numerical effect)", "source_basis": ["ggml/src/ggml-vulkan/ggml-vulkan.cpp:3260", "ggml/src/ggml-vulkan/ggml-vulkan.cpp:3080"], "affects_output_layer_gemm": True, "rank": 4, "info_value": "low", "cost": "high", "discriminator_arm": None, "note": "No backend cache-control switch exists; VK_NULL_HANDLE excludes application cache, not driver-internal behavior."},
    {"id": "H5", "mechanism": "Shape-sensitive reduction, MMVQ, cooperative matrix and split-K path selection", "source_basis": ["ggml/src/ggml-vulkan/ggml-vulkan.cpp:9052", "ggml/src/ggml-vulkan/ggml-vulkan.cpp:9839", "ggml/src/ggml-vulkan/vulkan-shaders/mul_mat_vec_base.glsl:97"], "affects_output_layer_gemm": True, "rank": 5, "info_value": "high", "cost": "low", "discriminator_arm": "A2", "note": "Disabling only coopmat capability is a narrow shader-family/reduction-path screen; it does not jointly toggle MMVQ or split-K."},
    {"id": "H6", "mechanism": "ASLR/pointer-keyed reuse and submission timeline values (unproven indirect effect)", "source_basis": ["ggml/src/ggml-vulkan/ggml-vulkan.cpp:9664", "ggml/src/ggml-vulkan/ggml-vulkan.cpp:8572"], "affects_output_layer_gemm": False, "rank": 6, "info_value": "low", "cost": "high", "discriminator_arm": None, "note": "No control directly fixes pointer-keyed reuse or makes pointer values arithmetic inputs; serialization is assigned to H2, not double-counted here."},
]

_GEOMETRY = {"ngl": 1, "case": "case-3072", "fresh_process_per_unit": True, "request_contract": "byte-exact accepted #241/#250"}
_CONTRAST = "accepted #248/#250 retained populations read-only"
ARMS = {
    "A1": {"namespace": "d252-arm-serialize", "one_factor": "Enable GGML_VK_SERIALIZE_SUBMISSIONS to fence/serialize compute submissions", "control": {"name": "GGML_VK_SERIALIZE_SUBMISSIONS", "kind": "env", "provenance": "ggml/src/ggml-vulkan/ggml-vulkan.cpp:7435"}, "geometry": dict(_GEOMETRY), "units": {"variable_stop": 5, "min": 2}, "contrast": _CONTRAST},
    "A2": {"namespace": "d252-arm-no-coopmat", "one_factor": "Enable GGML_VK_DISABLE_COOPMAT to disable KHR cooperative-matrix feature detection", "control": {"name": "GGML_VK_DISABLE_COOPMAT", "kind": "env", "provenance": "ggml/src/ggml-vulkan/ggml-vulkan.cpp:6600"}, "geometry": dict(_GEOMETRY), "units": {"variable_stop": 5, "min": 2}, "contrast": _CONTRAST},
    "A3": {"namespace": "d252-arm-no-async", "one_factor": "Enable GGML_VK_DISABLE_ASYNC to disable backend asynchronous interface support", "control": {"name": "GGML_VK_DISABLE_ASYNC", "kind": "env", "provenance": "ggml/src/ggml-vulkan/ggml-vulkan.cpp:6724"}, "geometry": dict(_GEOMETRY), "units": {"variable_stop": 5, "min": 2}, "contrast": _CONTRAST},
    "A4": {"namespace": "d252-arm-host-memory", "one_factor": "Enable GGML_VK_PREFER_HOST_MEMORY to prefer coherent host-visible allocation", "control": {"name": "GGML_VK_PREFER_HOST_MEMORY", "kind": "env", "provenance": "ggml/src/ggml-vulkan/ggml-vulkan.cpp:6553"}, "geometry": dict(_GEOMETRY), "units": {"variable_stop": 5, "min": 2}, "contrast": _CONTRAST},
    "A5": {"namespace": "d252-arm-device-local", "one_factor": "Enable GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM to prefer device-local-only allocation", "control": {"name": "GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM", "kind": "env", "provenance": "ggml/src/ggml-vulkan/ggml-vulkan.cpp:6556"}, "geometry": dict(_GEOMETRY), "units": {"variable_stop": 5, "min": 2}, "contrast": _CONTRAST},
}


def _control_provenance(path_data, control):
    return {f'{proof["path"]}:{line}' for item in path_data["controls"] if item.get("name") == control for proof in item.get("proven", []) for line in proof["lines"]}


def validate_arms(arms=None):
    arms = ARMS if arms is None else arms
    problems = []
    try:
        path_data = _load_path()
    except (OSError, ValueError, KeyError) as exc:
        return [f"cannot load vulkan-path.json: {exc}"]
    seen = set()
    for arm_id, arm in arms.items():
        prefix = f"{arm_id}: "
        control = arm.get("control", {})
        name, provenance = control.get("name"), control.get("provenance")
        if not provenance:
            problems.append(prefix + "missing control provenance")
        if not name or not any(row["name"] == name for row in path_data.get("controls", [])):
            problems.append(prefix + "control name absent from vulkan-path.json controls")
        if provenance and provenance not in _control_provenance(path_data, name):
            problems.append(prefix + "control provenance absent from vulkan-path.json")
        namespace = arm.get("namespace")
        if not namespace:
            problems.append(prefix + "missing namespace")
        elif namespace in seen:
            problems.append(prefix + "duplicate namespace")
        seen.add(namespace)
        if not arm.get("one_factor", "").strip():
            problems.append(prefix + "empty one_factor")
        units = arm.get("units", {})
        if units.get("variable_stop") != REPEAT_LAW["deterministic_requires"] or units.get("min") not in (2, REPEAT_LAW["screening_stability"]):
            problems.append(prefix + "unit counts violate REPEAT_LAW")
    return problems


def matrix_document():
    return {"schema": "inferswarm.issue252.hypothesis-matrix.phase0/1", "authority": "repository-only; zero physical authority", "repeat_law": REPEAT_LAW, "terminal_vocabulary": TERMINAL_VOCABULARY, "hypotheses": HYPOTHESES, "arms": ARMS}


def matrix_bytes():
    return (json.dumps(matrix_document(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main():
    problems = validate_arms()
    if problems:
        raise SystemExit("invalid arms: " + "; ".join(problems))
    MATRIX_PATH.write_bytes(matrix_bytes())


if __name__ == "__main__":
    main()
