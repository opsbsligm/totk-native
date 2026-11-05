// Read-only capability query. Creates an instance, no device, queue or game.
#include <vulkan/vulkan.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    VkApplicationInfo app = {VK_STRUCTURE_TYPE_APPLICATION_INFO, .pApplicationName="NativeDeck port capability check",
                             .apiVersion=VK_API_VERSION_1_3};
    VkInstanceCreateInfo ci = {VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo=&app};
    VkInstance instance;
    if (vkCreateInstance(&ci, NULL, &instance) != VK_SUCCESS) return 1;
    uint32_t count=0;
    vkEnumeratePhysicalDevices(instance, &count, NULL);
    VkPhysicalDevice *devices=calloc(count, sizeof *devices);
    if (!devices) { vkDestroyInstance(instance,NULL); return 1; }
    vkEnumeratePhysicalDevices(instance, &count, devices);
    int found=0, supported=0;
    for (uint32_t i=0; i<count; i++) {
        VkPhysicalDeviceProperties props;
        vkGetPhysicalDeviceProperties(devices[i], &props);
        if (!strstr(props.deviceName,"VANGOGH")) continue; // never accept llvmpipe as Deck proof
        found=1;
        uint32_t n=0;
        vkEnumerateDeviceExtensionProperties(devices[i], NULL, &n, NULL);
        VkExtensionProperties *ext=calloc(n,sizeof *ext);
        if (!ext) continue;
        vkEnumerateDeviceExtensionProperties(devices[i],NULL,&n,ext);
        int host=0, shader=0;
        for (uint32_t k=0;k<n;k++) {
            if (!strcmp(ext[k].extensionName,VK_EXT_EXTERNAL_MEMORY_HOST_EXTENSION_NAME)) host=1;
            if (!strcmp(ext[k].extensionName,VK_EXT_SHADER_OBJECT_EXTENSION_NAME)) shader=1;
        }
        VkPhysicalDeviceShaderObjectFeaturesEXT so={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_OBJECT_FEATURES_EXT};
        VkPhysicalDeviceFeatures2 f={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext=shader ? &so : NULL};
        vkGetPhysicalDeviceFeatures2(devices[i], &f);
        supported=host && shader && so.shaderObject && props.apiVersion>=VK_API_VERSION_1_3;
        printf("GPU=%s\nVulkan=%u.%u.%u\nIntegratedGPU=%d\nExternalMemoryHost=%d\nShaderObjectExtension=%d\nShaderObjectFeature=%d\nRequiredCapabilitiesPresent=%d\nGamePlayabilityValidated=false\n",
               props.deviceName,VK_API_VERSION_MAJOR(props.apiVersion),VK_API_VERSION_MINOR(props.apiVersion),
               VK_API_VERSION_PATCH(props.apiVersion),props.deviceType==VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU,
               host,shader,so.shaderObject,supported);
        free(ext);
    }
    free(devices);
    vkDestroyInstance(instance,NULL);
    return found && supported ? 0 : 1;
}
