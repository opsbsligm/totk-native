/* SPDX-License-Identifier: MIT */
#pragma once
#include "native_atmosphere.h"
static void nd_draw_atmosphere(const char *game,bool chinese) {
    auto label=[chinese](const char *en,const char *zh) {return chinese?zh:en;};
    ImGui::SeparatorText(label("Cheats / Atmosphere","金手指 / Atmosphere"));
    if(ImGui::Button(label("Reload matching cheats","重新加载匹配的金手指"))) nd_atm_reload(game);
    for(size_t i=0;i<nd_atm_count();i++) {
        NdAtmInfo info;nd_atm_info(i,&info);bool on=info.enabled;
        ImGui::PushID((int)i);ImGui::BeginDisabled(!info.supported);
        if(ImGui::Checkbox(info.name,&on)) nd_atm_request(i,on);
        ImGui::EndDisabled();
        if(*info.note) ImGui::TextWrapped("%s",info.note);
        ImGui::PopID();
    }
    if(*nd_atm_error()) ImGui::TextWrapped("%s",nd_atm_error());
    if(ImGui::TreeNode(label("Cheat file / scope","金手指文件与支持范围"))) {
        ImGui::TextWrapped("%s",nd_atm_file());
        ImGui::TextWrapped("%s",label("Exact build ID; 0600 permissions. Data/heap codes 0-A only. All start off. Disabling stops writes; changed game data may persist.","匹配版本；文件权限 0600。只支持数据与堆内存指令，默认全部关闭。关闭后停止写入，已经改变的游戏数据可能保留。"));
        ImGui::TreePop();
    }
}
