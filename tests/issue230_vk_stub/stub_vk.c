/* Recording Vulkan stub for #230 contract tests (see vulkan.h). */
#include "vulkan.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---- call recording ------------------------------------------------ */

static FILE *g_log = NULL;
static void ensure_log(void) {
    if (!g_log) g_log = fopen("stub-calls.log", "w");
}
#define REC(...) do { ensure_log(); fprintf(g_log, __VA_ARGS__); \
                      fflush(g_log); } while (0)

/* ---- fake objects --------------------------------------------------- */

struct VkInstance_T { int dummy; };
struct VkPhysicalDevice_T { uint8_t uuid[16]; char name[64]; };
struct VkDevice_T { VkPhysicalDevice pd; uint32_t n_ext; char exts[2][64]; };
struct VkQueue_T { int dummy; };
struct VkDeviceMemory_T { int id; int fd_exported; };
struct VkBuffer_T { int id; VkDeviceMemory mem; };
struct VkCommandPool_T { int id; };
struct VkCommandBuffer_T { int id; };
struct VkFence_T { int id; };

/* Two fake physical devices with RADV-style UUIDs encoding the BDFs
 * 0000:06:00.0 and 0000:09:00.0 (4 zero bytes, bus, dev, zeros). */
static VkPhysicalDevice make_pd(uint8_t bus, uint8_t dev) {
    VkPhysicalDevice pd = calloc(1, sizeof *pd);
    memset(pd->uuid, 0, 16);
    pd->uuid[4] = bus;
    pd->uuid[5] = dev;
    snprintf(pd->name, sizeof pd->name, "AMD Radeon Pro V340 (RADV VEGA10)");
    return pd;
}
static VkPhysicalDevice g_pds[2];
static int g_pds_init = 0;
static void init_pds(void) {
    if (g_pds_init) return;
    g_pds[0] = make_pd(0x06, 0x00);
    g_pds[1] = make_pd(0x09, 0x00);
    g_pds_init = 1;
}

/* host-mapped memory per device memory object (for vkMapMemory) */
#define NMEM 256
static unsigned char *g_mem[NMEM];
static int g_nmem = 0;
static int g_ids = 0;

/* fd bookkeeping: export hands out fd numbers 100+n; import accepts
 * only fds actually exported for the same handle type. */
static int g_exported_fd = -1;
static VkFlags g_exported_ht = 0;
static int g_import_calls = 0;

/* ---- instance ------------------------------------------------------- */

VkResult vkCreateInstance(const VkInstanceCreateInfo *ci,
                          const void *alloc, VkInstance *out) {
    REC("vkCreateInstance appInfo=%p apiVersion=0x%x extCount=%u\n",
        (void*)(ci ? ci->pApplicationInfo : NULL),
        ci && ci->pApplicationInfo ? ci->pApplicationInfo->apiVersion : 0,
        ci ? ci->enabledExtensionCount : 0);
    if (!ci || !ci->pApplicationInfo) return VK_ERROR_OUT_OF_HOST_MEMORY;
    *out = calloc(1, sizeof **out);
    return VK_SUCCESS;
}
void vkDestroyInstance(VkInstance i, const void *a) { REC("vkDestroyInstance\n"); }

VkResult vkEnumeratePhysicalDevices(VkInstance inst, uint32_t *n,
                                    VkPhysicalDevice *out) {
    init_pds();
    if (!out) { *n = 2; return VK_SUCCESS; }
    if (*n < 2) return VK_ERROR_OUT_OF_HOST_MEMORY;
    out[0] = g_pds[0]; out[1] = g_pds[1];
    REC("vkEnumeratePhysicalDevices -> 2\n");
    return VK_SUCCESS;
}

void vkGetPhysicalDeviceProperties2(VkPhysicalDevice pd,
                                    VkPhysicalDeviceProperties2 *props) {
    VkPhysicalDeviceIDProperties *idp =
        (VkPhysicalDeviceIDProperties *)props->pNext;
    if (idp && idp->sType == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES) {
        memcpy(idp->deviceUUID, pd->uuid, 16);
    }
    snprintf(props->properties.deviceName,
             sizeof props->properties.deviceName, "%s", pd->name);
    props->properties.apiVersion = VK_MAKE_VERSION(1, 4, 305);
}

typedef struct { VkDeviceSize size; uint32_t alignment; uint32_t memoryTypeBits; } MemoryReq;

void vkGetPhysicalDeviceMemoryProperties(VkPhysicalDevice pd,
                                         VkPhysicalDeviceMemoryProperties *mp) {
    mp->memoryTypeCount = 2;
    mp->memoryTypes[0].propertyFlags = VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT;
    mp->memoryTypes[0].heapIndex = 0;
    mp->memoryTypes[1].propertyFlags = VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT
        | VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT
        | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    mp->memoryTypes[1].heapIndex = 0;
    mp->memoryHeapCount = 1;
    mp->memoryHeaps[0].size = 8ull << 30;
    mp->memoryHeaps[0].flags = 1;
}

void vkGetPhysicalDeviceQueueFamilyProperties(VkPhysicalDevice pd,
                                              uint32_t *n,
                                              VkQueueFamilyProperties *qf) {
    if (!qf) { *n = 1; return; }
    memset(qf, 0, sizeof *qf * (*n < 1 ? 1 : *n));
    qf[0].queueFlags = VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT;
    qf[0].queueCount = 1;
}

VkResult vkCreateDevice(VkPhysicalDevice pd, const VkDeviceCreateInfo *ci,
                        const void *alloc, VkDevice *out) {
    VkDevice d = calloc(1, sizeof *d);
    d->pd = pd;
    d->n_ext = ci->enabledExtensionCount > 2 ? 2 : ci->enabledExtensionCount;
    for (uint32_t i = 0; i < d->n_ext && i < 2; i++)
        snprintf(d->exts[i], 64, "%s", ci->ppEnabledExtensionNames[i]);
    *out = d;
    for (uint32_t i = 0; i < d->n_ext; i++)
        REC("vkCreateDevice pd_uuid=%02x%02x ext[%u]=%s\n",
            pd->uuid[4], pd->uuid[5], i, d->exts[i]);
    return VK_SUCCESS;
}
void vkDestroyDevice(VkDevice d, const void *a) { REC("vkDestroyDevice\n"); }
void vkGetDeviceQueue(VkDevice d, uint32_t fam, uint32_t idx, VkQueue *q) {
    *q = calloc(1, sizeof **q);
}

VkResult vkCreateBuffer(VkDevice d, const VkBufferCreateInfo *ci,
                        const void *a, VkBuffer *out) {
    VkBuffer b = calloc(1, sizeof *b);
    b->id = g_ids++;
    b->mem = NULL;
    *out = b;
    REC("vkCreateBuffer size=%llu usage=0x%x extHandleTypes=0x%x\n",
        (unsigned long long)ci->size, ci->usage,
        ci->pNext ? ((VkExternalMemoryBufferCreateInfo *)ci->pNext)
                    ->handleTypes : 0);
    return VK_SUCCESS;
}
void vkDestroyBuffer(VkDevice d, VkBuffer b, const void *a) {}

void vkGetBufferMemoryRequirements(VkDevice d, VkBuffer b, void *out) {
    MemoryReq *r = out;
    r->size = 4096;
    r->alignment = 4096;
    r->memoryTypeBits = 0x3;  /* both types */
}

static void g_mem_alias_on_import(VkDeviceMemory m, int origin_id) {
    if (m->id < NMEM && origin_id >= 0 && origin_id < NMEM
        && g_mem[origin_id]) {
        g_mem[m->id] = g_mem[origin_id];
    }
}

VkResult vkAllocateMemory(VkDevice d, const VkMemoryAllocateInfo *ai,
                          const void *a, VkDeviceMemory *out) {
    VkDeviceMemory m = calloc(1, sizeof *m);
    m->id = g_ids++;
    const VkImportMemoryFdInfoKHR *imp =
        (const VkImportMemoryFdInfoKHR *)ai->pNext;
    if (imp && imp->sType == VK_STRUCTURE_TYPE_IMPORT_MEMORY_FD_INFO_KHR) {
        g_import_calls++;
        REC("vkAllocateMemory IMPORT fd=%d handleType=0x%x type=%u\n",
            imp->fd, imp->handleType, ai->memoryTypeIndex);
        if (g_exported_fd < 0 || imp->fd != g_exported_fd) {
            REC("IMPORT REJECTED fd mismatch\n");
            return VK_ERROR_INVALID_EXTERNAL_HANDLE;
        }
        if (imp->handleType != g_exported_ht) {
            REC("IMPORT REJECTED handle type mismatch\n");
            return VK_ERROR_INVALID_EXTERNAL_HANDLE;
        }
        /* the imported allocation ALIASES the exported memory's shadow
         * (what a real driver does via the fd) */
        g_mem_alias_on_import(m, g_exported_fd - 100);
    } else {
        const VkExportMemoryAllocateInfo *ex =
            (const VkExportMemoryAllocateInfo *)ai->pNext;
        if (ex && ex->sType ==
            VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO) {
            m->fd_exported = 1;
            REC("vkAllocateMemory EXPORT handleTypes=0x%x\n",
                ex->handleTypes);
        }
    }
    if (m->id < NMEM && !g_mem[m->id]) g_mem[m->id] = calloc(1, 64 << 20);
    *out = m;
    return VK_SUCCESS;
}
void vkFreeMemory(VkDevice d, VkDeviceMemory m, const void *a) {}

VkResult vkBindBufferMemory(VkDevice d, VkBuffer b, VkDeviceMemory m,
                            VkDeviceSize off) { b->mem = m; return VK_SUCCESS; }

VkResult vkMapMemory(VkDevice d, VkDeviceMemory m, VkDeviceSize o,
                     VkDeviceSize sz, VkFlags f, void **out) {
    *out = (m->id < NMEM && g_mem[m->id]) ? g_mem[m->id] + o : NULL;
    return *out ? VK_SUCCESS : VK_ERROR_OUT_OF_HOST_MEMORY;
}
void vkUnmapMemory(VkDevice d, VkDeviceMemory m) {}

VkResult vkCreateCommandPool(VkDevice d, const VkCommandPoolCreateInfo *ci,
                             const void *a, VkCommandPool *out) {
    *out = calloc(1, sizeof **out);
    return VK_SUCCESS;
}
void vkDestroyCommandPool(VkDevice d, VkCommandPool p, const void *a) {}

VkResult vkAllocateCommandBuffers(VkDevice d,
                                  const VkCommandBufferAllocateInfo *ai,
                                  VkCommandBuffer *out) {
    *out = calloc(1, sizeof **out);
    return VK_SUCCESS;
}
void vkFreeCommandBuffers(VkDevice d, VkCommandPool p, uint32_t n,
                          const VkCommandBuffer *bs) {}
VkResult vkBeginCommandBuffer(VkCommandBuffer b,
                              const VkCommandBufferBeginInfo *i) {
    return VK_SUCCESS;
}
VkResult vkEndCommandBuffer(VkCommandBuffer b) { return VK_SUCCESS; }

void vkCmdCopyBuffer(VkCommandBuffer cb, VkBuffer src, VkBuffer dst,
                     uint32_t n, const void *regions) {
    REC("vkCmdCopyBuffer src=%d dst=%d\n", src->id, dst->id);
    if (src->mem && dst->mem && g_mem[src->mem->id] && g_mem[dst->mem->id]) {
        memcpy(g_mem[dst->mem->id], g_mem[src->mem->id], 1 << 20);
    }
}

VkResult vkQueueSubmit(VkQueue q, uint32_t n, const VkSubmitInfo *si,
                       VkFence fence) {
    REC("vkQueueSubmit\n");
    return VK_SUCCESS;
}
VkResult vkWaitForFences(VkDevice d, uint32_t n, const VkFence *f,
                         VkBool32 all, uint64_t t) { return VK_SUCCESS; }
VkResult vkResetFences(VkDevice d, uint32_t n, const VkFence *f) {
    return VK_SUCCESS;
}
VkResult vkCreateFence(VkDevice d, const VkFenceCreateInfo *ci,
                       const void *a, VkFence *out) {
    *out = calloc(1, sizeof **out);
    return VK_SUCCESS;
}
void vkDestroyFence(VkDevice d, VkFence f, const void *a) {}

VkResult vkGetMemoryFdKHR(VkDevice d, const VkMemoryGetFdInfoKHR *gi,
                          int *fd) {
    REC("vkGetMemoryFdKHR handleType=0x%x\n", gi->handleType);
    if (!gi->memory || !gi->memory->fd_exported)
        return VK_ERROR_INVALID_EXTERNAL_HANDLE;
    g_exported_fd = 100 + gi->memory->id;
    g_exported_ht = gi->handleType;
    *fd = g_exported_fd;
    return VK_SUCCESS;
}

VkResult vkGetMemoryFdPropertiesKHR(VkDevice d, VkFlags ht, int fd,
                                    VkMemoryFdPropertiesKHR *out) {
    REC("vkGetMemoryFdPropertiesKHR ht=0x%x fd=%d\n", ht, fd);
    if (fd != g_exported_fd || (g_exported_ht && ht != g_exported_ht)) {
        REC("FDPROPS REJECTED\n");
        return VK_ERROR_INVALID_EXTERNAL_HANDLE;
    }
    out->memoryTypeBits = 0x3;
    return VK_SUCCESS;
}

void *vkGetDeviceProcAddr(VkDevice d, const char *name) {
    if (!strcmp(name, "vkGetMemoryFdKHR")) return (void*)vkGetMemoryFdKHR;
    if (!strcmp(name, "vkGetMemoryFdPropertiesKHR"))
        return (void*)vkGetMemoryFdPropertiesKHR;
    return NULL;
}
