/* SPDX-License-Identifier: MIT */
/* Original touch-first application chrome. No renderer or game dependency. */
#pragma once
#include "imgui.h"
#include <algorithm>
#include <cmath>
struct NdSidebar {
    int page=0,previous_anchor=-1,scroll=0;
    bool previous_open=false,dragging=false,dragged=false;
    ImVec2 position,start;
    float scale=1;
};
static const ImVec2 nd_docks[]={{0,0},{.5f,0},{1,0},{1,.5f},{1,1},{.5f,1},{0,1},{0,.5f}};
static inline void nd_sidebar_style(float scale) {
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,ImVec2(18*scale,16*scale));
    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding,16*scale);
    ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding,9*scale);
    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding,ImVec2(12*scale,12*scale));
    ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing,ImVec2(10*scale,12*scale));
    ImGui::PushStyleVar(ImGuiStyleVar_ScrollbarSize,24*scale);
    ImGui::PushStyleVar(ImGuiStyleVar_GrabMinSize,24*scale);
    ImGui::PushStyleColor(ImGuiCol_WindowBg,ImVec4(.047f,.075f,.082f,.98f));
    ImGui::PushStyleColor(ImGuiCol_ChildBg,ImVec4(0,0,0,0));
    ImGui::PushStyleColor(ImGuiCol_Border,ImVec4(.18f,.29f,.28f,1));
    ImGui::PushStyleColor(ImGuiCol_Text,ImVec4(.91f,.95f,.93f,1));
    ImGui::PushStyleColor(ImGuiCol_TextDisabled,ImVec4(.57f,.68f,.65f,1));
    ImGui::PushStyleColor(ImGuiCol_FrameBg,ImVec4(.10f,.17f,.18f,1));
    ImGui::PushStyleColor(ImGuiCol_FrameBgHovered,ImVec4(.16f,.29f,.28f,1));
    ImGui::PushStyleColor(ImGuiCol_FrameBgActive,ImVec4(.20f,.36f,.33f,1));
    ImGui::PushStyleColor(ImGuiCol_Button,ImVec4(.12f,.23f,.22f,1));
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered,ImVec4(.18f,.36f,.31f,1));
    ImGui::PushStyleColor(ImGuiCol_ButtonActive,ImVec4(.23f,.46f,.37f,1));
    ImGui::PushStyleColor(ImGuiCol_CheckMark,ImVec4(.49f,.88f,.67f,1));
    ImGui::PushStyleColor(ImGuiCol_SliderGrab,ImVec4(.39f,.75f,.58f,1));
    ImGui::PushStyleColor(ImGuiCol_SliderGrabActive,ImVec4(.59f,.93f,.72f,1));
    ImGui::PushStyleColor(ImGuiCol_Header,ImVec4(.16f,.32f,.28f,1));
    ImGui::PushStyleColor(ImGuiCol_HeaderHovered,ImVec4(.23f,.43f,.35f,1));
}
static inline void nd_sidebar_unstyle() {ImGui::PopStyleColor(16);ImGui::PopStyleVar(7);}
static inline void nd_ui_status(const char *text,int status=0) {
    ImGui::TextColored(status>0?ImVec4(.55f,.91f,.69f,1):status<0?ImVec4(1,.70f,.40f,1):ImVec4(.62f,.74f,.70f,1),"%s",text);
}
static inline void nd_ui_label(const char *text) {ImGui::Spacing();ImGui::TextUnformatted(text);ImGui::SetNextItemWidth(-1);}
static inline bool nd_ui_choice(const char *id,int *selected,const char *const names[],int count) {
    bool changed=false;int current=*selected;
    if(current<0 || current>=count) current=0;
    const ImGuiStyle &style=ImGui::GetStyle();
    float rows=(44.f+style.ItemSpacing.y)*count+2*style.WindowPadding.y;
    ImGui::SetNextWindowSizeConstraints(ImVec2(0,0),ImVec2(FLT_MAX,std::min(rows,ImGui::GetIO().DisplaySize.y*.75f)));
    if(ImGui::BeginCombo(id,names[current])) {
        for(int i=0;i<count;i++) if(ImGui::Selectable(names[i],i==current,0,ImVec2(0,44))) {*selected=i;changed=true;}
        ImGui::EndCombo();
    }
    return changed;
}
// Always end the parent with nd_sidebar_end. A collapsed handle has no content child.
static inline bool nd_sidebar_begin(NdSidebar &s,bool open,int anchor,const char *title,bool zh,bool *toggle) {
    ImGuiIO &io=ImGui::GetIO();s.scale=std::clamp(io.DisplaySize.y/800.f,.75f,1.35f);
    float k=s.scale,margin=12*k;anchor=std::clamp(anchor,0,7);
    ImVec2 size=open?ImVec2(std::min(448*k,io.DisplaySize.x-2*margin),io.DisplaySize.y-2*margin):ImVec2(64*k,100*k);
    ImVec2 a=nd_docks[anchor];
    if(!s.dragging || s.previous_anchor!=anchor || s.previous_open!=open)
        s.position=ImVec2(margin+a.x*(io.DisplaySize.x-2*margin-size.x),margin+a.y*(io.DisplaySize.y-2*margin-size.y));
    s.previous_anchor=anchor;s.previous_open=open;
    s.position.x=std::clamp(s.position.x,0.f,std::max(0.f,io.DisplaySize.x-size.x));
    s.position.y=std::clamp(s.position.y,0.f,std::max(0.f,io.DisplaySize.y-size.y));
    nd_sidebar_style(k);
    ImGui::SetNextWindowPos(s.position,ImGuiCond_Always);ImGui::SetNextWindowSize(size,ImGuiCond_Always);
    ImGui::Begin("##native-touch-sidebar",nullptr,ImGuiWindowFlags_NoTitleBar|ImGuiWindowFlags_NoMove|
                 ImGuiWindowFlags_NoResize|ImGuiWindowFlags_NoSavedSettings|ImGuiWindowFlags_NoScrollbar);
    if(!open) {
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding,ImVec2(0,0));
        ImGui::SetCursorPos(ImVec2(0,0));
        if(ImGui::Button(zh?"设置##edge":"Menu##edge",size)) *toggle=true;
        ImGui::PopStyleVar();return false;
    }
    ImGui::TextDisabled("%s",zh?"掌机设置":"DECK SETTINGS");
    ImGui::SameLine(ImGui::GetWindowWidth()-88*k);
    if(ImGui::Button(zh?"收起":"Close",ImVec2(66*k,46*k))) *toggle=true;
    ImGui::TextUnformatted(title);
    ImVec2 grab=ImGui::GetCursorScreenPos();
    ImGui::InvisibleButton("##dock-drag",ImVec2(-1,32*k));
    ImGui::GetWindowDrawList()->AddRectFilled(ImVec2(grab.x+150*k,grab.y+12*k),ImVec2(grab.x+230*k,grab.y+17*k),IM_COL32(91,133,117,255),3*k);
    if(ImGui::IsItemActivated()) {s.start=s.position;s.dragged=false;}
    if(ImGui::IsItemActive() && ImGui::IsMouseDragging(0,8*k)) {
        s.dragging=s.dragged=true;ImVec2 d=ImGui::GetMouseDragDelta();s.position=ImVec2(s.start.x+d.x,s.start.y+d.y);
    }
    const char *tabs_en[]={"Display","Controls","Amiibo","Cheats"},*tabs_zh[]={"画面","控制","Amiibo","金手指"};
    float gap=ImGui::GetStyle().ItemSpacing.x,w=(ImGui::GetContentRegionAvail().x-3*gap)/4;
    for(int i=0;i<4;i++) {
        if(i) ImGui::SameLine();
        ImGui::PushID(i);
        bool selected=i==s.page;
        if(selected) ImGui::PushStyleColor(ImGuiCol_Button,ImVec4(.19f,.41f,.32f,1));
        if(ImGui::Button(zh?tabs_zh[i]:tabs_en[i],ImVec2(w,48*k))) s.page=i;
        if(selected) ImGui::PopStyleColor();
        ImGui::PopID();
    }
    ImGui::Separator();
    ImGui::BeginChild("##sidebar-content",ImVec2(0,-62*k),ImGuiChildFlags_None,ImGuiWindowFlags_NoMove);
    if(s.scroll) {ImGui::SetScrollY(ImGui::GetScrollY()+s.scroll*240*k);s.scroll=0;}
    return true;
}
static inline bool nd_sidebar_end(NdSidebar &s,bool open,int *anchor,bool zh,ImVec2 *lower,ImVec2 *upper) {
    bool changed=false;
    if(open) {
        float scroll=ImGui::GetScrollY(),max=ImGui::GetScrollMaxY();ImGui::EndChild();
        ImGui::Separator();
        ImGui::BeginDisabled(scroll<=0);if(ImGui::Button(zh?"向上":"Up",ImVec2(96*s.scale,46*s.scale))) s.scroll=-1;ImGui::EndDisabled();
        ImGui::SameLine();ImGui::BeginDisabled(scroll>=max);if(ImGui::Button(zh?"向下":"Down",ImVec2(96*s.scale,46*s.scale))) s.scroll=1;ImGui::EndDisabled();
        ImGui::SameLine();ImGui::TextDisabled("%s",zh?"触屏操作":"TOUCH");
    }
    ImVec2 pos=ImGui::GetWindowPos(),size=ImGui::GetWindowSize();
    *lower=pos;*upper=ImVec2(pos.x+size.x,pos.y+size.y);
    if(s.dragging && !ImGui::IsMouseDown(0)) {
        s.dragging=false;
        if(s.dragged) {
            ImVec2 screen=ImGui::GetIO().DisplaySize;float best=1e30f;int nearest=*anchor;
            for(int i=0;i<8;i++) {
                float dx=(s.position.x+size.x*.5f)/screen.x-nd_docks[i].x;
                float dy=(s.position.y+size.y*.5f)/screen.y-nd_docks[i].y;
                float distance=dx*dx+dy*dy;if(distance<best) {best=distance;nearest=i;}
            }
            *anchor=nearest;s.previous_anchor=-1;changed=true;
        }
        s.dragged=false;
    }
    ImGui::End();nd_sidebar_unstyle();return changed;
}
