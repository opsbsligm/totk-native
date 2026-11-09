/* SPDX-License-Identifier: MIT */
#pragma once
#include "native_amiibo.h"
#include "native_ui_text.h"
#include <stdio.h>
static void nd_draw_amiibo_library(const char *game,bool chinese) {
    auto t=[chinese](const char *en,const char *zh){return chinese?zh:en;};
    NdAmiiboSnapshot state;nd_amiibo_snapshot(&state);
    bool read=state.loaded && state.current_identity_read;
    nd_ui_status(read?t("Current figure read by game","本次公仔身份已被游戏读取"):
        state.state==4?t("Figure mounted; awaiting game read","公仔已挂载，等待游戏读取"):
        state.state==2?t("Detected; awaiting game read","已检测，等待游戏读取"):
        state.loaded?t("Ready for an in-game scan","已就绪，等待游戏内扫描"):t("Select a virtual figure below","请选择下方虚拟公仔"),read?1:0);
    ImGui::TextWrapped("%s",t("Select the Amiibo ability in game, then scan here. Each explicit scan creates a fresh virtual identity.",
        "先在游戏中选择 Amiibo 能力，再在这里刷入。每次点击生成新的虚拟身份，可反复刷同一公仔。"));
    static int selected=0;const char *names[64];int count=(int)nd_amiibo_virtual_count();
    for(int i=0;i<count;i++) names[i]=nd_amiibo_virtual_name((size_t)i,chinese);
    nd_ui_label(t("Built-in figures","内置公仔"));nd_ui_choice("##virtual-figure",&selected,names,count);
    bool supported=nd_amiibo_virtual_supported((size_t)selected)!=0;
    ImGui::BeginDisabled(!supported);
    if(ImGui::Button(t("Scan / scan again","刷入公仔 / 再刷一次"),ImVec2(-1,52))) nd_amiibo_scan_virtual((size_t)selected);
    ImGui::EndDisabled();
    if(!supported) ImGui::TextWrapped("%s",t("Wolf Link needs an application-area save; unavailable.","狼林克需要应用区存档，目前不可用。"));
    if(state.loaded) {
        ImGui::TextWrapped("%s",state.virtual_index>=0?nd_amiibo_virtual_name((size_t)state.virtual_index,chinese):state.name);
        if(ImGui::Button(t("Remove figure","移开公仔"),ImVec2(-1,48))) nd_amiibo_remove();
    }
    ImGui::TextWrapped("%s",t("Check the game for rewards. Reading a figure's identity does not confirm a reward.",
        "奖励请以游戏中的掉落和提示为准；读取公仔身份不代表已获得奖励。"));
    if(*state.error) ImGui::TextWrapped("%s",nd_ui_message(state.error,chinese));
    ImGui::Separator();
    if(ImGui::TreeNode(t("Scan diagnostics","扫描诊断"))) {
        ImGui::TextWrapped(t("Scans: %llu  Mounts: %llu\nGame identity reads: %llu","刷入 %llu 次 · 挂载 %llu 次\n游戏身份读取 %llu 次"),
            (unsigned long long)state.scans,(unsigned long long)state.mounts,(unsigned long long)state.model_reads);
        ImGui::TextWrapped("%s",t("Session totals; repeated reads are not additional scans or rewards.",
            "以上为本次运行的累计调用次数；重复读取不代表新增扫描或奖励。"));
        ImGui::TreePop();
    }
    if(ImGui::TreeNode(t("Own tag files / advanced","自有标签文件 / 高级"))) {
        static bool listed=false;static int files=0;static char folder[4096],local[ND_AMIIBO_MAX_FILES][256];
        bool refresh=ImGui::Button(t("Refresh local library","刷新本地标签库"),ImVec2(-1,48));
        if(!listed || refresh) {files=nd_amiibo_library(game,folder,local);listed=true;}
        if(ImGui::BeginCombo(t("Tag file","标签文件"),state.loaded?state.name:t("Choose a file","选择文件"))) {
            for(int i=0;i<files;i++) {
                ImGui::PushID(i);ImGui::BeginDisabled(state.state==2 || state.state==4);
                if(ImGui::Selectable(local[i],false,0,ImVec2(0,44))) {
                    char path[4096];int n=snprintf(path,sizeof path,"%s/%s",folder,local[i]);
                    if(n>0 && (size_t)n<sizeof path) nd_amiibo_load(path);
                }
                ImGui::EndDisabled();ImGui::PopID();
            }
            ImGui::EndCombo();
        }
        ImGui::TextWrapped("%s",folder);
        ImGui::TextWrapped("%s",t("Read-only identity; no application save or tag writes.","仅读取身份，不支持应用区存档或标签写入。"));
        ImGui::TreePop();
    }
}
