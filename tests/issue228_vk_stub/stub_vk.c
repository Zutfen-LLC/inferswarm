/* Recording stub loader for #228 contract tests: implements every
 * prototype the census probe calls and writes each call's arguments to
 * $V2E_STUB_LOG (one JSON-ish line per call). */
#define _GNU_SOURCE
#include "vulkan/vulkan.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static FILE *vlog(void) {
    const char *p = getenv("V2E_STUB_LOG");
    if (!p) return NULL;
    FILE *f = fopen(p, "a");
    return f;
}

static VkPhysicalDevice pd(int i) { return (VkPhysicalDevice)(uintptr_t)(0x1000 + i); }

VkResult vkCreateInstance(const VkInstanceCreateInfo *ci, const void *a, VkInstance *out) {
    (void)a;
    FILE *f = vlog();
    uint32_t api = 0; int has_app = 0;
    if (ci && ci->pApplicationInfo) {
        has_app = 1;
        api = ci->pApplicationInfo->apiVersion;
    }
    if (f) { fprintf(f, "CALL vkCreateInstance has_pApplicationInfo=%d apiVersion=%u.%u.%u enabledExtensionCount=%u\n",
        has_app, VK_API_VERSION_MAJOR(api), VK_API_VERSION_MINOR(api), VK_API_VERSION_PATCH(api),
        ci ? ci->enabledExtensionCount : 0); fclose(f); }
    *out = (VkInstance)(uintptr_t)0x1;
    return VK_SUCCESS;
}
void vkDestroyInstance(VkInstance i, const void *a) { (void)i; (void)a; }

VkResult vkEnumerateInstanceVersion(uint32_t *v) {
    FILE *f = vlog();
    if (f) { fprintf(f, "CALL vkEnumerateInstanceVersion\n"); fclose(f); }
    const char *e = getenv("V2E_STUB_INSTANCE_API");
    *v = e ? (uint32_t)strtoul(e, NULL, 0) : VK_MAKE_VERSION(1,4,0);
    return VK_SUCCESS;
}
VkResult vkEnumerateInstanceExtensionProperties(const char *l, uint32_t *n, VkExtensionProperties *p) {
    (void)l;
    if (p) {
        *n = 1;
        memset(p, 0, sizeof *p);
        strcpy(p[0].extensionName, "VK_KHR_surface");
    } else {
        *n = 1;
    }
    return VK_SUCCESS;
}
VkResult vkEnumeratePhysicalDeviceGroups(VkInstance i, uint32_t *n, VkPhysicalDeviceGroupProperties *g) {
    (void)i;
    FILE *f = vlog();
    if (f) { fprintf(f, "CALL vkEnumeratePhysicalDeviceGroups\n"); fclose(f); }
    const char *m = getenv("V2E_STUB_GROUPS");
    int multi = m && atoi(m) == 1;  /* 1 = both vegas in ONE group; 0 = two single groups */
    if (!g) { *n = multi ? 1 : 2; return VK_SUCCESS; }
    if (multi) {
        *n = 1;
        g[0].physicalDeviceCount = 2;
        g[0].physicalDevices[0] = pd(0);
        g[0].physicalDevices[1] = pd(1);
        g[0].subsetAllocation = 0;
    } else {
        *n = 2;
        g[0].physicalDeviceCount = 1; g[0].physicalDevices[0] = pd(0);
        g[1].physicalDeviceCount = 1; g[1].physicalDevices[0] = pd(1);
    }
    return VK_SUCCESS;
}
void vkGetPhysicalDeviceProperties(VkPhysicalDevice d, VkPhysicalDeviceProperties *p) {
    memset(p, 0, sizeof *p);
    p->vendorID = 0x1002; p->deviceID = 0x6864;
    strcpy(p->deviceName, "AMD Radeon Pro V340 (RADV VEGA10)");
    p->apiVersion = VK_MAKE_VERSION(1,4,305);
}
void vkGetPhysicalDeviceProperties2(VkPhysicalDevice d, VkPhysicalDeviceProperties2 *p2) {
    vkGetPhysicalDeviceProperties(d, &p2->properties);
    /* walk pNext for ID properties; UUID bytes 4/5 = bus/dev (RADV) */
    uint8_t bus = 6, dev = 0;
    if ((uintptr_t)d == 0x1001) { bus = 9; dev = 0; }
    for (void *n = p2->pNext; n; ) {
        VkStructureType *st = (VkStructureType *)n;
        if (*st == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES) {
            VkPhysicalDeviceIDProperties *idp = (VkPhysicalDeviceIDProperties *)n;
            memset(idp->deviceUUID, 0, 16);
            idp->deviceUUID[4] = bus; idp->deviceUUID[5] = dev;
            memset(idp->driverUUID, 0x41, 16);
        }
        n = ((struct { VkStructureType st; void *next; } *)n)->next;
    }
}
void vkGetPhysicalDeviceMemoryProperties(VkPhysicalDevice d, VkPhysicalDeviceMemoryProperties *m) {
    (void)d;
    memset(m, 0, sizeof *m);
    m->memoryHeapCount = 2;
    m->memoryHeaps[0] = (VkMemoryHeap){ .size = 8339791872ULL, .flags = 0 };
    m->memoryHeaps[1] = (VkMemoryHeap){ .size = 8573157376ULL, .flags = VK_MEMORY_HEAP_DEVICE_LOCAL_BIT };
    m->memoryTypeCount = 2;
    m->memoryTypes[0] = (VkMemoryType){ .propertyFlags = VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, .heapIndex = 1 };
    m->memoryTypes[1] = (VkMemoryType){ .propertyFlags = 0, .heapIndex = 0 };
}
void vkGetPhysicalDeviceQueueFamilyProperties(VkPhysicalDevice d, uint32_t *n, VkQueueFamilyProperties *q) {
    (void)d;
    if (!q) { *n = 1; return; }
    *n = 1;
    q[0].queueFlags = VK_QUEUE_COMPUTE_BIT;
}
VkResult vkEnumeratePhysicalDevices(VkInstance i, uint32_t *n, VkPhysicalDevice *d) {
    (void)i;
    if (!d) { *n = 2; return VK_SUCCESS; }
    *n = 2; d[0] = pd(0); d[1] = pd(1);
    return VK_SUCCESS;
}
VkResult vkCreateDevice(VkPhysicalDevice pdev, const VkDeviceCreateInfo *ci, const void *a, VkDevice *out) {
    (void)pdev; (void)a;
    FILE *f = vlog();
    uint32_t ngrp = 0; const void *gnext = NULL;
    for (const void *n = ci->pNext; n; ) {
        VkStructureType st = *(const VkStructureType *)n;
        if (st == VK_STRUCTURE_TYPE_DEVICE_GROUP_DEVICE_CREATE_INFO) {
            const VkDeviceGroupDeviceCreateInfo *g = (const VkDeviceGroupDeviceCreateInfo *)n;
            gnext = n; ngrp = g->physicalDeviceCount;
        }
        n = ((const struct { VkStructureType st; const void *next; } *)n)->next;
    }
    if (f) { fprintf(f, "CALL vkCreateDevice group_pNext=%s group_device_count=%u queueCreateInfoCount=%u enabledExtensionCount=%u\n",
        gnext ? "present" : "absent", ngrp, ci->queueCreateInfoCount, ci->enabledExtensionCount); fclose(f); }
    *out = (VkDevice)(uintptr_t)0x2;
    return VK_SUCCESS;
}
void vkGetDeviceGroupPeerMemoryFeatures(VkDevice d, uint32_t heap, uint32_t local, uint32_t remote, VkPeerMemoryFeatureFlags *fl) {
    (void)d;
    FILE *f = vlog();
    if (f) { fprintf(f, "CALL vkGetDeviceGroupPeerMemoryFeatures heap=%u local=%u remote=%u\n", heap, local, remote); fclose(f); }
    const char *e = getenv("V2E_STUB_PEER_FEATURES");
    *fl = e ? (VkPeerMemoryFeatureFlags)strtoul(e, NULL, 0)
            : (VK_PEER_MEMORY_FEATURE_COPY_SRC_BIT | VK_PEER_MEMORY_FEATURE_COPY_DST_BIT);
}
void vkGetPhysicalDeviceExternalBufferProperties(VkPhysicalDevice d, const VkPhysicalDeviceExternalBufferInfo *i, VkExternalBufferProperties *p) {
    (void)d;
    FILE *f = vlog();
    if (f) { fprintf(f, "CALL vkGetPhysicalDeviceExternalBufferProperties usage=0x%x handleType=0x%x\n", i->usage, i->handleType); fclose(f); }
    memset(p, 0, sizeof *p);
    const char *e = getenv("V2E_STUB_EXT_FEATURES");
    unsigned feat = e ? strtoul(e, NULL, 0) : 0;
    p->externalMemoryProperties.externalMemoryFeatures = feat;
    p->externalMemoryProperties.compatibleHandleTypes = i->handleType;
}
VkResult vkGetPhysicalDeviceImageFormatProperties2(VkPhysicalDevice d, const VkPhysicalDeviceImageFormatInfo2 *i, VkImageFormatProperties2 *p) {
    (void)d; (void)i;
    memset(p, 0, sizeof *p);
    return VK_SUCCESS;
}
VkResult vkEnumerateDeviceExtensionProperties(VkPhysicalDevice d, const char *l, uint32_t *n, VkExtensionProperties *p) {
    (void)d; (void)l;
    if (p) {
        *n = 1; memset(p, 0, sizeof *p);
        strcpy(p[0].extensionName, "VK_KHR_external_memory_fd");
    } else *n = 1;
    return VK_SUCCESS;
}
