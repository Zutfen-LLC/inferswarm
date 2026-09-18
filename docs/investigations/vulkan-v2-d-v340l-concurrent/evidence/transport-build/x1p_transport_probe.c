
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
