// SPDX-License-Identifier: MIT
// Exercise the production chrome with actual ImGui mouse/touch-style events.
#include "native_sidebar_ui.h"
#include "native_touch.h"
#include "native_imgui_input.h"
#include "imgui_internal.h"
#include <cassert>
#include <cstdio>
#include <map>
#include <string>
static std::map<ImGuiID,ImRect> boxes;
static std::map<std::string,ImRect> items;
void ImGuiTestEngineHook_ItemAdd(ImGuiContext*,ImGuiID id,const ImRect &r,const ImGuiLastItemData*) {boxes[id]=r;}
void ImGuiTestEngineHook_ItemInfo(ImGuiContext*,ImGuiID id,const char *label,ImGuiItemStatusFlags) {if(boxes.count(id)) items[label]=boxes[id];}
void ImGuiTestEngineHook_Log(ImGuiContext*,const char*,...) {}
const char *ImGuiTestEngine_FindItemDebugLabel(ImGuiContext*,ImGuiID) {return nullptr;}
static NdSidebar sidebar;
static bool opened;
static int anchor=4,full_frames;
static NdPointer pointer;
static void frame() {
    boxes.clear();items.clear();ImGui::NewFrame();bool toggle=false;ImVec2 lo,hi;
    if(nd_sidebar_begin(sidebar,opened,anchor,"Native Deck",false,&toggle)) {full_frames++;ImGui::TextUnformatted("Actual setting content");}
    assert(ImGui::GetStyle().Colors[ImGuiCol_WindowBg].w==1);
    assert(ImGui::GetStyle().Colors[ImGuiCol_PopupBg].w==1);
    nd_sidebar_end(sidebar,opened,&anchor,false,&lo,&hi);
    if(toggle) opened=!opened;
    ImGui::Render();
    auto size=ImGui::GetIO().DisplaySize;
    assert(lo.x>=0 && lo.y>=0 && hi.x<=size.x+.01f && hi.y<=size.y+.01f);
}
static void tap(const char *label) {
    assert(items.count(label));ImVec2 p=items[label].GetCenter();auto &io=ImGui::GetIO();
    io.AddMousePosEvent(p.x,p.y);frame();io.AddMouseButtonEvent(0,true);frame();
    io.AddMouseButtonEvent(0,false);frame();frame();
}
static void route(int type,ImVec2 p) {
    auto &io=ImGui::GetIO();auto size=io.DisplaySize;
    bool hit=items.count("##edge-badge") && items["##edge-badge"].Contains(p);
    NdTouchResult r=nd_pointer_mouse(&pointer,type,7,p.x,p.y,size.x,size.y,hit,opened);
    assert(r.consumed && r.emit);
    io.AddMouseSourceEvent(ImGuiMouseSource_Mouse);io.AddMousePosEvent(r.x,r.y);
    if(type!=ND_TOUCH_MOVE) io.AddMouseButtonEvent(0,r.down);
    frame();
}
static void scenario(float width,float height) {
    ImGui::CreateContext();auto &io=ImGui::GetIO();io.IniFilename=nullptr;io.DisplaySize=ImVec2(width,height);io.DeltaTime=1.f/60;
    unsigned char *p;int w,h;io.Fonts->GetTexDataAsRGBA32(&p,&w,&h);
    ImGui::GetCurrentContext()->TestEngineHookItems=true;sidebar=NdSidebar();opened=false;anchor=4;full_frames=0;
    frame();frame();assert(!opened && full_frames==0);
    assert(items.count("##edge-badge"));assert(items["##edge-badge"].GetWidth()>=44);
    tap("##edge-badge");assert(opened && full_frames==0 && sidebar.layer==1);
    assert(items.count("Open full settings"));assert(!items.count("Actual setting content"));
    tap("Open full settings");assert(opened && sidebar.layer==2 && full_frames>0);
    tap("Back");assert(opened && sidebar.layer==1);
    tap("Cheats");assert(opened && sidebar.layer==2 && sidebar.page==3);
    tap("Hide");assert(!opened);
    // Drag the collapsed badge to the opposite corner without opening it.
    assert(items.count("##edge-badge"));ImVec2 origin=items["##edge-badge"].GetCenter();
    pointer=NdPointer();route(ND_TOUCH_MOVE,origin);route(ND_TOUCH_DOWN,origin);
    route(ND_TOUCH_MOVE,ImVec2(60,60));frame();route(ND_TOUCH_UP,ImVec2(60,60));frame();
    assert(!opened && anchor==0);
    tap("##edge-badge");assert(opened && sidebar.layer==1);tap("Hide");assert(!opened);
    // Cancel queued DOWN without losing another input source's release.
    io.AddKeyEvent(ImGuiKey_F24,true);frame();assert(ImGui::IsKeyDown(ImGuiKey_F24));
    ImVec2 badge=items["##edge-badge"].GetCenter();
    io.AddMousePosEvent(badge.x,badge.y);io.AddMouseButtonEvent(0,true);
    io.AddKeyEvent(ImGuiKey_F24,false);nd_imgui_cancel_pointer(io);frame();frame();
    assert(!io.MouseDown[0] && !ImGui::IsKeyDown(ImGuiKey_F24) && !opened);
    // Also discard mouse events left for another frame by ImGui's trickling.
    io.AddMousePosEvent(badge.x,badge.y);io.AddMouseButtonEvent(0,true);frame();
    io.AddMouseButtonEvent(0,false);io.AddMouseButtonEvent(0,true);
    nd_imgui_cancel_pointer(io);frame();frame();assert(!io.MouseDown[0] && !opened);
    // Full reset is a barrier before, not after, a fresh gesture in that batch.
    io.AddMousePosEvent(badge.x,badge.y);io.AddMouseButtonEvent(0,true);io.AddKeyEvent(ImGuiKey_F24,true);
    nd_imgui_reset_input(io);assert(io.Ctx->InputEventsQueue.empty());
    frame();assert(!io.MouseDown[0] && !ImGui::IsKeyDown(ImGuiKey_F24));
    tap("##edge-badge");assert(opened && sidebar.layer==1);tap("Hide");assert(!opened);
    puts("Queued pointer cancellation preserves key releases; full reset accepts fresh gestures PASS");
    ImGui::DestroyContext();
}
int main() {scenario(1280,720);scenario(1280,800);scenario(1920,1080);scenario(800,480);puts("Production three-stage chrome, direct badge drag, bounds and balanced child stack passed");}
