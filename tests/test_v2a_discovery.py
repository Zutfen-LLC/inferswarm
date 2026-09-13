"""Issue #163 CPU-only contract tests for V2-A subject discovery.

Device names in fixtures are synthetic loader/runtime data, not subject
identifiers of any accepted campaign.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v2a_discovery as discovery  # noqa: E402

# Fixtures mirror the runtime/loader/lspci printed grammars observed on
# the proving node, with synthetic opaque values.
LISTING = """\
Available devices:
  Vulkan4: Synthetic Alpha GPU (8019 MiB, 7160 MiB free)
  Vulkan9: Synthetic Beta GPU (8438 MiB, 8122 MiB free)
"""

LISTING_REVERSED = """\
Available devices:
  Vulkan9: Synthetic Beta GPU (8438 MiB, 8122 MiB free)
  Vulkan4: Synthetic Alpha GPU (8019 MiB, 7160 MiB free)
"""

LOADER = """\
==========
VULKANINFO
==========

Vulkan Instance Version: 1.4.309

Devices:
========
GPU0:
\tapiVersion         = 1.4.305
\tvendorID           = 0x9999
\tdeviceID           = 0x0001
\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
\tdeviceName         = Synthetic Alpha GPU
\tdriverName         = synthetic-alpha-driver
VkPhysicalDevicePCIBusInfoPropertiesEXT:
----------------------------------------
\tpciDomain   = 0
\tpciBus      = 10
\tpciDevice   = 0
\tpciFunction = 0

GPU1:
\tapiVersion         = 1.4.305
\tvendorID           = 0x9999
\tdeviceID           = 0x0002
\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
\tdeviceName         = Synthetic Beta GPU
\tdriverName         = synthetic-beta-driver
VkPhysicalDevicePCIBusInfoPropertiesEXT:
----------------------------------------
\tpciDomain   = 0
\tpciBus      = 31
\tpciDevice   = 0
\tpciFunction = 0
"""

LSPCI = """\
0a:00.0 VGA compatible controller: Synthetic Alpha [9999:0001]
1f:00.0 VGA compatible controller: Synthetic Beta [9999:0002]
"""


def build(listing=LISTING, loader=LOADER, lspci=LSPCI, hostname="node-d", strict=True):
    return discovery.build_inventory(
        runtime_executable="llama-cli", listing_probe=listing, loader_probe=loader,
        lspci_text=lspci, hostname=hostname, strict=strict)


class BindingTests(unittest.TestCase):
    def test_selectors_bind_to_stable_bdfs(self):
        inventory = build()
        by_selector = {d["selector"]: d for d in inventory["devices"]}
        self.assertEqual(by_selector["Vulkan4"]["pci_bdf"], "0a:00.0")
        self.assertEqual(by_selector["Vulkan9"]["pci_bdf"], "1f:00.0")

    def test_reordered_selectors_do_not_change_physical_binding(self):
        forward = {d["selector"]: d["pci_bdf"] for d in build()["devices"]}
        reversed_inventory = {d["selector"]: d["pci_bdf"]
                              for d in build(listing=LISTING_REVERSED)["devices"]}
        self.assertEqual(forward, reversed_inventory)

    def test_wrong_selector_bdf_pairing_fails_closed(self):
        # The name join mechanically pairs each selector with its loader
        # device; swapping names in the loader breaks resolution.
        tampered_loader = LOADER.replace("Synthetic Alpha GPU", "Synthetic Gamma GPU")
        with self.assertRaises(discovery.DiscoveryError):
            build(loader=tampered_loader)

    def test_stale_lspci_inventory_fails_closed(self):
        with self.assertRaises(discovery.DiscoveryError):
            build(lspci="07:00.0 VGA compatible controller: stale [1234:5678]\n")

    def test_duplicate_selector_fails_closed(self):
        duplicated = LISTING + "  Vulkan4: Synthetic Alpha GPU (8019 MiB, 7160 MiB free)\n"
        with self.assertRaises(discovery.DiscoveryError):
            build(listing=duplicated)

    def test_missing_bdf_in_loader_fails_closed(self):
        no_pci = LOADER.split("VkPhysicalDevicePCIBusInfoPropertiesEXT")[0]
        with self.assertRaises(discovery.DiscoveryError):
            build(loader=no_pci)

    def test_ambiguous_duplicate_device_names_fail_closed(self):
        # Two identical physical loader devices: exact-name join is
        # ambiguous; the first match must NOT be silently used.
        loader_dup = LOADER + """\
GPU2:
\tvendorID           = 0x9999
\tdeviceID           = 0x0001
\tdeviceName         = Synthetic Alpha GPU
\tdriverName         = synthetic-alpha-driver
VkPhysicalDevicePCIBusInfoPropertiesEXT:
----------------------------------------
\tpciDomain   = 0
\tpciBus      = 5
\tpciDevice   = 0
\tpciFunction = 0
"""
        recorded = build(loader=loader_dup, strict=False)
        alpha = [d for d in recorded["devices"] if d["selector"] == "Vulkan4"][0]
        self.assertEqual(alpha["binding_status"], "AMBIGUOUS")
        self.assertEqual(alpha["candidate_bdfs"], ["05:00.0", "0a:00.0"])
        with self.assertRaises(discovery.DiscoveryError):
            build(loader=loader_dup)

    def test_no_device_rows_fails_closed(self):
        with self.assertRaises(discovery.DiscoveryError):
            build(listing="Available devices:\n")

    def test_non_pci_software_devices_are_not_bound(self):
        loader_with_llvmpipe = LOADER + """\
GPU9:
\tapiVersion         = 1.4.305
\tvendorID           = 0x10005
\tdeviceID           = 0x0000
\tdeviceName         = software rasterizer (CPU)
\tdriverName         = software
"""
        listing_with_sw = LISTING + "  Vulkan12: software rasterizer CPU (8192 MiB, 8192 MiB free)\n"
        # A runtime selector whose device has no PCI identity has no
        # stable physical binding: recorded UNRESOLVED in the inventory,
        # and strict binding fails closed rather than bind null.
        recorded = build(loader=loader_with_llvmpipe, listing=listing_with_sw, strict=False)
        by_selector = {d["selector"]: d for d in recorded["devices"]}
        self.assertEqual(by_selector["Vulkan12"]["binding_status"], "UNRESOLVED")
        self.assertIsNone(by_selector["Vulkan12"]["pci_bdf"])
        with self.assertRaises(discovery.DiscoveryError):
            build(loader=loader_with_llvmpipe, listing=listing_with_sw)


class InventoryContractTests(unittest.TestCase):
    def test_inventory_is_explicitly_non_authorizing(self):
        inventory = build()
        self.assertEqual(inventory["authorization"], "NON_AUTHORIZING")
        self.assertIn("no selection", inventory["nonclaims"][0])
        self.assertTrue(all(d["descriptive_only"] for d in inventory["devices"]))

    def test_retained_facts_per_device(self):
        inventory = build()
        for device in inventory["devices"]:
            for key in ("selector", "device_name", "device_local_vram_bytes",
                        "device_local_vram_free_bytes", "pci_bdf", "lspci_line",
                        "vendor_device_ids", "loader_driver_name"):
                self.assertIn(key, device)
        self.assertEqual(inventory["vulkan_loader_identity"], "1.4.309")


if __name__ == "__main__":
    unittest.main()
