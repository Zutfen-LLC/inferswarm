
#define _POSIX_C_SOURCE 199309L
#include <vulkan/vulkan.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>

/* ---------- fail-closed helpers ---------- */

static char g_stage[64] = "init";
static char g_detail[512] = "";

#define STAGE(s) do { snprintf(g_stage, sizeof g_stage, "%s", s); } while (0)
#define CK(x, stage, msg) do { VkResult r_ = (x); STAGE(stage); \
    if (r_ != VK_SUCCESS) { \
        snprintf(g_detail, sizeof g_detail, "%s: vkResult=%d", msg, (int)r_); \
        fprintf(stderr, "{\"event\":\"error\",\"stage\":\"%s\",\"vkResult\":%d,\"detail\":\"%s\"}\n", g_stage, (int)r_, g_detail); \
        exit(2); } } while (0)
#define CKC(x, stage, msg) do { if (!(x)) { STAGE(stage); \
        snprintf(g_detail, sizeof g_detail, "%s", msg); \
        fprintf(stderr, "{\"event\":\"error\",\"stage\":\"%s\",\"detail\":\"%s\"}\n", g_stage, g_detail); exit(2); } } while (0)

static uint32_t pattern_dword(uint64_t i, uint32_t seed) {
    /* deterministic position-dependent pattern (uint32 wraparound) */
    return (uint32_t)(0x9E3779B1u * (uint32_t)i + seed);
}

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

/* ---------- device identity ---------- */

typedef struct {
    VkPhysicalDevice pd;
    uint8_t uuid[16];
    char bdf[32];
    char name[256];
    uint32_t api_version;
} DevId;

/* RADV encodes the BDF in the deviceUUID: 4 zero bytes, bus, device,
 * then zeros. Derived here and CORROBORATED against the expected BDF
 * from the fresh mapping; a mismatch selects nothing (fail closed). */
static int bdf_from_uuid(const uint8_t uuid[16], char *out, size_t n) {
    if (uuid[0] || uuid[1] || uuid[2] || uuid[3]) return 0;
    if (uuid[6] || uuid[7] || uuid[8] || uuid[9] || uuid[10] || uuid[11] ||
        uuid[12] || uuid[13] || uuid[14] || uuid[15]) return 0;
    snprintf(out, n, "0000:%02x:%02x.0", uuid[4], uuid[5]);
    return 1;
}

static void enumerate_devices(VkInstance inst, DevId *out, uint32_t *count,
                              uint32_t max) {
    uint32_t n = 0;
    CK(vkEnumeratePhysicalDevices(inst, &n, NULL), "enumerate", "count");
    CKC(n >= 1, "enumerate", "no physical devices");
    VkPhysicalDevice *pds = calloc(n ? n : 1, sizeof(VkPhysicalDevice));
    CK(vkEnumeratePhysicalDevices(inst, &n, pds), "enumerate", "devices");
    uint32_t k = 0;
    for (uint32_t i = 0; i < n && k < max; i++) {
        VkPhysicalDeviceProperties2 p2;
        memset(&p2, 0, sizeof p2);
        VkPhysicalDeviceIDProperties idp;
        memset(&idp, 0, sizeof idp);
        idp.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES;
        p2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
        p2.pNext = &idp;
        vkGetPhysicalDeviceProperties2(pds[i], &p2);
        DevId d;
        memset(&d, 0, sizeof d);
        d.pd = pds[i];
        memcpy(d.uuid, idp.deviceUUID, 16);
        snprintf(d.name, sizeof d.name, "%s", p2.properties.deviceName);
        d.api_version = p2.properties.apiVersion;
        if (!bdf_from_uuid(d.uuid, d.bdf, sizeof d.bdf)) {
            /* not a RADV-style UUID; record with empty bdf — never
             * selectable */
            d.bdf[0] = 0;
        }
        out[k++] = d;
    }
    free(pds);
    *count = k;
}

static int find_by_bdf(const DevId *devs, uint32_t count, const char *bdf) {
    for (uint32_t i = 0; i < count; i++)
        if (devs[i].bdf[0] && strcmp(devs[i].bdf, bdf) == 0) return (int)i;
    return -1;
}

/* ---------- one logical device per physical device ---------- */

typedef struct {
    VkDevice dev;
    uint32_t queue_family;
    VkQueue queue;
    const DevId *id;
} Logical;

static void open_logical(const DevId *id, int dma_buf_mode, Logical *out) {
    uint32_t qfc = 0;
    VkQueueFamilyProperties qf[8];
    vkGetPhysicalDeviceQueueFamilyProperties(id->pd, &qfc, NULL);
    if (qfc > 8) qfc = 8;
    vkGetPhysicalDeviceQueueFamilyProperties(id->pd, &qfc, qf);
    uint32_t pick = UINT32_MAX;
    for (uint32_t i = 0; i < qfc; i++) {
        if ((qf[i].queueFlags & (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT)) ||
            (qf[i].queueFlags & VK_QUEUE_TRANSFER_BIT)) { pick = i; break; }
    }
    CKC(pick != UINT32_MAX, "device_source", "no usable queue family");

    float prio = 1.0f;
    VkDeviceQueueCreateInfo q;
    memset(&q, 0, sizeof q);
    q.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    q.queueFamilyIndex = pick;
    q.queueCount = 1;
    q.pQueuePriorities = &prio;

    const char *exts[2];
    uint32_t next_ext = 0;
    exts[next_ext++] = "VK_KHR_external_memory_fd";
    if (dma_buf_mode) exts[next_ext++] = "VK_EXT_external_memory_dma_buf";

    VkDeviceCreateInfo ci;
    memset(&ci, 0, sizeof ci);
    ci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    ci.queueCreateInfoCount = 1;
    ci.pQueueCreateInfos = &q;
    ci.enabledExtensionCount = next_ext;
    ci.ppEnabledExtensionNames = exts;
    /* NO device-group chaining: this logical device is created from
     * exactly one physical device; there is no device-zero ambiguity. */
    CK(vkCreateDevice(id->pd, &ci, NULL, &out->dev), "device_source",
       "vkCreateDevice");
    vkGetDeviceQueue(out->dev, pick, 0, &out->queue);
    out->queue_family = pick;
    out->id = id;
}

/* ---------- buffer + memory helpers ---------- */

typedef struct {
    VkBuffer buf;
    VkDeviceMemory mem;
    VkDeviceSize size;
} Buf;

static void make_export_buffer(Logical *lg, VkDeviceSize size,
                               VkExternalMemoryHandleTypeFlagBits ht,
                               Buf *out) {
    VkExternalMemoryBufferCreateInfo eb;
    memset(&eb, 0, sizeof eb);
    eb.sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO;
    eb.handleTypes = ht;
    VkBufferCreateInfo bi;
    memset(&bi, 0, sizeof bi);
    bi.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bi.size = size;
    bi.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
    bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    bi.pNext = &eb;
    CK(vkCreateBuffer(lg->dev, &bi, NULL, &out->buf), "buffer_source",
       "vkCreateBuffer(source exportable)");
    VkMemoryRequirements mr;
    vkGetBufferMemoryRequirements(lg->dev, out->buf, &mr);
    VkPhysicalDeviceMemoryProperties mp;
    vkGetPhysicalDeviceMemoryProperties(lg->id->pd, &mp);
    int32_t type = -1;
    for (uint32_t i = 0; i < mp.memoryTypeCount; i++) {
        if (!(mr.memoryTypeBits & (1u << i))) continue;
        if (mp.memoryTypes[i].propertyFlags &
            VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT) { type = (int32_t)i; break; }
    }
    CKC(type >= 0, "memory_source_export",
        "no device-local memory type for source buffer");
    VkExportMemoryAllocateInfo ex;
    memset(&ex, 0, sizeof ex);
    ex.sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO;
    ex.handleTypes = ht;
    VkMemoryAllocateInfo ma;
    memset(&ma, 0, sizeof ma);
    ma.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    ma.allocationSize = mr.size;
    ma.memoryTypeIndex = (uint32_t)type;
    ma.pNext = &ex;
    CK(vkAllocateMemory(lg->dev, &ma, NULL, &out->mem),
       "memory_source_export", "vkAllocateMemory(export)");
    CK(vkBindBufferMemory(lg->dev, out->buf, out->mem, 0),
       "memory_source_export", "vkBindBufferMemory(source)");
    out->size = size;
}

static void make_import_view(Logical *lg, int fd,
                             VkExternalMemoryHandleTypeFlagBits ht,
                             VkDeviceSize size, Buf *out,
                             int32_t *chosen_type,
                             VkExternalMemoryHandleTypeFlags *compat_out,
                             int *props_query_mode) {
    /* Memory-type compatibility for the import.
     *
     * vkGetMemoryFdPropertiesKHR is the authoritative fd query, but
     * the installed Mesa implements it ONLY for DMA_BUF: for
     * OPAQUE_FD it returns VK_ERROR_INVALID_EXTERNAL_HANDLE even on
     * the exporting device itself (physically observed on this stack;
     * retained in the attempt-1 supersession record). Per the Vulkan
     * spec the query is OPTIONAL: for opaque_fd the destination
     * buffer is created WITH VkExternalMemoryBufferCreateInfo chained,
     * so its own memoryRequirements.memoryTypeBits already reflects
     * importability of that handle type, and the import itself is
     * validated by vkAllocateMemory (checked). The query outcome is
     * retained either way; dma_buf REQUIRES a successful query. */
    PFN_vkGetMemoryFdPropertiesKHR pGetProps =
        (PFN_vkGetMemoryFdPropertiesKHR)vkGetDeviceProcAddr(
            lg->dev, "vkGetMemoryFdPropertiesKHR");
    CKC(pGetProps != NULL, "fd_import_properties",
        "vkGetMemoryFdPropertiesKHR not exposed");
    VkMemoryFdPropertiesKHR fp;
    memset(&fp, 0, sizeof fp);
    fp.sType = VK_STRUCTURE_TYPE_MEMORY_FD_PROPERTIES_KHR;
    VkResult r = pGetProps(lg->dev, ht, fd, &fp);
    int query_supported = (r == VK_SUCCESS);
    if (!query_supported && ht == VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT) {
        STAGE("fd_import_properties");
        fprintf(stderr, "{\"event\":\"error\",\"stage\":\"fd_import_properties\",\"vkResult\":%d,\"detail\":\"vkGetMemoryFdPropertiesKHR rejected the fd for the dma_buf handle type (query is required for dma_buf)\"}\n", (int)r);
        exit(2);
    }
    if (props_query_mode)
        *props_query_mode = query_supported ? 1 : 0;
    if (compat_out) *compat_out = query_supported ? fp.memoryTypeBits : 0xFFFFFFFFu;

    VkExternalMemoryBufferCreateInfo eb;
    memset(&eb, 0, sizeof eb);
    eb.sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO;
    eb.handleTypes = ht;
    VkBufferCreateInfo bi;
    memset(&bi, 0, sizeof bi);
    bi.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bi.size = size;
    bi.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
    bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    bi.pNext = &eb;
    CK(vkCreateBuffer(lg->dev, &bi, NULL, &out->buf), "buffer_dest_view",
       "vkCreateBuffer(destination import view)");
    VkMemoryRequirements mr;
    vkGetBufferMemoryRequirements(lg->dev, out->buf, &mr);
    uint32_t usable = query_supported
        ? (mr.memoryTypeBits & fp.memoryTypeBits)
        : mr.memoryTypeBits;  /* import-chained buffer requirements */
    CKC(usable != 0, "memory_dest_import",
        "empty memory-type intersection (buffer requirements & import"
        " properties) for the destination import");
    VkPhysicalDeviceMemoryProperties mp;
    vkGetPhysicalDeviceMemoryProperties(lg->id->pd, &mp);
    int32_t type = -1;
    for (uint32_t i = 0; i < 32; i++) {
        if (!(usable & (1u << i))) continue;
        type = (int32_t)i;  /* prefer device-local if present */
        if (mp.memoryTypes[i].propertyFlags &
            VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT) break;
    }
    CKC(type >= 0, "memory_dest_import", "no compatible memory type index");
    VkImportMemoryFdInfoKHR imp;
    memset(&imp, 0, sizeof imp);
    imp.sType = VK_STRUCTURE_TYPE_IMPORT_MEMORY_FD_INFO_KHR;
    imp.handleType = ht;
    imp.fd = fd;
    VkMemoryAllocateInfo ma;
    memset(&ma, 0, sizeof ma);
    ma.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    ma.allocationSize = mr.size;
    ma.memoryTypeIndex = (uint32_t)type;
    ma.pNext = &imp;
    CK(vkAllocateMemory(lg->dev, &ma, NULL, &out->mem),
       "memory_dest_import", "vkAllocateMemory(import)");
    /* fd ownership: opaque_fd transfers to the driver on success;
     * dma_buf is NOT consumed — the caller closes it after import. */
    CK(vkBindBufferMemory(lg->dev, out->buf, out->mem, 0),
       "memory_dest_import", "vkBindBufferMemory(import view)");
    if (chosen_type) *chosen_type = type;
    out->size = size;
}

static void make_local_buffer(Logical *lg, VkDeviceSize size,
                              VkBufferUsageFlags usage, int host_visible,
                              Buf *out) {
    VkBufferCreateInfo bi;
    memset(&bi, 0, sizeof bi);
    bi.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bi.size = size;
    bi.usage = usage;
    bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    CK(vkCreateBuffer(lg->dev, &bi, NULL, &out->buf), "buffer_dest_local",
       "vkCreateBuffer");
    VkMemoryRequirements mr;
    vkGetBufferMemoryRequirements(lg->dev, out->buf, &mr);
    VkPhysicalDeviceMemoryProperties mp;
    vkGetPhysicalDeviceMemoryProperties(lg->id->pd, &mp);
    int32_t type = -1;
    for (uint32_t i = 0; i < mp.memoryTypeCount; i++) {
        if (!(mr.memoryTypeBits & (1u << i))) continue;
        VkFlags want = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                       VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        if (host_visible) {
            if ((mp.memoryTypes[i].propertyFlags & want) == want)
                { type = (int32_t)i; break; }
        } else if (mp.memoryTypes[i].propertyFlags &
                   VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT) {
            type = (int32_t)i; break;
        }
    }
    CKC(type >= 0, "buffer_dest_local", "no suitable memory type");
    VkMemoryAllocateInfo ma;
    memset(&ma, 0, sizeof ma);
    ma.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    ma.allocationSize = mr.size;
    ma.memoryTypeIndex = (uint32_t)type;
    CK(vkAllocateMemory(lg->dev, &ma, NULL, &out->mem), "buffer_dest_local",
       "vkAllocateMemory");
    CK(vkBindBufferMemory(lg->dev, out->buf, out->mem, 0),
       "buffer_dest_local", "vkBindBufferMemory");
    out->size = size;
}

/* ---------- command recording + fence-ordered submission ---------- */

static void record_copy(Logical *lg, VkCommandPool pool, VkBuffer src,
                        VkBuffer dst, VkDeviceSize size, VkFence fence) {
    VkCommandBufferAllocateInfo ai;
    memset(&ai, 0, sizeof ai);
    ai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    ai.commandPool = pool;
    ai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    ai.commandBufferCount = 1;
    VkCommandBuffer cb;
    CK(vkAllocateCommandBuffers(lg->dev, &ai, &cb), "copy_dest",
       "vkAllocateCommandBuffers");
    VkCommandBufferBeginInfo bi;
    memset(&bi, 0, sizeof bi);
    bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    CK(vkBeginCommandBuffer(cb, &bi), "copy_dest", "vkBeginCommandBuffer");
    VkBufferCopy reg;
    memset(&reg, 0, sizeof reg);
    reg.size = size;
    vkCmdCopyBuffer(cb, src, dst, 1, &reg);
    CK(vkEndCommandBuffer(cb), "copy_dest", "vkEndCommandBuffer");
    VkSubmitInfo si;
    memset(&si, 0, sizeof si);
    si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    si.commandBufferCount = 1;
    si.pCommandBuffers = &cb;
    /* submitted on the OWNING logical device's queue: the physical
     * execution device is lg->id (UUID+BDF retained per rep). */
    CK(vkQueueSubmit(lg->queue, 1, &si, fence), "copy_dest",
       "vkQueueSubmit");
    CK(vkWaitForFences(lg->dev, 1, &fence, VK_TRUE, UINT64_MAX),
       "copy_dest", "vkWaitForFences");
    vkFreeCommandBuffers(lg->dev, pool, 1, &cb);
}

static void make_pool_fence(Logical *lg, VkCommandPool *pool, VkFence *fence) {
    VkCommandPoolCreateInfo pi;
    memset(&pi, 0, sizeof pi);
    pi.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    pi.queueFamilyIndex = lg->queue_family;
    CK(vkCreateCommandPool(lg->dev, &pi, NULL, pool), "cmdpool_dest",
       "vkCreateCommandPool");
    VkFenceCreateInfo fi;
    memset(&fi, 0, sizeof fi);
    fi.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    CK(vkCreateFence(lg->dev, &fi, NULL, fence), "cmdpool_dest",
       "vkCreateFence");
}

static void reset_fence(Logical *lg, VkFence fence) {
    CK(vkResetFences(lg->dev, 1, &fence), "copy_dest", "vkResetFences");
}

/* ---------- instance ---------- */

static VkInstance make_instance(void) {
    VkApplicationInfo app;
    memset(&app, 0, sizeof app);
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.pApplicationName = "issue230-v2f-transfer";
    app.applicationVersion = 1;
    app.apiVersion = VK_MAKE_VERSION(1, 1, 0);
    VkInstanceCreateInfo ci;
    memset(&ci, 0, sizeof ci);
    ci.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    ci.pApplicationInfo = &app;
    VkInstance inst;
    CK(vkCreateInstance(&ci, NULL, &inst), "instance", "vkCreateInstance");
    return inst;
}

/* ===================================================================== */
/* identity subcommand: enumerate + UUID->BDF, no allocations beyond the */
/* instance; read-only.                                                  */
/* ===================================================================== */

static int identity_main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: identity <bdf_a> <bdf_b>\n");
        return 2;
    }
    VkInstance inst = make_instance();
    DevId devs[8];
    uint32_t count = 0;
    enumerate_devices(inst, devs, &count, 8);
    printf("{\"event\":\"identity\",\"devices\":[");
    for (uint32_t i = 0; i < count; i++) {
        char uuid_hex[33];
        for (int b = 0; b < 16; b++)
            snprintf(uuid_hex + b * 2, 3, "%02x", devs[i].uuid[b]);
        printf("%s{\"uuid\":\"%s\",\"bdf\":\"%s\",\"name\":\"%s\"}",
               i ? "," : "", uuid_hex,
               devs[i].bdf[0] ? devs[i].bdf : "", devs[i].name);
    }
    printf("],\"expected\":{\"a\":\"%s\",\"b\":\"%s\"}}\n", argv[2], argv[3]);
    int ia = find_by_bdf(devs, count, argv[2]);
    int ib = find_by_bdf(devs, count, argv[3]);
    if (ia < 0 || ib < 0 || ia == ib) {
        fprintf(stderr, "{\"event\":\"error\",\"stage\":\"select_source\","
                "\"detail\":\"expected BDFs not both present as distinct "
                "UUID-bound devices\"}\n");
        return 3;
    }
    vkDestroyInstance(inst, NULL);
    return 0;
}

/* ===================================================================== */
/* transfer arm: source fill (setup) -> export/import -> dest-side copy  */
/* (THE measured inter-die transfer) -> readback verify.                 */
/* ===================================================================== */

static int transfer_main(int argc, char **argv) {
    if (argc != 10) {
        fprintf(stderr, "usage: transfer <mechanism> <direction> "
                "<bdf_src> <bdf_dst> <size> <reps> <warmups> <seed>\n");
        return 2;
    }
    const char *mechanism = argv[2];
    const char *direction = argv[3];
    const char *bdf_src = argv[4];
    const char *bdf_dst = argv[5];
    uint64_t size = strtoull(argv[6], NULL, 10);
    int reps = atoi(argv[7]);
    int warmups = atoi(argv[8]);
    uint32_t seed0 = (uint32_t)strtoul(argv[9], NULL, 10);
    int dma = strcmp(mechanism, "dma_buf") == 0;
    VkExternalMemoryHandleTypeFlagBits ht = dma
        ? VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT
        : VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;

    VkInstance inst = make_instance();
    DevId devs[8];
    uint32_t count = 0;
    enumerate_devices(inst, devs, &count, 8);
    int isrc = find_by_bdf(devs, count, bdf_src);
    int idst = find_by_bdf(devs, count, bdf_dst);
    STAGE("select_source");
    if (isrc < 0 || idst < 0 || isrc == idst) {
        fprintf(stderr, "{\"event\":\"error\",\"stage\":\"select_source\","
                "\"detail\":\"source/dest BDFs not distinct UUID-bound "
                "devices\"}\n");
        return 3;
    }

    Logical lg_src, lg_dst;
    memset(&lg_src, 0, sizeof lg_src);
    memset(&lg_dst, 0, sizeof lg_dst);
    open_logical(&devs[isrc], dma, &lg_src);
    open_logical(&devs[idst], dma, &lg_dst);

    /* source: exportable device-local buffer + host-visible staging */
    Buf s_export, s_staging;
    make_export_buffer(&lg_src, size, ht, &s_export);
    make_local_buffer(&lg_src, size, VK_BUFFER_USAGE_TRANSFER_DST_BIT, 1,
                      &s_staging);
    VkCommandPool pool_src;
    VkFence fence_src;
    make_pool_fence(&lg_src, &pool_src, &fence_src);

    /* export fd once per arm (allocation identity retained) */
    STAGE("fd_export");
    PFN_vkGetMemoryFdKHR pGetFd = (PFN_vkGetMemoryFdKHR)vkGetDeviceProcAddr(
        lg_src.dev, "vkGetMemoryFdKHR");
    CKC(pGetFd != NULL, "fd_export", "vkGetMemoryFdKHR not exposed");
    int fd = -1;
    {
        VkMemoryGetFdInfoKHR gi;
        memset(&gi, 0, sizeof gi);
        gi.sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR;
        gi.memory = s_export.mem;
        gi.handleType = ht;
        VkResult r = pGetFd(lg_src.dev, &gi, &fd);
        if (r != VK_SUCCESS) {
            fprintf(stderr, "{\"event\":\"error\",\"stage\":\"fd_export\",\"vkResult\":%d,\"detail\":\"export of source memory failed\"}\n", (int)r);
            return 2;
        }
    }
    CKC(fd >= 0, "fd_export", "export returned invalid fd");

    /* destination: import view + local buffer + staging */
    Buf d_view, d_local, d_staging;
    int32_t chosen_type = -1;
    VkExternalMemoryHandleTypeFlags compat = 0;
    int props_query_supported = -1;
    make_import_view(&lg_dst, fd, ht, size, &d_view, &chosen_type,
                     &compat, &props_query_supported);
    /* fd lifecycle: opaque_fd consumed by driver on successful import;
     * dma_buf kept by caller, closed once below. */
    int fd_consumed = !dma;
    if (!fd_consumed) { close(fd); fd = -1; }

    make_local_buffer(&lg_dst, size, VK_BUFFER_USAGE_TRANSFER_DST_BIT, 0,
                      &d_local);
    make_local_buffer(&lg_dst, size,
                      VK_BUFFER_USAGE_TRANSFER_DST_BIT |
                      VK_BUFFER_USAGE_TRANSFER_SRC_BIT, 1, &d_staging);
    VkCommandPool pool_dst;
    VkFence fence_dst;
    make_pool_fence(&lg_dst, &pool_dst, &fence_dst);

    /* fill the source buffer through host-visible staging (setup) */
    void *s_map = NULL;
    CK(vkMapMemory(lg_src.dev, s_staging.mem, 0, size, 0, &s_map),
       "fill_source", "vkMapMemory(source staging)");
    uint32_t *words = (uint32_t *)s_map;
    uint64_t ndword = size / 4;

    printf("{\"event\":\"arm\",\"mechanism\":\"%s\",\"direction\":\"%s\","
           "\"size\":%llu,\"reps\":%d,\"warmups\":%d,"
           "\"source\":{\"bdf\":\"%s\",\"queue_family\":%u},"
           "\"destination\":{\"bdf\":\"%s\",\"queue_family\":%u,"
           "\"import_memory_type\":%d,\"import_compatible_bits\":%u,"
           "\"fd_props_query_supported\":%d},"
           "\"handle_type_bit\":%u,\"fd_lifecycle\":\"%s\"}\n",
           mechanism, direction, (unsigned long long)size, reps, warmups,
           devs[isrc].bdf, lg_src.queue_family, devs[idst].bdf,
           lg_dst.queue_family, (int)chosen_type, (unsigned)compat,
           props_query_supported, (unsigned)ht, fd_consumed
               ? "opaque_fd: consumed by driver on import"
               : "dma_buf: caller closes after import");

    for (int rep = -warmups; rep < reps; rep++) {
        int measured = rep >= 0;
        uint32_t seed = seed0 + (uint32_t)(rep + warmups) + 1u;
        /* host writes the pattern into source staging */
        for (uint64_t i = 0; i < ndword; i++)
            words[i] = pattern_dword(i, seed);
        reset_fence(&lg_src, fence_src);
        record_copy(&lg_src, pool_src, s_staging.buf, s_export.buf, size,
                    fence_src);   /* source-side fill: src-die-local setup */

        /* THE measured inter-die transfer: destination-device copy from
         * the imported view of the source allocation. */
        reset_fence(&lg_dst, fence_dst);
        double t0 = now_sec();
        record_copy(&lg_dst, pool_dst, d_view.buf, d_local.buf, size,
                    fence_dst);
        double t1 = now_sec();

        /* verification: dest-local -> dest staging -> host compare */
        reset_fence(&lg_dst, fence_dst);
        record_copy(&lg_dst, pool_dst, d_local.buf, d_staging.buf, size,
                    fence_dst);
        void *d_map = NULL;
        CK(vkMapMemory(lg_dst.dev, d_staging.mem, 0, size, 0, &d_map),
           "verify_readback", "vkMapMemory(dest staging)");
        uint32_t *dwords = (uint32_t *)d_map;
        uint64_t bad = 0;
        uint64_t first_bad = 0;
        for (uint64_t i = 0; i < ndword; i++) {
            if (dwords[i] != pattern_dword(i, seed)) {
                if (bad == 0) first_bad = i;
                bad++;
            }
        }
        vkUnmapMemory(lg_dst.dev, d_staging.mem);
        if (bad > 0) {
            /* correctness mismatch: immediate-stop condition; no
             * further rep runs. */
            printf("{\"event\":\"rep\",\"rep\":%d,\"measured\":%d,"
                   "\"seed\":%u,\"ok\":false,\"mismatch_dwords\":%llu,"
                   "\"first_mismatch_dword\":%llu}\n",
                   rep, measured, seed, (unsigned long long)bad,
                   (unsigned long long)first_bad);
            fflush(stdout);
            fprintf(stderr, "{\"event\":\"error\",\"stage\":"
                    "\"verify_readback\",\"detail\":\"correctness "
                    "mismatch: %llu of %llu dwords differ\"}\n",
                    (unsigned long long)bad, (unsigned long long)ndword);
            return 4;
        }
        if (measured) {
            printf("{\"event\":\"rep\",\"rep\":%d,\"measured\":1,"
                   "\"seed\":%u,\"ok\":true,\"elapsed_ns\":%lld}\n",
                   rep, seed,
                   (long long)((t1 - t0) * 1e9));
            fflush(stdout);
        } else {
            printf("{\"event\":\"rep\",\"rep\":%d,\"measured\":0,"
                   "\"seed\":%u,\"ok\":true}\n", rep, seed);
            fflush(stdout);
        }
    }

    printf("{\"event\":\"summary\",\"mechanism\":\"%s\",\"direction\":\"%s\","
           "\"size\":%llu,\"ok\":true}\n", mechanism, direction,
           (unsigned long long)size);

    vkUnmapMemory(lg_src.dev, s_staging.mem);
    vkDestroyCommandPool(lg_dst.dev, pool_dst, NULL);
    vkDestroyFence(lg_dst.dev, fence_dst, NULL);
    vkDestroyCommandPool(lg_src.dev, pool_src, NULL);
    vkDestroyFence(lg_src.dev, fence_src, NULL);
    vkDestroyBuffer(lg_dst.dev, d_view.buf, NULL);
    vkFreeMemory(lg_dst.dev, d_view.mem, NULL);
    vkDestroyBuffer(lg_dst.dev, d_local.buf, NULL);
    vkFreeMemory(lg_dst.dev, d_local.mem, NULL);
    vkDestroyBuffer(lg_dst.dev, d_staging.buf, NULL);
    vkFreeMemory(lg_dst.dev, d_staging.mem, NULL);
    vkDestroyBuffer(lg_src.dev, s_export.buf, NULL);
    vkFreeMemory(lg_src.dev, s_export.mem, NULL);
    vkDestroyBuffer(lg_src.dev, s_staging.buf, NULL);
    vkFreeMemory(lg_src.dev, s_staging.mem, NULL);
    vkDestroyDevice(lg_dst.dev, NULL);
    vkDestroyDevice(lg_src.dev, NULL);
    vkDestroyInstance(inst, NULL);
    return 0;
}

/* ===================================================================== */
/* controls                                                              */
/* ===================================================================== */

/* same-die copy control: identical buffers/copies, source and
 * destination BOTH on one die — the intra-die reference. */
static int generic_copy_main(const char *kind, int argc, char **argv);

static int samedie_main(int argc, char **argv) {
    return generic_copy_main("samedie", argc, argv);
}

/* host-staged control: src D2H (fill from host-visible staging is H2D
 * on src; then read the SRC device-local buffer down to host staging),
 * host memcpy, then H2D into dst device-local via dst staging, then
 * verify. The measured window spans the full host-mediated chain. */
static int hoststaged_main(int argc, char **argv) {
    return generic_copy_main("hoststaged", argc, argv);
}

/* fresh link ceiling control: measure H2D (staging->device) and D2H
 * (device->staging) separately on ONE die, fresh allocations. */
static int linkio_main(int argc, char **argv) {
    return generic_copy_main("linkio", argc, argv);
}

static int generic_copy_main(const char *kind, int argc, char **argv) {
    /* argv: <prog> <kind-arg...>; layouts differ per kind; normalized
     * here: <bdf_a> <bdf_b_or_same> <size> <reps> <warmups> <seed> */
    const char *bdf_a, *bdf_b;
    int argi = 2;
    if (strcmp(kind, "samedie") == 0 || strcmp(kind, "linkio") == 0) {
        if (argc != 7) {
            fprintf(stderr, "usage: %s <bdf> <size> <reps> <warmups> "
                    "<seed>\n", kind);
            return 2;
        }
        bdf_a = argv[argi++];
        bdf_b = bdf_a;
    } else {
        if (argc != 8) {
            fprintf(stderr, "usage: %s <bdf_src> <bdf_dst> <size> <reps> "
                    "<warmups> <seed>\n", kind);
            return 2;
        }
        bdf_a = argv[argi++];
        bdf_b = argv[argi++];
    }
    uint64_t size = strtoull(argv[argi++], NULL, 10);
    int reps = atoi(argv[argi++]);
    int warmups = atoi(argv[argi++]);
    uint32_t seed0 = (uint32_t)strtoul(argv[argi++], NULL, 10);

    VkInstance inst = make_instance();
    DevId devs[8];
    uint32_t count = 0;
    enumerate_devices(inst, devs, &count, 8);
    int ia = find_by_bdf(devs, count, bdf_a);
    int ib = find_by_bdf(devs, count, bdf_b);
    STAGE("select_source");
    if (ia < 0 || ib < 0) {
        fprintf(stderr, "{\"event\":\"error\",\"stage\":\"select_source\","
                "\"detail\":\"control BDF not UUID-bound\"}\n");
        return 3;
    }
    if (strcmp(kind, "samedie") == 0 && ia != ib) {
        fprintf(stderr, "{\"event\":\"error\",\"stage\":\"select_source\","
                "\"detail\":\"samedie control must use one die\"}\n");
        return 3;
    }

    Logical lg_a, lg_b;
    memset(&lg_a, 0, sizeof lg_a);
    memset(&lg_b, 0, sizeof lg_b);
    open_logical(&devs[ia], 0, &lg_a);
    if (ib == ia) {
        lg_b = lg_a;
    } else {
        open_logical(&devs[ib], 0, &lg_b);
    }

    Buf a_dev, a_stg, b_dev, b_stg;
    make_local_buffer(&lg_a, size,
                      VK_BUFFER_USAGE_TRANSFER_DST_BIT |
                      VK_BUFFER_USAGE_TRANSFER_SRC_BIT, 0, &a_dev);
    make_local_buffer(&lg_a, size,
                      VK_BUFFER_USAGE_TRANSFER_DST_BIT |
                      VK_BUFFER_USAGE_TRANSFER_SRC_BIT, 1, &a_stg);
    make_local_buffer(&lg_b, size,
                      VK_BUFFER_USAGE_TRANSFER_DST_BIT |
                      VK_BUFFER_USAGE_TRANSFER_SRC_BIT, 0, &b_dev);
    make_local_buffer(&lg_b, size,
                      VK_BUFFER_USAGE_TRANSFER_DST_BIT |
                      VK_BUFFER_USAGE_TRANSFER_SRC_BIT, 1, &b_stg);
    VkCommandPool pool_a, pool_b;
    VkFence fence_a, fence_b;
    make_pool_fence(&lg_a, &pool_a, &fence_a);
    make_pool_fence(&lg_b, &pool_b, &fence_b);

    void *a_map = NULL, *b_map = NULL;
    CK(vkMapMemory(lg_a.dev, a_stg.mem, 0, size, 0, &a_map),
       "staging_source", "vkMapMemory(a staging)");
    CK(vkMapMemory(lg_b.dev, b_stg.mem, 0, size, 0, &b_map),
       "staging_dest", "vkMapMemory(b staging)");
    uint64_t ndword = size / 4;
    uint32_t *awords = (uint32_t *)a_map;
    uint32_t *bwords = (uint32_t *)b_map;

    printf("{\"event\":\"arm\",\"kind\":\"%s\",\"size\":%llu,\"reps\":%d,"
           "\"warmups\":%d,\"die_a\":\"%s\",\"die_b\":\"%s\"}\n",
           kind, (unsigned long long)size, reps, warmups,
           devs[ia].bdf, devs[ib].bdf);

    for (int rep = -warmups; rep < reps; rep++) {
        int measured = rep >= 0;
        uint32_t seed = seed0 + (uint32_t)(rep + warmups) + 1u;
        for (uint64_t i = 0; i < ndword; i++)
            awords[i] = pattern_dword(i, seed);
        double elapsed_ns = -1.0;
        int ok = 1;
        if (strcmp(kind, "samedie") == 0) {
            /* a_stg -> a_dev -> a_stg (all on one die), timed on the
             * device-local copy leg */
            reset_fence(&lg_a, fence_a);
            record_copy(&lg_a, pool_a, a_stg.buf, a_dev.buf, size, fence_a);
            reset_fence(&lg_a, fence_a);
            double t0 = now_sec();
            record_copy(&lg_a, pool_a, a_dev.buf, a_stg.buf, size, fence_a);
            double t1 = now_sec();
            elapsed_ns = (t1 - t0) * 1e9;
            ok = 1;
            for (uint64_t i = 0; i < ndword; i++)
                if (awords[i] != pattern_dword(i, seed)) { ok = 0; break; }
        } else if (strcmp(kind, "linkio") == 0) {
            /* H2D and D2H legs separately (fresh host-facing link
             * ceiling on this die) */
            reset_fence(&lg_a, fence_a);
            double t0 = now_sec();
            record_copy(&lg_a, pool_a, a_stg.buf, a_dev.buf, size, fence_a);
            double t1 = now_sec();
            reset_fence(&lg_a, fence_a);
            double t2 = now_sec();
            record_copy(&lg_a, pool_a, a_dev.buf, a_stg.buf, size, fence_a);
            double t3 = now_sec();
            elapsed_ns = (t3 - t2 + t1 - t0) * 1e9;  /* both legs summed */
            ok = 1;
            for (uint64_t i = 0; i < ndword; i++)
                if (awords[i] != pattern_dword(i, seed)) { ok = 0; break; }
            if (measured && ok) {
                printf("{\"event\":\"rep\",\"rep\":%d,\"measured\":1,"
                       "\"seed\":%u,\"ok\":true,"
                       "\"h2d_ns\":%lld,\"d2h_ns\":%lld,"
                       "\"elapsed_ns\":%lld}\n",
                       rep, seed, (long long)((t1 - t0) * 1e9),
                       (long long)((t3 - t2) * 1e9),
                       (long long)((t3 - t2 + t1 - t0) * 1e9));
                fflush(stdout);
                continue;
            }
        } else {  /* hoststaged */
            /* a_stg(host pattern) -> a_dev (H2D on A)
             * a_dev -> a_stg (D2H on A)          [measured window start]
             * host: bwords <- awords
             * b_stg -> b_dev (H2D on B)
             * b_dev -> b_stg (D2H on B, verify)  [measured window end] */
            reset_fence(&lg_a, fence_a);
            record_copy(&lg_a, pool_a, a_stg.buf, a_dev.buf, size, fence_a);
            double t0 = now_sec();
            reset_fence(&lg_a, fence_a);
            record_copy(&lg_a, pool_a, a_dev.buf, a_stg.buf, size, fence_a);
            memcpy(b_map, a_map, size);
            reset_fence(&lg_b, fence_b);
            record_copy(&lg_b, pool_b, b_stg.buf, b_dev.buf, size, fence_b);
            reset_fence(&lg_b, fence_b);
            record_copy(&lg_b, pool_b, b_dev.buf, b_stg.buf, size, fence_b);
            double t1 = now_sec();
            elapsed_ns = (t1 - t0) * 1e9;
            ok = 1;
            for (uint64_t i = 0; i < ndword; i++)
                if (bwords[i] != pattern_dword(i, seed)) { ok = 0; break; }
        }
        if (!ok) {
            fprintf(stderr, "{\"event\":\"error\",\"stage\":"
                    "\"verify_readback\",\"detail\":\"control %s "
                    "correctness mismatch\"}\n", kind);
            return 4;
        }
        if (measured) {
            printf("{\"event\":\"rep\",\"rep\":%d,\"measured\":1,"
                   "\"seed\":%u,\"ok\":true,\"elapsed_ns\":%.0f}\n",
                   rep, seed, elapsed_ns);
        } else {
            printf("{\"event\":\"rep\",\"rep\":%d,\"measured\":0,"
                   "\"seed\":%u,\"ok\":true}\n", rep, seed);
        }
        fflush(stdout);
    }
    printf("{\"event\":\"summary\",\"kind\":\"%s\",\"size\":%llu,"
           "\"ok\":true}\n", kind, (unsigned long long)size);

    vkUnmapMemory(lg_a.dev, a_stg.mem);
    if (ib != ia) {
        vkUnmapMemory(lg_b.dev, b_stg.mem);
        vkDestroyCommandPool(lg_b.dev, pool_b, NULL);
        vkDestroyFence(lg_b.dev, fence_b, NULL);
        vkDestroyBuffer(lg_b.dev, b_dev.buf, NULL);
        vkFreeMemory(lg_b.dev, b_dev.mem, NULL);
        vkDestroyBuffer(lg_b.dev, b_stg.buf, NULL);
        vkFreeMemory(lg_b.dev, b_stg.mem, NULL);
        vkDestroyDevice(lg_b.dev, NULL);
    } else {
        vkDestroyBuffer(lg_a.dev, b_dev.buf, NULL);
        vkFreeMemory(lg_a.dev, b_dev.mem, NULL);
        vkDestroyBuffer(lg_a.dev, b_stg.buf, NULL);
        vkFreeMemory(lg_a.dev, b_stg.mem, NULL);
        vkDestroyCommandPool(lg_a.dev, pool_b, NULL);
        vkDestroyFence(lg_a.dev, fence_b, NULL);
    }
    vkDestroyCommandPool(lg_a.dev, pool_a, NULL);
    vkDestroyFence(lg_a.dev, fence_a, NULL);
    vkDestroyBuffer(lg_a.dev, a_dev.buf, NULL);
    vkFreeMemory(lg_a.dev, a_dev.mem, NULL);
    vkDestroyBuffer(lg_a.dev, a_stg.buf, NULL);
    vkFreeMemory(lg_a.dev, a_stg.mem, NULL);
    vkDestroyDevice(lg_a.dev, NULL);
    vkDestroyInstance(inst, NULL);
    return 0;
}

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "identity") == 0)
        return identity_main(argc, argv);
    if (argc > 1 && strcmp(argv[1], "transfer") == 0)
        return transfer_main(argc, argv);
    if (argc > 1 && strcmp(argv[1], "samedie") == 0)
        return samedie_main(argc, argv);
    if (argc > 1 && strcmp(argv[1], "hoststaged") == 0)
        return hoststaged_main(argc, argv);
    if (argc > 1 && strcmp(argv[1], "linkio") == 0)
        return linkio_main(argc, argv);
    fprintf(stderr, "usage: %s identity|transfer|samedie|hoststaged|"
            "linkio ...\n", argv[0]);
    return 2;
}
