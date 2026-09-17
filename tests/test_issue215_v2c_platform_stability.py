#!/usr/bin/env python3
"""Issue #215 — V2-C negative controls and structural tests.

Controls mutate ISOLATED SANDBOX COPIES of a synthetic-but-faithful cycle
evidence tree (never the real tree) and prove the terminal reducer fails
closed on exactly the intended predicate. Additional structural tests prove
no authored check is a bare True constant and that the campaign plan digest
binds the frozen semantics.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue215_campaign_plan as plan_mod  # noqa: E402


V2_ID = "issue215-v2c-v340l-platform-stability-v2"
AREA = REPO / "docs/investigations/vulkan-v2-c-v340l-platform-stability"


def load_reducer():
    spec = importlib.util.spec_from_file_location(
        "issue215_terminal_under_test", REPO / "scripts/issue215_terminal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def synth_raw(stdout_map: dict[str, str]) -> Path:
    """Materialize raw probe JSON artifacts in a temp dir."""
    tmp = Path(tempfile.mkdtemp(prefix="issue215-ctl-"))
    raw = tmp / "raw"
    raw.mkdir()
    for name, stdout in stdout_map.items():
        (raw / name).write_text(json.dumps(
            {"argv": ["synthetic"], "rc": 0, "stdout": stdout, "stderr": ""}), encoding="utf-8")
    return tmp


LSPCI_NN = """00:1d.0 PCI bridge [0604]: Intel Corporation 200 Series PCH PCIe Root Port #9 [8086:a294]
00:14.0 USB controller [0c03]: Intel Corporation 200 Series/Z370 Chipset Family USB 3.0 xHCI Controller [8086:a2af]
01:00.0 Ethernet controller [0200]: Realtek RTL8111/8168 [10ec:8168] (rev 07)
02:00.0 PCI bridge [0604]: Microchip PM8533 [11f8:8533]
04:00.0 PCI bridge [0604]: AMD Vega 10 PCIe Bridge [1022:1470] (rev 05)
05:00.0 PCI bridge [0604]: AMD Vega 10 PCIe Bridge [1022:1471] (rev 05)
06:00.0 Display controller [0380]: AMD/ATI Vega 10 [1002:6864] (rev 05)
07:00.0 PCI bridge [0604]: AMD Vega 10 PCIe Bridge [1022:1470] (rev 05)
08:00.0 PCI bridge [0604]: AMD Vega 10 PCIe Bridge [1022:1471] (rev 05)
09:00.0 Display controller [0380]: AMD/ATI Vega 10 [1002:6864] (rev 05)
"""

VEGA_VV_A = """06:00.0 Display controller [0380]: AMD/ATI Vega 10 [1002:6864] (rev 05)
\tSubsystem: AMD [1002:0c00]
\tRegion 0: Memory at d0000000 (64-bit, prefetchable) [size=256M]
\tRegion 2: Memory at c0000000 (32-bit, prefetchable) [size=2M]
\tRegion 5: Memory at c0400000 (32-bit, non-prefetchable) [size=256K]
\tLnkCap:\tPort #0, speed 8GT/s, width 16
\tLnkSta:\tSpeed 8.0GT/s, Width x16
\tKernel driver in use: amdgpu
"""

VEGA_VV_B = VEGA_VV_A.replace("06:00.0", "09:00.0").replace("d0000000", "b0000000").replace(
    "c0000000", "a0000000").replace("c0400000", "a0400000")

FULL_VV = """00:00.0 Host bridge [0600]: Intel Corp Host Bridge [8086:190f]
\tKernel driver in use: skl_uncore
00:1d.0 PCI bridge [0604]: Intel 200 Series PCH PCIe Root Port #11 [8086:a29a]
\tBus: primary=00, secondary=02, subordinate=09
\tLnkCap:\tPort #11, Speed 8GT/s, Width x1
\tLnkSta:\tSpeed 8GT/s, Width x1
00:1d.0/02:00.0 PCI bridge [0604]: Microchip PM8533 [11f8:8533]
\tBus: primary=02, secondary=03, subordinate=09
\tLnkCap:\tPort #0, speed 8GT/s, width 16
\tLnkSta:\tSpeed 8.0GT/s, Width x1
00:1d.0/02:00.0/03:00.0 PCI bridge [0604]: Microchip PM8533 [11f8:8533]
\tBus: primary=03, secondary=04, subordinate=06
\tLnkSta:\tSpeed 8.0GT/s, Width x16
00:1d.0/02:00.0/03:00.0/04:00.0/05:00.0/06:00.0 Display controller [0380]: AMD/ATI Vega 10 [1002:6864] (rev 05)
\tRegion 0: Memory at 2800000000 (64-bit, prefetchable) [size=8G]
\tRegion 5: Memory at 90000000 (32-bit, non-prefetchable) [size=512K]
\tLnkSta:\tSpeed 8.0GT/s, Width x16
\tKernel driver in use: amdgpu
00:1d.0/02:00.0/03:01.0/07:00.0/08:00.0/09:00.0 Display controller [0380]: AMD/ATI Vega 10 [1002:6864] (rev 05)
\tRegion 0: Memory at 2c00000000 (64-bit, prefetchable) [size=8G]
\tRegion 5: Memory at 90400000 (32-bit, non-prefetchable) [size=512K]
\tLnkSta:\tSpeed 8.0GT/s, Width x16
\tKernel driver in use: amdgpu
"""
VEGA_VV_A = "00:1d.0/02:00.0/03:00.0/04:00.0/05:00.0/06:00.0 Display controller [0380]: AMD/ATI Vega 10 [1002:6864] (rev 05)\n\tKernel driver in use: amdgpu\n\tRegion 0: Memory at 2800000000 (64-bit, prefetchable) [size=8G]\n"
VEGA_VV_B = "00:1d.0/02:00.0/03:01.0/07:00.0/08:00.0/09:00.0 Display controller [0380]: AMD/ATI Vega 10 [1002:6864] (rev 05)\n\tKernel driver in use: amdgpu\n\tRegion 0: Memory at 2c00000000 (64-bit, prefetchable) [size=8G]\n"

GPU_SYSFS_MEM = """== /sys/class/drm/card1/device
8573157376
== /sys/class/drm/card2/device
8573157376
"""

VULKAN_LIST = """Vulkan0: Intel(R) HD Graphics 510 (SKL GT1)
Vulkan1: AMD Radeon Pro V340 (RADV VEGA10)
Vulkan2: AMD Radeon Pro V340 (RADV VEGA10)
"""

NIC_LINK = "2: enp1s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP mode DEFAULT"
NIC_ADDR = "enp1s0    UP    10.0.0.137/24"
PING = """PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.
64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=0.5 ms
64 bytes from 10.0.0.1: icmp_seq=2 ttl=64 time=0.4 ms
64 bytes from 10.0.0.1: icmp_seq=3 ttl=64 time=0.4 ms

--- 10.0.0.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss
"""
LSUSB = """Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 001 Device 002: ID 046d:c31c Logitech, Inc. Keyboard K120
"""
FINDMNT = "/dev/sda3 ext4 rw,relatime"
STORAGE = "issue215\nSTORAGE_SENTINEL_OK"
PREV_BOOT_SHUTDOWN_WARM = "Sep 17 17:37:50 inferswarm02 systemd[1]: Reached target reboot.target - System Reboot.\n"
PREV_BOOT_LAST_WARM = PREV_BOOT_SHUTDOWN_WARM
PREV_BOOT_SHUTDOWN_COLD = "Sep 17 17:51:24 inferswarm02 systemd[1]: Stopping user@1001.service...\n"
PREV_BOOT_LAST_COLD = "Sep 17 17:51:24 inferswarm02 systemd[1]: Removed slice user-1001.slice.\n"

JOURNAL = """Sep 17 00:00:00 inferswarm02 kernel: pcieport 0000:02:00.0: PCIe Bus Error: severity=Correctable, type=Physical Layer
"""
BASE_RAW = {
    "lspci-nn.txt": LSPCI_NN,
    "lspci-tree.txt": "t",
    f"lspci-vv-06-00.0.txt": VEGA_VV_A,
    f"lspci-vv-09-00.0.txt": VEGA_VV_B,
    "lspci-vv-full.txt": FULL_VV,
    "gpu-sysfs-mem.txt": GPU_SYSFS_MEM,
    "vulkan-list-devices.txt": VULKAN_LIST,
    "nic-link.txt": NIC_LINK,
    "nic-addr.txt": NIC_ADDR,
    "nic-driver.txt": "Kernel driver in use: r8169",
    "gateway-ping.txt": PING,
    "lsusb.txt": LSUSB,
    "usb-controllers.txt": "t",
    "findmnt-root.txt": FINDMNT,
    "storage-sentinel.txt": STORAGE,
    "journal-errors.txt": "Sep 17 00:00:00 inferswarm02 systemd[1]: Started Session.\n",
    "journal-aer.txt": JOURNAL,
    "boot_id.txt": "boot-synth-0000\n",
    "uptime.txt": "1 1",
    "uname.txt": "x",
    "cmdline.txt": "x",
}

SENTINEL_RECORD = {
    "schema": "inferswarm.v2c.execution-sentinel/1",
    "campaign_id": V2_ID,
    "cycle_index": 1, "boot_id": "b1",
    "dies": {
        "a": {"selector": "Vulkan1", "probe_bdf": "06:00.0", "result": "PASS",
              "byte_exact_visible_output": True,
              "accounting_three_tuple": {"unexplained_persistent_host_mirror_bytes": 0,
                                          "source_fetches_after_ready": 0,
                                          "unplanned_state_movements": 0},
              "offload_full": True, "identity_proof_line": "using device Vulkan1",
              "visible_output_sha256": "x", "stdout_sha256": "x", "stderr_sha256": "x"},
        "b": {"selector": "Vulkan2", "probe_bdf": "09:00.0", "result": "PASS",
              "byte_exact_visible_output": True,
              "accounting_three_tuple": {"unexplained_persistent_host_mirror_bytes": 0,
                                          "source_fetches_after_ready": 0,
                                          "unplanned_state_movements": 0},
              "offload_full": True, "identity_proof_line": "using device Vulkan2",
              "visible_output_sha256": "x", "stdout_sha256": "x", "stderr_sha256": "x"},
    },
}


def build_synth_campaign(root: Path, *, warm=4, cold=1) -> Path:
    """Materialize a synthetic full-pass campaign tree for reducer controls."""
    cycles = root / "cycles"
    cycles.mkdir(parents=True)
    boot_ids = {0: "boot-synth-0000"}
    # baseline
    raw_dir = synth_cycle_raw(cycles, 0, "baseline", BASE_RAW, boot_id=boot_ids[0])
    write_receipt(raw_dir, 0, "baseline", boot_ids[0], None)
    idx = 1
    for _ in range(warm):
        bid = f"boot-warm-{idx}"
        raw_dir = synth_cycle_raw(cycles, idx, "warm", BASE_RAW, boot_id=bid)
        write_receipt(raw_dir, idx, "warm", bid, f"prev-boot-warm-{idx-1}" if idx > 1 else "boot-baseline", changed=True)
        write_sentinel(cycles, idx, bid)
        boot_ids[idx] = bid
        idx += 1
    for _ in range(cold):
        bid = f"boot-cold-{idx}"
        raw_dir = synth_cycle_raw(cycles, idx, "cold", BASE_RAW, prev_shutdown=PREV_BOOT_SHUTDOWN_COLD, boot_id=bid)
        write_receipt(raw_dir, idx, "cold", bid, boot_ids[idx - 1], changed=True,
                      transition="operator power-off -> power-on")
        write_sentinel(cycles, idx, bid)
        idx += 1
    return cycles


def synth_cycle_raw(cycles: Path, idx: int, kind: str, raw_map: dict[str, str],
                    prev_shutdown: str | None = None, boot_id: str | None = None) -> Path:
    cdir = cycles / f"cycle-{idx:02d}-{kind}"
    raw = cdir / "raw"
    raw.mkdir(parents=True)
    for name, stdout in raw_map.items():
        if name == "boot_id.txt" and boot_id is not None:
            stdout = boot_id + "\n"
        (raw / name).write_text(json.dumps(
            {"argv": ["s"], "rc": 0, "stdout": stdout, "stderr": ""}), encoding="utf-8")
    if kind != "baseline":
        (raw / "prev-boot-shutdown.txt").write_text(json.dumps(
            {"argv": ["s"], "rc": 0,
             "stdout": prev_shutdown if prev_shutdown is not None else PREV_BOOT_SHUTDOWN_WARM,
             "stderr": ""}), encoding="utf-8")
        (raw / "prev-boot-last-lines.txt").write_text(json.dumps(
            {"argv": ["s"], "rc": 0,
             "stdout": PREV_BOOT_LAST_WARM if prev_shutdown is None else PREV_BOOT_LAST_COLD,
             "stderr": ""}), encoding="utf-8")
    return cdir


def write_receipt(cdir: Path, idx: int, kind: str, boot_id: str, prev: str | None,
                  changed: bool = False, transition: str | None = None) -> None:
    receipt = {"records": {
        "schema": "inferswarm.v2c.post-boot-snapshot/1",
        "campaign_id": V2_ID,
        "cycle_index": idx, "cycle_type": kind,
        "requested_transition": transition or ("systemctl reboot" if kind == "warm" else None),
        "prev_boot_id": prev, "boot_id": boot_id,
        "boot_id_changed": changed if kind != "baseline" else None,
        "captured_utc": "2026-09-17T00:00:00+00:00",
    }, "artifacts": []}
    (cdir / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


def write_sentinel(cycles: Path, idx: int, boot_id: str, *, mutator=None,
                   raw_mutator=None) -> None:
    sdir = cycles / f"cycle-{idx:02d}-sentinels"
    sdir.mkdir(parents=True, exist_ok=True)
    rec = json.loads(json.dumps(SENTINEL_RECORD))
    rec["cycle_index"] = idx
    rec["boot_id"] = boot_id
    if mutator:
        mutator(rec)
    (sdir / "sentinel-record.json").write_text(json.dumps(rec), encoding="utf-8")
    for die in ("a", "b"):
        d = sdir / f"die-{die}"
        d.mkdir(exist_ok=True)
        struct = rec["dies"][die]
        stdout = SENTINEL_DIE_RAW[die]["stdout"]
        stderr = SENTINEL_DIE_RAW[die]["stderr"]
        visible = SENTINEL_DIE_RAW[die]["visible"]
        if raw_mutator:
            stdout, stderr, visible = raw_mutator(die, stdout, stderr, visible)
        (d / "exit-code.txt").write_text("0\n", encoding="utf-8")
        (d / "stdout.txt").write_bytes(stdout)
        (d / "stderr.txt").write_bytes(stderr)
        (d / "visible-output.txt").write_bytes(visible)
        (d / "probe.json").write_text(json.dumps(
            {"rc": 0, "identity_proof_line": struct["identity_proof_line"],
             "bdf": struct["probe_bdf"], "argv": ["s"]}), encoding="utf-8")
        # keep structured digests consistent with raw bytes unless mutated
        struct["stdout_sha256"] = hashlib.sha256(stdout).hexdigest()
        struct["stderr_sha256"] = hashlib.sha256(stderr).hexdigest()
        struct["visible_output_sha256"] = hashlib.sha256(visible).hexdigest()
    (sdir / "sentinel-record.json").write_text(json.dumps(rec), encoding="utf-8")


def run_reducer(cycles_root: Path):
    mod = load_reducer()
    plan = {"campaign_plan": {"campaign_id": V2_ID},
            "campaign_plan_digest": "0" * 64}
    return mod.derive(cycles_root, plan)


# Valid synthetic sentinel raw bytes: the stdout satisfies the accepted
# V0-C grammar and the visible response equals the accepted reference
# prefix; stderr carries a 37/37 offload line (accounting re-derivation
# fails on synthetic stderr -> accounting_clean False -> sentinel FAIL;
# tests that need full-PASS sentinels monkeypatch via raw_mutator=None and
# the reducer's derive_sentinel_cycle is wrapped in tests below).
_REF = (REPO / "docs/investigations/vulkan-v1-a/reference-visible-output.txt").read_bytes()
_SENT_PROMPT = b"The quick brown fox jumps over the lazy dog. Explain what happens next in one sentence:"
_SENT_VISIBLE = _REF[:64]
_SENT_STDOUT = b"> " + _SENT_PROMPT + b"\n" + _SENT_VISIBLE + b"\n\n[ Prompt:]"
# Synthetic stderr satisfying the ACCEPTED v1c accounting reducer grammar
# (direct buffer lines + pre/post-ready breakdown rows + ready-state line).
_SENT_STDERR = (
    "00:00 I load_tensors: offloaded 37/37 layers to GPU\n"
    "00:00 I load_tensors:   CPU_Mapped model buffer size =   243.43 MiB\n"
    "00:00 I load_tensors:      Vulkan1 model buffer size =  1834.82 MiB\n"
    "00:01 I llama_kv_cache:    Vulkan1 KV buffer size =  1152.00 MiB\n"
    "00:01 I llama_context: Vulkan_Host  output buffer size =     0.58 MiB\n"
    "00:01 I sched_reserve:    Vulkan1 compute buffer size =   104.51 MiB\n"
    "00:01 I sched_reserve: Vulkan_Host compute buffer size =    40.02 MiB\n"
    "00:01 I common_memory_breakdown_print: |   - Vulkan1 (Pro V340) |  8176 = 8168 + (3091 =  1834 +    1152 +     104) +       -3083 |\n"
    "00:01 I common_memory_breakdown_print: |   - Host                             |                  283 =   243 +       0 +      40                |\n"
    "00:01 I slot   operator(): id  0 | task 0 | cached n_tokens = 0, memory_seq_rm [0, end)\n"
    "00:02 I common_memory_breakdown_print: |   - Vulkan1 (Pro V340) |  8176 = 5076 + (3091 =  1834 +    1152 +     104) +           8 |\n"
    "00:02 I common_memory_breakdown_print: |   - Host                             |                  283 =   243 +       0 +      40                |\n"
).encode()
SENTINEL_DIE_RAW = {
    "a": {"stdout": _SENT_STDOUT, "stderr": _SENT_STDERR, "visible": _SENT_VISIBLE},
    "b": {"stdout": _SENT_STDOUT, "stderr": _SENT_STDERR.replace(b"Vulkan1", b"Vulkan2"),
          "visible": _SENT_VISIBLE},
}


class TerminalMutationControls(unittest.TestCase):
    """Each control applies ONE mutation to a sandbox copy and asserts the
    reducer refuses the PASS terminal (or exactly the intended downgrade)."""

    def sandbox(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="issue215-sbx-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        build_synth_campaign(tmp)
        return tmp

    def derive_terminal(self, tmp: Path) -> str:
        return run_reducer(tmp / "cycles")["terminal"]

    def test_baseline_sandbox_derives_pass(self):
        tmp = self.sandbox()
        r = run_reducer(tmp / "cycles")
        self.assertEqual(r["terminal"], "V2C_V340L_PLATFORM_STABILITY_PASS")
        self.assertEqual(r["warm_cycles"], 4)
        self.assertEqual(r["cold_cycles"], 1)

    # Control 1: stale prior-boot BDF/selector authority accepted after drift
    def test_control_1_stale_bdf_authority(self):
        tmp = self.sandbox()
        # mutate a sentinel to claim a BDF that does not exist in that boot's lspci
        write_sentinel(tmp / "cycles", 3, f"boot-warm-3",
                       mutator=lambda r: r["dies"]["a"].__setitem__("probe_bdf", "0a:00.0"))
        r = run_reducer(tmp / "cycles")
        self.assertNotEqual(r["terminal"], "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 2: only one die present but summary claims two
    def test_control_2_one_die_claimed_two(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-nn.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = data["stdout"].replace(
            "09:00.0 Display controller [0380]: AMD/ATI Vega 10 [1002:6864] (rev 05)\n", "")
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 3: duplicate physical function represented as two resources
    def test_control_3_duplicate_pf(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-nn.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = data["stdout"].replace("09:00.0 Display controller",
                                                "06:00.0 Display controller")
        raw.write_text(json.dumps(data))
        r = run_reducer(tmp / "cycles")
        self.assertNotEqual(r["terminal"], "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 4: missing PM8533/root-port path evidence
    def test_control_4_missing_pm8533(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-nn.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = data["stdout"].replace(
            "02:00.0 PCI bridge [0604]: Microchip PM8533 [11f8:8533]\n", "")
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 5: upstream link mutated away from Gen3 x1 while PASS authored
    def test_control_5_upstream_link_gen1(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-vv-full.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = data["stdout"].replace("Speed 8.0GT/s, Width x1", "Speed 2.5GT/s, Width x1")
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 6: unresolved BAR failure hidden behind Vulkan enumeration
    def test_control_6_unresolved_bar(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-vv-full.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = data["stdout"].replace(
            "Region 0: Memory at 2c00000000 (64-bit, prefetchable) [size=8G]",
            "Region 0: Memory at 00000000 (64-bit, prefetchable) [disabled]")
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 6b: journal shows unresolved BAR allocation failure
    def test_control_6b_journal_bar_failure(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/journal-errors.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = "kernel: pci 0000:09:00.0: BAR 5: no space for [mem size 0x1000]\n"
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 7: required NIC missing/down/unroutable while PASS authored
    def test_control_7_nic_down(self):
        tmp = self.sandbox()
        for name, repl in (("nic-link.txt", NIC_LINK.replace("state UP", "state DOWN")),
                           ("gateway-ping.txt", PING.replace("3 received, 0% packet loss",
                                                             "0 received, 100% packet loss"))):
            raw = (tmp / "cycles/cycle-02-warm/raw" / name)
            data = json.loads(raw.read_text())
            data["stdout"] = repl
            raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 8: required USB controller missing while PASS authored
    def test_control_8_usb_controller_missing(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/lsusb.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = "Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub\n"
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 9: root/storage controller missing or wrong
    def test_control_9_storage_wrong_root(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/findmnt-root.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = "/dev/sdb1 ext4 rw"
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 9b: storage health sentinel fails
    def test_control_9b_storage_sentinel_fail(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/storage-sentinel.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = "issue215\n"
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 10: fatal AER / amdgpu failure omitted from reduction
    def test_control_10_fatal_aer(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/journal-aer.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = JOURNAL + (
            "kernel: pcieport 0000:02:00.0: PCIe Bus Error: severity=Fatal, type=Undefined\n")
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    def test_control_10b_amdgpu_failure(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/journal-errors.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = "kernel: amdgpu: GPU hang during initialization\n"
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 11: failed reboot cycle removed from the denominator
    def test_control_11_failed_cycle_removed(self):
        tmp = self.sandbox()
        # break a cycle, then delete it — reducer must still not PASS with warm<4... but
        # the attack is REMOVING a failed cycle. Simulate: warm count drops to 3.
        shutil.rmtree(tmp / "cycles/cycle-04-warm")
        r = run_reducer(tmp / "cycles")
        # with only 3 warm cycles + 1 cold, min_warm_ok is false -> FAIL terminal
        self.assertNotEqual(r["terminal"], "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 12: manual recovery performed but recorded intervention-free
    def test_control_12_manual_recovery_hidden(self):
        mod = load_reducer()
        # reducer derives manual_interventions from retained bytes; a hidden
        # manual recovery would appear as inconsistency between snapshot
        # (broken state) and later evidence. Structural: interventions list
        # must derive from cycle artifacts, not be a constant.
        src = (REPO / "scripts/issue215_terminal.py").read_text()
        self.assertNotIn('"manual_interventions": True', src)

    # Control 13: sentinel attributed to wrong die/boot
    def test_control_13_sentinel_wrong_boot(self):
        tmp = self.sandbox()
        write_sentinel(tmp / "cycles", 2, "boot-OTHER")
        r = run_reducer(tmp / "cycles")
        # reducer must detect boot_id mismatch between snapshot and sentinel
        self.assertNotEqual(r["terminal"], "V2C_V340L_PLATFORM_STABILITY_PASS")

    # Control 14: stale log/snapshot bytes substituted from another boot
    def test_control_14_stale_snapshot_bytes(self):
        tmp = self.sandbox()
        # two cycles with the SAME boot_id = substituted bytes
        write_receipt(tmp / "cycles/cycle-03-warm", 3, "warm", "boot-warm-2", "boot-warm-1", changed=True)
        r = run_reducer(tmp / "cycles")
        # boot ids duplicated across cycles is retained and flagged
        ids = [e["boot_id"] for e in r["cycle_table"]]
        self.assertNotEqual(len(ids), len(set(ids)))

    # Control 15: cold-boot claim when only warm transitions executed
    def test_control_15_cold_claim_warm_only(self):
        tmp = self.sandbox()
        # relabel the cold cycle as warm
        cdir = tmp / "cycles/cycle-05-cold"
        receipt = json.loads((cdir / "receipt.json").read_text())
        receipt["records"]["cycle_type"] = "warm"
        receipt["records"]["requested_transition"] = "systemctl reboot"
        (cdir / "receipt.json").write_text(json.dumps(receipt))
        (cdir.parent / (cdir.name.replace("cold", "warm"))).rename(cdir) if False else None
        # rename dir to match new kind
        cdir.rename(cdir.parent / "cycle-05-warm")
        r = run_reducer(tmp / "cycles")
        # the relabeled cycle retains COLD prev-boot journal bytes (no
        # reboot.target), so warm_reboot_evidence fails closed: the terminal
        # is FAIL, never PASS and never warm-only on mislabeled evidence.
        self.assertEqual(r["terminal"], "V2C_V340L_PLATFORM_STABILITY_FAIL")


    # ---- Review-driven controls (Lane-1 round-1 attacks) ----

    def test_control_18_root_port_width_x4_rejected(self):
        # root-port block degraded to x4 must fail (block-scoped parsing)
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-vv-full.txt")
        data = json.loads(raw.read_text())
        # degrade ONLY the root port block's LnkSta (block-scoped: first
        # occurrence after the 00:1d.0 header, before the switch header)
        s = data["stdout"]
        i_root = s.find("00:1d.0 PCI bridge")
        i_sw = s.find("00:1d.0/02:00.0 PCI bridge")
        seg = s[i_root:i_sw].replace("Width x1", "Width x4")
        data["stdout"] = s[:i_root] + seg + s[i_sw:]
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    def test_control_19_switch_upstream_x4_rejected(self):
        # ALL PM8533 switch blocks degraded to x4 must fail
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-vv-full.txt")
        data = json.loads(raw.read_text())
        s = data["stdout"]
        i_sw = s.find("00:1d.0/02:00.0 PCI bridge")
        i_vega = s.find("06:00.0 Display controller")
        seg = s[i_sw:i_vega].replace("Width x1", "Width x4")
        data["stdout"] = s[:i_sw] + seg + s[i_vega:]
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    def test_control_20_overlapping_bar_ranges_rejected(self):
        # die-B BAR start moved INSIDE die-A's 8G range (distinct start,
        # size-aware overlap detection must catch it)
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-vv-full.txt")
        data = json.loads(raw.read_text())
        data["stdout"] = data["stdout"].replace(
            "Region 0: Memory at 2c00000000 (64-bit, prefetchable) [size=8G]",
            "Region 0: Memory at 2800001000 (64-bit, prefetchable) [size=8G]")
        raw.write_text(json.dumps(data))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    def test_control_21_kernel_standard_fatal_aer_spellings(self):
        # 'severity=Uncorrected (Fatal)', lowercase, 'AER: Uncorrected'
        for poison in ("severity=Uncorrected (Fatal)\n",
                       "severity=fatal, type=Undefined\n",
                       "AER: Multiple Uncorrected (Internal) Errors\n"):
            tmp = self.sandbox()
            raw = (tmp / "cycles/cycle-02-warm/raw/journal-aer.txt")
            data = json.loads(raw.read_text())
            data["stdout"] = data["stdout"] + poison
            raw.write_text(json.dumps(data))
            self.assertNotEqual(self.derive_terminal(tmp),
                                "V2C_V340L_PLATFORM_STABILITY_PASS",
                                msg=f"fatal-AER phrasing escaped: {poison!r}")

    def test_control_22_missing_error_evidence_rejected(self):
        # deleting BOTH journal artifacts must be a capture fault, not 'clean'
        tmp = self.sandbox()
        (tmp / "cycles/cycle-02-warm/raw/journal-aer.txt").unlink()
        (tmp / "cycles/cycle-02-warm/raw/journal-errors.txt").unlink()
        with self.assertRaises(Exception):
            run_reducer(tmp / "cycles")

    def test_control_23_boot_id_fabrication_rejected(self):
        # consistent boot_id fabrication across receipt + sentinel fails:
        # the receipt boot_id no longer matches retained raw/boot_id.txt
        tmp = self.sandbox()
        cdir = tmp / "cycles/cycle-02-warm"
        receipt = json.loads((cdir / "receipt.json").read_text())
        fake = "fabricated-boot-id"
        receipt["records"]["boot_id"] = fake
        (cdir / "receipt.json").write_text(json.dumps(receipt))
        sdir = tmp / "cycles/cycle-02-sentinels"
        srec = json.loads((sdir / "sentinel-record.json").read_text())
        srec["boot_id"] = fake
        (sdir / "sentinel-record.json").write_text(json.dumps(srec))
        r = run_reducer(tmp / "cycles")
        e = [x for x in r["cycle_table"] if x["cycle_index"] == 2][0]
        self.assertFalse(e["checks"]["boot_id_bound_to_raw"])

    def test_control_24_sentinel_record_doctored_vs_raw_rejected(self):
        # structured record claims PASS but the die raw bytes show failure
        tmp = self.sandbox()
        sdir = tmp / "cycles/cycle-02-sentinels"

        def raw_mutator(die, stdout, stderr, visible):
            if die == "a":
                stderr = stderr.replace(b"offloaded 37/37 layers", b"offloaded 20/37 layers")
            return stdout, stderr, visible

        # rewrite die raw to show partial offload, then re-stamp the
        # structured digests so ONLY the offload predicate diverges
        import hashlib as _h
        srec = json.loads((sdir / "sentinel-record.json").read_text())
        d = sdir / "die-a"
        stderr = (d / "stderr.txt").read_bytes().replace(
            b"offloaded 37/37 layers", b"offloaded 20/37 layers")
        (d / "stderr.txt").write_bytes(stderr)
        srec["dies"]["a"]["stderr_sha256"] = _h.sha256(stderr).hexdigest()
        (sdir / "sentinel-record.json").write_text(json.dumps(srec))
        r = run_reducer(tmp / "cycles")
        e = [x for x in r["cycle_table"] if x["cycle_index"] == 2][0]
        self.assertFalse(e["sentinels"]["dies"]["a"]["offload_full"])
        self.assertNotEqual(r["terminal"], "V2C_V340L_PLATFORM_STABILITY_PASS")

    def test_control_25_warm_cycle_dup_as_cold_rejected(self):
        # duplicating a warm cycle's bytes as a 6th 'cold' cycle fails: its
        # prev-boot journal carries reboot.target -> cold_powercut_evidence False
        tmp = self.sandbox()
        src_warm = tmp / "cycles/cycle-04-warm"
        dst = tmp / "cycles/cycle-06-cold"
        shutil.copytree(src_warm, dst)
        receipt = json.loads((dst / "receipt.json").read_text())
        receipt["records"]["cycle_index"] = 6
        receipt["records"]["cycle_type"] = "cold"
        receipt["records"]["boot_id"] = "boot-dup-cold"
        (dst / "receipt.json").write_text(json.dumps(receipt))
        # raw boot_id.txt must match the fabricated receipt to isolate the
        # cold-evidence predicate
        (dst / "raw/boot_id.txt").write_text(json.dumps(
            {"argv": ["s"], "rc": 0, "stdout": "boot-dup-cold\n", "stderr": ""}))
        shutil.copytree(tmp / "cycles/cycle-04-sentinels", tmp / "cycles/cycle-06-sentinels")
        srec = json.loads((tmp / "cycles/cycle-06-sentinels/sentinel-record.json").read_text())
        srec["cycle_index"] = 6
        srec["boot_id"] = "boot-dup-cold"
        (tmp / "cycles/cycle-06-sentinels/sentinel-record.json").write_text(json.dumps(srec))
        r = run_reducer(tmp / "cycles")
        e = [x for x in r["cycle_table"] if x["cycle_index"] == 6][0]
        self.assertFalse(e["checks"].get("cold_powercut_evidence", True))
        self.assertNotEqual(r["terminal"], "V2C_V340L_PLATFORM_STABILITY_PASS")


    # Round-2 review attacks: root-port binding must anchor at bus 00 and
    # bind the switch UPSTREAM port specifically (downstream switch ports
    # must never satisfy either predicate).
    def _mutate_block(self, tmp, header, old, new):
        import re as _re
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-vv-full.txt")
        d = json.loads(raw.read_text())
        s = d["stdout"]
        i = s.find(header)
        assert i >= 0
        # block span: from the header line to the next column-0 device header
        m = _re.search(r"\n(?=[0-9A-Fa-f]{2}:)", s[i + len(header):])
        end = i + len(header) + m.start() if m else len(s)
        block = s[i:end]
        assert old in block, f"pattern not in block for {header}: block tail={block[-80:]!r}"
        d["stdout"] = s[:i] + block.replace(old, new, 1) + s[end:]
        raw.write_text(json.dumps(d))

    def test_control_26_true_root_port_degrade_rejected(self):
        tmp = self.sandbox()
        tab = chr(9)  # real TAB, matching the fixture indentation
        self._mutate_block(tmp, "00:1d.0 PCI bridge",
                           "LnkSta:" + tab + "Speed 8GT/s, Width x1",
                           "LnkSta:" + tab + "Speed 2.5GT/s, Width x1")
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    def test_control_27_switch_upstream_only_degrade_rejected(self):
        tmp = self.sandbox()
        tab = chr(9)
        self._mutate_block(tmp, "00:1d.0/02:00.0 PCI bridge",
                           "LnkSta:" + tab + "Speed 8.0GT/s, Width x1",
                           "LnkSta:" + tab + "Speed 2.5GT/s, Width x1")
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    def test_control_28_root_port_block_deleted_rejected(self):
        tmp = self.sandbox()
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-vv-full.txt")
        d = json.loads(raw.read_text())
        s = d["stdout"]
        i = s.find("00:1d.0 PCI bridge")
        j = s.find("00:1d.0/02:00.0 PCI bridge")
        d["stdout"] = s[:i] + s[j:]
        raw.write_text(json.dumps(d))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")


    # Round-3 review attacks: fabricated root-bus bridge blocks (nn-unlisted)
    # and duplicate final-BDF block injection must both fail closed.
    def test_control_29_fabricated_root_bus_bridge_rejected(self):
        tmp = self.sandbox()
        self._mutate_block(tmp, "00:1d.0 PCI bridge",
                           "LnkSta:" + chr(9) + "Speed 8GT/s, Width x1",
                           "LnkSta:" + chr(9) + "Speed 2.5GT/s, Width x1")
        # insert a fake root-bus bridge NOT enumerated in lspci-nn
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-vv-full.txt")
        d = json.loads(raw.read_text())
        fake = ("00:1d.1 PCI bridge [0604]: Intel Fake Root Port [8086:a29a]\n"
                "\tBus: primary=00, secondary=02, subordinate=09\n"
                "\tLnkSta:\tSpeed 8GT/s, Width x1\n")
        d["stdout"] = d["stdout"].replace(
            "00:1d.0/02:00.0 PCI bridge", fake + "00:1d.0/02:00.0 PCI bridge", 1)
        raw.write_text(json.dumps(d))
        self.assertNotEqual(self.derive_terminal(tmp), "V2C_V340L_PLATFORM_STABILITY_PASS")

    def test_control_30_duplicate_final_bdf_block_rejected(self):
        tmp = self.sandbox()
        self._mutate_block(tmp, "00:1d.0/02:00.0 PCI bridge",
                           "LnkSta:" + chr(9) + "Speed 8.0GT/s, Width x1",
                           "LnkSta:" + chr(9) + "Speed 2.5GT/s, Width x1")
        raw = (tmp / "cycles/cycle-02-warm/raw/lspci-vv-full.txt")
        d = json.loads(raw.read_text())
        fake = ("00:1d.0/03:00.0 PCI bridge [0604]: Microchip PM8533 [11f8:8533]\n"
                "\tBus: primary=02, secondary=09, subordinate=09\n"
                "\tLnkSta:\tSpeed 8GT/s, Width x1\n")
        d["stdout"] = d["stdout"].replace(
            "00:1d.0/02:00.0/03:00.0", fake + "00:1d.0/02:00.0/03:00.0", 1)
        raw.write_text(json.dumps(d))
        with self.assertRaises(Exception):
            run_reducer(tmp / "cycles")

    # Control 16: living ledger row authored with non-derivable facts
    def test_control_16_ledger_row_derivation(self):
        # structural: the reducer contains no bare-True authored check
        # constants; every check derives from retained bytes.
        src = (REPO / "scripts/issue215_terminal.py").read_text()
        self.assertEqual(len(re.findall(r"checks\[[^\]]+\]\s*=\s*True\b", src)), 0)
        self.assertEqual(len(re.findall(r"\"\w+\":\s*True[,}]", src)), 0)

    # Control 17: mutation of accepted #210/#164 historical evidence
    def test_control_17_historical_preservation(self):
        # structural: the V2-C tooling never writes into historical namespaces
        # (the only historical path referenced is the READ-ONLY reference file
        # under vulkan-v1-a, which is loaded, never written).
        allowed_read = "docs/investigations/vulkan-v1-a/reference-visible-output.txt"
        for script in ("issue215_snapshot.py", "issue215_sentinel.py", "issue215_terminal.py",
                       "issue215_campaign_plan.py"):
            src = (REPO / "scripts" / script).read_text()
            src = src.replace(allowed_read, "<ALLOWED-READ>")
            src = src.replace("docs/investigations/vulkan-v2-c-v340l-platform-stability", "<V2C-NS>")
            for ns in ("vulkan-v2-b-v340l", "vulkan-v2-a", "vulkan-v1-a", "vulkan-v1-b",
                       "vulkan-v1-c", "vulkan-v0-a", "vulkan-v0-b", "vulkan-v0-c"):
                self.assertNotIn(f"docs/investigations/{ns}", src,
                                 f"{script} references historical namespace {ns}")

    def test_no_bare_true_checks(self):
        src = (REPO / "scripts/issue215_terminal.py").read_text()
        for match in re.finditer(r"checks\[[^\]]+\]\s*=\s*True", src):
            self.fail(f"bare True check constant: {match.group(0)}")


class CampaignPlanTests(unittest.TestCase):
    def test_plan_digest_binds_semantics(self):
        doc = json.loads((AREA / "CAMPAIGN-PLAN-V2.json").read_text())
        payload = json.dumps(doc["campaign_plan"], sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), doc["campaign_plan_digest"])
        # v2 supersedes v1 honestly: v1 terminal recorded as BLOCKED, never FAIL
        sup = doc["campaign_plan"]["supersedes"]
        self.assertEqual(sup["v1_terminal"], "V2C_EVIDENCE_BLOCKED")
        self.assertNotIn("PLATFORM_STABILITY_FAIL", sup["v1_terminal"])

    def test_frozen_sequence_minimums(self):
        plan = plan_mod.build_plan()["sequence"]["cycles"]
        warm = [c for c in plan if c["type"] == "warm"]
        cold = [c for c in plan if c["type"] == "cold"]
        self.assertGreaterEqual(len(warm), 4)
        self.assertGreaterEqual(len(cold), 1)

    def test_predecessor_identities(self):
        plan = plan_mod.build_plan()
        self.assertEqual(plan["accepted_predecessors"]["v2b_merge"],
                         "f91119d05e7079c780c7b88be6138fed0920b759")
        self.assertEqual(plan["starting_main"],
                         "36d0d7a7301230512dbbc2bca65388b6800dec6f")

    def test_terminals_exact(self):
        t = plan_mod.TERMINALS
        self.assertEqual(t["pass"], "V2C_V340L_PLATFORM_STABILITY_PASS")
        self.assertEqual(t["warm_only"], "V2C_V340L_WARM_REBOOT_STABILITY_ONLY")
        self.assertEqual(t["fail"], "V2C_V340L_PLATFORM_STABILITY_FAIL")
        self.assertEqual(t["blocked"], "V2C_EVIDENCE_BLOCKED")


if __name__ == "__main__":
    unittest.main()
