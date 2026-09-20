#ifndef VULKAN_STUB_H
#define VULKAN_STUB_H
/* Recording Vulkan stub for #230 contract tests. Mirrors the surface
 * the V2-F transfer probe uses. Every entry point RECORDS its call
 * arguments into a side log (stub-calls.log) the tests parse. */
#include <stdint.h>
#include <stddef.h>

#define VK_DEFINE_HANDLE(x) typedef struct x##_T* x
VK_DEFINE_HANDLE(VkInstance);
VK_DEFINE_HANDLE(VkPhysicalDevice);
VK_DEFINE_HANDLE(VkDevice);
VK_DEFINE_HANDLE(VkQueue);
VK_DEFINE_HANDLE(VkDeviceMemory);
VK_DEFINE_HANDLE(VkBuffer);
VK_DEFINE_HANDLE(VkCommandPool);
VK_DEFINE_HANDLE(VkCommandBuffer);
VK_DEFINE_HANDLE(VkFence);

#define VK_MAKE_VERSION(maj,min,pat) ((uint32_t)(maj)<<22 | (uint32_t)(min)<<12 | (uint32_t)(pat))
#define VK_UUID_SIZE 16
#define VK_MAX_EXTENSION_NAME_SIZE 256

typedef enum { VK_SUCCESS = 0, VK_ERROR_OUT_OF_HOST_MEMORY = -4,
               VK_ERROR_INVALID_EXTERNAL_HANDLE = -10 } VkResult;
typedef uint32_t VkFlags;
typedef uint32_t VkBool32;
typedef uint64_t VkDeviceSize;

typedef enum VkStructureType {
  VK_STRUCTURE_TYPE_APPLICATION_INFO = 0,
  VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
  VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2,
  VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES,
  VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
  VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
  VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
  VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO,
  VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
  VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO,
  VK_STRUCTURE_TYPE_IMPORT_MEMORY_FD_INFO_KHR,
  VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR,
  VK_STRUCTURE_TYPE_MEMORY_FD_PROPERTIES_KHR,
  VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
  VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
  VK_STRUCTURE_TYPE_SUBMIT_INFO,
  VK_STRUCTURE_TYPE_FENCE_CREATE_INFO,
  VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
  VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MEMORY_PROPERTIES,
} VkStructureType;

typedef struct { VkStructureType sType; const void* pNext; const char* pApplicationName; uint32_t applicationVersion; const char* pEngineName; uint32_t engineVersion; uint32_t apiVersion; } VkApplicationInfo;
typedef struct { VkStructureType sType; const void* pNext; const VkApplicationInfo* pApplicationInfo; uint32_t enabledLayerCount; const char* const* ppEnabledLayerNames; uint32_t enabledExtensionCount; const char* const* ppEnabledExtensionNames; } VkInstanceCreateInfo;
typedef struct { uint32_t vendorID; uint32_t deviceID; uint32_t driverVersion; char deviceName[256]; uint32_t apiVersion; uint32_t deviceType; uint8_t pipelineCacheUUID[16]; } VkPhysicalDeviceProperties;
typedef struct { VkStructureType sType; void* pNext; VkPhysicalDeviceProperties properties; } VkPhysicalDeviceProperties2;
typedef struct { VkStructureType sType; void* pNext; uint8_t deviceUUID[16]; uint8_t driverUUID[16]; uint8_t deviceLUID[16]; uint32_t deviceNodeMask; VkBool32 deviceLUIDValid; } VkPhysicalDeviceIDProperties;
typedef struct { uint32_t queueFlags; uint32_t queueCount; uint32_t timestampValidBits; uint32_t minImageTransferGranularity[3]; } VkQueueFamilyProperties;
typedef struct { VkStructureType sType; void* pNext; uint32_t queueFamilyIndex; uint32_t queueCount; const float* pQueuePriorities; } VkDeviceQueueCreateInfo;
typedef struct { VkStructureType sType; void* pNext; uint32_t queueCreateInfoCount; const VkDeviceQueueCreateInfo* pQueueCreateInfos; uint32_t enabledLayerCount; const char* const* ppEnabledLayerNames; uint32_t enabledExtensionCount; const char* const* ppEnabledExtensionNames; const void* pNext2; } VkDeviceCreateInfo;
typedef uint32_t VkBufferUsageFlags;
typedef struct { VkStructureType sType; void* pNext; VkDeviceSize size; VkBufferUsageFlags usage; uint32_t sharingMode; } VkBufferCreateInfo;
typedef struct { VkStructureType sType; void* pNext; VkFlags handleTypes; } VkExternalMemoryBufferCreateInfo;
typedef struct { VkFlags propertyFlags; uint32_t heapIndex; } VkMemoryType;
typedef struct { VkDeviceSize size; VkFlags flags; } VkMemoryHeap;
typedef struct { uint32_t memoryTypeCount; VkMemoryType memoryTypes[32]; uint32_t memoryHeapCount; VkMemoryHeap memoryHeaps[16]; } VkPhysicalDeviceMemoryProperties;
typedef struct { VkStructureType sType; void* pNext; VkDeviceSize allocationSize; uint32_t memoryTypeIndex; } VkMemoryAllocateInfo;
typedef struct { VkStructureType sType; void* pNext; VkFlags handleTypes; } VkExportMemoryAllocateInfo;
typedef struct { VkStructureType sType; void* pNext; VkFlags handleType; int fd; } VkImportMemoryFdInfoKHR;
typedef struct { VkStructureType sType; void* pNext; VkDeviceMemory memory; VkFlags handleType; } VkMemoryGetFdInfoKHR;
typedef struct { VkStructureType sType; void* pNext; uint32_t memoryTypeBits; } VkMemoryFdPropertiesKHR;
typedef struct { VkStructureType sType; void* pNext; uint32_t commandPoolCount; } VkCommandPoolCreateInfoDummy;
typedef struct { VkStructureType sType; void* pNext; uint32_t commandPoolFlags; uint32_t queueFamilyIndex; } VkCommandPoolCreateInfo;
typedef struct { VkStructureType sType; void* pNext; uint32_t level; uint32_t commandBufferCount; VkCommandPool commandPool; } VkCommandBufferAllocateInfo;
typedef struct { VkStructureType sType; void* pNext; uint32_t flags; } VkCommandBufferBeginInfo;
typedef struct { VkStructureType sType; void* pNext; uint32_t commandBufferCount; const VkCommandBuffer* pCommandBuffers; uint32_t signalSemaphoreCount; const void* pSignalSemaphores; uint32_t waitSemaphoreCount; const void* pWaitSemaphores; } VkSubmitInfo;
typedef struct { VkStructureType sType; void* pNext; uint32_t flags; } VkFenceCreateInfo;

#define VK_QUEUE_GRAPHICS_BIT 0x1
#define VK_QUEUE_COMPUTE_BIT 0x2
#define VK_QUEUE_TRANSFER_BIT 0x4
#define VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT 0x1
#define VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT 0x2
#define VK_MEMORY_PROPERTY_HOST_COHERENT_BIT 0x4
#define VK_BUFFER_USAGE_TRANSFER_SRC_BIT 0x4
#define VK_BUFFER_USAGE_TRANSFER_DST_BIT 0x8
#define VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT 0x1
#define VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT 0x200
#define VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MEMORY_PROPERTIES \
  VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MEMORY_PROPERTIES

VkResult vkCreateInstance(const VkInstanceCreateInfo*, const void*, VkInstance*);
void vkDestroyInstance(VkInstance, const void*);
VkResult vkEnumeratePhysicalDevices(VkInstance, uint32_t*, VkPhysicalDevice*);
void vkGetPhysicalDeviceProperties2(VkPhysicalDevice, VkPhysicalDeviceProperties2*);
void vkGetPhysicalDeviceMemoryProperties(VkPhysicalDevice, VkPhysicalDeviceMemoryProperties*);
void vkGetPhysicalDeviceQueueFamilyProperties(VkPhysicalDevice, uint32_t*, VkQueueFamilyProperties*);
VkResult vkCreateDevice(VkPhysicalDevice, const VkDeviceCreateInfo*, const void*, VkDevice*);
void vkDestroyDevice(VkDevice, const void*);
void vkGetDeviceQueue(VkDevice, uint32_t, uint32_t, VkQueue*);
VkResult vkCreateBuffer(VkDevice, const VkBufferCreateInfo*, const void*, VkBuffer*);
void vkDestroyBuffer(VkDevice, VkBuffer, const void*);
void vkGetBufferMemoryRequirements(VkDevice, VkBuffer, void*);  /* VkMemoryRequirements* */
VkResult vkAllocateMemory(VkDevice, const VkMemoryAllocateInfo*, const void*, VkDeviceMemory*);
void vkFreeMemory(VkDevice, VkDeviceMemory, const void*);
VkResult vkBindBufferMemory(VkDevice, VkBuffer, VkDeviceMemory, VkDeviceSize);
VkResult vkMapMemory(VkDevice, VkDeviceMemory, VkDeviceSize, VkDeviceSize, VkFlags, void**);
void vkUnmapMemory(VkDevice, VkDeviceMemory);
VkResult vkCreateCommandPool(VkDevice, const VkCommandPoolCreateInfo*, const void*, VkCommandPool*);
void vkDestroyCommandPool(VkDevice, VkCommandPool, const void*);
VkResult vkAllocateCommandBuffers(VkDevice, const VkCommandBufferAllocateInfo*, VkCommandBuffer*);
void vkFreeCommandBuffers(VkDevice, VkCommandPool, uint32_t, const VkCommandBuffer*);
VkResult vkBeginCommandBuffer(VkCommandBuffer, const VkCommandBufferBeginInfo*);
VkResult vkEndCommandBuffer(VkCommandBuffer);
void vkCmdCopyBuffer(VkCommandBuffer, VkBuffer, VkBuffer, uint32_t, const void*); /* VkBufferCopy* */
VkResult vkQueueSubmit(VkQueue, uint32_t, const VkSubmitInfo*, VkFence);
VkResult vkWaitForFences(VkDevice, uint32_t, const VkFence*, VkBool32, uint64_t);
VkResult vkResetFences(VkDevice, uint32_t, const VkFence*);
VkResult vkCreateFence(VkDevice, const VkFenceCreateInfo*, const void*, VkFence*);
void vkDestroyFence(VkDevice, VkFence, const void*);
VkResult vkGetMemoryFdKHR(VkDevice, const VkMemoryGetFdInfoKHR*, int*);
VkResult vkGetMemoryFdPropertiesKHR(VkDevice, VkFlags, int, VkMemoryFdPropertiesKHR*);
void* vkGetDeviceProcAddr(VkDevice, const char*);

#endif

/* additions used by the transfer probe */
#define VK_COMMAND_BUFFER_LEVEL_PRIMARY 0
#define VK_SHARING_MODE_EXCLUSIVE 0
#define VK_TRUE 1
typedef struct { VkDeviceSize srcOffset; VkDeviceSize dstOffset; VkDeviceSize size; } VkBufferCopy;
typedef uint32_t VkExternalMemoryHandleTypeFlags;
typedef uint32_t VkExternalMemoryHandleTypeFlagBits;
typedef struct { VkDeviceSize size; uint32_t alignment; uint32_t memoryTypeBits; } VkMemoryRequirements;
typedef VkResult (*PFN_vkGetMemoryFdKHR)(VkDevice, const VkMemoryGetFdInfoKHR*, int*);
typedef VkResult (*PFN_vkGetMemoryFdPropertiesKHR)(VkDevice, VkFlags, int, VkMemoryFdPropertiesKHR*);
