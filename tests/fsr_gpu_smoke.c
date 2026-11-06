/* SPDX-License-Identifier: MIT */
/* Offscreen component test: synthetic solid colour only; never starts a game. */
#include "../src/vk/vk.h"
#include "../src/vk/fsr.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct {VkImage image;VkDeviceMemory memory;VkImageView view;} Image;
static uint32_t memory_type(uint32_t bits,VkMemoryPropertyFlags flags) {
    for(uint32_t i=0;i<vkc.memory.memoryTypeCount;i++) if((bits&(1u<<i)) && (vkc.memory.memoryTypes[i].propertyFlags&flags)==flags) return i;
    abort();
}
static Image image(uint32_t w,uint32_t h,int sampled) {
    Image out={0};VkImageCreateInfo ci={VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,.imageType=VK_IMAGE_TYPE_2D,.format=VK_FORMAT_B8G8R8A8_UNORM,
        .extent={w,h,1},.mipLevels=1,.arrayLayers=1,.samples=VK_SAMPLE_COUNT_1_BIT,.tiling=VK_IMAGE_TILING_OPTIMAL,
        .usage=VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT|(sampled?VK_IMAGE_USAGE_SAMPLED_BIT:0)};
    assert(vk.vkCreateImage(vkc.device,&ci,NULL,&out.image)==VK_SUCCESS);VkMemoryRequirements req;vk.vkGetImageMemoryRequirements(vkc.device,out.image,&req);
    VkMemoryAllocateInfo ai={VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=req.size,.memoryTypeIndex=memory_type(req.memoryTypeBits,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
    assert(vk.vkAllocateMemory(vkc.device,&ai,NULL,&out.memory)==VK_SUCCESS);assert(vk.vkBindImageMemory(vkc.device,out.image,out.memory,0)==VK_SUCCESS);
    if(sampled) {VkImageViewCreateInfo vi={VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,.image=out.image,.viewType=VK_IMAGE_VIEW_TYPE_2D,.format=VK_FORMAT_B8G8R8A8_UNORM,
        .components={VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_ONE},.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};
        assert(vk.vkCreateImageView(vkc.device,&vi,NULL,&out.view)==VK_SUCCESS);}
    return out;
}
static void destroy(Image *i) {if(i->view) vk.vkDestroyImageView(vkc.device,i->view,NULL);vk.vkDestroyImage(vkc.device,i->image,NULL);vk.vkFreeMemory(vkc.device,i->memory,NULL);}
static void barrier(VkCommandBuffer cb,VkImage image,VkImageLayout old,VkImageLayout next,VkAccessFlags src,VkAccessFlags dst) {
    VkImageMemoryBarrier b={VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,.srcAccessMask=src,.dstAccessMask=dst,.oldLayout=old,.newLayout=next,
        .srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.image=image,.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};
    vk.vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,0,NULL,0,NULL,1,&b);
}
static VkResult fail_sampler(VkDevice d,const VkSamplerCreateInfo *i,const VkAllocationCallbacks *a,VkSampler *s) {(void)d;(void)i;(void)a;(void)s;return VK_ERROR_OUT_OF_DEVICE_MEMORY;}
int main(int argc,char **argv) {
    assert(vk_init(NULL));if(argc>1 && !strcmp(argv[1],"--require-deck")) assert(strstr(vkc.props.deviceName,"VANGOGH"));
    printf("GPU=%s; shader_object=%d; GamePlayabilityValidated=false\n",vkc.props.deviceName,vkc.has_shader_object);assert(vkc.has_shader_object);
    VkCommandPool pool;VkCommandPoolCreateInfo pi={VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,.queueFamilyIndex=vkc.family,.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT};
    assert(vk.vkCreateCommandPool(vkc.device,&pi,NULL,&pool)==VK_SUCCESS);VkCommandBuffer cb;
    VkCommandBufferAllocateInfo ca={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};assert(vk.vkAllocateCommandBuffers(vkc.device,&ca,&cb)==VK_SUCCESS);
    for(int scenario=0;scenario<9;scenario++) {
        uint32_t sw=scenario==3?52:64,sh=scenario==3?44:48,dw=scenario==1?sw:131,dh=scenario==1?sh:99;
        Image src=image(sw,sh,1),dst=image(dw,dh,0);VkBuffer buffer;VkDeviceMemory mem;
        VkBufferCreateInfo bi={VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,.size=(VkDeviceSize)dw*dh*4,.usage=VK_BUFFER_USAGE_TRANSFER_DST_BIT};assert(vk.vkCreateBuffer(vkc.device,&bi,NULL,&buffer)==VK_SUCCESS);
        VkMemoryRequirements req;vk.vkGetBufferMemoryRequirements(vkc.device,buffer,&req);VkMemoryAllocateInfo ai={VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=req.size,.memoryTypeIndex=memory_type(req.memoryTypeBits,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
        assert(vk.vkAllocateMemory(vkc.device,&ai,NULL,&mem)==VK_SUCCESS);assert(vk.vkBindBufferMemory(vkc.device,buffer,mem,0)==VK_SUCCESS);
        assert(vk.vkResetCommandPool(vkc.device,pool,0)==VK_SUCCESS);VkCommandBufferBeginInfo begin={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};assert(vk.vkBeginCommandBuffer(cb,&begin)==VK_SUCCESS);
        barrier(cb,src.image,VK_IMAGE_LAYOUT_UNDEFINED,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,0,VK_ACCESS_TRANSFER_WRITE_BIT);
        VkClearColorValue color={{.25f,.5f,.75f,1}};VkImageSubresourceRange range={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};vk.vkCmdClearColorImage(cb,src.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,&color,1,&range);
        barrier(cb,src.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,VK_ACCESS_TRANSFER_WRITE_BIT,VK_ACCESS_TRANSFER_READ_BIT);
        barrier(cb,dst.image,VK_IMAGE_LAYOUT_UNDEFINED,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,0,VK_ACCESS_TRANSFER_WRITE_BIT);
        int crop[4]={0,0,(int)sw,(int)sh};if(scenario==4) {crop[0]=2;crop[1]=3;crop[2]-=4;crop[3]-=6;}
        nd_fsr_configure(scenario!=5,scenario==2?0:50);
        PFN_vkCreateSampler original=vk.vkCreateSampler;int shader=vkc.has_shader_object;
        if(scenario==6) {nd_fsr_shutdown();vkc.has_shader_object=0;}
        if(scenario==7) {nd_fsr_shutdown();vk.vkCreateSampler=fail_sampler;}
        if(scenario==8) nd_fsr_shutdown();
        int drew=nd_fsr_record(cb,src.image,src.view,sw,sh,crop,dst.image,0,0,dw,dh);
        vk.vkCreateSampler=original;vkc.has_shader_object=shader;
        assert(drew==(scenario<5 || scenario==8));
        if(drew) {
            assert(nd_fsr_status()==1);barrier(cb,dst.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,VK_ACCESS_TRANSFER_WRITE_BIT,VK_ACCESS_TRANSFER_READ_BIT);
            VkBufferImageCopy copy={.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},.imageExtent={dw,dh,1}};vk.vkCmdCopyImageToBuffer(cb,dst.image,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,buffer,1,&copy);
            VkBufferMemoryBarrier host={VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT,.dstAccessMask=VK_ACCESS_HOST_READ_BIT,.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.buffer=buffer,.size=VK_WHOLE_SIZE};
            vk.vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,0,NULL,1,&host,0,NULL);
        } else if(scenario!=5) assert(nd_fsr_status()==-1);
        assert(vk.vkEndCommandBuffer(cb)==VK_SUCCESS);VkSubmitInfo submit={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};assert(vk.vkQueueSubmit(vkc.queue,1,&submit,VK_NULL_HANDLE)==VK_SUCCESS);assert(vk.vkQueueWaitIdle(vkc.queue)==VK_SUCCESS);
        if(drew) {void *mapped;assert(vk.vkMapMemory(vkc.device,mem,0,VK_WHOLE_SIZE,0,&mapped)==VK_SUCCESS);unsigned char *pixel=(unsigned char *)mapped+4*((dh/2)*dw+dw/2);assert(abs((int)pixel[0]-191)<=3 && abs((int)pixel[1]-128)<=3 && abs((int)pixel[2]-64)<=3 && pixel[3]==255);vk.vkUnmapMemory(vkc.device,mem);}
        printf("scenario=%d recorded=%d status=%d PASS\n",scenario,drew,nd_fsr_status());destroy(&src);destroy(&dst);vk.vkDestroyBuffer(vkc.device,buffer,NULL);vk.vkFreeMemory(vkc.device,mem,NULL);
    }
    nd_fsr_shutdown();vk.vkDeviceWaitIdle(vkc.device);puts("FSR component: EASU, RCAS, crop, resize, toggle, missing capability, allocation failure and recovery PASS");return 0;
}
