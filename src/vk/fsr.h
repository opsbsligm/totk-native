/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <vulkan/vulkan.h>
#ifdef __cplusplus
extern "C" {
#endif
void nd_fsr_configure(int enabled,int sharpness);
int nd_fsr_enabled(void);
int nd_fsr_sharpness(void);
int nd_fsr_status(void); // 0 not tried, 1 ready, -1 unavailable (bilinear fallback)
int nd_fsr_record(VkCommandBuffer,VkImage,VkImageView,uint32_t,uint32_t,const int[4],VkImage,int,int,uint32_t,uint32_t);
void nd_fsr_shutdown(void);
#ifdef __cplusplus
}
#endif
