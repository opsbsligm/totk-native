/* SPDX-License-Identifier: MIT */
/* Renderer-thread barriers for the pinned Dear ImGui event queue. */
#pragma once
#include "imgui_internal.h"

static inline void nd_imgui_cancel_pointer(ImGuiIO &io) {
    // ClearInputMouse changes current state, not queued DOWN events. Preserve
    // keyboard/gamepad releases and text while removing the canceled pointer.
    auto &pending=io.Ctx->InputEventsQueue;
    int kept=0;
    for(int i=0;i<pending.Size;i++) {
        auto type=pending[i].Type;
        if(type!=ImGuiInputEventType_MousePos && type!=ImGuiInputEventType_MouseButton && type!=ImGuiInputEventType_MouseWheel)
            pending[kept++]=pending[i];
    }
    pending.resize(kept);
    io.ClearInputMouse();
}

static inline void nd_imgui_reset_input(ImGuiIO &io) {
    io.ClearEventsQueue();
    io.ClearInputKeys();
    io.ClearInputMouse();
}
