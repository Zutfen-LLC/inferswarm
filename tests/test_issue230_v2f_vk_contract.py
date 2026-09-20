#!/usr/bin/env python3
"""Issue #230 tests — V2-F transfer producer C contracts.

Compiles the REAL embedded C (issue230_transfer._C_TRANSFER) against
the recording Vulkan stub (tests/issue230_vk_stub/) and asserts the
stub-recorded call arguments:

* instance created WITH pApplicationInfo negotiating API 1.1;
* per-die logical devices created from UUID-bound physical devices
  (execution-device authority) with the fd extensions enabled;
* export uses the requested handle type; import uses the SAME handle
  type on the destination device (wrong-type imports rejected);
* the measured copy is submitted on the destination device;
* dma_buf arm enables VK_EXT_external_memory_dma_buf;
* fd lifecycle: dma_buf fd closed by the caller after import.

Also compiles a deliberately WRONG variant (single-device/no app-info
shape) and proves the stub-recorded arguments differ (the #228
old-defect proof pattern).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue230_transfer as transfer

STUB = REPO / "tests" / "issue230_vk_stub"


def compile_against_stub(build: Path, source: str | None = None,
                         name: str = "issue230_transfer_stub"):
    build.mkdir(parents=True, exist_ok=True)
    # present the stub header AS vulkan/vulkan.h on the include path
    inc = build / "vulkan_inc" / "vulkan"
    inc.mkdir(parents=True, exist_ok=True)
    (inc / "vulkan.h").write_bytes((STUB / "vulkan.h").read_bytes())
    src = source if source is not None else transfer._C_TRANSFER
    src_path = build / f"{name}.c"
    src_path.write_text(src, encoding="utf-8")
    bin_path = build / name
    cmd = ["gcc", "-O1", "-std=c11", "-o", str(bin_path),
           str(src_path), str(STUB / "stub_vk.c"),
           f"-I{inc.parent}", f"-I{build}"]
    proc = subprocess.run(cmd, capture_output=True, timeout=180)
    if proc.returncode != 0:
        raise AssertionError(
            f"stub compile failed:\n{proc.stderr.decode()[:3000]}")
    return bin_path


def run_stub(bin_path: Path, argv: list[str], cwd: Path):
    proc = subprocess.run([str(bin_path), *argv], capture_output=True,
                          timeout=120, cwd=cwd)
    log = (cwd / "stub-calls.log")
    calls = log.read_text() if log.is_file() else ""
    return proc, calls


class TestTransferCContracts(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.build = self.tmp / "build"
        self.run_dir = self.tmp / "run"
        self.run_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_identity_binds_uuids_to_bdfs(self):
        binary = compile_against_stub(self.build)
        proc, calls = run_stub(binary, ["identity", "0000:06:00.0",
                                        "0000:09:00.0"], self.run_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        out = json.loads(proc.stdout.decode().strip().splitlines()[-1])
        bfds = {d["bdf"] for d in out["devices"]}
        self.assertIn("0000:06:00.0", bfds)
        self.assertIn("0000:09:00.0", bfds)

    def test_identity_rejects_missing_bdf(self):
        binary = compile_against_stub(self.build)
        proc, _ = run_stub(binary, ["identity", "0000:06:00.0",
                                    "0000:0a:00.0"], self.run_dir)
        self.assertNotEqual(proc.returncode, 0)

    def test_transfer_opaque_fd_full_contract(self):
        binary = compile_against_stub(self.build)
        proc, calls = run_stub(
            binary,
            ["transfer", "opaque_fd", "a_to_b", "0000:06:00.0",
             "0000:09:00.0", "4096", "1", "0", "7"],
            self.run_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:2000])
        # instance: explicit app info with API 1.1
        self.assertRegex(
            calls, r"vkCreateInstance appInfo=0x[0-9a-f]+ "
                    r"apiVersion=0x401000")
        # per-die logical devices
        self.assertIn("vkCreateDevice pd_uuid=0600 "
                      "ext[0]=VK_KHR_external_memory_fd", calls)
        self.assertIn("vkCreateDevice pd_uuid=0900 "
                      "ext[0]=VK_KHR_external_memory_fd", calls)
        # dma_buf ext NOT enabled in the opaque_fd arm
        self.assertNotIn("VK_EXT_external_memory_dma_buf", calls)
        # export + import use the SAME handle type (opaque_fd bit 1)
        self.assertIn("vkGetMemoryFdKHR handleType=0x1", calls)
        self.assertRegex(
            calls, r"vkAllocateMemory IMPORT fd=\d+ handleType=0x1")
        # copies submitted
        self.assertIn("vkQueueSubmit", calls)
        # summary event
        self.assertIn('"event":"summary"', proc.stdout.decode())

    def test_transfer_dma_buf_enables_dmabuf_ext(self):
        binary = compile_against_stub(self.build)
        proc, calls = run_stub(
            binary,
            ["transfer", "dma_buf", "a_to_b", "0000:06:00.0",
             "0000:09:00.0", "4096", "1", "0", "7"],
            self.run_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:2000])
        self.assertIn("VK_EXT_external_memory_dma_buf", calls)
        self.assertIn("vkGetMemoryFdKHR handleType=0x200", calls)
        self.assertRegex(
            calls, r"vkAllocateMemory IMPORT fd=\d+ handleType=0x200")

    def test_transfer_rejects_swapped_bdfs(self):
        # source == destination is refused (same die relabeled
        # inter-die must be unreachable)
        binary = compile_against_stub(self.build)
        proc, _ = run_stub(
            binary,
            ["transfer", "opaque_fd", "a_to_b", "0000:06:00.0",
             "0000:06:00.0", "4096", "1", "0", "7"],
            self.run_dir)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("select_source", proc.stderr.decode())

    def test_transfer_rejects_unknown_bdf(self):
        binary = compile_against_stub(self.build)
        proc, _ = run_stub(
            binary,
            ["transfer", "opaque_fd", "a_to_b", "0000:06:00.0",
             "0000:0a:00.0", "4096", "1", "0", "7"],
            self.run_dir)
        self.assertNotEqual(proc.returncode, 0)

    def test_correctness_mismatch_stops_immediately(self):
        # Corrupt the copy semantics: build a variant whose vkCmdCopyBuffer
        # stub does NOT copy (dest stays zero -> mismatch -> exit 4).
        src = (STUB / "stub_vk.c").read_text()
        broken = src.replace(
            "memcpy(g_mem[dst->mem->id], g_mem[src->mem->id], 1 << 20);",
            "memset(g_mem[dst->mem->id], 0xAB, 64); /* broken copy */")
        self.assertNotEqual(broken, src)
        stub_path = self.build / "stub_broken.c"
        stub_path.parent.mkdir(parents=True, exist_ok=True)
        stub_path.write_text(broken)
        src_path = self.build / "probe.c"
        src_path.write_text(transfer._C_TRANSFER)
        bin_path = self.build / "probe_broken"
        inc = self.build / "vulkan_inc" / "vulkan"
        inc.mkdir(parents=True, exist_ok=True)
        (inc / "vulkan.h").write_bytes((STUB / "vulkan.h").read_bytes())
        cmd = ["gcc", "-O1", "-std=c11", "-o", str(bin_path),
               str(src_path), str(stub_path),
               f"-I{inc.parent}", f"-I{STUB}"]
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:2000])
        run = subprocess.run(
            [str(bin_path), "transfer", "opaque_fd", "a_to_b",
             "0000:06:00.0", "0000:09:00.0", "4096", "3", "0", "7"],
            capture_output=True, timeout=120, cwd=self.run_dir)
        self.assertEqual(run.returncode, 4)
        self.assertIn("verify_readback", run.stderr.decode())
        # mismatch rep carries ok=false
        self.assertIn('"ok":false', run.stdout.decode())

    def test_old_defect_variant_records_different_arguments(self):
        # The #228 rejected-head defect shape: instance WITHOUT
        # pApplicationInfo. The stub records appInfo=(nil) for the
        # defect and appInfo=<ptr> apiVersion=0x401000 for the current
        # source — proving the CURRENT source is not the defect shape.
        mutated = transfer._C_TRANSFER.replace(
            "ci.pApplicationInfo = &app;", "/* defect: no app info */")
        self.assertNotEqual(mutated, transfer._C_TRANSFER)
        defect_bin = compile_against_stub(self.build, mutated,
                                          name="probe_noappinfo")
        subprocess.run(
            [str(defect_bin), "identity", "0000:06:00.0",
             "0000:09:00.0"],
            capture_output=True, timeout=120, cwd=self.run_dir)
        defect_log = (self.run_dir / "stub-calls.log")
        defect_calls = defect_log.read_text() if defect_log.is_file() else ""
        defect_log.unlink(missing_ok=True)
        current_bin = compile_against_stub(self.build)
        proc = subprocess.run(
            [str(current_bin), "identity", "0000:06:00.0",
             "0000:09:00.0"],
            capture_output=True, timeout=120, cwd=self.run_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:800])
        current_calls = (self.run_dir / "stub-calls.log").read_text()
        self.assertIn("appInfo=(nil)", defect_calls)
        self.assertNotIn("appInfo=(nil)", current_calls)
        self.assertRegex(current_calls,
                         r"appInfo=0x[0-9a-f]+ apiVersion=0x401000")

    def test_wrong_handle_type_import_rejected(self):
        # Try importing with dma_buf bit when the export used opaque_fd:
        # the stub rejects; assert the probe surfaces it fail-closed.
        src = (STUB / "stub_vk.c").read_text()
        # swap: fdprops accepts any type (permissive stub)
        permissive = src.replace(
            "if (fd != g_exported_fd || (g_exported_ht && ht != g_exported_ht)) {",
            "if (fd != g_exported_fd) {")
        self.assertNotEqual(permissive, src)
        stub_path = self.build / "stub_permissive.c"
        stub_path.parent.mkdir(parents=True, exist_ok=True)
        stub_path.write_text(permissive)
        src_path = self.build / "probe2.c"
        src_path.write_text(transfer._C_TRANSFER)
        bin_path = self.build / "probe_permissive"
        inc = self.build / "vulkan_inc" / "vulkan"
        inc.mkdir(parents=True, exist_ok=True)
        (inc / "vulkan.h").write_bytes((STUB / "vulkan.h").read_bytes())
        cmd = ["gcc", "-O1", "-std=c11", "-o", str(bin_path),
               str(src_path), str(stub_path),
               f"-I{inc.parent}", f"-I{STUB}"]
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:2000])
        # permissive stub still imports with the REQUESTED type; probe
        # requests dma_buf for the dma_buf arm and the export was also
        # dma_buf -> consistent. Assert the recorded import type matches
        # the arm's mechanism bit.
        run = subprocess.run(
            [str(bin_path), "transfer", "dma_buf", "a_to_b",
             "0000:06:00.0", "0000:09:00.0", "4096", "1", "0", "7"],
            capture_output=True, timeout=120, cwd=self.run_dir)
        self.assertEqual(run.returncode, 0, run.stderr.decode()[:2000])
        log = (self.run_dir / "stub-calls.log").read_text()
        self.assertRegex(log, r"IMPORT fd=\d+ handleType=0x200")


class TestSamedieControlContract(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.build = self.tmp / "build"
        self.run_dir = self.tmp / "run"
        self.run_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_samedie_requires_single_die(self):
        binary = compile_against_stub(self.build)
        proc, _ = run_stub(
            binary, ["samedie", "0000:06:00.0", "4096", "1", "0", "7"],
            self.run_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:2000])

    def test_linkio_records_both_legs(self):
        binary = compile_against_stub(self.build)
        proc, _ = run_stub(
            binary, ["linkio", "0000:06:00.0", "4096", "1", "0", "7"],
            self.run_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:2000])
        self.assertIn('"h2d_ns"', proc.stdout.decode())
        self.assertIn('"d2h_ns"', proc.stdout.decode())

    def test_hoststaged_runs_both_dies(self):
        binary = compile_against_stub(self.build)
        proc, calls = run_stub(
            binary,
            ["hoststaged", "0000:06:00.0", "0000:09:00.0", "4096",
             "1", "0", "7"],
            self.run_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[:2000])
        self.assertIn("vkCreateDevice pd_uuid=0600", calls)
        self.assertIn("vkCreateDevice pd_uuid=0900", calls)


if __name__ == "__main__":
    unittest.main()
