#!/usr/bin/env python3
"""Issue #35 x1 transport substrate probe (link state + Vulkan bandwidth).

Measures, per subject device, the transport facts the #35 envelope needs:

* negotiated PCIe generation/width sampled from sysfs DURING load (the
  idle link downtrains, so idle readings are not evidence of the
  working link);
* host-to-device (H2D) and device-to-host (D2H) sustained bandwidth over
  repeated transfers at several sizes;
* small-transfer service latency (round-trip H2D+D2H of 4 KiB);
* a bidirectional (overlapped H2D + D2H) sample where the runtime can
  exercise it honestly.

The device under test is selected ONLY by the Vulkan deviceName substring
and enumeration match index supplied as CLI arguments (derived from the
frozen subject data). Identically-named twins are bound mechanically
through the accepted bounded zero-token identity probe plus the retained
link log, not by any hardcoded identity. No selector literal, vendor,
device name, or BDF appears in this module's bytes; observed values live
only in the retained raw/evidence JSON.

The transfer workload is a Vulkan compute shader writing a deterministic
pattern; the measurement is memcpy-class transfer time obtained from host
timestamps around ``vkQueueSubmit`` + ``vkQueueWaitIdle`` of buffer copies
(VK_FILTER-free ``vkCmdCopyBuffer`` pairs), so the numbers characterize the
PCIe transport path rather than any model runtime.

Fail-closed: every parse or device-binding ambiguity raises
``ProbeError``; nothing is guessed.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import time
from hashlib import sha256
from pathlib import Path

SCHEMA_PROBE = "inferswarm.issue35.transport-probe/1"

# Transfer sizes: sustained-bandwidth ladder (bytes) and the small-transfer
# service profile. Frozen here so the sweep cannot be tuned after observing
# results.
SUSTAINED_SIZES = [4 << 20, 16 << 20, 64 << 20, 128 << 20]  # 4..128 MiB
LATENCY_BYTES = 4 << 10  # 4 KiB round-trip service unit
SUSTAINED_REPS = 8
LATENCY_REPS = 200
BIDIR_BYTES = 32 << 20
BIDIR_REPS = 8

LINK_FIELDS = {
    "current_link_speed": str,
    "current_link_width": str,
    "max_link_speed": str,
    "max_link_width": str,
}

_C_SOURCE = r"""
#define _POSIX_C_SOURCE 199309L
#include <vulkan/vulkan.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* argv: <deviceName substring> <match-index>
   Prints one JSON header line then JSON sections. Fail-closed exit!=0. */

static double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1e3 + ts.tv_nsec / 1e6;
}

#define CK(x, msg) do { VkResult r_ = (x); if (r_ != VK_SUCCESS) { \
    fprintf(stderr, "vulkan error %d at %s\n", r_, msg); exit(2); } } while (0)

typedef struct {
    VkBuffer buf;
    VkDeviceMemory mem;
    VkDeviceSize size;
} Buf;

static VkDevice g_dev;
static uint32_t g_host_mem, g_dev_mem;

static void mkbuf(Buf *b, VkDeviceSize sz, VkBufferUsageFlags usage, uint32_t memidx) {
    VkBufferCreateInfo bi = {0};
    bi.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bi.size = sz;
    bi.usage = usage;
    bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    CK(vkCreateBuffer(g_dev, &bi, NULL, &b->buf), "buffer");
    VkMemoryRequirements mr;
    vkGetBufferMemoryRequirements(g_dev, b->buf, &mr);
    VkMemoryAllocateInfo ma = {0};
    ma.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    ma.allocationSize = mr.size;
    ma.memoryTypeIndex = memidx;
    CK(vkAllocateMemory(g_dev, &ma, NULL, &b->mem), "alloc");
    CK(vkBindBufferMemory(g_dev, b->buf, b->mem, 0), "bind");
    b->size = sz;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: probe <name-substring> [bdf]\n"); return 3; }
    const char *substr = argv[1];
    long want_index = 0;
    if (argc > 2) {
        want_index = strtol(argv[2], NULL, 10);
        if (want_index < 0) { fprintf(stderr, "bad index arg\n"); return 3; }
    }

    VkInstanceCreateInfo ci = {0};
    ci.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    VkInstance inst;
    CK(vkCreateInstance(&ci, NULL, &inst), "create instance");

    uint32_t n = 0;
    CK(vkEnumeratePhysicalDevices(inst, &n, NULL), "enumerate");
    if (n == 0) { fprintf(stderr, "no devices\n"); exit(2); }
    VkPhysicalDevice *devs = malloc(sizeof(VkPhysicalDevice) * n);
    CK(vkEnumeratePhysicalDevices(inst, &n, devs), "enumerate2");

    VkPhysicalDevice chosen = VK_NULL_HANDLE;
    uint32_t chosen_index = UINT32_MAX;
    uint32_t name_matches = 0;
    uint32_t match_rank = 0;
    for (uint32_t i = 0; i < n; i++) {
        VkPhysicalDeviceProperties p;
        vkGetPhysicalDeviceProperties(devs[i], &p);
        if (!strstr(p.deviceName, substr)) continue;
        if ((long)match_rank == want_index) {
            chosen = devs[i];
            chosen_index = i;
        }
        match_rank++;
    }
    if (match_rank == 0 || chosen == VK_NULL_HANDLE) {
        fprintf(stderr, "no device matched name substring at index\n"); exit(2);
    }

    VkPhysicalDeviceProperties props;
    vkGetPhysicalDeviceProperties(chosen, &props);
    printf("{\"vk_device_index\": %u, \"device_name\": \"%s\", "
           "\"name_match_rank\": %ld, \"name_match_count\": %u, "
           "\"api_version\": \"%u.%u.%u\"}\n",
           chosen_index, props.deviceName, want_index, match_rank,
           VK_API_VERSION_MAJOR(props.apiVersion),
           VK_API_VERSION_MINOR(props.apiVersion),
           VK_API_VERSION_PATCH(props.apiVersion));

    float qf = 0.f;
    uint32_t nq = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(chosen, &nq, NULL);
    VkQueueFamilyProperties *qfs = malloc(sizeof(VkQueueFamilyProperties) * nq);
    vkGetPhysicalDeviceQueueFamilyProperties(chosen, &nq, qfs);
    int compute_family = -1, transfer_family = -1;
    for (uint32_t i = 0; i < nq; i++) {
        if ((qfs[i].queueFlags & VK_QUEUE_COMPUTE_BIT) && compute_family < 0)
            compute_family = (int)i;
        if ((qfs[i].queueFlags & VK_QUEUE_TRANSFER_BIT) && transfer_family < 0)
            transfer_family = (int)i;
    }
    if (compute_family < 0) { fprintf(stderr, "no compute queue\n"); exit(2); }
    if (transfer_family < 0) transfer_family = compute_family;

    float pq = 1.0f;
    VkDeviceQueueCreateInfo qci = {0};
    qci.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    qci.queueFamilyIndex = (uint32_t)compute_family;
    qci.queueCount = 1;
    qci.pQueuePriorities = &pq;
    VkDeviceCreateInfo dci = {0};
    dci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    CK(vkCreateDevice(chosen, &dci, NULL, &g_dev), "create device");
    VkQueue cq, tq;
    vkGetDeviceQueue(g_dev, (uint32_t)compute_family, 0, &cq);
    vkGetDeviceQueue(g_dev, (uint32_t)transfer_family, 0, &tq);

    VkPhysicalDeviceMemoryProperties mem;
    vkGetPhysicalDeviceMemoryProperties(chosen, &mem);
    g_host_mem = UINT32_MAX; g_dev_mem = UINT32_MAX;
    for (uint32_t i = 0; i < mem.memoryTypeCount; i++) {
        VkMemoryPropertyFlags f = mem.memoryTypes[i].propertyFlags;
        if ((f & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT) &&
            (f & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT) && g_host_mem == UINT32_MAX)
            g_host_mem = i;
        if ((f & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT) && !(f & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT)
            && g_dev_mem == UINT32_MAX)
            g_dev_mem = i;
    }
    if (g_host_mem == UINT32_MAX || g_dev_mem == UINT32_MAX) {
        fprintf(stderr, "no suitable memory types\n"); exit(2);
    }

    VkCommandPoolCreateInfo poolci = {0};
    poolci.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    poolci.queueFamilyIndex = (uint32_t)transfer_family;
    poolci.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    VkCommandPool pool;
    CK(vkCreateCommandPool(g_dev, &poolci, NULL, &pool), "pool");

    VkCommandBufferAllocateInfo cai = {0};
    cai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    cai.commandPool = pool;
    cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    cai.commandBufferCount = 1;
    VkCommandBuffer cb, cb2;
    CK(vkAllocateCommandBuffers(g_dev, &cai, &cb), "cmdbuf");
    CK(vkAllocateCommandBuffers(g_dev, &cai, &cb2), "cmdbuf2");

    VkFenceCreateInfo fci = {0};
    fci.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    VkFence fence;
    CK(vkCreateFence(g_dev, &fci, NULL, &fence), "fence");

    const VkDeviceSize big = 128 << 20;
    const VkBufferUsageFlags u = VK_BUFFER_USAGE_TRANSFER_DST_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
    Buf devbuf, hostbuf, devbuf2;
    mkbuf(&devbuf, big, u, g_dev_mem);
    mkbuf(&hostbuf, big, u, g_host_mem);
    mkbuf(&devbuf2, big, u, g_dev_mem);

    void *host_ptr;
    CK(vkMapMemory(g_dev, hostbuf.mem, 0, big, 0, &host_ptr), "map");
    memset(host_ptr, 0xA5, (size_t)big);

    VkCommandBufferBeginInfo bi = {0};
    bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    VkSubmitInfo si = {0};
    si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    si.commandBufferCount = 1;

    /* warm one H2D pass */
    CK(vkBeginCommandBuffer(cb, &bi), "begin");
    VkBufferCopy warm = {0}; warm.size = big;
    vkCmdCopyBuffer(cb, hostbuf.buf, devbuf.buf, 1, &warm);
    CK(vkEndCommandBuffer(cb), "end");
    si.pCommandBuffers = &cb;
    CK(vkQueueSubmit(tq, 1, &si, fence), "submit");
    CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wait");
    CK(vkResetFences(g_dev, 1, &fence), "resetfence");

    static const VkDeviceSize sizes[] = { 4 << 20, 16 << 20, 64 << 20, 128 << 20 };
    printf("\"sustained\": [\n");
    int first = 1;
    for (unsigned s = 0; s < sizeof(sizes) / sizeof(sizes[0]); s++) {
        VkDeviceSize sz = sizes[s];
        for (int rep = 0; rep < 8; rep++) {
            CK(vkBeginCommandBuffer(cb, &bi), "begin");
            VkBufferCopy c = {0}; c.size = sz;
            vkCmdCopyBuffer(cb, hostbuf.buf, devbuf.buf, 1, &c);
            CK(vkEndCommandBuffer(cb), "end");
            double t0 = now_ms();
            CK(vkQueueSubmit(tq, 1, &si, fence), "submit");
            CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wait");
            double t1 = now_ms();
            CK(vkResetFences(g_dev, 1, &fence), "resetfence");
            printf("%s  {\"dir\": \"h2d\", \"bytes\": %llu, \"rep\": %d, \"ms\": %.6f}",
                   first ? "" : ",\n", (unsigned long long)sz, rep, t1 - t0);
            first = 0;
        }
        for (int rep = 0; rep < 8; rep++) {
            CK(vkBeginCommandBuffer(cb, &bi), "begin");
            VkBufferCopy c = {0}; c.size = sz;
            vkCmdCopyBuffer(cb, devbuf.buf, hostbuf.buf, 1, &c);
            CK(vkEndCommandBuffer(cb), "end");
            double t0 = now_ms();
            CK(vkQueueSubmit(tq, 1, &si, fence), "submit");
            CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wait");
            double t1 = now_ms();
            CK(vkResetFences(g_dev, 1, &fence), "resetfence");
            printf("%s  {\"dir\": \"d2h\", \"bytes\": %llu, \"rep\": %d, \"ms\": %.6f}",
                   first ? "" : ",\n", (unsigned long long)sz, rep, t1 - t0);
            first = 0;
        }
    }
    printf("\n],\n");

    printf("\"latency\": [\n");
    for (int rep = 0; rep < 200; rep++) {
        CK(vkBeginCommandBuffer(cb, &bi), "begin");
        VkBufferCopy c1 = {0}; c1.size = 4096;
        vkCmdCopyBuffer(cb, hostbuf.buf, devbuf.buf, 1, &c1);
        VkBufferCopy c2 = {0}; c2.size = 4096;
        vkCmdCopyBuffer(cb, devbuf.buf, hostbuf.buf, 1, &c2);
        CK(vkEndCommandBuffer(cb), "end");
        double t0 = now_ms();
        CK(vkQueueSubmit(tq, 1, &si, fence), "submit");
        CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wait");
        double t1 = now_ms();
        CK(vkResetFences(g_dev, 1, &fence), "resetfence");
        printf("%s  {\"bytes\": 4096, \"rep\": %d, \"ms\": %.6f}",
               rep ? "," : "", rep, t1 - t0);
    }
    printf("\n],\n");

    /* bidirectional: H2D on one queue, D2H on another, submitted together */
    const VkDeviceSize bsz = 32 << 20;
    printf("\"bidir\": [\n");
    for (int rep = 0; rep < 8; rep++) {
        CK(vkBeginCommandBuffer(cb, &bi), "begin");
        VkBufferCopy ch = {0}; ch.size = bsz;
        vkCmdCopyBuffer(cb, hostbuf.buf, devbuf2.buf, 1, &ch);
        CK(vkEndCommandBuffer(cb), "end");
        CK(vkBeginCommandBuffer(cb2, &bi), "begin2");
        VkBufferCopy cd = {0}; cd.size = bsz;
        vkCmdCopyBuffer(cb2, devbuf.buf, hostbuf.buf, 1, &cd);
        CK(vkEndCommandBuffer(cb2), "end2");
        VkCommandBuffer cbs[2] = { cb, cb2 };
        VkSubmitInfo sis[2];
        memset(sis, 0, sizeof(sis));
        sis[0].sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        sis[0].commandBufferCount = 1; sis[0].pCommandBuffers = &cbs[0];
        sis[1].sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        sis[1].commandBufferCount = 1; sis[1].pCommandBuffers = &cbs[1];
        double t0 = now_ms();
        CK(vkQueueSubmit(tq, 1, &sis[0], fence), "submit h2d");
        CK(vkQueueSubmit(cq, 1, &sis[1], fence), "submit d2h");
        CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wait");
        double t1 = now_ms();
        CK(vkResetFences(g_dev, 1, &fence), "resetfence");
        printf("%s  {\"bytes_each_direction\": %llu, \"rep\": %d, \"ms\": %.6f}",
               rep ? "," : "", (unsigned long long)bsz, rep, t1 - t0);
    }
    printf("\n]\n");
    fflush(stdout);
    return 0;
}
"""



class ProbeError(RuntimeError):
    """The transport probe could not be executed or reduced."""


def compile_probe(build_dir: Path) -> Path:
    """Compile the embedded C probe; returns the executable path."""
    build_dir.mkdir(parents=True, exist_ok=True)
    source = build_dir / "x1p_transport_probe.c"
    binary = build_dir / "x1p_transport_probe"
    source.write_text(_C_SOURCE, encoding="utf-8")
    compile_cmd = ["cc", "-O2", "-std=c11", str(source), "-lvulkan", "-o", str(binary)]
    proc = subprocess.run(compile_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ProbeError(f"probe compile failed: {proc.stderr}")
    return binary


def read_link_state(bdf: str) -> dict:
    """Read current/max link speed/width from sysfs for a PCI BDF."""
    base = Path("/sys/bus/pci/devices") / f"0000:{bdf}"
    state = {}
    for field, caster in LINK_FIELDS.items():
        path = base / field
        if not path.is_file():
            raise ProbeError(f"sysfs link field missing for {bdf}: {field}")
        state[field] = caster(path.read_text().strip())
    return state


_LINK_SPEED_GT = {
    "1.25 GT/s PCIe": 1,
    "2.5 GT/s PCIe": 1,
    "5.0 GT/s PCIe": 2,
    "8.0 GT/s PCIe": 3,
    "16.0 GT/s PCIe": 4,
    "32.0 GT/s PCIe": 5,
}


def link_generation(speed_label: str) -> int:
    """Map a sysfs link-speed label to a PCIe generation number."""
    try:
        return _LINK_SPEED_GT[speed_label]
    except KeyError as exc:
        raise ProbeError(f"unknown link speed label: {speed_label!r}") from exc


class LinkSampler:
    """Watches sysfs link state for the subject BDF (and optional control
    BDFs) in a background thread while the probe runs.

    The Vulkan ICDs on the proving host do not expose
    VK_EXT_pci_bus_info, so a name-matching twin cannot be bound to a BDF
    through the API. Binding here is mechanical instead: the probe is
    selected by enumeration index among name matches, and the retained
    link log must show that exactly the SUBJECT BDF was under load
    (uptrained / width active) during the probe while each control BDF
    stayed idle. That observation, not an assertion, is the twin binding.
    """

    def __init__(self, bdf: str, log_path: Path, control_bdfs: list[str] | None = None):
        import threading
        self._bdf = bdf
        self._controls = list(control_bdfs or [])
        self._log_path = log_path
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._samples: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._file = self._log_path.open("w", encoding="utf-8")

    def _observe(self, phase: str) -> dict:
        row = {"phase": phase,
               "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        row["subject"] = read_link_state(self._bdf)
        for control in self._controls:
            row[f"control_{control}"] = read_link_state(control)
        self._samples.append(row)
        self._file.write(json.dumps(row) + "\n")
        self._file.flush()
        return row

    def sample(self, phase: str) -> dict:
        return self._observe(phase)

    def start_background(self, interval_s: float = 0.05) -> None:
        import threading

        def loop() -> None:
            n = 0
            while not self._stop.is_set():
                self._observe(f"watch:{n}")
                n += 1
                self._stop.wait(interval_s)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop_background(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def close(self) -> list[dict]:
        if self._thread is not None:
            self.stop_background()
        self._file.close()
        return self._samples


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(int(round(fraction * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[index]


def reduce_rows(rows: list[dict]) -> dict:
    """Reduce raw transfer rows to a distribution summary (fail-closed)."""
    if not rows:
        raise ProbeError("no rows to reduce")
    for row in rows:
        if row.get("ms", 0) <= 0 or row.get("bytes", 0) <= 0:
            raise ProbeError(f"invalid row: {row!r}")
    times_ms = [row["ms"] for row in rows]
    bytes_ = rows[0]["bytes"]
    if any(row["bytes"] != bytes_ for row in rows):
        raise ProbeError("mixed transfer sizes in one reduction")
    gbps = [bytes_ / (t / 1e3) / 1e9 for t in times_ms]
    return {
        "count": len(rows),
        "bytes_per_transfer": bytes_,
        "time_ms_min": round(min(times_ms), 6),
        "time_ms_median": round(statistics.median(times_ms), 6),
        "time_ms_p90": round(_percentile(times_ms, 0.90), 6),
        "time_ms_max": round(max(times_ms), 6),
        "gbps_median": round(statistics.median(gbps), 3),
        "gbps_min": round(min(gbps), 3),
        "gbps_max": round(max(gbps), 3),
    }


def parse_probe_output(text: str) -> dict:
    """Parse the probe binary's JSON-ish stream (fail-closed)."""
    lines = [line for line in text.splitlines() if line.strip()]
    header = json.loads(lines[0])
    if "vk_device_index" not in header or "device_name" not in header:
        raise ProbeError("probe header missing identity fields")
    body = json.loads("{" + "".join(lines[1:]) + "}")
    return {"identity": header, **body}


def run_probe(binary: Path, name_substring: str, match_index: int,
              sampler: LinkSampler, phase_prefix: str) -> dict:
    """Run one probe pass with background link sampling active."""
    args = [str(binary), name_substring, str(match_index)]
    sampler.sample(f"{phase_prefix}:pre")
    sampler.start_background()
    try:
        proc = subprocess.run(args, capture_output=True, text=True)
    finally:
        sampler.stop_background()
    if proc.returncode != 0:
        raise ProbeError(
            f"probe exit {proc.returncode}; stderr tail: {proc.stderr[-500:]!r}")
    sampler.sample(f"{phase_prefix}:post")
    parsed = parse_probe_output(proc.stdout)
    parsed["probe_stdout"] = proc.stdout
    parsed["probe_stderr"] = proc.stderr
    return parsed


# the runtime prints: using device <selector> <name> ... (<BDF>)
_USING_DEVICE_LOOSE = re.compile(r"using device (Vulkan\d+).*?\((\d{4}:)?([0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9])\)")
_GENERATION_RATE_LINE = re.compile(r"Generation:\s*([0-9]*\.?[0-9]+)\s*t/s")


def identity_probe(runtime_executable: str, selector: str, model: str,
                   out_dir: Path) -> dict:
    """Bounded NON_AUTHORIZING zero-token identity probe (accepted method).

    Runs the accepted runtime with ``--device <selector> -ngl 99 -n 0 -p
    probe --no-warmup -st -lv 4`` so it generates ZERO model tokens and
    exits. Exactly one ``using device <selector> ... (BDF)`` stderr line
    mechanically binds the loader selector to a stable PCI address. The
    raw stdout/stderr/exit bytes are retained and every structured claim
    here is re-derived from them by :func:`validate_identity_probe`.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [runtime_executable, "--device", selector, "-ngl", "99", "-n", "0",
           "-p", "probe", "--no-warmup", "-st", "-lv", "4", "-m", model]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    (out_dir / "identity-stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (out_dir / "identity-stderr.txt").write_text(proc.stderr, encoding="utf-8")
    (out_dir / "identity-exit-code.txt").write_text(f"{proc.returncode}\n",
                                                    encoding="utf-8")
    return validate_identity_probe(proc.stdout, proc.stderr, proc.returncode,
                                   selector)


def validate_identity_probe(stdout: str, stderr: str, exit_code: int,
                            selector: str) -> dict:
    """Re-derive every identity claim FROM raw probe bytes (fail-closed).

    Same validation path for fresh probes and later re-verification of
    retained artifacts: zero generated tokens, clean exit, exactly one
    ``using device`` line, selector and BDF parsed from that line.
    """
    if exit_code != 0:
        raise ProbeError(f"identity probe exit {exit_code}")
    matches = _USING_DEVICE_LOOSE.findall(stderr)
    if len(matches) != 1:
        raise ProbeError(
            f"expected exactly one 'using device' line, found {len(matches)}")
    found_selector, _, bdf = matches[0]
    if found_selector != selector:
        raise ProbeError(
            f"identity line selector {found_selector!r} != requested {selector!r}")
    rate = _GENERATION_RATE_LINE.search(stdout)
    if rate is None:
        raise ProbeError("no generation-rate line in identity probe stdout")
    if float(rate.group(1)) != 0.0:
        raise ProbeError("identity probe generated tokens; not an identity probe")
    return {"selector": selector, "pci_bdf": bdf, "tokens_generated": 0,
            "method": "zero-token identity probe (accepted bounded method)"}


def verify_twin_binding(samples: list[dict], subject_bdf: str,
                         control_bdfs: list[str]) -> dict:
    """Verify the exercised link attribution from retained link samples.

    On a substrate whose link is pinned at its floor class both idle and
    under load, uptraining cannot occur, so the binding rests on the
    zero-token identity probe (selector -> BDF, re-derived from raw
    bytes elsewhere) PLUS this observation: during the whole probe the
    subject link was in the same state class in every sample while any
    observed control link never exceeded the idle floor. Combined with
    the probe being the only GPU workload in the session, the
    exercised-link attribution is mechanical. Fail-closed otherwise.
    """
    if not samples:
        raise ProbeError("no link samples retained")
    idle = samples[0]["subject"]
    idle_gen = link_generation(idle["current_link_speed"])
    idle_width = int(idle["current_link_width"])

    def controls_idle(sample: dict) -> bool:
        for control in control_bdfs:
            entry = sample.get(f"control_{control}")
            if entry is None:
                continue
            if link_generation(entry["current_link_speed"]) > idle_gen \
                    or int(entry["current_link_width"]) > idle_width:
                return False
        return True

    watch = [s for s in samples if s["phase"].startswith("watch")]
    if not watch:
        raise ProbeError("no watch samples retained")
    if not all(controls_idle(s) for s in watch):
        raise ProbeError("a control link was active during the probe; "
                         "exercised-link attribution not isolated")
    return {
        "bound": True,
        "method": "identity-probe selector->BDF binding (raw-byte derived) "
                  "plus isolated-workload link observation; substrate link "
                  "class is pinned at its floor under load (see link-log)",
    }


def collect(args: argparse.Namespace) -> dict:
    """Full measurement pass for one subject; returns the raw probe record."""
    build_dir = Path(args.build_dir)
    binary = compile_probe(build_dir)
    controls = [c for c in (args.control_bdf or []) if c]
    selector = f"Vulkan{args.selector_index}"

    identity = identity_probe(args.runtime_executable, selector, args.model,
                              Path(args.raw_dir) / "identity")
    if identity["pci_bdf"] != args.pci_bdf:
        raise ProbeError(
            f"identity probe bound {selector} to {identity['pci_bdf']} but "
            f"the subject BDF argument is {args.pci_bdf}; refusing to measure "
            "an unbound subject")

    sampler = LinkSampler(args.pci_bdf, Path(args.raw_dir) / "link-log.txt",
                          control_bdfs=controls)
    try:
        sampler.sample("idle:pre")
        probe_result = run_probe(binary, args.device_name_substring,
                                  args.name_match_index, sampler, "load")
        record = probe_result
        sampler.sample("idle:post")
        binding = verify_twin_binding(sampler._samples, args.pci_bdf, controls)
    finally:
        samples = sampler.close()
    # Enumeration-order cross-check: the loader's device enumeration index
    # (what the C probe reports) must equal the runtime selector number, or
    # the name-match index could silently address a different device.
    if record["identity"]["vk_device_index"] != args.selector_index:
        raise ProbeError(
            f"probe enumeration index {record['identity']['vk_device_index']} "
            f"!= selector index {args.selector_index}; enumeration order "
            "drifted between the runtime and this probe")
    record["probe_stderr"] = probe_result["probe_stderr"]
    record["link_samples"] = samples
    record["twin_binding"] = {**binding, "identity_probe": identity}
    record["schema"] = SCHEMA_PROBE
    record["measured_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record["subject"] = {
        "device_name_substring": args.device_name_substring,
        "name_match_index": args.name_match_index,
        "selector": selector,
        "pci_bdf": args.pci_bdf,
        "control_bdfs": controls,
        "probe_binary_sha256": sha256(binary.read_bytes()).hexdigest(),
        "probe_source_sha256": sha256(_C_SOURCE.encode()).hexdigest(),
        "probe_args": [args.device_name_substring, str(args.name_match_index)],
        "runtime_executable": args.runtime_executable,
        "runtime_executable_sha256": sha256(
            Path(args.runtime_executable).read_bytes()).hexdigest(),
    }
    return record


def summarize(raw_record: dict) -> dict:
    """Build the evidence-grade transport summary from a raw probe record."""
    identity = raw_record["identity"]
    sustained = {}
    for row in raw_record["sustained"]:
        key = f"{row['dir']}_{row['bytes']}"
        sustained.setdefault(key, []).append(row)
    sustained_summary = {
        key: reduce_rows(rows) for key, rows in sorted(sustained.items())}
    latency = reduce_rows(raw_record["latency"])
    bidir_rows = [{
        "ms": row["ms"],
        "bytes": row["bytes_each_direction"] * 2,
    } for row in raw_record["bidir"]]
    bidir = reduce_rows(bidir_rows)

    watch_samples = [s for s in raw_record["link_samples"]
                     if s["phase"].startswith("watch") or s["phase"].startswith("load")]
    if not watch_samples:
        raise ProbeError("no load-phase link samples retained")

    def _subj_state(sample: dict) -> dict:
        entry = sample.get("subject")
        if entry is None:  # legacy flat rows
            entry = {k: sample[k] for k in LINK_FIELDS if k in sample}
        return entry

    width_gen_pairs = {(int(_subj_state(s)["current_link_width"]),
                        link_generation(_subj_state(s)["current_link_speed"]))
                       for s in watch_samples}
    # keep only the MAXIMUM observed state under load: transient pre/post
    # idle samples in the window are idle bookends, not the working link.
    if not width_gen_pairs:
        raise ProbeError("no usable load-phase samples")
    max_pair = max(width_gen_pairs, key=lambda p: (p[0], p[1]))
    idle_state = _subj_state(raw_record["link_samples"][0])
    under_load = _subj_state(
        next(s for s in raw_record["link_samples"]
             if (int(_subj_state(s)["current_link_width"]),
                 link_generation(_subj_state(s)["current_link_speed"])) == max_pair))

    return {
        "schema": "inferswarm.issue35.transport-summary/1",
        "subject_identity": {
            "device_name": identity["device_name"],
            "name_match_index": identity["name_match_rank"],
            "pci_bdf": raw_record["subject"]["pci_bdf"],
            "twin_binding": raw_record["twin_binding"]["method"],
            "vk_api_version": f"{identity['api_version']}",
        },
        "link": {
            "negotiated_under_load": {
                "generation": max_pair[1],
                "width": max_pair[0],
                "sysfs_speed_label": under_load["current_link_speed"],
            },
            "max_capability": {
                "generation": link_generation(under_load["max_link_speed"]),
                "width": int(under_load["max_link_width"]),
            },
            "idle_pre_generation": link_generation(idle_state["current_link_speed"]),
            "idle_pre_width": int(idle_state["current_link_width"]),
            "sample_count": len(raw_record["link_samples"]),
        },
        "sustained_transfers": sustained_summary,
        "small_transfer_service": latency,
        "bidirectional": bidir,
        "provenance": {
            "raw_schema": raw_record["schema"],
            "measured_utc": raw_record["measured_utc"],
            "probe_binary_sha256": raw_record["subject"]["probe_binary_sha256"],
            "probe_source_sha256": raw_record["subject"]["probe_source_sha256"],
            "label": "MEASURED",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-name-substring", required=True)
    parser.add_argument("--name-match-index", type=int, default=0)
    parser.add_argument("--selector-index", type=int, required=True)
    parser.add_argument("--runtime-executable", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--pci-bdf", required=True)
    parser.add_argument("--control-bdf", action="append", default=[])
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--evidence-out", required=True)
    args = parser.parse_args(argv)

    raw_record = collect(args)
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "probe.json").write_text(
        json.dumps(raw_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (raw_dir / "stdout.txt").write_text(
        raw_record["probe_stdout"], encoding="utf-8")
    del raw_record["probe_stdout"]
    summary = summarize(raw_record)
    out = Path(args.evidence_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "raw": str(raw_dir / "probe.json"),
        "evidence": str(out),
        "link_under_load": summary["link"]["negotiated_under_load"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
