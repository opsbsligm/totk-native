#pragma once
#include <stdint.h>
#include <SDL3/SDL.h>
#include <vulkan/vulkan.h>
#ifdef __cplusplus
extern "C" {
#endif
int nd_control_event(const SDL_Event *event, SDL_Window *window);
int nd_control_captured(void);
uint32_t nd_control_suppressed_pad_buttons(void);
void nd_control_apply_window(SDL_Window *window);
int nd_control_fps_limit(void);
void nd_control_draw(VkCommandBuffer command, VkImageView target, VkFormat format, uint32_t width, uint32_t height);
void nd_control_device_reset(void);
#ifdef __cplusplus
}
#endif
