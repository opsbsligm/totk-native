/* SPDX-License-Identifier: MIT */
/* Original touch-first application chrome. No renderer or game dependency. */
#pragma once
#include "imgui.h"
#include <algorithm>
#include <cmath>
// One rounded card per settings section. The content child splits its draw list into
// two layers at begin: widgets render into layer 1, section cards are appended into
// layer 0 just before the child ends, so the cards always sit behind the widgets no
// matter when the geometry is known.
struct NdSidebarSections {
    float left=0,right=0,tops[64]={},radius=10;int count=0;float scale=1;
    ImDrawList *child=nullptr;int flushed=0,cards=0;
    void begin_card() {if(count<64) tops[count++]=ImGui::GetCursorScreenPos().y;}
    void flush() {
        if(!child) return;
        if(count && count<64) tops[count++]=ImGui::GetCursorScreenPos().y+8.f*scale;
        child->ChannelsSetCurrent(0);
        for(int n=0;n+1<count;n++) {
            float top=tops[n]-12.f*scale,bottom=tops[n+1]-12.f*scale;
            if(bottom>top+1) {
                child->AddRectFilled(ImVec2(left,top),ImVec2(right,bottom),IM_COL32(14,28,37,238),radius);
                child->AddRect(ImVec2(left,top),ImVec2(right,bottom),IM_COL32(70,130,116,80),radius,0,1.f);
                ++cards;
            }
        }
        count=0;++flushed;
    }
};
static NdSidebarSections *nd_sections=nullptr; // Set once per frame by nd_sidebar_begin.
static inline void nd_ui_label(const char *text) {
    ImGui::Spacing();
    if(nd_sections) nd_sections->begin_card();
    ImGui::TextColored(ImVec4(.62f,.83f,.79f,1),"%s",text);
    ImGui::SetNextItemWidth(-1);
}
static const ImVec2 nd_docks[]={{0,0},{.5f,0},{1,0},{1,.5f},{1,1},{.5f,1},{0,1},{0,.5f}};
static inline void nd_sidebar_style(float scale) {
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,ImVec2(18*scale,16*scale));
    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding,20*scale);
    ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding,12*scale);
    ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing,ImVec2(12*scale,10*scale));
    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding,ImVec2(12*scale,11*scale));
    // The list is dragged with a finger and reported by the pill at its edge, so the classic bar is off:
    // its grab is far too small a target to aim at, and two indicators would only compete.
    ImGui::PushStyleVar(ImGuiStyleVar_ScrollbarSize,0);
    ImGui::PushStyleVar(ImGuiStyleVar_GrabMinSize,24*scale);
    ImGui::PushStyleColor(ImGuiCol_WindowBg,ImVec4(.043f,.071f,.094f,1));
    ImGui::PushStyleColor(ImGuiCol_PopupBg,ImVec4(.055f,.090f,.120f,1));
    ImGui::PushStyleColor(ImGuiCol_ChildBg,ImVec4(0,0,0,0));
    ImGui::PushStyleColor(ImGuiCol_Border,ImVec4(.26f,.52f,.47f,.55f));
    ImGui::PushStyleColor(ImGuiCol_Text,ImVec4(.94f,.97f,.96f,1));
    ImGui::PushStyleColor(ImGuiCol_TextDisabled,ImVec4(.55f,.71f,.69f,1));
    ImGui::PushStyleColor(ImGuiCol_FrameBg,ImVec4(.086f,.141f,.176f,1));
    ImGui::PushStyleColor(ImGuiCol_FrameBgHovered,ImVec4(.129f,.220f,.267f,1));
    ImGui::PushStyleColor(ImGuiCol_FrameBgActive,ImVec4(.169f,.310f,.365f,1));
    ImGui::PushStyleColor(ImGuiCol_Button,ImVec4(.094f,.153f,.192f,1));
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered,ImVec4(.149f,.263f,.322f,1));
    ImGui::PushStyleColor(ImGuiCol_ButtonActive,ImVec4(.212f,.392f,.455f,1));
    ImGui::PushStyleColor(ImGuiCol_CheckMark,ImVec4(.498f,.937f,.706f,1));
    ImGui::PushStyleColor(ImGuiCol_SliderGrab,ImVec4(.396f,.804f,.604f,1));
    ImGui::PushStyleColor(ImGuiCol_SliderGrabActive,ImVec4(.596f,.957f,.737f,1));
    ImGui::PushStyleColor(ImGuiCol_Header,ImVec4(.157f,.310f,.353f,1));
    ImGui::PushStyleColor(ImGuiCol_HeaderHovered,ImVec4(.220f,.431f,.482f,1));
    ImGui::PushStyleColor(ImGuiCol_Separator,ImVec4(.231f,.439f,.412f,.45f));
    ImGui::PushStyleColor(ImGuiCol_ScrollbarBg,ImVec4(0,0,0,0));
    ImGui::PushStyleColor(ImGuiCol_ScrollbarGrab,ImVec4(.220f,.400f,.380f,.75f));
    ImGui::PushStyleColor(ImGuiCol_ScrollbarGrabHovered,ImVec4(.310f,.560f,.520f,.9f));
}
static inline void nd_sidebar_unstyle() {ImGui::PopStyleColor(21);ImGui::PopStyleVar(7);}
static inline void nd_ui_status(const char *text,int status=0) {
    ImGui::TextColored(status>0?ImVec4(.55f,.91f,.69f,1):status<0?ImVec4(1,.70f,.40f,1):ImVec4(.62f,.74f,.70f,1),"%s",text);
}
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
struct NdSidebar {
    int page=0,previous_anchor=-1,scroll=0,layer=1,previous_layer=-1;
    bool previous_open=false,dragging=false,dragged=false,content_active=false;
    NdSidebarSections sections;
    ImVec2 position,start;
    float scale=1;
    // The finger-driven list. The surface behind the content records where a press began, and the list
    // moves with the finger from there, so a settings page scrolls like the rest of the system. The pill
    // at the content edge fades in while the list can move and fades out again once the finger is off it.
    bool pan_active=false,panning=false;
    float content_top=0,content_height=0,pan_press_y=0,pan_scroll=0,scroll_hint=0,quick_top=0;
    // Where the list stood last frame, and the part of it a finger can actually reach: published so the
    // input regression can aim inside the list without reaching into ImGui's private window list.
    float last_scroll=0,last_scroll_max=0,visible_left=0,visible_top=0,visible_bottom=0;
};
// The universal adjust glyph: three tracks, each with its own knob. It reads as "settings" on every
// platform and needs no font, which the game's own font cannot guarantee for CJK in any case.
static inline void nd_glyph_adjust(ImDrawList *draw,ImVec2 c,float k,ImU32 ink) {
    for(int i=0;i<3;i++) {
        float y=c.y+(i-1)*8.f*k,x0=c.x-11.f*k,x1=c.x+11.f*k;
        draw->AddLine(ImVec2(x0,y),ImVec2(x1,y),ink,2.6f*k);
        float knob=i==0?c.x+5.f*k:i==1?c.x-5.f*k:c.x+1.f*k;
        draw->AddCircleFilled(ImVec2(knob,y),3.6f*k,ink);
    }
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
    ImGuiIO &io=ImGui::GetIO();nd_sections=nullptr;s.scale=std::clamp(io.DisplaySize.y/800.f,.75f,1.35f);
    float k=s.scale,margin=14*k;anchor=std::clamp(anchor,0,7);s.content_active=false;
    if(!open) s.layer=1;
    int layer=open?s.layer:0;
    s.pan_active=false;
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
        // A soft shadow underneath keeps the badge readable over snow or sky, which an outline alone
        // cannot: the Deck's own homescreen badges do the same for the same reason.
        float half=24*k;
        draw->AddRectFilled(ImVec2(c.x-half,4.f*k+c.y-half),ImVec2(c.x+half,4.f*k+c.y+half),IM_COL32(0,0,0,90),14*k);
        draw->AddRectFilled(ImVec2(c.x-half,c.y-half),ImVec2(c.x+half,c.y+half),
            hot?IM_COL32(31,62,70,246):IM_COL32(14,31,39,232),14*k);
        draw->AddRect(ImVec2(c.x-half,c.y-half),ImVec2(c.x+half,c.y+half),
            hot?IM_COL32(120,220,190,255):IM_COL32(82,164,142,190),14*k,0,1.4f*k);
        // A thumb is never precisely on target, so the accent marks the docked edge rather than the hover point.
        draw->AddRectFilled(ImVec2(c.x-half,c.y-half),ImVec2(c.x+half,c.y-half+4*k),
            IM_COL32(120,220,190,hot?220:120),14*k,ImDrawFlags_RoundCornersTop);
        nd_glyph_adjust(draw,c,k,hot?IM_COL32(159,240,216,255):IM_COL32(206,228,222,235));
        return false;
    }
    const ImGuiStyle &style=ImGui::GetStyle();
    s.quick_top=ImGui::GetCursorPosY();
    const char *hide=zh?"收起":"Hide",*back=zh?"返回":"Back";
    float hide_width=std::max(56*k,ImGui::CalcTextSize(hide).x+2*style.FramePadding.x);
    if(layer==2) {
        float back_width=std::max(70*k,ImGui::CalcTextSize(back).x+2*style.FramePadding.x);
        if(ImGui::Button(back,ImVec2(back_width,std::max(44.f,44*k)))) s.layer=1;
        ImGui::SameLine();ImGui::TextDisabled("%s",zh?"完整设置":"SETTINGS");
    } else ImGui::TextDisabled("%s",zh?"快捷面板":"QUICK PANEL");
    ImGui::SameLine(ImGui::GetWindowWidth()-style.WindowPadding.x-hide_width);
    if(ImGui::Button(hide,ImVec2(hide_width,std::max(44.f,44*k)))) *toggle=true;
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
    float gap=style.ItemSpacing.x,available=ImGui::GetContentRegionAvail().x,total=3*gap;
    float minimum[4];
    for(int i=0;i<4;i++) {
        minimum[i]=std::max(44.f,ImGui::CalcTextSize(zh?tabs_zh[i]:tabs_en[i]).x+2*style.FramePadding.x);
        total+=minimum[i];
    }
    bool wrap=total>available;
    ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding,std::max(44.f,46*k)*.5f);
    for(int i=0;i<4;i++) {
        if(i && (!wrap || i%2)) ImGui::SameLine();ImGui::PushID(i);bool selected=i==s.page;
        float width=wrap?(available-gap)*.5f:minimum[i]+(available-total)*.25f;
        if(selected) {
            ImGui::PushStyleColor(ImGuiCol_Button,ImGui::GetColorU32(ImVec4(.149f,.361f,.322f,1)));
            ImGui::PushStyleColor(ImGuiCol_ButtonHovered,ImGui::GetColorU32(ImVec4(.188f,.431f,.384f,1)));
        }
        if(ImGui::Button(zh?tabs_zh[i]:tabs_en[i],ImVec2(width,std::max(44.f,46*k)))) s.page=i;
        if(selected) {
            // Underline the active tab so the state reads even with colour-blind themes.
            ImVec2 a=ImGui::GetItemRectMin(),b=ImGui::GetItemRectMax();
            ImGui::GetWindowDrawList()->AddLine(ImVec2(a.x+width*.30f,b.y-2.f),ImVec2(b.x-width*.30f,b.y-2.f),
                IM_COL32(120,220,190,235),2.f*k);
            ImGui::PopStyleColor(2);
        }
        ImGui::PopID();
    }
    ImGui::PopStyleVar();
    ImGui::Separator();
    ImGui::BeginChild("##sidebar-content",ImVec2(0,-62*k),ImGuiChildFlags_None,ImGuiWindowFlags_NoMove);s.content_active=true;
        ImDrawList *content=ImGui::GetWindowDrawList();content->ChannelsSplit(2);content->ChannelsSetCurrent(1);
        ImVec2 cp=ImGui::GetWindowPos();float cw=ImGui::GetWindowSize().x,pad=style.WindowPadding.x;
        s.sections.child=content;s.sections.left=cp.x-pad;s.sections.right=cp.x+cw+pad;
        s.sections.radius=12*k;s.sections.scale=k;s.sections.count=0;s.sections.cards=0;
        nd_sections=&s.sections;
        s.content_top=ImGui::GetCursorPosY();
        s.visible_left=cp.x+pad;s.visible_top=cp.y+pad;s.visible_bottom=cp.y+ImGui::GetWindowSize().y-pad;
    if(s.scroll) {ImGui::SetScrollY(ImGui::GetScrollY()+s.scroll*240*k);s.scroll=0;}
    return true;
}
static inline bool nd_sidebar_end(NdSidebar &s,bool /*open*/,int *anchor,bool zh,ImVec2 *lower,ImVec2 *upper) {
    bool changed=false;
    if(s.content_active) {
        // Submit the tap surface after the page so a control that claimed the press keeps it: a press on a
        // label or a card scrolls the list, a press on a control does not.
        float scroll=ImGui::GetScrollY(),max=ImGui::GetScrollMaxY();
        s.last_scroll=scroll;s.last_scroll_max=max;
        {
            float bottom=ImGui::GetCursorPosY(),visible=ImGui::GetWindowSize().y-2*ImGui::GetStyle().WindowPadding.y;
            s.content_height=std::max(bottom-s.content_top,0.f);
            ImGui::SetCursorPosY(s.content_top);
            ImGui::InvisibleButton("##content-pan",ImVec2(ImGui::GetContentRegionAvail().x,
                std::max(std::max(s.content_height,visible),44.f)));
            s.pan_active=ImGui::IsItemActive();
        }
        // Drag to pan: the list follows the finger from where the press began, capped by the range, so a
        // page that does not scroll does not move either.
        if(s.pan_active) {
            ImVec2 at=ImGui::GetMousePos();
            if(std::isfinite(at.y)) {
                if(!s.panning) {s.panning=true;s.pan_press_y=at.y;s.pan_scroll=scroll;}
                else if(std::abs(at.y-s.pan_press_y)>2.f)
                    ImGui::SetScrollY(std::clamp(s.pan_scroll-(at.y-s.pan_press_y),0.f,std::max(max,0.f)));
            }
        } else s.panning=false;
        // A slim pill stands in for a scroll bar: too thin to aim at by finger, clear enough to say where
        // the list is. It brightens while panning and dims to a reminder when the finger leaves.
        {
            bool movable=max>1.f;
            float wanted=!movable?0.f:s.pan_active?1.f:scroll<=0?0.f:.4f;
            s.scroll_hint+=(wanted-s.scroll_hint)*std::clamp(ImGui::GetIO().DeltaTime*4.f,0.f,1.f);
            if(s.scroll_hint>.02f) {
                const ImGuiStyle &style=ImGui::GetStyle();
                ImDrawList *list=ImGui::GetWindowDrawList();ImVec2 wp=ImGui::GetWindowPos(),ws=ImGui::GetWindowSize();
                float track=ws.y-2*style.WindowPadding.y,x=wp.x+ws.x-style.WindowPadding.x-6.f*s.scale;
                float ratio=std::clamp(ws.y/(ws.y+std::max(max,0.f)),.08f,1.f),height=std::max(30.f*s.scale,track*ratio);
                float travel=std::max(track-height,0.f),top=wp.y+style.WindowPadding.y+
                    travel*(movable?std::clamp(scroll/max,0.f,1.f):0.f);
                list->ChannelsSetCurrent(1);
                list->AddRectFilled(ImVec2(x-3.f*s.scale,top),ImVec2(x+3.f*s.scale,top+height),
                    IM_COL32(120,220,190,(unsigned char)(s.scroll_hint*170.f)),3.f*s.scale);
            }
        }
        s.sections.flush();s.sections.child->ChannelsMerge();s.sections.child=nullptr;nd_sections=nullptr;
        ImGui::EndChild();
        // No scroll buttons: the finger drags the list itself, and the space is better spent on settings.
        ImGui::TextDisabled("%s",zh?"页面可上下拖动":"DRAG TO SCROLL");
    }
    ImVec2 pos=ImGui::GetWindowPos(),size=ImGui::GetWindowSize();
    if(!s.content_active && s.previous_open && s.layer==1) {
        // The quick panel is a way into the full menu, not a place to stay: a tap on its background opens
        // it. Submitted last, so the tabs, the drag bar and the two buttons all keep their press.
        float bottom=std::max(ImGui::GetCursorPosY(),s.quick_top);
        ImGui::SetCursorPos(ImVec2(ImGui::GetStyle().WindowPadding.x,s.quick_top));
        ImVec2 pad=ImGui::GetStyle().WindowPadding;
        ImGui::InvisibleButton("##quick-expand",ImVec2(size.x-2*pad.x,size.y-2*pad.y));
        if(ImGui::IsItemClicked(0)) {s.layer=2;s.scroll=0;}
        ImGui::SetCursorPosY(bottom);
    }
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
