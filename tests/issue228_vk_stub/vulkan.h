/* Minimal structurally-faithful Vulkan stub for #228 contract tests.
 * Types and prototypes mirror the real header's shapes for exactly the
 * surface the census probe uses. A separate stub .so implements the
 * prototypes and RECORDS the arguments it receives. */
#ifndef VULKAN_STUB_H
#define VULKAN_STUB_H
#include <stdint.h>
#include <stddef.h>
#define VK_DEFINE_HANDLE(x) typedef struct x##_T* x
VK_DEFINE_HANDLE(VkInstance); VK_DEFINE_HANDLE(VkPhysicalDevice); VK_DEFINE_HANDLE(VkDevice);
#define VK_MAKE_VERSION(maj,min,pat) ((uint32_t)(maj)<<22 | (uint32_t)(min)<<12 | (uint32_t)(pat))
#define VK_API_VERSION_MAJOR(v) ((uint32_t)(v) >> 22)
#define VK_API_VERSION_MINOR(v) (((uint32_t)(v) >> 12) & 0x3ff)
#define VK_API_VERSION_PATCH(v) ((uint32_t)(v) & 0xfff)
#define VK_UUID_SIZE 16
#define VK_MAX_EXTENSION_NAME_SIZE 256
#define VK_MAX_DEVICE_GROUP_SIZE 8
#define VK_MAX_MEMORY_HEAPS 16
#define VK_MAX_MEMORY_TYPES 32
typedef enum { VK_SUCCESS = 0, VK_ERROR_INCOMPATIBLE_DRIVER = -9 } VkResult;
typedef uint32_t VkFlags;
typedef uint32_t VkBool32;
typedef enum VkStructureType {
  VK_STRUCTURE_TYPE_APPLICATION_INFO = 0,
  VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
  VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GROUP_PROPERTIES,
  VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2,
  VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES,
  VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
  VK_STRUCTURE_TYPE_DEVICE_GROUP_DEVICE_CREATE_INFO,
  VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
  VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_BUFFER_INFO,
  VK_STRUCTURE_TYPE_EXTERNAL_BUFFER_PROPERTIES,
  VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_IMAGE_FORMAT_INFO,
  VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_FORMAT_INFO_2,
  VK_STRUCTURE_TYPE_EXTERNAL_IMAGE_FORMAT_PROPERTIES,
  VK_STRUCTURE_TYPE_IMAGE_FORMAT_PROPERTIES_2,
} VkStructureType;
typedef struct { VkStructureType sType; const void* pNext; const char* pApplicationName; uint32_t applicationVersion; const char* pEngineName; uint32_t engineVersion; uint32_t apiVersion; } VkApplicationInfo;
typedef struct { VkStructureType sType; const void* pNext; const VkApplicationInfo* pApplicationInfo; uint32_t enabledLayerCount; const char* const* ppEnabledLayerNames; uint32_t enabledExtensionCount; const char* const* ppEnabledExtensionNames; } VkInstanceCreateInfo;
typedef struct { uint32_t vendorID; uint32_t deviceID; uint32_t driverVersion; char deviceName[256]; uint32_t apiVersion; uint32_t deviceType; } VkPhysicalDeviceProperties;
typedef struct { VkStructureType sType; void* pNext; VkPhysicalDeviceProperties properties; } VkPhysicalDeviceProperties2;
typedef struct { VkStructureType sType; void* pNext; uint8_t deviceUUID[VK_UUID_SIZE]; uint8_t driverUUID[VK_UUID_SIZE]; uint8_t deviceLUID[VK_UUID_SIZE]; uint32_t deviceNodeMask; VkBool32 deviceLUIDValid; } VkPhysicalDeviceIDProperties;
typedef struct { VkStructureType sType; void* pNext; uint32_t physicalDeviceCount; VkPhysicalDevice physicalDevices[VK_MAX_DEVICE_GROUP_SIZE]; VkBool32 subsetAllocation; } VkPhysicalDeviceGroupProperties;
typedef struct { uint32_t queueFlags; uint32_t queueCount; uint32_t timestampValidBits; uint32_t minImageTransferGranularity[3]; } VkQueueFamilyProperties;
typedef uint64_t VkDeviceSize;
typedef uint32_t VkBufferUsageFlags;
typedef struct { VkStructureType sType; void* pNext; uint32_t queueFamilyIndex; uint32_t queueCount; const float* pQueuePriorities; } VkDeviceQueueCreateInfo;
typedef struct { VkStructureType sType; void* pNext; uint32_t physicalDeviceCount; const VkPhysicalDevice* pPhysicalDevices; } VkDeviceGroupDeviceCreateInfo;
typedef struct { VkStructureType sType; void* pNext; uint32_t queueCreateInfoCount; const VkDeviceQueueCreateInfo* pQueueCreateInfos; uint32_t enabledLayerCount; const char* const* ppEnabledLayerNames; uint32_t enabledExtensionCount; const char* const* ppEnabledExtensionNames; const void* pNext2; } VkDeviceCreateInfo;

typedef uint32_t VkPeerMemoryFeatureFlags;
typedef struct VkDeviceMemory_T* VkDeviceMemory;

typedef uint64_t VkDeviceSize;
typedef uint32_t VkBufferUsageFlags;
typedef struct { VkFlags propertyFlags; uint32_t heapIndex; } VkMemoryType;
typedef struct { VkDeviceSize size; VkFlags flags; } VkMemoryHeap;
typedef struct { uint32_t memoryTypeCount; VkMemoryType memoryTypes[VK_MAX_MEMORY_TYPES]; uint32_t memoryHeapCount; VkMemoryHeap memoryHeaps[VK_MAX_MEMORY_HEAPS]; } VkPhysicalDeviceMemoryProperties;
typedef struct { VkStructureType sType; const void* pNext; VkFlags usage; VkFlags handleType; } VkPhysicalDeviceExternalBufferInfo;
typedef struct { uint32_t externalMemoryFeatures; VkFlags compatibleHandleTypes; VkFlags exportFromImportedHandleTypes; } VkExternalMemoryProperties;
typedef struct { VkStructureType sType; void* pNext; VkExternalMemoryProperties externalMemoryProperties; } VkExternalBufferProperties;
typedef struct { VkStructureType sType; const void* pNext; VkFlags handleType; } VkPhysicalDeviceExternalImageFormatInfo;
typedef struct { VkStructureType sType; const void* pNext; uint32_t format; uint32_t type; uint32_t tiling; VkFlags usage; } VkPhysicalDeviceImageFormatInfo2;
typedef struct { VkStructureType sType; void* pNext; VkExternalMemoryProperties externalMemoryProperties; } VkExternalImageFormatProperties;
typedef struct { VkStructureType sType; void* pNext; uint32_t x; } VkImageFormatProperties2;
typedef struct { char extensionName[VK_MAX_EXTENSION_NAME_SIZE]; uint32_t specVersion; } VkExtensionProperties;



#define VK_QUEUE_COMPUTE_BIT 0x2
#define VK_MEMORY_HEAP_DEVICE_LOCAL_BIT 0x1
#define VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT 0x1
#define VK_PEER_MEMORY_FEATURE_COPY_SRC_BIT 0x1
#define VK_PEER_MEMORY_FEATURE_COPY_DST_BIT 0x2
#define VK_PEER_MEMORY_FEATURE_GENERIC_SRC_BIT 0x4
#define VK_PEER_MEMORY_FEATURE_GENERIC_DST_BIT 0x8
#define VK_EXTERNAL_MEMORY_FEATURE_EXPORTABLE_BIT 0x2
#define VK_EXTERNAL_MEMORY_FEATURE_IMPORTABLE_BIT 0x4
#define VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT 0x1
#define VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT 0x80
#define VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT 0x20
#define VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_MAPPED_FOREIGN_MEMORY_BIT_EXT 0x40
#define VK_BUFFER_USAGE_TRANSFER_SRC_BIT 0x4
#define VK_BUFFER_USAGE_TRANSFER_DST_BIT 0x8
#define VK_BUFFER_USAGE_STORAGE_BUFFER_BIT 0x40
#define VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT 0x10
#define VK_FORMAT_R8_UINT 68
#define VK_IMAGE_TYPE_2D 1
#define VK_IMAGE_TILING_LINEAR 0
#define VK_IMAGE_USAGE_TRANSFER_SRC_BIT 0x1
#define VK_IMAGE_USAGE_TRANSFER_DST_BIT 0x2
VkResult vkCreateInstance(const VkInstanceCreateInfo*, const void*, VkInstance*);
void vkDestroyInstance(VkInstance, const void*);
VkResult vkEnumerateInstanceVersion(uint32_t*);
VkResult vkEnumerateInstanceExtensionProperties(const char*, uint32_t*, VkExtensionProperties*);
VkResult vkEnumeratePhysicalDeviceGroups(VkInstance, uint32_t*, VkPhysicalDeviceGroupProperties*);
void vkGetPhysicalDeviceProperties(VkPhysicalDevice, VkPhysicalDeviceProperties*);
void vkGetPhysicalDeviceProperties2(VkPhysicalDevice, VkPhysicalDeviceProperties2*);
void vkGetPhysicalDeviceMemoryProperties(VkPhysicalDevice, VkPhysicalDeviceMemoryProperties*);
void vkGetPhysicalDeviceQueueFamilyProperties(VkPhysicalDevice, uint32_t*, VkQueueFamilyProperties*);
VkResult vkEnumeratePhysicalDevices(VkInstance, uint32_t*, VkPhysicalDevice*);
VkResult vkCreateDevice(VkPhysicalDevice, const VkDeviceCreateInfo*, const void*, VkDevice*);
void vkGetDeviceGroupPeerMemoryFeatures(VkDevice, uint32_t, uint32_t, uint32_t, VkPeerMemoryFeatureFlags*);
void vkGetPhysicalDeviceExternalBufferProperties(VkPhysicalDevice, const VkPhysicalDeviceExternalBufferInfo*, VkExternalBufferProperties*);
VkResult vkGetPhysicalDeviceImageFormatProperties2(VkPhysicalDevice, const VkPhysicalDeviceImageFormatInfo2*, VkImageFormatProperties2*);
VkResult vkEnumerateDeviceExtensionProperties(VkPhysicalDevice, const char*, uint32_t*, VkExtensionProperties*);
#endif
