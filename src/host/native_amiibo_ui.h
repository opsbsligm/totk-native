/* SPDX-License-Identifier: MIT */
#pragma once
#include "native_amiibo.h"
#include <stdio.h>
// Presentation thread only; bounded listing is refreshed explicitly, not every frame.
static void nd_draw_amiibo_library(const char *game,bool chinese) {
    static bool listed=false;static int count=0;static char folder[4096],names[ND_AMIIBO_MAX_FILES][256];
    auto label=[chinese](const char *en,const char *zh) {return chinese?zh:en;};
    ImGui::SeparatorText("Amiibo");
    if(!listed || ImGui::Button(label("Refresh local library","刷新本地标签库"))) {
        count=nd_amiibo_library(game,folder,names);listed=true;
    }
    NdAmiiboSnapshot state;nd_amiibo_snapshot(&state);
    const char *status=state.state==4?label("Mounted","已读取"):state.state==2?label("Tag detected","已检测到标签"):
        state.state==1?label("Waiting for a tag","等待扫描标签"):label("Reader idle","扫描器空闲");
    ImGui::TextUnformatted(status);
    if(state.loaded) {
        ImGui::TextWrapped("%s",state.name);
        if(ImGui::Button(label("Remove tag","移开标签"))) nd_amiibo_remove();
    }
    if(ImGui::BeginCombo(label("Local tag file","本地标签文件"),state.loaded?state.name:label("Choose a .bin file","选择标签文件"))) {
        for(int i=0;i<count;i++) {
            ImGui::PushID(i);ImGui::BeginDisabled(state.state==2 || state.state==4);
            if(ImGui::Selectable(names[i])) {
                char path[4096];int n=snprintf(path,sizeof path,"%s/%s",folder,names[i]);
                if(n>0 && (size_t)n<sizeof path) nd_amiibo_load(path);
            }
            ImGui::EndDisabled();ImGui::PopID();
        }
        ImGui::EndCombo();
    }
    if(count<=0) ImGui::TextWrapped("%s",label("Place owned 540-byte .bin dumps in this folder, then refresh:","将自有的标签文件放入此目录，然后刷新："));
    if(ImGui::TreeNode(label("Library folder / scope","标签目录与支持范围"))) {
        ImGui::TextWrapped("%s",folder);
        ImGui::TextWrapped("%s",label("Read-only figure identity. Application-area saves and tag writes are unavailable.","只读取标签身份；应用区存档与标签写入目前不可用。"));
        ImGui::TreePop();
    }
    if(*state.error) ImGui::TextWrapped("%s",state.error);
}
