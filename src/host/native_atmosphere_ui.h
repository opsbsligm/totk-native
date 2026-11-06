/* SPDX-License-Identifier: MIT */
#pragma once
#include "native_atmosphere.h"
#include "native_ui_text.h"
static void nd_draw_atmosphere(const char *game,bool chinese) {
    auto t=[chinese](const char *en,const char *zh){return chinese?zh:en;};
    static bool requested=false;
    if(!requested) {nd_atm_reload_async(game);requested=true;}
    bool busy=nd_atm_loading()!=0;
    ImGui::BeginDisabled(busy);
    if(ImGui::Button(t("Reload matching cheats","加载 / 刷新本版本金手指"),ImVec2(-1,48))) nd_atm_reload_async(game);
    if(ImGui::Button(t("Load built-in presets","加载本版本常用预设"),ImVec2(-1,48))) nd_atm_load_defaults(game);
    ImGui::EndDisabled();
    if(ImGui::Button(t("Disable all","全部关闭"),ImVec2(-1,48))) nd_atm_disable_all();
    if(busy) nd_ui_status(t("Reading file in background","正在后台读取文件"));
    size_t count=nd_atm_count();
    if(!count && !busy) ImGui::TextWrapped("%s",t("No entries loaded. Load built-in presets or import a matching file.","暂无可用项目。可加载内置预设，或导入匹配版本的文件。"));
    for(size_t i=0;i<count;i++) {
        NdAtmInfo info;nd_atm_info(i,&info);bool on=info.enabled;
        ImGui::PushID((int)i);ImGui::Separator();
        ImGui::TextWrapped("%s",nd_ui_message(info.name,chinese));
        if(info.builtin) ImGui::TextDisabled("%s",t("Built-in / exact build / starts off","内置预设 · 精确版本 · 默认关闭"));
        ImGui::BeginDisabled(busy || !info.supported);
        if(ImGui::Checkbox(t("Enable this cheat","启用此项"),&on)) nd_atm_request(i,on);
        ImGui::EndDisabled();
        const char *status=!info.supported?t("Unavailable","不可用"):!on?t("Off","已关闭"):
            !info.frames?t("Enabled; awaiting game frame","已启用，等待游戏帧"):
            !info.writes?t("Running; awaiting condition","正在执行，等待条件触发"):
            info.mismatches?t("Memory changed again after writing","写入后内存再次变化"):
            info.verified_writes?t("Memory write read back successfully","内存写入已读回验证"):t("Write pending verification","已写入，等待读回验证");
        nd_ui_status(status,info.enabled && info.verified_writes && !info.mismatches?1:*info.note?-1:0);
        if(info.frames) ImGui::TextWrapped(t("Frames %llu  Writes %llu\nVerified %llu  Changed %llu","执行 %llu 帧 · 写入 %llu 次\n读回一致 %llu 次 · 变化 %llu 次"),
            (unsigned long long)info.frames,(unsigned long long)info.writes,(unsigned long long)info.verified_writes,(unsigned long long)info.mismatches);
        if(*info.note) ImGui::TextWrapped("%s",nd_ui_message(info.note,chinese));
        ImGui::PopID();
    }
    if(*nd_atm_error()) ImGui::TextWrapped("%s",nd_ui_message(nd_atm_error(),chinese));
    if(ImGui::TreeNode(t("Version file / support","版本文件与支持范围"))) {
        ImGui::TextWrapped("%s",nd_atm_file());
        ImGui::TextWrapped("%s",t("Exact build; data and heap only. Code patches require rebuilding. Turning off stops writes and may not undo saved changes.",
            "按实际版本加载，仅支持数据与堆内存。代码补丁需重新编译。关闭会停止写入，已改变或保存的数据不一定恢复。"));
        ImGui::TreePop();
    }
}
