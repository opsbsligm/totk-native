// SPDX-License-Identifier: MIT
// Exercise the production chrome with actual ImGui mouse/touch-style events.
#include "native_sidebar_ui.h"
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
static void frame() {
    boxes.clear();items.clear();ImGui::NewFrame();bool toggle=false;ImVec2 lo,hi;
    if(nd_sidebar_begin(sidebar,opened,anchor,"Native Deck",false,&toggle)) {full_frames++;ImGui::TextUnformatted("Actual setting content");}
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
    io.AddMousePosEvent(origin.x,origin.y);frame();io.AddMouseButtonEvent(0,true);frame();
    io.AddMousePosEvent(60,60);frame();frame();io.AddMouseButtonEvent(0,false);frame();frame();
    assert(!opened && anchor==0);
    tap("##edge-badge");assert(opened && sidebar.layer==1);tap("Hide");assert(!opened);
    ImGui::DestroyContext();
}
int main() {scenario(1280,720);scenario(1280,800);scenario(1920,1080);scenario(800,480);puts("Production three-stage chrome, direct badge drag, bounds and balanced child stack passed");}
