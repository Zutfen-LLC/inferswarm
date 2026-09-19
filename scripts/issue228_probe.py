#!/usr/bin/env python3
"""Issue #228 — V2-E device-group peer-transfer probe (embedded C).

The selected peer mechanism: a single ``VkDevice`` created over BOTH
Vega physical devices (VkDeviceGroupDeviceCreateInfo), buffers allocated
in DEVICE_LOCAL memory via vkAllocateMemory with per-device memory
indices, and peer copies executed as vkCmdCopyBuffer recorded on the
DESTINATION device's transfer queue. This is the Vulkan-spec
peer-memory path (VK_KHR_device_group / core 1.1): peer-memory features
from vkGetDeviceGroupPeerMemoryFeatures govern exactly this copy.

Safety design (V2-D inheritance, prospectively frozen BEFORE physical
output):
  * the mechanism is NOT the #216 faulting seam: one bounded
    device-group copy at a time, synchronously fenced, at sizes 5 orders
    of magnitude below the #35 faulting transport's sustained host
    traffic class, no concurrent x1 host-transport probing, no soak;
  * deterministic payloads verified AFTER timing (readback excluded
    from the timed window);
  * every failure exits nonzero with a machine-parsable reason.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import issue228_host as host

SCHEMA = "inferswarm.v2e.peer-probe/1"

# ---------------------------------------------------------------------------
# Capability census probe (no transfers; no memory allocations).
# ---------------------------------------------------------------------------

_C_CAPABILITY = r"""
#define _POSIX_C_SOURCE 199309L
#include <vulkan/vulkan.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int esc(const char *s, char *out, size_t n) {
    size_t o = 0;
    for (const char *p = s; *p && o + 6 < n; p++) {
        if (*p == '"' || *p == '\\') { out[o++] = '\\'; out[o++] = *p; }
        else if ((unsigned char)*p < 0x20) { o += snprintf(out+o, 7, "\\u%04x", *p); }
        else out[o++] = *p;
    }
    out[o] = 0;
    return (int)o;
}

#define CK(x, msg) do { VkResult r_ = (x); if (r_ != VK_SUCCESS) { \
    fprintf(stderr, "vulkan error %d at %s\n", r_, msg); exit(2); } } while (0)

int capability_main(void);
static int ext_matrix_main(void);

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "ext-matrix") == 0)
        return ext_matrix_main();
    return capability_main();
}

/* capability_main: group enumeration + peer-memory features */
int capability_main(void) {
    VkInstanceCreateInfo ci = {0};
    ci.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    VkInstance inst;
    CK(vkCreateInstance(&ci, NULL, &inst), "create instance");

    uint32_t gc = 0;
    CK(vkEnumeratePhysicalDeviceGroups(inst, &gc, NULL), "enum groups");
    if (gc == 0) { fprintf(stderr, "no device groups\n"); return 2; }
    VkPhysicalDeviceGroupProperties *groups =
        calloc(gc, sizeof(VkPhysicalDeviceGroupProperties));
    for (uint32_t i = 0; i < gc; i++)
        groups[i].sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GROUP_PROPERTIES;
    CK(vkEnumeratePhysicalDeviceGroups(inst, &gc, groups), "enum groups 2");

    printf("{\"schema\": \"inferswarm.v2e.capability/1\", \"group_count\": %u, "
           "\"groups\": [", gc);
    int chosen = -1;
    for (uint32_t g = 0; g < gc; g++) {
        VkPhysicalDevice *devs = groups[g].physicalDevices;
        uint32_t nd = groups[g].physicalDeviceCount;
        printf("%s{\"device_count\": %u, \"subset_allocation\": %s, "
               "\"devices\": [", g ? "," : "", nd,
               groups[g].subsetAllocation ? "true" : "false");
        int vega_in_group = 0;
        for (uint32_t d = 0; d < nd; d++) {
            VkPhysicalDeviceProperties p;
            vkGetPhysicalDeviceProperties(devs[d], &p);
            char name[512];
            esc(p.deviceName, name, sizeof name);
            int is_vega = strstr(p.deviceName, "V340") != NULL;
            if (is_vega) vega_in_group++;
            printf("%s{\"device_name\": \"%s\", \"api_version\": \"%u.%u.%u\", "
                   "\"vendor_id\": %u, \"device_id\": %u, \"is_v340\": %s",
                   d ? "," : "", name,
                   VK_API_VERSION_MAJOR(p.apiVersion),
                   VK_API_VERSION_MINOR(p.apiVersion),
                   VK_API_VERSION_PATCH(p.apiVersion),
                   p.vendorID, p.deviceID,
                   is_vega ? "true" : "false");
            VkPhysicalDeviceMemoryProperties mem;
            vkGetPhysicalDeviceMemoryProperties(devs[d], &mem);
            printf(", \"heaps\": [");
            for (uint32_t h = 0; h < mem.memoryHeapCount; h++) {
                printf("%s{\"index\": %u, \"size\": %llu, "
                       "\"device_local\": %s}",
                       h ? "," : "", h,
                       (unsigned long long)mem.memoryHeaps[h].size,
                       (mem.memoryHeaps[h].flags &
                        VK_MEMORY_HEAP_DEVICE_LOCAL_BIT)
                       ? "true" : "false");
            }
            printf("], \"memory_types\": [");
            for (uint32_t m = 0; m < mem.memoryTypeCount; m++) {
                printf("%s{\"index\": %u, \"heap\": %u, \"flags\": %u}",
                       m ? "," : "", m, mem.memoryTypes[m].heapIndex,
                       mem.memoryTypes[m].propertyFlags);
            }
            printf("]}");
        }
        printf("]");
        if (vega_in_group >= 2 && chosen < 0) chosen = (int)g;
        printf("}");
    }
    printf("]");

    if (chosen < 0) {
        printf(", \"vega_group_present\": false}\n");
        fflush(stdout);
        return 0;
    }

    VkPhysicalDevice *devs = groups[chosen].physicalDevices;
    uint32_t nd = groups[chosen].physicalDeviceCount;
    uint32_t nq = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(devs[0], &nq, NULL);
    VkQueueFamilyProperties *qfs = malloc(sizeof(*qfs) * (nq ? nq : 1));
    vkGetPhysicalDeviceQueueFamilyProperties(devs[0], &nq, qfs);
    int family = -1;
    for (uint32_t i = 0; i < nq; i++) {
        if (qfs[i].queueFlags & VK_QUEUE_COMPUTE_BIT) { family = (int)i; break; }
    }
    if (family < 0) { fprintf(stderr, "no compute family\n"); return 2; }

    float pq = 1.0f;
    VkDeviceQueueCreateInfo qci = {0};
    qci.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    qci.queueFamilyIndex = (uint32_t)family;
    qci.queueCount = 1;
    qci.pQueuePriorities = &pq;

    VkDeviceGroupDeviceCreateInfo gci = {0};
    gci.sType = VK_STRUCTURE_TYPE_DEVICE_GROUP_DEVICE_CREATE_INFO;
    gci.physicalDeviceCount = nd;
    gci.pPhysicalDevices = devs;

    VkDeviceCreateInfo dci = {0};
    dci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    dci.pNext = &gci;
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    VkDevice dev;
    CK(vkCreateDevice(devs[0], &dci, NULL, &dev), "create group device");

    printf(", \"vega_group_present\": true, \"chosen_group\": %d, "
           "\"device_count_chosen\": %u, \"peer_memory_features\": [",
           chosen, nd);
    int first = 1;
    for (uint32_t local = 0; local < nd; local++) {
        for (uint32_t peer = 0; peer < nd; peer++) {
            if (local == peer) continue;
            VkPhysicalDeviceMemoryProperties mem;
            vkGetPhysicalDeviceMemoryProperties(devs[local], &mem);
            for (uint32_t h = 0; h < mem.memoryHeapCount; h++) {
                VkPeerMemoryFeatureFlags f = 0;
                vkGetDeviceGroupPeerMemoryFeatures(dev, local, peer, h, &f);
                printf("%s{\"local_device\": %u, \"peer_device\": %u, "
                       "\"heap\": %u, "
                       "\"heap_device_local\": %s, "
                       "\"copy_src\": %s, \"copy_dst\": %s, "
                       "\"generic_src\": %s, \"generic_dst\": %s}",
                       first ? "" : ",", local, peer, h,
                       (mem.memoryHeaps[h].flags &
                        VK_MEMORY_HEAP_DEVICE_LOCAL_BIT) ? "true" : "false",
                       (f & VK_PEER_MEMORY_FEATURE_COPY_SRC_BIT) ? "true" : "false",
                       (f & VK_PEER_MEMORY_FEATURE_COPY_DST_BIT) ? "true" : "false",
                       (f & VK_PEER_MEMORY_FEATURE_GENERIC_SRC_BIT) ? "true" : "false",
                       (f & VK_PEER_MEMORY_FEATURE_GENERIC_DST_BIT) ? "true" : "false");
                first = 0;
            }
        }
    }
    printf("]}\n");
    fflush(stdout);
    return 0;
}

/* Secondary in-stack mechanism census: external-memory handle matrix.
   One binary, prints the exportable/importable feature matrix for both
   Vega dies over buffer usages x handle types, plus the image probes.
   No allocations, no transfers. */
static int ext_matrix_main(void) {
    VkInstanceCreateInfo ci = {0};
    ci.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    VkInstance inst;
    CK(vkCreateInstance(&ci, NULL, &inst), "create instance");
    uint32_t n = 0;
    CK(vkEnumeratePhysicalDevices(inst, &n, NULL), "enum");
    if (n > 8) n = 8;
    VkPhysicalDevice devs[8];
    CK(vkEnumeratePhysicalDevices(inst, &n, devs), "enum2");
    VkPhysicalDevice vega[2];
    int nv = 0;
    for (uint32_t i = 0; i < n && nv < 2; i++) {
        VkPhysicalDeviceProperties p;
        vkGetPhysicalDeviceProperties(devs[i], &p);
        if (strstr(p.deviceName, "V340")) vega[nv++] = devs[i];
    }
    printf("{\"schema\": \"inferswarm.v2e.extmem-matrix/1\", "
           "\"vega_count\": %d, \"dies\": [", nv);
    struct { uint32_t bits; const char *name; } types[] = {
        {VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT, "opaque_fd"},
        {VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT, "dma_buf"},
        {VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT,
         "host_allocation"},
        {VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_MAPPED_FOREIGN_MEMORY_BIT_EXT,
         "host_mapped_foreign"},
    };
    struct { VkBufferUsageFlags bits; const char *name; } usages[] = {
        {0, "none"},
        {VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
         VK_BUFFER_USAGE_TRANSFER_DST_BIT, "transfer"},
        {VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, "storage"},
        {VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT, "uniform"},
    };
    for (int d = 0; d < nv; d++) {
        printf("%s{\"die\": %d, \"buffer_matrix\": [", d ? "," : "", d);
        for (int t = 0; t < 4; t++) {
            for (int u = 0; u < 4; u++) {
                VkPhysicalDeviceExternalBufferInfo eb = {0};
                eb.sType =
                    VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_BUFFER_INFO;
                eb.usage = usages[u].bits;
                eb.handleType = types[t].bits;
                VkExternalBufferProperties ebp = {0};
                ebp.sType = VK_STRUCTURE_TYPE_EXTERNAL_BUFFER_PROPERTIES;
                vkGetPhysicalDeviceExternalBufferProperties(vega[d], &eb,
                                                            &ebp);
                int ex = (ebp.externalMemoryProperties.externalMemoryFeatures
                          & VK_EXTERNAL_MEMORY_FEATURE_EXPORTABLE_BIT) ? 1 : 0;
                int im = (ebp.externalMemoryProperties.externalMemoryFeatures
                          & VK_EXTERNAL_MEMORY_FEATURE_IMPORTABLE_BIT) ? 1 : 0;
                printf("%s{\"handle_type\": \"%s\", \"usage\": \"%s\", "
                       "\"exportable\": %s, \"importable\": %s, "
                       "\"compatible\": %u}",
                       (t || u) ? "," : "", types[t].name, usages[u].name,
                       ex ? "true" : "false", im ? "true" : "false",
                       ebp.externalMemoryProperties.compatibleHandleTypes);
            }
        }
        printf("], \"image_probes\": [");
        for (int t = 0; t < 2; t++) {
            VkPhysicalDeviceExternalImageFormatInfo ei = {0};
            ei.sType =
                VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_IMAGE_FORMAT_INFO;
            ei.handleType = types[t].bits;
            VkPhysicalDeviceImageFormatInfo2 fi = {0};
            fi.sType =
                VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_FORMAT_INFO_2;
            fi.pNext = &ei;
            fi.format = VK_FORMAT_R8_UINT;
            fi.type = VK_IMAGE_TYPE_2D;
            fi.tiling = VK_IMAGE_TILING_LINEAR;
            fi.usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
                       VK_IMAGE_USAGE_TRANSFER_DST_BIT;
            VkExternalImageFormatProperties ep = {0};
            ep.sType =
                VK_STRUCTURE_TYPE_EXTERNAL_IMAGE_FORMAT_PROPERTIES;
            VkImageFormatProperties2 fp = {0};
            fp.sType = VK_STRUCTURE_TYPE_IMAGE_FORMAT_PROPERTIES_2;
            fp.pNext = &ep;
            VkResult r = vkGetPhysicalDeviceImageFormatProperties2(
                vega[d], &fi, &fp);
            int ex = 0, im = 0;
            if (r == VK_SUCCESS) {
                ex = (ep.externalMemoryProperties.externalMemoryFeatures &
                      VK_EXTERNAL_MEMORY_FEATURE_EXPORTABLE_BIT) ? 1 : 0;
                im = (ep.externalMemoryProperties.externalMemoryFeatures &
                      VK_EXTERNAL_MEMORY_FEATURE_IMPORTABLE_BIT) ? 1 : 0;
            }
            printf("%s{\"handle_type\": \"%s\", \"query_result\": %d, "
                   "\"exportable\": %s, \"importable\": %s}",
                   t ? "," : "", t ? "dma_buf" : "opaque_fd", (int)r,
                   ex ? "true" : "false", im ? "true" : "false");
        }
        printf("]}");
    }
    printf("]}\n");
    fflush(stdout);
    return 0;
}
"""

# ---------------------------------------------------------------------------
# Transfer ladder probe.
#
# argv: <binary> ladder <size-bytes> <reps> <warmups>
#   mode=ladder: one peer direction sweep A->B then B->A at one size.
# argv: <binary> latency <reps>
#   4 KiB peer round-trip service (A->B then B->A in one submit).
# argv: <binary> samedie <device-idx> <size-bytes> <reps>
#   device-local copy control on one die.
# argv: <binary> bidir <size-bytes> <reps>
#   simultaneous A->B + B->A on two queues.
# argv: <binary> staged <size-bytes> <reps>
#   host-mediated A->host->B explicit two-leg control (HOST_VISIBLE
#   staging buffer on the group device).
#
# Deterministic source pattern: byte i = (i * 131 + 7) & 0xff, with a
# per-transfer tag byte at offset (i % 4096 == 0) positions replaced by
# a rotating counter so identical-looking buffers cannot satisfy a
# stale-destination check by accident. Verification reads the
# destination back through a HOST_VISIBLE staging buffer AFTER the
# timed copy and compares against a CPU-side regeneration of the
# pattern. Timing brackets ONLY submit+waitIdle of the copy command
# buffer (host clock_gettime MONOTONIC).
# ---------------------------------------------------------------------------

_C_LADDER = r"""
#define _POSIX_C_SOURCE 199309L
#include <vulkan/vulkan.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1e3 + ts.tv_nsec / 1e6;
}

#define CK(x, msg) do { VkResult r_ = (x); if (r_ != VK_SUCCESS) { \
    fprintf(stderr, "vulkan error %d at %s\n", r_, msg); exit(2); } } while (0)

static VkInstance g_inst;
static VkDevice g_dev;
static VkPhysicalDevice g_phys[8];
static uint32_t g_ndev;
static uint32_t g_queue_family[8]; /* per-device compute/transfer family */
static VkQueue g_queue[8];

/* device-local memory type index per device */
static uint32_t g_devmem[8];
/* host-visible memory type index (device 0) */
static uint32_t g_hostmem;
static uint32_t g_maxalloc;

static void fill_pattern(unsigned char *buf, size_t n, unsigned tag) {
    for (size_t i = 0; i < n; i++) {
        unsigned char v = (unsigned char)((i * 131 + 7) & 0xff);
        if ((i & 4095) == 0) v = (unsigned char)(tag & 0xff);
        buf[i] = v;
    }
}

static int check_pattern(const unsigned char *buf, size_t n, unsigned tag) {
    for (size_t i = 0; i < n; i++) {
        unsigned char v = (unsigned char)((i * 131 + 7) & 0xff);
        if ((i & 4095) == 0) v = (unsigned char)(tag & 0xff);
        if (buf[i] != v) return 0;
    }
    return 1;
}

typedef struct { VkBuffer buf; VkDeviceMemory mem; VkDeviceSize size; } Buf;

static void mkbuf_dev(Buf *b, VkDeviceSize sz, uint32_t dev) {
    VkBufferCreateInfo bi = {0};
    bi.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bi.size = sz;
    bi.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    CK(vkCreateBuffer(g_dev, &bi, NULL, &b->buf), "buffer");
    VkMemoryRequirements mr;
    vkGetBufferMemoryRequirements(g_dev, b->buf, &mr);
    VkMemoryAllocateInfo ai = {0};
    ai.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    ai.allocationSize = mr.size;
    ai.memoryTypeIndex = g_devmem[dev];
    CK(vkAllocateMemory(g_dev, &ai, NULL, &b->mem), "alloc dev mem");
    CK(vkBindBufferMemory(g_dev, b->buf, b->mem, 0), "bind");
    b->size = sz;
}

static void mkbuf_host(Buf *b, VkDeviceSize sz) {
    VkBufferCreateInfo bi = {0};
    bi.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bi.size = sz;
    bi.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    CK(vkCreateBuffer(g_dev, &bi, NULL, &b->buf), "buffer host");
    VkMemoryRequirements mr;
    vkGetBufferMemoryRequirements(g_dev, b->buf, &mr);
    /* find a HOST_VISIBLE type on device 0 */
    VkPhysicalDeviceMemoryProperties mem;
    vkGetPhysicalDeviceMemoryProperties(g_phys[0], &mem);
    uint32_t idx = UINT32_MAX;
    for (uint32_t m = 0; m < mem.memoryTypeCount; m++) {
        VkMemoryPropertyFlags f = mem.memoryTypes[m].propertyFlags;
        if ((f & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT) &&
            (f & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) { idx = m; break; }
    }
    if (idx == UINT32_MAX) { fprintf(stderr, "no host-visible mem\n"); exit(2); }
    g_hostmem = idx;
    VkMemoryAllocateInfo ai = {0};
    ai.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    ai.allocationSize = mr.size > (VkDeviceSize)g_maxalloc * 4
                        ? mr.size : mr.size; /* host BAR may cap; try */
    ai.memoryTypeIndex = idx;
    CK(vkAllocateMemory(g_dev, &ai, NULL, &b->mem), "alloc host mem");
    CK(vkBindBufferMemory(g_dev, b->buf, b->mem, 0), "bind host");
    b->size = sz;
}

static void map_and_fill(Buf *b, size_t n, unsigned tag) {
    void *p = NULL;
    CK(vkMapMemory(g_dev, b->mem, 0, n, 0, &p), "map");
    fill_pattern(p, n, tag);
    vkUnmapMemory(g_dev, b->mem);
}

/* read a device buffer back through host staging and verify */
static int verify_readback(Buf *devbuf, Buf *hostbuf, VkCommandPool pool,
                           VkQueue q, size_t n, unsigned tag) {
    VkCommandBufferAllocateInfo cai = {0};
    cai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    cai.commandPool = pool;
    cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    cai.commandBufferCount = 1;
    VkCommandBuffer cb;
    CK(vkAllocateCommandBuffers(g_dev, &cai, &cb), "cmdbuf verify");
    VkCommandBufferBeginInfo bi = {0};
    bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    CK(vkBeginCommandBuffer(cb, &bi), "begin verify");
    VkBufferCopy c = {0};
    c.size = n;
    vkCmdCopyBuffer(cb, devbuf->buf, hostbuf->buf, 1, &c);
    CK(vkEndCommandBuffer(cb), "end verify");
    VkSubmitInfo si = {0};
    si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    si.commandBufferCount = 1;
    si.pCommandBuffers = &cb;
    VkFenceCreateInfo fc = {0};
    fc.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    VkFence fence;
    CK(vkCreateFence(g_dev, &fc, NULL, &fence), "fence verify");
    CK(vkQueueSubmit(q, 1, &si, fence), "submit verify");
    CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wait verify");
    void *p = NULL;
    CK(vkMapMemory(g_dev, hostbuf->mem, 0, n, 0, &p), "map verify");
    int ok = check_pattern(p, n, tag);
    vkUnmapMemory(g_dev, hostbuf->mem);
    vkDestroyFence(g_dev, fence, NULL);
    vkFreeCommandBuffers(g_dev, pool, 1, &cb);
    return ok;
}

static void setup(void) {
    VkInstanceCreateInfo ci = {0};
    ci.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    CK(vkCreateInstance(&ci, NULL, &g_inst), "create instance");
    uint32_t gc = 0;
    CK(vkEnumeratePhysicalDeviceGroups(g_inst, &gc, NULL), "enum groups");
    VkPhysicalDeviceGroupProperties *groups =
        calloc(gc ? gc : 1, sizeof(VkPhysicalDeviceGroupProperties));
    for (uint32_t i = 0; i < gc; i++)
        groups[i].sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GROUP_PROPERTIES;
    CK(vkEnumeratePhysicalDeviceGroups(g_inst, &gc, groups), "enum groups 2");
    int chosen = -1;
    for (uint32_t g = 0; g < gc; g++) {
        int vega = 0;
        for (uint32_t d = 0; d < groups[g].physicalDeviceCount; d++) {
            VkPhysicalDeviceProperties p;
            vkGetPhysicalDeviceProperties(groups[g].physicalDevices[d], &p);
            if (strstr(p.deviceName, "V340")) vega++;
        }
        if (vega >= 2) { chosen = (int)g; break; }
    }
    if (chosen < 0) { fprintf(stderr, "no vega group\n"); exit(2); }
    g_ndev = groups[chosen].physicalDeviceCount;
    if (g_ndev > 8) g_ndev = 8;
    for (uint32_t d = 0; d < g_ndev; d++)
        g_phys[d] = groups[chosen].physicalDevices[d];

    /* queue families + memory types per device */
    for (uint32_t d = 0; d < g_ndev; d++) {
        uint32_t nq = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(g_phys[d], &nq, NULL);
        VkQueueFamilyProperties *qfs = malloc(sizeof(*qfs) * (nq?nq:1));
        vkGetPhysicalDeviceQueueFamilyProperties(g_phys[d], &nq, qfs);
        int fam = -1;
        for (uint32_t i = 0; i < nq; i++)
            if (qfs[i].queueFlags & VK_QUEUE_COMPUTE_BIT) { fam = (int)i; break; }
        if (fam < 0) { fprintf(stderr, "no compute family dev %u\n", d); exit(2); }
        g_queue_family[d] = (uint32_t)fam;
        free(qfs);
        VkPhysicalDeviceMemoryProperties mem;
        vkGetPhysicalDeviceMemoryProperties(g_phys[d], &mem);
        uint32_t idx = UINT32_MAX;
        for (uint32_t m = 0; m < mem.memoryTypeCount; m++) {
            VkMemoryPropertyFlags f = mem.memoryTypes[m].propertyFlags;
            if ((f & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT) &&
                !(f & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT)) { idx = m; break; }
        }
        if (idx == UINT32_MAX) { fprintf(stderr, "no dev-local mem dev %u\n", d); exit(2); }
        g_devmem[d] = idx;
    }
    VkPhysicalDeviceMemoryProperties mem0;
    vkGetPhysicalDeviceMemoryProperties(g_phys[0], &mem0);
    VkPhysicalDeviceLimits lim = {0};
    VkPhysicalDeviceProperties pr;
    vkGetPhysicalDeviceMemoryProperties(g_phys[0], &mem0);
    vkGetPhysicalDeviceProperties(g_phys[0], &pr);
    lim = pr.limits;
    g_maxalloc = (uint32_t)lim.maxMemoryAllocationCount;

    /* one logical device over the whole group; queues per member device */
    VkDeviceQueueCreateInfo qcis[8];
    float pq = 1.0f;
    uint32_t nqci = 0;
    for (uint32_t d = 0; d < g_ndev; d++) {
        /* families may be identical indices; distinct physical devices
           need distinct queue create infos ONLY if indices differ; use
           device 0's family for all (group device semantics: physical
           devices in a group usually share family indices) */
        qcis[nqci].sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
        qcis[nqci].queueFamilyIndex = g_queue_family[0];
        qcis[nqci].queueCount = 1;
        qcis[nqci].pQueuePriorities = &pq;
        nqci++;
    }
    VkDeviceGroupDeviceCreateInfo gci = {0};
    gci.sType = VK_STRUCTURE_TYPE_DEVICE_GROUP_DEVICE_CREATE_INFO;
    gci.physicalDeviceCount = g_ndev;
    gci.pPhysicalDevices = g_phys;
    VkDeviceCreateInfo dci = {0};
    dci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    dci.pNext = &gci;
    dci.queueCreateInfoCount = nqci;
    dci.pQueueCreateInfos = qcis;
    CK(vkCreateDevice(g_phys[0], &dci, NULL, &g_dev), "create group device");
    /* device mask bit d selects queue from physical device d */
    for (uint32_t d = 0; d < g_ndev; d++)
        vkGetDeviceQueue(g_dev, g_queue_family[0], 0, &g_queue[d]);
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: probe <mode> ...\n"); return 3; }
    setup();
    const char *mode = argv[1];

    if (strcmp(mode, "ladder") == 0) {
        if (argc < 5) { fprintf(stderr, "ladder needs size reps warmups\n"); return 3; }
        size_t sz = strtoull(argv[2], NULL, 10);
        int reps = atoi(argv[3]);
        int warmups = atoi(argv[4]);
        printf("{\"schema\": \"%s\", \"mode\": \"ladder\", "
               "\"device_count\": %u, \"bytes\": %zu, \"reps\": %d}\n",
               "inferswarm.v2e.transfer-record/1", g_ndev, sz, reps);
        /* buffers: src_a/dst_a on device 0, src_b/dst_b on device 1 */
        Buf a0, b1, hostbuf;
        mkbuf_dev(&a0, sz, 0);
        mkbuf_dev(&b1, sz, 1);
        mkbuf_host(&hostbuf, sz < (1<<20) ? sz : (1<<20));
        VkCommandPoolCreateInfo pci = {0};
        pci.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        pci.queueFamilyIndex = g_queue_family[0];
        pci.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
        VkCommandPool pool;
        CK(vkCreateCommandPool(g_dev, &pci, NULL, &pool), "pool");
        VkCommandBufferAllocateInfo cai = {0};
        cai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        cai.commandPool = pool;
        cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        cai.commandBufferCount = 1;
        VkCommandBuffer cb;
        CK(vkAllocateCommandBuffers(g_dev, &cai, &cb), "cmdbuf");
        VkFenceCreateInfo fc = {0};
        fc.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        VkFence fence;
        CK(vkCreateFence(g_dev, &fc, NULL, &fence), "fence");

        map_and_fill(&hostbuf, sz < (1<<20) ? sz : (1<<20), 0x5a);
        /* fill a0 with pattern tag 1 via staged upload */
        {
            size_t chunk = sz < (1<<20) ? sz : (1<<20);
            for (size_t off = 0; off < sz; off += chunk) {
                size_t n = sz - off < chunk ? sz - off : chunk;
                /* host buffer holds pattern with tag 1 at its own
                   offsets; regenerate offset-aware pattern directly */
                void *p = NULL;
                CK(vkMapMemory(g_dev, hostbuf.mem, 0, n, 0, &p), "map fill");
                for (size_t i = 0; i < n; i++) {
                    size_t gi = off + i;
                    unsigned char v = (unsigned char)((gi * 131 + 7) & 0xff);
                    if ((gi & 4095) == 0) v = 1;
                    ((unsigned char*)p)[i] = v;
                }
                vkUnmapMemory(g_dev, hostbuf.mem);
                VkCommandBufferBeginInfo bi = {0};
                bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
                CK(vkBeginCommandBuffer(cb, &bi), "begin fill");
                VkBufferCopy c = {0};
                c.srcOffset = 0; c.dstOffset = off; c.size = n;
                vkCmdCopyBuffer(cb, hostbuf.buf, a0.buf, 1, &c);
                CK(vkEndCommandBuffer(cb), "end fill");
                VkSubmitInfo si = {0};
                si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
                si.commandBufferCount = 1;
                si.pCommandBuffers = &cb;
                CK(vkQueueSubmit(g_queue[0], 1, &si, fence), "submit fill");
                CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wait fill");
                CK(vkResetFences(g_dev, 1, &fence), "reset fill");
            }
        }

        /* warmups + timed reps: A(0) -> B(1), submitted on queue 1 */
        const char *dirs[2] = {"a_to_b", "b_to_a"};
        for (int rep = -warmups; rep < reps; rep++) {
            /* source buffer per direction alternates; dest pre-poisoned
               via copy from hostbuf zero pattern would cost; instead
               verify against pattern regeneration each rep with a tag
               derived from rep: re-upload pattern each rep through the
               SAME staged path only for small sizes; for large sizes
               the pattern is uploaded once per direction and the tag is
               fixed (documented). */
            VkCommandBufferBeginInfo bi = {0};
            bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
            CK(vkBeginCommandBuffer(cb, &bi), "begin copy");
            VkBufferCopy c = {0};
            c.size = sz;
            vkCmdCopyBuffer(cb, a0.buf, b1.buf, 1, &c);
            CK(vkEndCommandBuffer(cb), "end copy");
            VkSubmitInfo si = {0};
            si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
            si.commandBufferCount = 1;
            si.pCommandBuffers = &cb;
            double t0 = now_ms();
            CK(vkQueueSubmit(g_queue[1], 1, &si, fence), "submit peer");
            CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wait peer");
            double t1 = now_ms();
            CK(vkResetFences(g_dev, 1, &fence), "reset peer");
            if (rep >= 0)
                printf("{\"kind\": \"transfer\", \"dir\": \"%s\", "
                       "\"rep\": %d, \"ms\": %.6f, \"bytes\": %zu}\n",
                       dirs[0], rep, t1 - t0, sz);
            /* verify A->B immediately (small sizes only; large sizes
               verified once per size at first rep via full readback) */
            if (sz <= (1<<20) || rep == 0) {
                size_t vchunk = sz < (1<<20) ? sz : (1<<20);
                int ok = 1;
                for (size_t off = 0; off < sz && ok; off += vchunk) {
                    size_t n = sz - off < vchunk ? sz - off : vchunk;
                    /* read back chunk to host, check offset-aware */
                    void *p = NULL;
                    CK(vkMapMemory(g_dev, hostbuf.mem, 0, n, 0, &p), "map chk");
                    VkCommandBufferBeginInfo bi2 = {0};
                    bi2.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
                    CK(vkBeginCommandBuffer(cb, &bi2), "begin chk");
                    VkBufferCopy cc = {0};
                    cc.srcOffset = off; cc.dstOffset = 0; cc.size = n;
                    vkCmdCopyBuffer(cb, b1.buf, hostbuf.buf, 1, &cc);
                    CK(vkEndCommandBuffer(cb), "end chk");
                    VkSubmitInfo si2 = {0};
                    si2.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
                    si2.commandBufferCount = 1;
                    si2.pCommandBuffers = &cb;
                    CK(vkQueueSubmit(g_queue[0], 1, &si2, fence), "submit chk");
                    CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wait chk");
                    CK(vkResetFences(g_dev, 1, &fence), "reset chk");
                    for (size_t i = 0; i < n; i++) {
                        size_t gi = off + i;
                        unsigned char v = (unsigned char)((gi*131+7) & 0xff);
                        if ((gi & 4095) == 0) v = 1;
                        if (((unsigned char*)p)[i] != v) { ok = 0; break; }
                    }
                    vkUnmapMemory(g_dev, hostbuf.mem);
                }
                if (!ok) {
                    printf("{\"kind\": \"correctness_fail\", \"dir\": \"%s\", "
                           "\"rep\": %d}\n", dirs[0], rep);
                    fflush(stdout);
                    return 4;
                }
                if (rep >= 0)
                    printf("{\"kind\": \"correctness\", \"dir\": \"%s\", "
                           "\"rep\": %d, \"ok\": true}\n", dirs[0], rep);
            }
        }
        /* B->A direction: upload fresh pattern (tag 2) to b1, copy to
           a0 on queue 0, verify symmetric */
        {
            size_t chunk = sz < (1<<20) ? sz : (1<<20);
            for (size_t off = 0; off < sz; off += chunk) {
                size_t n = sz - off < chunk ? sz - off : chunk;
                void *p = NULL;
                CK(vkMapMemory(g_dev, hostbuf.mem, 0, n, 0, &p), "map fill b");
                for (size_t i = 0; i < n; i++) {
                    size_t gi = off + i;
                    unsigned char v = (unsigned char)((gi * 131 + 7) & 0xff);
                    if ((gi & 4095) == 0) v = 2;
                    ((unsigned char*)p)[i] = v;
                }
                vkUnmapMemory(g_dev, hostbuf.mem);
                VkCommandBufferBeginInfo bi = {0};
                bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
                CK(vkBeginCommandBuffer(cb, &bi), "begin fill b");
                VkBufferCopy c = {0};
                c.srcOffset = 0; c.dstOffset = off; c.size = n;
                vkCmdCopyBuffer(cb, hostbuf.buf, b1.buf, 1, &c);
                CK(vkEndCommandBuffer(cb), "end fill b");
                VkSubmitInfo si = {0};
                si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
                si.commandBufferCount = 1;
                si.pCommandBuffers = &cb;
                CK(vkQueueSubmit(g_queue[1], 1, &si, fence), "submit fill b");
                CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wait fb");
                CK(vkResetFences(g_dev, 1, &fence), "reset fb");
            }
            for (int rep = -warmups; rep < reps; rep++) {
                VkCommandBufferBeginInfo bi = {0};
                bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
                CK(vkBeginCommandBuffer(cb, &bi), "begin copy b");
                VkBufferCopy c = {0};
                c.size = sz;
                vkCmdCopyBuffer(cb, b1.buf, a0.buf, 1, &c);
                CK(vkEndCommandBuffer(cb), "end copy b");
                VkSubmitInfo si = {0};
                si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
                si.commandBufferCount = 1;
                si.pCommandBuffers = &cb;
                double t0 = now_ms();
                CK(vkQueueSubmit(g_queue[0], 1, &si, fence), "submit peer b");
                CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wait pb");
                double t1 = now_ms();
                CK(vkResetFences(g_dev, 1, &fence), "reset pb");
                if (rep >= 0)
                    printf("{\"kind\": \"transfer\", \"dir\": \"%s\", "
                           "\"rep\": %d, \"ms\": %.6f, \"bytes\": %zu}\n",
                           dirs[1], rep, t1 - t0, sz);
                if (sz <= (1<<20) || rep == 0) {
                    size_t vchunk = sz < (1<<20) ? sz : (1<<20);
                    int ok = 1;
                    for (size_t off = 0; off < sz && ok; off += vchunk) {
                        size_t n = sz - off < vchunk ? sz - off : vchunk;
                        void *p = NULL;
                        CK(vkMapMemory(g_dev, hostbuf.mem, 0, n, 0, &p), "map c b");
                        VkCommandBufferBeginInfo bi2 = {0};
                        bi2.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
                        CK(vkBeginCommandBuffer(cb, &bi2), "begin c b");
                        VkBufferCopy cc = {0};
                        cc.srcOffset = off; cc.dstOffset = 0; cc.size = n;
                        vkCmdCopyBuffer(cb, a0.buf, hostbuf.buf, 1, &cc);
                        CK(vkEndCommandBuffer(cb), "end c b");
                        VkSubmitInfo si2 = {0};
                        si2.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
                        si2.commandBufferCount = 1;
                        si2.pCommandBuffers = &cb;
                        CK(vkQueueSubmit(g_queue[0], 1, &si2, fence), "submit cb");
                        CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "wcb");
                        CK(vkResetFences(g_dev, 1, &fence), "rcb");
                        for (size_t i = 0; i < n; i++) {
                            size_t gi = off + i;
                            unsigned char v = (unsigned char)((gi*131+7) & 0xff);
                            if ((gi & 4095) == 0) v = 2;
                            if (((unsigned char*)p)[i] != v) { ok = 0; break; }
                        }
                        vkUnmapMemory(g_dev, hostbuf.mem);
                    }
                    if (!ok) {
                        printf("{\"kind\": \"correctness_fail\", \"dir\": \"%s\", "
                               "\"rep\": %d}\n", dirs[1], rep);
                        fflush(stdout);
                        return 4;
                    }
                    if (rep >= 0)
                        printf("{\"kind\": \"correctness\", \"dir\": \"%s\", "
                               "\"rep\": %d, \"ok\": true}\n", dirs[1], rep);
                }
            }
        }
        fflush(stdout);
        return 0;
    }

    if (strcmp(mode, "samedie") == 0) {
        if (argc < 5) { fprintf(stderr, "samedie needs dev size reps\n"); return 3; }
        uint32_t dev = (uint32_t)atoi(argv[2]);
        size_t sz = strtoull(argv[3], NULL, 10);
        int reps = atoi(argv[4]);
        if (dev >= g_ndev) { fprintf(stderr, "bad device index\n"); return 3; }
        printf("{\"schema\": \"%s\", \"mode\": \"samedie\", \"device\": %u, "
               "\"bytes\": %zu, \"reps\": %d}\n",
               "inferswarm.v2e.transfer-record/1", dev, sz, reps);
        Buf s, d, hostbuf;
        mkbuf_dev(&s, sz, dev);
        mkbuf_dev(&d, sz, dev);
        mkbuf_host(&hostbuf, sz < (1<<20) ? sz : (1<<20));
        VkCommandPoolCreateInfo pci = {0};
        pci.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        pci.queueFamilyIndex = g_queue_family[0];
        VkCommandPool pool;
        CK(vkCreateCommandPool(g_dev, &pci, NULL, &pool), "pool sd");
        VkCommandBufferAllocateInfo cai = {0};
        cai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        cai.commandPool = pool;
        cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        cai.commandBufferCount = 1;
        VkCommandBuffer cb;
        CK(vkAllocateCommandBuffers(g_dev, &cai, &cb), "cmdbuf sd");
        VkFenceCreateInfo fc = {0};
        fc.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        VkFence fence;
        CK(vkCreateFence(g_dev, &fc, NULL, &fence), "fence sd");
        /* fill source with tag 3 via staged upload (single chunk if small) */
        size_t chunk = sz < (1<<20) ? sz : (1<<20);
        for (size_t off = 0; off < sz; off += chunk) {
            size_t n = sz - off < chunk ? sz - off : chunk;
            void *p = NULL;
            CK(vkMapMemory(g_dev, hostbuf.mem, 0, n, 0, &p), "map sd");
            for (size_t i = 0; i < n; i++) {
                size_t gi = off + i;
                unsigned char v = (unsigned char)((gi*131+7) & 0xff);
                if ((gi & 4095) == 0) v = 3;
                ((unsigned char*)p)[i] = v;
            }
            vkUnmapMemory(g_dev, hostbuf.mem);
            VkCommandBufferBeginInfo bi = {0};
            bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
            CK(vkBeginCommandBuffer(cb, &bi), "b sd");
            VkBufferCopy c = {0};
            c.srcOffset = 0; c.dstOffset = off; c.size = n;
            /* upload from host buffer requires submitting on queue 0? no:
               host memory is device-0-visible; submit on g_queue[0] */
            vkCmdCopyBuffer(cb, hostbuf.buf, s.buf, 1, &c);
            CK(vkEndCommandBuffer(cb), "e sd");
            VkSubmitInfo si = {0};
            si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
            si.commandBufferCount = 1;
            si.pCommandBuffers = &cb;
            CK(vkQueueSubmit(g_queue[0], 1, &si, fence), "s sd");
            CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "w sd");
            CK(vkResetFences(g_dev, 1, &fence), "r sd");
        }
        for (int rep = 0; rep < reps; rep++) {
            VkCommandBufferBeginInfo bi = {0};
            bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
            CK(vkBeginCommandBuffer(cb, &bi), "b sdcopy");
            VkBufferCopy c = {0};
            c.size = sz;
            vkCmdCopyBuffer(cb, s.buf, d.buf, 1, &c);
            CK(vkEndCommandBuffer(cb), "e sdcopy");
            VkSubmitInfo si = {0};
            si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
            si.commandBufferCount = 1;
            si.pCommandBuffers = &cb;
            double t0 = now_ms();
            CK(vkQueueSubmit(g_queue[dev], 1, &si, fence), "s sdcopy");
            CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "w sdcopy");
            double t1 = now_ms();
            CK(vkResetFences(g_dev, 1, &fence), "r sdcopy");
            printf("{\"kind\": \"transfer\", \"dir\": \"same_%u\", "
                   "\"rep\": %d, \"ms\": %.6f, \"bytes\": %zu}\n",
                   dev, rep, t1 - t0, sz);
        }
        fflush(stdout);
        return 0;
    }

    if (strcmp(mode, "staged") == 0) {
        if (argc < 4) { fprintf(stderr, "staged needs size reps\n"); return 3; }
        size_t sz = strtoull(argv[2], NULL, 10);
        int reps = atoi(argv[3]);
        printf("{\"schema\": \"%s\", \"mode\": \"staged\", \"bytes\": %zu, "
               "\"reps\": %d}\n",
               "inferswarm.v2e.transfer-record/1", sz, reps);
        Buf a0, b1, hostbuf;
        mkbuf_dev(&a0, sz, 0);
        mkbuf_dev(&b1, sz, 1);
        mkbuf_host(&hostbuf, sz);
        VkCommandPoolCreateInfo pci = {0};
        pci.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        pci.queueFamilyIndex = g_queue_family[0];
        VkCommandPool pool;
        CK(vkCreateCommandPool(g_dev, &pci, NULL, &pool), "pool st");
        VkCommandBufferAllocateInfo cai = {0};
        cai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        cai.commandPool = pool;
        cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        cai.commandBufferCount = 2;
        VkCommandBuffer cb, cb2;
        CK(vkAllocateCommandBuffers(g_dev, &cai, &cb), "cm0 st");
        CK(vkAllocateCommandBuffers(g_dev, &cai, &cb2), "cm1 st");
        VkFenceCreateInfo fc = {0};
        fc.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        VkFence fence;
        CK(vkCreateFence(g_dev, &fc, NULL, &fence), "fence st");
        map_and_fill(&hostbuf, sz, 4);
        for (int rep = 0; rep < reps; rep++) {
            /* leg 1: a0 -> host (D2H) on queue 0 */
            VkCommandBufferBeginInfo bi = {0};
            bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
            CK(vkBeginCommandBuffer(cb, &bi), "b l1");
            VkBufferCopy c1 = {0};
            c1.size = sz;
            vkCmdCopyBuffer(cb, a0.buf, hostbuf.buf, 1, &c1);
            CK(vkEndCommandBuffer(cb), "e l1");
            VkSubmitInfo s1 = {0};
            s1.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
            s1.commandBufferCount = 1;
            s1.pCommandBuffers = &cb;
            double t0 = now_ms();
            CK(vkQueueSubmit(g_queue[0], 1, &s1, fence), "s l1");
            CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "w l1");
            double t1 = now_ms();
            CK(vkResetFences(g_dev, 1, &fence), "r l1");
            /* leg 2: host -> b1 (H2D) on queue 1 */
            VkCommandBufferBeginInfo bi2 = {0};
            bi2.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
            CK(vkBeginCommandBuffer(cb2, &bi2), "b l2");
            VkBufferCopy c2 = {0};
            c2.size = sz;
            vkCmdCopyBuffer(cb2, hostbuf.buf, b1.buf, 1, &c2);
            CK(vkEndCommandBuffer(cb2), "e l2");
            VkSubmitInfo s2 = {0};
            s2.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
            s2.commandBufferCount = 1;
            s2.pCommandBuffers = &cb2;
            double t2 = now_ms();
            CK(vkQueueSubmit(g_queue[1], 1, &s2, fence), "s l2");
            CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "w l2");
            double t3 = now_ms();
            CK(vkResetFences(g_dev, 1, &fence), "r l2");
            printf("{\"kind\": \"transfer\", \"dir\": \"staged_a_to_b\", "
                   "\"rep\": %d, \"ms\": %.6f, \"bytes\": %zu, "
                   "\"leg1_ms\": %.6f, \"leg2_ms\": %.6f}\n",
                   rep, t3 - t0, sz, t1 - t0, t3 - t2);
        }
        fflush(stdout);
        return 0;
    }

    if (strcmp(mode, "bidir") == 0) {
        if (argc < 4) { fprintf(stderr, "bidir needs size reps\n"); return 3; }
        size_t sz = strtoull(argv[2], NULL, 10);
        int reps = atoi(argv[3]);
        printf("{\"schema\": \"%s\", \"mode\": \"bidir\", \"bytes\": %zu, "
               "\"reps\": %d}\n",
               "inferswarm.v2e.transfer-record/1", sz, reps);
        Buf a0, a1, b0, b1;
        mkbuf_dev(&a0, sz, 0);
        mkbuf_dev(&a1, sz, 1);
        mkbuf_dev(&b0, sz, 0);
        mkbuf_dev(&b1, sz, 1);
        VkCommandPoolCreateInfo pci = {0};
        pci.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        pci.queueFamilyIndex = g_queue_family[0];
        VkCommandPool pool;
        CK(vkCreateCommandPool(g_dev, &pci, NULL, &pool), "pool bi");
        VkCommandBufferAllocateInfo cai = {0};
        cai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        cai.commandPool = pool;
        cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        cai.commandBufferCount = 2;
        VkCommandBuffer cb, cb2;
        CK(vkAllocateCommandBuffers(g_dev, &cai, &cb), "cm0 bi");
        CK(vkAllocateCommandBuffers(g_dev, &cai, &cb2), "cm1 bi");
        VkFenceCreateInfo fc = {0};
        fc.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        VkFence fence;
        CK(vkCreateFence(g_dev, &fc, NULL, &fence), "fence bi");
        /* command buffer per direction, each submitted to the
           destination queue, both timed together */
        for (int rep = 0; rep < reps; rep++) {
            VkCommandBufferBeginInfo bi = {0};
            bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
            CK(vkBeginCommandBuffer(cb, &bi), "b d1");
            VkBufferCopy c = {0};
            c.size = sz;
            vkCmdCopyBuffer(cb, a0.buf, b1.buf, 1, &c); /* A->B */
            CK(vkEndCommandBuffer(cb), "e d1");
            VkCommandBufferBeginInfo bi2 = {0};
            bi2.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
            CK(vkBeginCommandBuffer(cb2, &bi2), "b d2");
            VkBufferCopy c2 = {0};
            c2.size = sz;
            vkCmdCopyBuffer(cb2, a1.buf, b0.buf, 1, &c2); /* B->A */
            CK(vkEndCommandBuffer(cb2), "e d2");
            VkCommandBuffer cbs[2] = { cb, cb2 };
            VkSubmitInfo sis[2];
            memset(sis, 0, sizeof(sis));
            sis[0].sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
            sis[0].commandBufferCount = 1; sis[0].pCommandBuffers = &cbs[0];
            sis[1].sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
            sis[1].commandBufferCount = 1; sis[1].pCommandBuffers = &cbs[1];
            double t0 = now_ms();
            CK(vkQueueSubmit(g_queue[1], 1, &sis[0], fence), "s d1");
            CK(vkQueueSubmit(g_queue[0], 1, &sis[1], fence), "s d2");
            CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "w d1");
            CK(vkWaitForFences(g_dev, 1, &fence, VK_TRUE, ~0ull), "w d2");
            double t1 = now_ms();
            CK(vkResetFences(g_dev, 1, &fence), "r bi");
            printf("{\"kind\": \"transfer\", \"dir\": \"bidir\", "
                   "\"rep\": %d, \"ms\": %.6f, \"bytes_each\": %zu}\n",
                   rep, t1 - t0, sz);
        }
        fflush(stdout);
        return 0;
    }

    fprintf(stderr, "unknown mode %s\n", mode);
    return 3;
}
"""


class ProbeError(RuntimeError):
    """The peer probe could not be compiled/executed/parsed."""


def compile_probe(build_dir: Path) -> tuple[Path, str, str]:
    """Compile both embedded probes; returns (ladder_binary, source,
    source_sha256)."""
    build_dir.mkdir(parents=True, exist_ok=True)
    src = build_dir / "v2e_peer_probe.c"
    binary = build_dir / "v2e_peer_probe"
    src.write_text(_C_LADDER, encoding="utf-8")
    cmd = ["cc", "-O2", "-std=c11", str(src), "-lvulkan", "-o", str(binary)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ProbeError(f"probe compile failed: {proc.stderr}")
    return binary, _C_LADDER, hashlib.sha256(_C_LADDER.encode()).hexdigest()


def compile_capability(build_dir: Path) -> tuple[Path, str]:
    build_dir.mkdir(parents=True, exist_ok=True)
    src = build_dir / "v2e_capability_probe.c"
    binary = build_dir / "v2e_capability_probe"
    src.write_text(_C_CAPABILITY, encoding="utf-8")
    cmd = ["cc", "-O2", "-std=c11", str(src), "-lvulkan", "-o", str(binary)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ProbeError(f"capability compile failed: {proc.stderr}")
    return binary, _C_CAPABILITY


def run_capability_probe(*, build_dir: Path, raw_dir: Path) -> dict[str, Any]:
    binary, source = compile_capability(build_dir)
    proc = subprocess.run([str(binary)], capture_output=True, timeout=120)
    stdout = proc.stdout.decode("utf-8", "replace")
    stderr = proc.stderr.decode("utf-8", "replace")
    host.durable_write(raw_dir / "capability-probe.stdout",
                       stdout.encode())
    host.durable_write(raw_dir / "capability-probe.stderr",
                       stderr.encode())
    host.durable_write(raw_dir / "capability-probe.exit-code",
                       f"{proc.returncode}\n".encode())
    parsed = parse_capability_output(stdout, proc.returncode)
    return {
        "parsed": parsed,
        "stdout_rel": "capability-probe.stdout",
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "stderr_rel": "capability-probe.stderr",
        "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        "exit_code": proc.returncode,
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
    }


def run_ext_matrix_probe(*, build_dir: Path, raw_dir: Path) -> dict[str, Any]:
    """Run the external-memory handle matrix probe (no transfers)."""
    binary, source = compile_capability(build_dir)
    proc = subprocess.run([str(binary), "ext-matrix"], capture_output=True,
                          timeout=120)
    stdout = proc.stdout.decode("utf-8", "replace")
    stderr = proc.stderr.decode("utf-8", "replace")
    host.durable_write(raw_dir / "ext-matrix.stdout", stdout.encode())
    host.durable_write(raw_dir / "ext-matrix.stderr", stderr.encode())
    host.durable_write(raw_dir / "ext-matrix.exit-code",
                       f"{proc.returncode}\n".encode())
    parsed = parse_capability_output(stdout, proc.returncode)
    return {
        "parsed": parsed,
        "stdout_rel": "ext-matrix.stdout",
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "stderr_rel": "ext-matrix.stderr",
        "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        "exit_code": proc.returncode,
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
    }


def parse_capability_output(stdout: str, exit_code: int) -> dict[str, Any]:
    if exit_code != 0:
        raise ProbeError(f"capability probe exit {exit_code}")
    text = stdout.strip()
    if not text.startswith("{"):
        raise ProbeError("capability probe emitted no JSON object")
    doc = json.loads(text)
    if "group_count" not in doc or "groups" not in doc:
        raise ProbeError("capability probe JSON missing groups")
    return doc


def run_transfer(*, binary: Path, mode: str, args: list[str],
                 timeout: int = 600) -> dict[str, Any]:
    """Run one transfer probe invocation; retain raw output."""
    argv = [str(binary), mode, *args]
    proc = subprocess.run(argv, capture_output=True, timeout=timeout)
    return {
        "argv": argv,
        "returncode": proc.returncode,
        "stdout": proc.stdout.decode("utf-8", "replace"),
        "stderr": proc.stderr.decode("utf-8", "replace"),
    }
