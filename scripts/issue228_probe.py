#!/usr/bin/env python3
"""Issue #228 — V2-E capability census probes (embedded C) — corrected.

Correction round (maintainer NO-GO on c9822fe). This module now contains
ONLY the read-only capability census machinery. The transfer-ladder probe
of the rejected round was removed outright: its embedded C could not
identify inter-die traffic (one logical queue was retrieved for every
group device and submits carried no device-group execution masks, so all
work executed on device zero), and its staged/bidir paths allocated two
command buffers into scalar handles. Re-enabling physical transfer
execution requires a new, reviewed producer — corrected capability
observations can never authorize the old ladder.

Census corrections implemented here (review findings 1/2):

* the Vulkan instance is created with an explicit ``VkApplicationInfo``
  negotiating API 1.1 — the minimum version at which every core call
  used here (``vkEnumerateInstanceVersion``,
  ``vkEnumeratePhysicalDeviceGroups``, ``vkGetPhysicalDeviceProperties2``,
  ``vkGetDeviceGroupPeerMemoryFeatures``) is core, so no instance
  extension enabling is required; requested/effective versions, loader
  API version, and relevant extension availability are all recorded;
* every enumerated device is bound to stable physical identity via
  ``VkPhysicalDeviceIDProperties`` (deviceUUID/driverUUID; the RADV
  deviceUUID encodes the PCI BDF, which validate_capability_census
  corroborates against the accepted fresh A/B mapping — never name
  substrings or enumeration order);
* the peer-memory query uses the spec argument order
  ``vkGetDeviceGroupPeerMemoryFeatures(device, heapIndex,
  localDeviceIndex, remoteDeviceIndex, pPeerMemoryFeatures)``;
* the external-memory matrix drops the invalid zero-usage rows and
  records per-device extension availability so negatives are scoped to
  the resource/usage/handle combinations actually queried;
* malformed or failed enumeration is an evidence FAILURE (nonzero exit
  + stderr reason), never proof of capability absence.

No transfer, no allocation beyond instance/device creation, no queue
submission exists in this module.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import issue228_host as host

SCHEMA_CAPABILITY = "inferswarm.v2e.capability/2"
SCHEMA_EXT_MATRIX = "inferswarm.v2e.extmem-matrix/2"

#: Instance extensions whose availability is recorded with the census.
#: With an instance API version of 1.1 none of them must be ENABLED for
#: the census calls to be legal; availability is recorded so negative
#: conclusions stay scoped to the observed stack.
RELEVANT_INSTANCE_EXTENSIONS = (
    "VK_KHR_device_group_creation",
    "VK_KHR_external_memory_capabilities",
    "VK_KHR_external_memory_fd",
    "VK_EXT_external_memory_dma_buf",
    "VK_KHR_get_physical_device_properties2",
)

#: Device extensions whose availability is recorded per Vega die.
RELEVANT_DEVICE_EXTENSIONS = (
    "VK_KHR_device_group",
    "VK_KHR_external_memory",
    "VK_KHR_external_memory_fd",
    "VK_EXT_external_memory_dma_buf",
)

#: Handle-type bits (VkExternalMemoryHandleTypeFlagBits) that can carry
#: device memory between processes/drivers on this platform. Host-only
#: import handle types (HOST_ALLOCATION 0x20, HOST_MAPPED_FOREIGN 0x40)
#: are deliberately excluded: the ability to import host memory is not
#: direct peer access between dies.
HANDLE_TYPE_BITS = {
    "opaque_fd": 0x1,
    "host_allocation": 0x20,
    "host_mapped_foreign": 0x40,
    "dma_buf": 0x80,
}
PEER_HANDLE_TYPES = ("opaque_fd", "dma_buf")

DMA_BUF_BIT = 0x80


class ProbeError(RuntimeError):
    """The capability probe could not be compiled/executed/parsed."""


class CensusInvalid(RuntimeError):
    """The retained census cannot support any capability conclusion."""


# ---------------------------------------------------------------------------
# Embedded C capability census (read-only; instance + queries only).
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

#define WANTED_API VK_MAKE_VERSION(1, 1, 0)
#define N_RELEVANT_INST 5
#define N_RELEVANT_DEV 4

static const char *RELEVANT_INST[N_RELEVANT_INST] = {
    "VK_KHR_device_group_creation",
    "VK_KHR_external_memory_capabilities",
    "VK_KHR_external_memory_fd",
    "VK_EXT_external_memory_dma_buf",
    "VK_KHR_get_physical_device_properties2",
};
static const char *RELEVANT_DEV[N_RELEVANT_DEV] = {
    "VK_KHR_device_group",
    "VK_KHR_external_memory",
    "VK_KHR_external_memory_fd",
    "VK_EXT_external_memory_dma_buf",
};

int capability_main(void);
static int ext_matrix_main(void);

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "ext-matrix") == 0)
        return ext_matrix_main();
    return capability_main();
}

static void print_relevant(const char *key, uint32_t total,
                           char (*found)[VK_MAX_EXTENSION_NAME_SIZE],
                           uint32_t nfound) {
    printf(", \"%s\": {\"total\": %u, \"relevant\": {", key, total);
    for (int r = 0; r < (key[0] == 'i' ? N_RELEVANT_INST : N_RELEVANT_DEV); r++) {
        const char *want = key[0] == 'i' ? RELEVANT_INST[r] : RELEVANT_DEV[r];
        int hit = 0;
        for (uint32_t f = 0; f < nfound; f++) {
            if (strcmp(found[f], want) == 0) { hit = 1; break; }
        }
        printf("%s\"%s\": %s", r ? "," : "", want, hit ? "true" : "false");
    }
    printf("}}");
}

/* enumerate extensions for one layer(NULL=instance) and print the
   relevant-membership record */
static void print_extension_record(VkPhysicalDevice dev, const char *key) {
    uint32_t total = 0;
    VkResult r;
    if (dev == (VkPhysicalDevice)0) {
        r = vkEnumerateInstanceExtensionProperties(NULL, &total, NULL);
    } else {
        r = vkEnumerateDeviceExtensionProperties(dev, NULL, &total, NULL);
    }
    if (r != VK_SUCCESS) {
        printf(", \"%s_error\": %d", key, (int)r);
        printf(", \"%s\": {\"total\": 0, \"relevant\": {", key);
        printf("}}");
        return;
    }
    VkExtensionProperties *props =
        calloc(total ? total : 1, sizeof(VkExtensionProperties));
    if (dev == (VkPhysicalDevice)0) {
        r = vkEnumerateInstanceExtensionProperties(NULL, &total, props);
    } else {
        r = vkEnumerateDeviceExtensionProperties(dev, NULL, &total, props);
    }
    if (r != VK_SUCCESS) {
        printf(", \"%s_error\": %d", key, (int)r);
        printf(", \"%s\": {\"total\": 0, \"relevant\": {", key);
        printf("}}");
        free(props);
        return;
    }
    static char names[256][VK_MAX_EXTENSION_NAME_SIZE];
    uint32_t nc = total < 256 ? total : 256;
    for (uint32_t i = 0; i < nc; i++)
        memcpy(names[i], props[i].extensionName, VK_MAX_EXTENSION_NAME_SIZE);
    print_relevant(key, total, names, nc);
    free(props);
}

/* print one physical device's identity + memory topology. Uses the
   Properties2/IDProperties chain so deviceUUID/driverUUID are captured
   (stable physical identity; the RADV deviceUUID encodes the BDF). */
static void print_device(VkPhysicalDevice dev) {
    VkPhysicalDeviceProperties2 p2;
    memset(&p2, 0, sizeof p2);
    p2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
    VkPhysicalDeviceIDProperties idp;
    memset(&idp, 0, sizeof idp);
    idp.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES;
    p2.pNext = &idp;
    vkGetPhysicalDeviceProperties2(dev, &p2);
    VkPhysicalDeviceProperties p = p2.properties;

    char name[512];
    esc(p.deviceName, name, sizeof name);
    char uuid[VK_UUID_SIZE * 2 + 1];
    char druuid[VK_UUID_SIZE * 2 + 1];
    for (int i = 0; i < VK_UUID_SIZE; i++) {
        snprintf(uuid + i * 2, 3, "%02x", idp.deviceUUID[i]);
        snprintf(druuid + i * 2, 3, "%02x", idp.driverUUID[i]);
    }
    printf("{\"device_name\": \"%s\", \"api_version\": \"%u.%u.%u\", "
           "\"driver_version\": %u, "
           "\"vendor_id\": %u, \"device_id\": %u, "
           "\"is_v340\": %s, "
           "\"device_uuid\": \"%s\", \"driver_uuid\": \"%s\"",
           name,
           VK_API_VERSION_MAJOR(p.apiVersion),
           VK_API_VERSION_MINOR(p.apiVersion),
           VK_API_VERSION_PATCH(p.apiVersion),
           p.driverVersion, p.vendorID, p.deviceID,
           strstr(p.deviceName, "V340") ? "true" : "false",
           uuid, druuid);
    VkPhysicalDeviceMemoryProperties mem;
    vkGetPhysicalDeviceMemoryProperties(dev, &mem);
    printf(", \"heaps\": [");
    for (uint32_t h = 0; h < mem.memoryHeapCount; h++) {
        printf("%s{\"index\": %u, \"size\": %llu, \"device_local\": %s}",
               h ? "," : "", h,
               (unsigned long long)mem.memoryHeaps[h].size,
               (mem.memoryHeaps[h].flags &
                VK_MEMORY_HEAP_DEVICE_LOCAL_BIT) ? "true" : "false");
    }
    printf("], \"memory_types\": [");
    for (uint32_t m = 0; m < mem.memoryTypeCount; m++) {
        printf("%s{\"index\": %u, \"heap\": %u, \"flags\": %u}",
               m ? "," : "", m, mem.memoryTypes[m].heapIndex,
               mem.memoryTypes[m].propertyFlags);
    }
    printf("]}");
}

/* capability_main: group enumeration + peer-memory features under a
   valid Vulkan 1.1 instance configuration. */
int capability_main(void) {
    VkApplicationInfo app;
    memset(&app, 0, sizeof app);
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.pApplicationName = "inferswarm-v2e-capability";
    app.pEngineName = "inferswarm";
    app.apiVersion = WANTED_API;

    VkInstanceCreateInfo ci;
    memset(&ci, 0, sizeof ci);
    ci.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    ci.pApplicationInfo = &app;
    VkInstance inst;
    CK(vkCreateInstance(&ci, NULL, &inst), "create instance");

    uint32_t ep = 0;
    CK(vkEnumerateInstanceVersion(&ep), "instance version");
    if (ep < WANTED_API) {
        fprintf(stderr, "loader api %u.%u.%u below required 1.1.0\n",
                VK_API_VERSION_MAJOR(ep), VK_API_VERSION_MINOR(ep),
                VK_API_VERSION_PATCH(ep));
        return 2;
    }

    uint32_t gc = 0;
    CK(vkEnumeratePhysicalDeviceGroups(inst, &gc, NULL), "enum groups");
    if (gc == 0) { fprintf(stderr, "no device groups\n"); return 2; }
    VkPhysicalDeviceGroupProperties *groups =
        calloc(gc, sizeof(VkPhysicalDeviceGroupProperties));
    if (!groups) { fprintf(stderr, "alloc groups\n"); return 2; }
    for (uint32_t i = 0; i < gc; i++)
        groups[i].sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GROUP_PROPERTIES;
    CK(vkEnumeratePhysicalDeviceGroups(inst, &gc, groups), "enum groups 2");

    printf("{\"schema\": \"inferswarm.v2e.capability/2\", "
           "\"requested_api_version\": \"1.1.0\", "
           "\"effective_api_version\": \"%u.%u.%u\"",
           VK_API_VERSION_MAJOR(ep), VK_API_VERSION_MINOR(ep),
           VK_API_VERSION_PATCH(ep));
    print_extension_record((VkPhysicalDevice)0, "instance_extensions");
    printf(", \"group_count\": %u, \"groups\": [", gc);
    int chosen = -1;
    for (uint32_t g = 0; g < gc; g++) {
        VkPhysicalDevice *devs = groups[g].physicalDevices;
        uint32_t nd = groups[g].physicalDeviceCount;
        if (nd == 0 || devs == NULL) {
            fprintf(stderr, "empty group %u\n", g);
            return 2;
        }
        printf("%s{\"device_count\": %u, \"subset_allocation\": %s, "
               "\"devices\": [", g ? "," : "", nd,
               groups[g].subsetAllocation ? "true" : "false");
        int vega_in_group = 0;
        for (uint32_t d = 0; d < nd; d++) {
            if (d) printf(",");
            print_device(devs[d]);
            VkPhysicalDeviceProperties tp;
            vkGetPhysicalDeviceProperties(devs[d], &tp);
            if (strstr(tp.deviceName, "V340")) vega_in_group++;
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
    if (!qfs) { fprintf(stderr, "alloc qfs\n"); return 2; }
    vkGetPhysicalDeviceQueueFamilyProperties(devs[0], &nq, qfs);
    int family = -1;
    for (uint32_t i = 0; i < nq; i++) {
        if (qfs[i].queueFlags & VK_QUEUE_COMPUTE_BIT) { family = (int)i; break; }
    }
    if (family < 0) { fprintf(stderr, "no compute family\n"); return 2; }

    float pq = 1.0f;
    VkDeviceQueueCreateInfo qci;
    memset(&qci, 0, sizeof qci);
    qci.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    qci.queueFamilyIndex = (uint32_t)family;
    qci.queueCount = 1;
    qci.pQueuePriorities = &pq;

    VkDeviceGroupDeviceCreateInfo gci;
    memset(&gci, 0, sizeof gci);
    gci.sType = VK_STRUCTURE_TYPE_DEVICE_GROUP_DEVICE_CREATE_INFO;
    gci.physicalDeviceCount = nd;
    gci.pPhysicalDevices = devs;

    VkDeviceCreateInfo dci;
    memset(&dci, 0, sizeof dci);
    dci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    dci.pNext = &gci;
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    /* enabled extensions: none — device-group + peer-memory queries are
       core 1.1; the record below states this explicitly */
    VkDevice dev;
    CK(vkCreateDevice(devs[0], &dci, NULL, &dev), "create group device");

    printf(", \"vega_group_present\": true, \"chosen_group\": %d, "
           "\"device_count_chosen\": %u, "
           "\"chosen_device_enabled_extensions\": []",
           chosen, nd);
    print_extension_record(devs[0], "chosen_device_extensions");
    printf(", \"peer_memory_features\": [");
    int first = 1;
    for (uint32_t local = 0; local < nd; local++) {
        for (uint32_t peer = 0; peer < nd; peer++) {
            if (local == peer) continue;
            VkPhysicalDeviceMemoryProperties mem;
            vkGetPhysicalDeviceMemoryProperties(devs[local], &mem);
            for (uint32_t h = 0; h < mem.memoryHeapCount; h++) {
                VkPeerMemoryFeatureFlags f = 0;
                /* SPEC ORDER: device, heapIndex, localDeviceIndex,
                   remoteDeviceIndex, pPeerMemoryFeatures */
                vkGetDeviceGroupPeerMemoryFeatures(dev, h, local, peer, &f);
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

/* Secondary in-stack mechanism census: external-memory handle matrix
   for the Vega dies. Valid resource usages only (the rejected round
   queried a zero-usage buffer, which is not a valid resource
   requirement and is excluded from authoritative decisions). No
   allocations, no transfers; per-device extension availability is
   recorded so negatives stay scoped. */
static int ext_matrix_main(void) {
    VkApplicationInfo app;
    memset(&app, 0, sizeof app);
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.pApplicationName = "inferswarm-v2e-capability";
    app.pEngineName = "inferswarm";
    app.apiVersion = WANTED_API;

    VkInstanceCreateInfo ci;
    memset(&ci, 0, sizeof ci);
    ci.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    ci.pApplicationInfo = &app;
    VkInstance inst;
    CK(vkCreateInstance(&ci, NULL, &inst), "create instance");
    uint32_t ep = 0;
    CK(vkEnumerateInstanceVersion(&ep), "instance version");
    if (ep < WANTED_API) {
        fprintf(stderr, "loader api %u.%u.%u below required 1.1.0\n",
                VK_API_VERSION_MAJOR(ep), VK_API_VERSION_MINOR(ep),
                VK_API_VERSION_PATCH(ep));
        return 2;
    }
    uint32_t n = 0;
    CK(vkEnumeratePhysicalDevices(inst, &n, NULL), "enum");
    if (n == 0) { fprintf(stderr, "no physical devices\n"); return 2; }
    if (n > 16) n = 16;
    VkPhysicalDevice devs[16];
    CK(vkEnumeratePhysicalDevices(inst, &n, devs), "enum2");
    VkPhysicalDevice vega[16];
    char vega_uuid[16][VK_UUID_SIZE * 2 + 1];
    int nv = 0;
    for (uint32_t i = 0; i < n && nv < 16; i++) {
        VkPhysicalDeviceProperties2 p2;
        memset(&p2, 0, sizeof p2);
        p2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
        VkPhysicalDeviceIDProperties idp;
        memset(&idp, 0, sizeof idp);
        idp.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES;
        p2.pNext = &idp;
        vkGetPhysicalDeviceProperties2(devs[i], &p2);
        if (!strstr(p2.properties.deviceName, "V340")) continue;
        vega[nv] = devs[i];
        for (int k = 0; k < VK_UUID_SIZE; k++)
            snprintf(vega_uuid[nv] + k * 2, 3, "%02x", idp.deviceUUID[k]);
        nv++;
    }
    if (nv == 0) { fprintf(stderr, "no vega devices\n"); return 2; }
    printf("{\"schema\": \"inferswarm.v2e.extmem-matrix/2\", "
           "\"requested_api_version\": \"1.1.0\", "
           "\"effective_api_version\": \"%u.%u.%u\", "
           "\"vega_count\": %d, \"dies\": [",
           VK_API_VERSION_MAJOR(ep), VK_API_VERSION_MINOR(ep),
           VK_API_VERSION_PATCH(ep), nv);
    struct { uint32_t bits; const char *name; } types[] = {
        {VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT, "opaque_fd"},
        {VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT, "dma_buf"},
        {VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT,
         "host_allocation"},
        {VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_MAPPED_FOREIGN_MEMORY_BIT_EXT,
         "host_mapped_foreign"},
    };
    struct { VkBufferUsageFlags bits; const char *name; } usages[] = {
        {VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
         VK_BUFFER_USAGE_TRANSFER_DST_BIT, "transfer"},
        {VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, "storage"},
        {VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT, "uniform"},
    };
    for (int d = 0; d < nv; d++) {
        printf("%s{\"die\": %d, \"device_uuid\": \"%s\"",
               d ? "," : "", d, vega_uuid[d]);
        char key[32];
        snprintf(key, sizeof key, "die_%d_extensions", d);
        print_extension_record(vega[d], key);
        printf(", \"buffer_matrix\": [");
        for (int t = 0; t < 4; t++) {
            for (int u = 0; u < 3; u++) {
                VkPhysicalDeviceExternalBufferInfo eb;
                memset(&eb, 0, sizeof eb);
                eb.sType =
                    VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_BUFFER_INFO;
                eb.usage = usages[u].bits;
                eb.handleType = types[t].bits;
                VkExternalBufferProperties ebp;
                memset(&ebp, 0, sizeof ebp);
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
            VkPhysicalDeviceExternalImageFormatInfo ei;
            memset(&ei, 0, sizeof ei);
            ei.sType =
                VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_IMAGE_FORMAT_INFO;
            ei.handleType = types[t].bits;
            VkPhysicalDeviceImageFormatInfo2 fi;
            memset(&fi, 0, sizeof fi);
            fi.sType =
                VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_FORMAT_INFO_2;
            fi.pNext = &ei;
            fi.format = VK_FORMAT_R8_UINT;
            fi.type = VK_IMAGE_TYPE_2D;
            fi.tiling = VK_IMAGE_TILING_LINEAR;
            fi.usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
                       VK_IMAGE_USAGE_TRANSFER_DST_BIT;
            VkExternalImageFormatProperties ep2;
            memset(&ep2, 0, sizeof ep2);
            ep2.sType =
                VK_STRUCTURE_TYPE_EXTERNAL_IMAGE_FORMAT_PROPERTIES;
            VkImageFormatProperties2 fp;
            memset(&fp, 0, sizeof fp);
            fp.sType = VK_STRUCTURE_TYPE_IMAGE_FORMAT_PROPERTIES_2;
            fp.pNext = &ep2;
            VkResult r = vkGetPhysicalDeviceImageFormatProperties2(
                vega[d], &fi, &fp);
            int ex = 0, im = 0;
            if (r == VK_SUCCESS) {
                ex = (ep2.externalMemoryProperties.externalMemoryFeatures &
                      VK_EXTERNAL_MEMORY_FEATURE_EXPORTABLE_BIT) ? 1 : 0;
                im = (ep2.externalMemoryProperties.externalMemoryFeatures &
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


def run_capability_probe(*, build_dir: Path, raw_dir: Path,
                         env: dict[str, str] | None = None) -> dict[str, Any]:
    """Compile and run the census probe; retain raw bytes durably.

    ``env`` is intended for stub-interposition contract tests
    (LD_LIBRARY_PATH etc.); physical collection passes None.
    """
    binary, source = compile_capability(build_dir)
    run_env = None
    if env:
        run_env = dict(env)
    proc = subprocess.run([str(binary)], capture_output=True, timeout=120,
                          env=run_env)
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


def run_ext_matrix_probe(*, build_dir: Path, raw_dir: Path,
                         env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run the external-memory handle matrix probe (no transfers)."""
    binary, source = compile_capability(build_dir)
    run_env = None
    if env:
        run_env = dict(env)
    proc = subprocess.run([str(binary), "ext-matrix"], capture_output=True,
                          timeout=120, env=run_env)
    stdout = proc.stdout.decode("utf-8", "replace")
    stderr = proc.stderr.decode("utf-8", "replace")
    host.durable_write(raw_dir / "ext-matrix.stdout", stdout.encode())
    host.durable_write(raw_dir / "ext-matrix.stderr", stderr.encode())
    host.durable_write(raw_dir / "ext-matrix.exit-code",
                       f"{proc.returncode}\n".encode())
    parsed = parse_ext_matrix_output(stdout, proc.returncode)
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
        raise ProbeError(
            f"capability probe exit {exit_code} (evidence failure, not "
            f"capability absence)")
    text = stdout.strip()
    if not text.startswith("{"):
        raise ProbeError("capability probe emitted no JSON object")
    doc = json.loads(text)
    if doc.get("schema") != SCHEMA_CAPABILITY:
        raise ProbeError(
            f"capability probe schema mismatch: {doc.get('schema')!r}")
    for key in ("requested_api_version", "effective_api_version",
                "group_count", "groups", "instance_extensions"):
        if key not in doc:
            raise ProbeError(f"capability probe JSON missing {key}")
    if not isinstance(doc["groups"], list) or not doc["groups"]:
        raise ProbeError("capability probe reported no groups")
    for g in doc["groups"]:
        if not isinstance(g.get("devices"), list) or not g["devices"]:
            raise ProbeError("capability group with no devices")
    return doc


def parse_ext_matrix_output(stdout: str, exit_code: int) -> dict[str, Any]:
    if exit_code != 0:
        raise ProbeError(
            f"ext-matrix probe exit {exit_code} (evidence failure, not "
            f"capability absence)")
    text = stdout.strip()
    if not text.startswith("{"):
        raise ProbeError("ext-matrix probe emitted no JSON object")
    doc = json.loads(text)
    if doc.get("schema") != SCHEMA_EXT_MATRIX:
        raise ProbeError(
            f"ext-matrix schema mismatch: {doc.get('schema')!r}")
    if "dies" not in doc or not doc["dies"]:
        raise ProbeError("ext-matrix probe JSON missing dies")
    return doc


# ---------------------------------------------------------------------------
# Census validation — the fail-closed authority for every capability
# conclusion. Both the collector and the reducer call THIS; neither may
# trust its own summary instead.
# ---------------------------------------------------------------------------

def _api_ge_1_1(version: str) -> bool:
    try:
        major, minor, _patch = (int(x) for x in version.split("."))
    except (ValueError, AttributeError):
        return False
    return (major, minor) >= (1, 1)


def bdf_from_device_uuid(uuid_hex: str) -> str | None:
    """Derive the PCI BDF encoded in a RADV deviceUUID.

    RADV builds deviceUUID as four zero bytes, then bus, device, then
    zeros. The derivation is only a hypothesis until corroborated
    against the accepted mapping — a mismatch fails the join closed.
    """
    try:
        raw = bytes.fromhex(uuid_hex)
    except ValueError:
        return None
    if len(raw) != 16:
        return None
    bus, dev = raw[4], raw[5]
    return f"0000:{bus:02x}:{dev:02x}.0"


def normalize_bdf(bdf: str) -> str:
    bdf = bdf.strip().lower()
    if not bdf.startswith("0000:"):
        bdf = f"0000:{bdf}"
    return bdf


def validate_capability_census(
        cap: dict[str, Any], ext: dict[str, Any],
        expected_bdfs: dict[str, str]) -> dict[str, Any]:
    """Validate a retained capability census against physical identity.

    ``expected_bdfs`` maps participant label -> normalized BDF from the
    fresh accepted A/B mapping (e.g. {"a": "0000:06:00.0", ...}).

    Returns a structured verdict. ``census_valid`` False means NO
    capability conclusion (positive or negative) may be drawn — the
    failure reasons explain why. Identity is established by
    deviceUUID->BDF corroboration only; name substrings and enumeration
    order are never physical authority.
    """
    reasons: list[str] = []

    # --- API configuration gate -------------------------------------
    requested = str(cap.get("requested_api_version", ""))
    effective = str(cap.get("effective_api_version", ""))
    api_ok = (_api_ge_1_1(requested) and _api_ge_1_1(effective))
    if not api_ok:
        reasons.append(
            f"census not produced under a valid >=1.1 instance "
            f"configuration (requested={requested!r}, "
            f"effective={effective!r})")
    ext_effective = str(ext.get("effective_api_version", ""))
    if not _api_ge_1_1(ext_effective):
        reasons.append(
            f"ext-matrix census not produced under a valid >=1.1 "
            f"instance configuration (effective={ext_effective!r})")

    # --- flatten vega devices (both census sources) ------------------
    cap_vega: list[dict[str, Any]] = []
    for g in cap.get("groups", []):
        for d in g.get("devices", []):
            if d.get("is_v340"):
                cap_vega.append(d)
    ext_vega = list(ext.get("dies", []))
    if len(cap_vega) != 2:
        reasons.append(
            f"capability census must enumerate exactly 2 V340 devices, "
            f"saw {len(cap_vega)}")
    if len(ext_vega) != 2:
        reasons.append(
            f"ext-matrix census must enumerate exactly 2 V340 dies, saw "
            f"{len(ext_vega)}")
    if reasons:
        return {"census_valid": False, "failure_reasons": reasons}

    cap_uuids = [d.get("device_uuid") for d in cap_vega]
    ext_uuids = [d.get("device_uuid") for d in ext_vega]
    if any(not u for u in cap_uuids) or any(not u for u in ext_uuids):
        reasons.append("census device missing deviceUUID identity")
        return {"census_valid": False, "failure_reasons": reasons}
    if len(set(cap_uuids)) != 2:
        reasons.append("duplicate deviceUUID among census V340 devices")
    if set(cap_uuids) != set(ext_uuids):
        reasons.append(
            "capability and ext-matrix censuses disagree on V340 "
            "device identity (UUID sets differ)")

    # --- identity join: UUID -> BDF -> accepted mapping ---------------
    expected_norm = {k: normalize_bdf(v) for k, v in expected_bdfs.items()}
    if len(set(expected_norm.values())) != len(expected_norm):
        reasons.append("accepted mapping does not carry distinct BDFs")
        return {"census_valid": False, "failure_reasons": reasons}
    uuid_to_participant: dict[str, str] = {}
    identity_rows: dict[str, dict[str, Any]] = {}
    for uuid in sorted(u for u in cap_uuids if u):
        derived = bdf_from_device_uuid(uuid)
        if derived is None:
            reasons.append(f"deviceUUID {uuid} not parseable for BDF")
            continue
        matches = [p for p, bdf in expected_norm.items() if bdf == derived]
        if len(matches) != 1:
            reasons.append(
                f"deviceUUID {uuid} derives BDF {derived} which does not "
                f"match exactly one accepted mapping participant")
            continue
        uuid_to_participant[uuid] = matches[0]
        identity_rows[matches[0]] = {
            "device_uuid": uuid,
            "derived_bdf": derived,
            "device_name": next(d.get("device_name") for d in cap_vega
                                if d.get("device_uuid") == uuid),
            "api_version": next(d.get("api_version") for d in cap_vega
                                if d.get("device_uuid") == uuid),
        }
    if set(uuid_to_participant) != set(cap_uuids) or \
            set(identity_rows) != set(expected_norm):
        reasons.append(
            "census identity join failed: UUID-derived BDFs do not "
            "cover exactly the accepted mapping participants")

    # --- group membership ---------------------------------------------
    group_index = None
    for gi, g in enumerate(cap.get("groups", [])):
        uuids = {d.get("device_uuid") for d in g.get("devices", [])}
        if set(cap_uuids) <= uuids:
            group_index = gi
            break
    if group_index is None:
        group_note = (
            "no Vulkan device group contains both V340 dies "
            "(co-membership absent on this stack)")
    else:
        group_note = f"both V340 dies are co-members of group {group_index}"

    # --- peer-memory features (spec-order rows, physically labeled) ---
    peer_rows = cap.get("peer_memory_features") or []
    directions: dict[str, dict[str, Any]] = {}
    if group_index is None:
        directions = {
            "a_to_b": {"present": False,
                       "basis": "no multi-die group; query unreachable"},
            "b_to_a": {"present": False,
                       "basis": "no multi-die group; query unreachable"},
        }
    else:
        devices = cap["groups"][group_index]["devices"]
        idx_to_uuid = [d.get("device_uuid") for d in devices]
        idx_to_part = [uuid_to_participant.get(u) for u in idx_to_uuid]
        heap_counts = [len(d.get("heaps", [])) for d in devices]
        by_direction: dict[tuple[str, str], list[dict[str, Any]]] = {}
        malformed_peer_rows = 0
        for row in peer_rows:
            try:
                li = int(row["local_device"])
                pi = int(row["peer_device"])
                h = int(row["heap"])
            except (KeyError, TypeError, ValueError):
                malformed_peer_rows += 1
                continue
            if not (0 <= li < len(devices) and 0 <= pi < len(devices)):
                malformed_peer_rows += 1
                continue
            if li == pi or not (0 <= h < heap_counts[li]):
                malformed_peer_rows += 1
                continue
            src = idx_to_part[li]
            dst = idx_to_part[pi]
            if src is None or dst is None or src == dst:
                continue
            by_direction.setdefault((src, dst), []).append(row)
        if malformed_peer_rows:
            reasons.append(
                f"{malformed_peer_rows} peer-feature rows carry invalid "
                f"device/heap indices")
        for src, dst in (("a", "b"), ("b", "a")):
            rows = by_direction.get((src, dst), [])
            # exact distinct direction rows on device-local heaps with
            # BOTH copy features; duplicate rows add nothing
            heaps = sorted({int(r["heap"]) for r in rows
                            if r.get("heap_device_local")
                            and r.get("copy_src") and r.get("copy_dst")})
            directions[f"{src}_to_{dst}"] = {
                "present": bool(heaps),
                "device_local_heaps": heaps,
                "row_count": len(rows),
            }
    peer_both = (directions.get("a_to_b", {}).get("present")
                 and directions.get("b_to_a", {}).get("present"))

    # --- external-memory mechanism (valid usages only) -----------------
    ext_directions: dict[str, dict[str, Any]] = {}
    usable_handles: list[str] = []
    dies_by_uuid = {d.get("device_uuid"): d for d in ext_vega}
    for handle in PEER_HANDLE_TYPES:
        bit = HANDLE_TYPE_BITS[handle]
        handle_ok = True
        handle_detail: dict[str, dict[str, Any]] = {}
        for src, dst in (("a", "b"), ("b", "a")):
            src_uuid = identity_rows.get(src, {}).get("device_uuid")
            dst_uuid = identity_rows.get(dst, {}).get("device_uuid")
            src_die = dies_by_uuid.get(src_uuid)
            dst_die = dies_by_uuid.get(dst_uuid)
            if src_die is None or dst_die is None:
                handle_ok = False
                handle_detail[f"{src}_to_{dst}"] = {
                    "usable": False, "basis": "identity join incomplete"}
                continue
            src_rows = [r for r in src_die.get("buffer_matrix", [])
                        if r.get("handle_type") == handle
                        and r.get("usage") == "transfer"]
            dst_rows = [r for r in dst_die.get("buffer_matrix", [])
                        if r.get("handle_type") == handle
                        and r.get("usage") == "transfer"]
            if len(src_rows) != 1 or len(dst_rows) != 1:
                handle_ok = False
                handle_detail[f"{src}_to_{dst}"] = {
                    "usable": False,
                    "basis": "matrix rows missing for handle/usage"}
                continue
            export_ok = bool(src_rows[0].get("exportable")) and \
                bool(dst_rows[0].get("importable"))
            compat_ok = ((int(src_rows[0].get("compatible") or 0) & bit)
                         and (int(dst_rows[0].get("compatible") or 0) & bit))
            handle_detail[f"{src}_to_{dst}"] = {
                "usable": export_ok and compat_ok,
                "source_exportable": bool(src_rows[0].get("exportable")),
                "destination_importable": bool(dst_rows[0].get("importable")),
                "compatible_handle_types_ok": compat_ok,
            }
            if not (export_ok and compat_ok):
                handle_ok = False
        if handle_ok:
            usable_handles.append(handle)
        ext_directions[handle] = handle_detail

    # scoped observations (recorded regardless of verdict)
    scoped: dict[str, Any] = {
        "instance_extensions": cap.get("instance_extensions"),
        "device_extensions": {
            f"die_{i}": d.get("die_0_extensions") or d.get("die_1_extensions")
            for i, d in enumerate(ext_vega)
            if f"die_{i}_extensions" in d or "die_0_extensions" in d
        },
        "host_only_handle_observations": {
            f"die_{i}": {
                "host_allocation_exportable_or_importable": any(
                    (r.get("exportable") or r.get("importable"))
                    for r in d.get("buffer_matrix", [])
                    if r.get("handle_type") in
                    ("host_allocation", "host_mapped_foreign")),
            }
            for i, d in enumerate(ext_vega)
        },
        "image_probe_observations": {
            f"die_{i}": d.get("image_probes") for i, d in enumerate(ext_vega)
        },
    }

    capable_mechanisms: list[str] = []
    if peer_both:
        capable_mechanisms.append("vulkan-device-group-peer-copy")
    if usable_handles:
        capable_mechanisms.append("vulkan-external-memory-fd")

    return {
        "census_valid": not reasons,
        "failure_reasons": reasons,
        "api": {"requested": requested, "effective": effective,
                "ext_matrix_effective": ext_effective},
        "identity": {"join_ok": not any("join" in r or "UUID" in r
                                        or "BDF" in r or "mapping" in r
                                        for r in reasons),
                     "participants": identity_rows},
        "group": {"both_dies_in_one_group": group_index is not None,
                  "note": group_note},
        "peer_features": {"directions": directions,
                          "both_directions_device_local_copy": peer_both},
        "external_memory": {"usable_handle_types": usable_handles,
                            "directions": ext_directions},
        "scoped_observations": scoped,
        "capable_mechanisms": capable_mechanisms,
    }
