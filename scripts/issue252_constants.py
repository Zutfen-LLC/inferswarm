"""Frozen authority constants for Issue #252 Phase  0 reconciliation."""
from __future__ import annotations

ISSUE = 252
PARENT_ISSUE = 188
PREDECESSOR_ISSUE = 250
ACCEPTED_PR = 251
CAMPAIGN_PR = 253  # this campaign's PR: the ONLY PR conversation accepting dispatch comments
KIND = "R8-I3C"
EXPECTED_BASE_HEAD = "850429973a2061ff82dc46dc06481ad13ebd24d9"
ACCEPTED_MERGE_HEAD = EXPECTED_BASE_HEAD
ACCEPTED_TERMINALIZATION_HEAD = "3e4e8790ed0225741642fecd7dc5ff707cd9b050"
ACCEPTED_EXECUTION_HEAD = "5d015b5bc437bb82d5e966d0da8b90ff44b079a1"
PREDECESSOR_TERMINAL = "R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED"
ACCEPTED_TERMINAL = "R8I3C_VULKAN_MECHANISM_LOCALIZED_FIX_VALIDATED"
NOT_VALIDATED_TERMINAL = "R8I3C_VULKAN_MECHANISM_LOCALIZED_FIX_NOT_VALIDATED"
UNRESOLVED_TERMINAL = "R8I3C_VULKAN_MECHANISM_UNRESOLVED"
DISPATCH_PHRASE_FORMAT = "R8I3C PHYSICAL DISPATCH #252"
LOCALIZED_FACTOR = "zero↔nonzero Vulkan participation"
COMPARATOR_SHA256 = "6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad"
MODEL = "Qwen3.8-Flash-Next-UD-IQ1_S"
MODEL_MEMBERS = {
    "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf": "88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf": "3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf": "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a",
}
ACCEPTED_248_MANIFEST_SELF_DIGEST = "af9dfd0f08e9d3c4cbeb8fe164f781bc64b488ad4aba23954f5893ac980ab3bc"
LLAMA_PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
LLAMA_PIN_TREE = "950999fe62b7fe55f44ab5b7394e3c8542f37f12"
HOST_FACTS = {
    "host": "inferswarm01",
    "reference_arm": "B",
    "gpu": "NVIDIA GeForce RTX 3060",
    "bdf": "00000000:03:00.0",
    "gpu_uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
    "driver": "610.57.04",
    "icd": "nvidia",
    "vulkan": "1.4.341",
}
TERMINALIZATION_REL = "docs/research/r8i3b-reference-runtime-boundary-localized-250-terminalization"
REFERENCE_PATHS = (
    "docs/research/r8i3b-reference-runtime-boundary-localized-250-terminalization/README.md",
    "docs/research/r8i3b-reference-runtime-boundary-localized-250-terminalization/TERMINAL.json",
    "docs/research/r8i3b-reference-runtime-boundary-localized-250-terminalization/accepted-original/preflight-complete.json",
    "docs/research/r8i3b-reference-runtime-boundary-localized-250-terminalization/reviewed-rederivation.json",
)
