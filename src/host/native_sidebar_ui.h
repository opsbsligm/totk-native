/* SPDX-License-Identifier: MIT */
/* Original touch-first application chrome. No renderer or game dependency. */
#pragma once
#include "imgui.h"
#include <algorithm>
#include <cmath>
struct NdSidebar {
    int page=0,previous_anchor=-1,scroll=0,layer=1,previous_layer=-1;
    bool previous_open=false,dragging=false,dragged=false,content_active=false;
    ImVec2 position,start;
    float scale=1;
};
static const ImVec2 nd_docks[]={{0,0},{.5f,0},{1,0},{1,.5f},{1,1},{.5f,1},{0,1},{0,.5f}};
static inline void nd_sidebar_style(float scale) {
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,ImVec2(20*scale,18*scale));
    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding,18*scale);
    ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding,10*scale);
    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding,ImVec2(12*scale,12*scale));
    ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing,ImVec2(12*scale,14*scale));
    ImGui::PushStyleVar(ImGuiStyleVar_ScrollbarSize,20*scale);
    ImGui::PushStyleVar(ImGuiStyleVar_GrabMinSize,24*scale);
    ImGui::PushStyleColor(ImGuiCol_WindowBg,ImVec4(.045f,.075f,.10f,1));
    ImGui::PushStyleColor(ImGuiCol_PopupBg,ImVec4(.055f,.090f,.120f,1));
    ImGui::PushStyleColor(ImGuiCol_ChildBg,ImVec4(0,0,0,0));
    ImGui::PushStyleColor(ImGuiCol_Border,ImVec4(.22f,.45f,.42f,.6f));
    ImGui::PushStyleColor(ImGuiCol_Text,ImVec4(.95f,.97f,.96f,1));
    ImGui::PushStyleColor(ImGuiCol_TextDisabled,ImVec4(.55f,.72f,.72f,1));
    ImGui::PushStyleColor(ImGuiCol_FrameBg,ImVec4(.09f,.15f,.19f,1));
    ImGui::PushStyleColor(ImGuiCol_FrameBgHovered,ImVec4(.14f,.24f,.30f,1));
    ImGui::PushStyleColor(ImGuiCol_FrameBgActive,ImVec4(.18f,.32f,.38f,1));
    ImGui::PushStyleColor(ImGuiCol_Button,ImVec4(.10f,.16f,.21f,1));
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered,ImVec4(.16f,.27f,.34f,1));
    ImGui::PushStyleColor(ImGuiCol_ButtonActive,ImVec4(.22f,.40f,.48f,1));
    ImGui::PushStyleColor(ImGuiCol_CheckMark,ImVec4(.50f,.95f,.72f,1));
    ImGui::PushStyleColor(ImGuiCol_SliderGrab,ImVec4(.40f,.82f,.62f,1));
    ImGui::PushStyleColor(ImGuiCol_SliderGrabActive,ImVec4(.60f,.96f,.74f,1));
    ImGui::PushStyleColor(ImGuiCol_Header,ImVec4(.18f,.36f,.40f,1));
    ImGui::PushStyleColor(ImGuiCol_HeaderHovered,ImVec4(.25f,.48f,.53f,1));
    ImGui::PushStyleColor(ImGuiCol_Separator,ImVec4(.22f,.42f,.40f,.5f));
}
static inline void nd_sidebar_unstyle() {ImGui::PopStyleColor(18);ImGui::PopStyleVar(7);}
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
// The captured/open state is distinct from the visible layer: badge -> quick -> full.
// Only the full layer opens a content child; always pair begin with end.
static inline void nd_sidebar_drag(NdSidebar &s,float k) {
    ImVec2 at=ImGui::GetCursorScreenPos();float width=ImGui::GetContentRegionAvail().x;
    ImGui::InvisibleButton("##dock-drag",ImVec2(width,std::max(44.f,36*k)));
    ImGui::GetWindowDrawList()->AddRectFilled(ImVec2(at.x+width*.36f,at.y+12*k),ImVec2(at.x+width*.64f,at.y+17*k),
        ImGui::IsItemHovered()?IM_COL32(120,220,190,235):IM_COL32(96,170,155,190),3*k);
    if(ImGui::IsItemActivated()) {s.start=s.position;s.dragged=false;}
    if(ImGui::IsItemActive() && ImGui::IsMouseDragging(0,8*k)) {
        s.dragging=s.dragged=true;ImVec2 d=ImGui::GetMouseDragDelta();s.position=ImVec2(s.start.x+d.x,s.start.y+d.y);
    }
}
static inline bool nd_sidebar_begin(NdSidebar &s,bool open,int anchor,const char *title,bool zh,bool *toggle) {
    // Cancel applies to both visible panel layers; it never opens a badge.
    if(open && (ImGui::IsKeyPressed(ImGuiKey_GamepadFaceRight,false) || ImGui::IsKeyPressed(ImGuiKey_Escape,false))) *toggle=true;
    ImGuiIO &io=ImGui::GetIO();s.scale=std::clamp(io.DisplaySize.y/800.f,.75f,1.35f);
    float k=s.scale,margin=14*k;anchor=std::clamp(anchor,0,7);s.content_active=false;
    if(!open) s.layer=1;
    int layer=open?s.layer:0;
    ImVec2 size=layer==2?ImVec2(std::min(456*k,io.DisplaySize.x-2*margin),io.DisplaySize.y-2*margin):
        layer==1?ImVec2(std::min(344*k,io.DisplaySize.x-2*margin),std::min(448*k,io.DisplaySize.y-2*margin)):ImVec2(std::max(48.f,56*k),std::max(48.f,56*k));
    ImVec2 a=nd_docks[anchor];
    if(!s.dragging || s.previous_anchor!=anchor || s.previous_open!=open || s.previous_layer!=layer)
        s.position=ImVec2(margin+a.x*(io.DisplaySize.x-2*margin-size.x),margin+a.y*(io.DisplaySize.y-2*margin-size.y));
    s.previous_anchor=anchor;s.previous_open=open;s.previous_layer=layer;
    s.position.x=std::clamp(s.position.x,0.f,std::max(0.f,io.DisplaySize.x-size.x));
    s.position.y=std::clamp(s.position.y,0.f,std::max(0.f,io.DisplaySize.y-size.y));
    nd_sidebar_style(k);
    ImGui::SetNextWindowPos(s.position,ImGuiCond_Always);ImGui::SetNextWindowSize(size,ImGuiCond_Always);
    ImGui::Begin("##native-touch-sidebar",nullptr,ImGuiWindowFlags_NoTitleBar|ImGuiWindowFlags_NoMove|
                 ImGuiWindowFlags_NoResize|ImGuiWindowFlags_NoSavedSettings|ImGuiWindowFlags_NoScrollbar);
    if(open) {
        ImDrawList *frame=ImGui::GetWindowDrawList();ImVec2 wp=ImGui::GetWindowPos();
        frame->AddRect(wp,ImVec2(wp.x+size.x,wp.y+size.y),ImGui::GetColorU32(ImGuiCol_Border),18*k,0,1.2f*k);
    }
    if(!open) {
        ImGui::SetCursorPos(ImVec2(0,0));
        bool clicked=ImGui::InvisibleButton("##edge-badge",size);
        if(ImGui::IsItemActivated()) {s.start=s.position;s.dragged=false;}
        if(ImGui::IsItemActive() && ImGui::IsMouseDragging(0,8*k)) {
            s.dragging=s.dragged=true;ImVec2 d=ImGui::GetMouseDragDelta();s.position=ImVec2(s.start.x+d.x,s.start.y+d.y);
        }
        if(clicked && !s.dragged) *toggle=true;
        ImDrawList *draw=ImGui::GetWindowDrawList();ImVec2 c=ImGui::GetWindowPos();c.x+=size.x*.5f;c.y+=size.y*.5f;
        bool hot=ImGui::IsItemHovered();
        draw->AddRectFilled(ImVec2(c.x-22*k,c.y-22*k),ImVec2(c.x+22*k,c.y+22*k),
            hot?IM_COL32(24,48,56,235):IM_COL32(12,26,33,215),12*k);
        draw->AddRect(ImVec2(c.x-22*k,c.y-22*k),ImVec2(c.x+22*k,c.y+22*k),
            hot?IM_COL32(120,220,190,255):IM_COL32(90,180,155,200),12*k,0,1.4f*k);
        ImU32 ink=hot?IM_COL32(151,235,211,255):IM_COL32(210,229,225,255);
        for(int i=0;i<8;i++) {
            if(i%2) continue;
            float a=i*3.14159265f*.25f;ImVec2 x(c.x+std::cos(a)*13*k,c.y+std::sin(a)*13*k),y(c.x+std::cos(a)*17*k,c.y+std::sin(a)*17*k);
            draw->AddLine(x,y,ink,3.4f*k);
        }
        draw->AddCircle(c,10*k,ink,24,2.6f*k);draw->AddCircleFilled(c,3.4f*k,ink,16);
        return false;
    }
    if(layer==2) {
        if(ImGui::Button(zh?"返回":"Back",ImVec2(70*k,std::max(44.f,44*k)))) s.layer=1;
        ImGui::SameLine();ImGui::TextDisabled("%s",zh?"完整设置":"SETTINGS");
    } else ImGui::TextDisabled("%s",zh?"快捷面板":"QUICK PANEL");
    ImGui::SameLine(ImGui::GetWindowWidth()-76*k);
    if(ImGui::Button(zh?"收起":"Hide",ImVec2(56*k,std::max(44.f,44*k)))) *toggle=true;
    {ImVec2 tl=ImGui::GetCursorScreenPos();ImDrawList *td=ImGui::GetWindowDrawList();
     td->AddRectFilled(ImVec2(tl.x,tl.y+4*k),ImVec2(tl.x+4*k,tl.y+std::max(18.f,24*k)),IM_COL32(120,220,190,255),2*k);
     ImGui::Indent(10*k);}
    ImGui::TextUnformatted(title);ImGui::Unindent(10*k);nd_sidebar_drag(s,k);
    const char *tabs_en[]={"Display","Controls","Amiibo","Cheats"},*tabs_zh[]={"画面","控制","Amiibo","金手指"};
    if(layer==1) {
        float width=(ImGui::GetContentRegionAvail().x-ImGui::GetStyle().ItemSpacing.x)*.5f;
        for(int i=0;i<4;i++) {
            if(i%2) ImGui::SameLine();ImGui::PushID(i);
            if(ImGui::Button(zh?tabs_zh[i]:tabs_en[i],ImVec2(width,56*k))) {s.page=i;s.layer=2;s.scroll=0;}
            ImGui::PopID();
        }
        ImGui::Spacing();
        if(ImGui::Button(zh?"展开完整设置":"Open full settings",ImVec2(-1,50*k))) s.layer=2;
        ImGui::TextDisabled("%s",zh?"触屏展开 · 拖动短条停靠":"TOUCH TO OPEN / DRAG TO DOCK");
        return false;
    }
    if(s.layer!=2) return false;
    float gap=ImGui::GetStyle().ItemSpacing.x,w=(ImGui::GetContentRegionAvail().x-3*gap)/4;
    for(int i=0;i<4;i++) {
        if(i) ImGui::SameLine();ImGui::PushID(i);bool selected=i==s.page;
        if(selected) ImGui::PushStyleColor(ImGuiCol_Button,ImVec4(.20f,.44f,.48f,1));
        if(ImGui::Button(zh?tabs_zh[i]:tabs_en[i],ImVec2(w,std::max(44.f,46*k)))) s.page=i;
        if(selected) ImGui::PopStyleColor();ImGui::PopID();
    }
    ImGui::Separator();
    ImGui::BeginChild("##sidebar-content",ImVec2(0,-62*k),ImGuiChildFlags_None,ImGuiWindowFlags_NoMove);s.content_active=true;
    if(s.scroll) {ImGui::SetScrollY(ImGui::GetScrollY()+s.scroll*240*k);s.scroll=0;}
    return true;
}
static inline bool nd_sidebar_end(NdSidebar &s,bool /*open*/,int *anchor,bool zh,ImVec2 *lower,ImVec2 *upper) {
    bool changed=false;
    if(s.content_active) {
        float scroll=ImGui::GetScrollY(),max=ImGui::GetScrollMaxY();ImGui::EndChild();
        ImGui::Separator();
        ImGui::BeginDisabled(scroll<=0);if(ImGui::Button(zh?"向上":"Up",ImVec2(96*s.scale,std::max(44.f,46*s.scale)))) s.scroll=-1;ImGui::EndDisabled();
        ImGui::SameLine();ImGui::BeginDisabled(scroll>=max);if(ImGui::Button(zh?"向下":"Down",ImVec2(96*s.scale,std::max(44.f,46*s.scale)))) s.scroll=1;ImGui::EndDisabled();
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
