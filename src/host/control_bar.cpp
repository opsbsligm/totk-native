#include "control_preferences.h"
// SDL's event thread only queues bounded value events. ImGui and Vulkan belong
// exclusively to the presentation thread. The panel never maps game buttons.
#include "control_bar.h"
#include "native_cheats.h"
#include "imgui.h"
#include "native_amiibo_ui.h"
#include "native_atmosphere_ui.h"
#include "../vk/fsr.h"
#include "imgui_impl_vulkan.h"
#include <SDL3/SDL_vulkan.h>
#include <atomic>
#include <mutex>
#include <vector>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <algorithm>
#include <unistd.h>
#include <sys/stat.h>
extern "C" {
#include "../vk/vk.h"
void runtime_input_clear(void);
void runtime_motion_start(void);
int runtime_hid_feedback_flag(const char *, int);
}

static std::mutex lock;
static std::vector<SDL_Event> events;
static std::atomic<bool> expanded{false};
static std::atomic<int> fps{-1}, request_w{0}, request_h{0};
static std::atomic<uint32_t> held_buttons{0}, suppressed_buttons{0};
static std::atomic<bool> reset_input{false};
static float x0, y0, x1, y1;
static int anchor=4;
static bool gyro=true;
static ImGuiContext *context;
static VkDescriptorPool descriptors;
static VkFormat backend_format;
static bool backend_ready;
static bool moving_panel;
static bool chinese, scalable_font;
static const ImVec2 anchors[]={{0,0},{.5f,0},{1,0},{1,.5f},{1,1},{.5f,1},{0,1},{0,.5f}};
static const char *label(const char *en,const char *zh) {return chinese?zh:en;}

// Fonts come from the package's checked personal shared-font inputs. Decode a
// private copy; never alter the game font buffer or its on-disk source.
static void *read_ui_font(const char *name,int *bytes) {
    const char *folder=getenv("TOTK_SHARED_FONTS");if(!folder || !*folder) return nullptr;
    char path[4096];int n=snprintf(path,sizeof path,"%s/%s.bfttf",folder,name);
    if(n<0 || (size_t)n>=sizeof path) return nullptr;
    FILE *f=fopen(path,"rb");if(!f) return nullptr;
    if(fseek(f,0,SEEK_END)) {fclose(f);return nullptr;}
    long size=ftell(f);if(size<12 || size>16*1024*1024 || (size-8)%4 || fseek(f,0,SEEK_SET)) {fclose(f);return nullptr;}
    auto *data=(unsigned char *)ImGui::MemAlloc((size_t)size);
    if(!data) {fclose(f);return nullptr;}
    bool ok=fread(data,1,(size_t)size,f)==(size_t)size;fclose(f);
    if(!ok) {ImGui::MemFree(data);return nullptr;}
    auto word=[](const unsigned char *p) {return (uint32_t)p[0]<<24|(uint32_t)p[1]<<16|(uint32_t)p[2]<<8|p[3];};
    uint32_t key=word(data)^0x7f9a0218u;
    if(!ok || (word(data+4)^key)!=(uint32_t)size-8 || ((word(data+8)^key)!=0x10000u && (word(data+8)^key)!=0x4f54544fu)) {ImGui::MemFree(data);return nullptr;}
    for(long i=8;i<size;i+=4) {
        uint32_t w=word(data+i)^key;data[i-8]=w>>24;data[i-7]=w>>16;data[i-6]=w>>8;data[i-5]=w;
    }
    *bytes=(int)size-8;return data;
}
static void fonts(ImGuiIO &io) {
    const char *lang=getenv("TOTK_LANG");chinese=lang && !strncmp(lang,"zh",2);
    int bytes;void *data=read_ui_font("0-standard",&bytes);
    if(data) {
        if(io.Fonts->AddFontFromMemoryTTF(data,bytes,22)) scalable_font=true;
        else ImGui::MemFree(data);
    }
    if(!scalable_font) {io.Fonts->AddFontDefault();chinese=false;return;}
    if(chinese) {
        data=read_ui_font("1-chinese-simplified",&bytes);
        if(data) {
            static ImVector<ImWchar> ranges;ImFontGlyphRangesBuilder builder;
            builder.AddRanges(io.Fonts->GetGlyphRangesDefault());
            builder.AddText("重新加载匹配的金手指文件与支持范围权限只数据堆内存默认全部关闭后停止写入已经改变可能保留刷新本地标签库已读取检测到等待扫描器空闲移开文件选择将自有的放入此目录然后与支持范围身份应用区存档写画面上采样双线性锐化扩展设置收起王国之泪确认返回帧率上限输出尺寸原生陀螺仪重新居中抗锯齿使用游戏默认目前不可用生成金手指未导入匹配版本的预设停靠左上右下边菜单触屏拖动选择位置保存数据已改变拒绝写入打开：");
            builder.BuildRanges(&ranges);ImFontConfig config;config.MergeMode=true;
            if(!io.Fonts->AddFontFromMemoryTTF(data,bytes,22,&config,ranges.Data)) {ImGui::MemFree(data);chinese=false;}
        } else chinese=false;
    }
}

int nd_control_captured(void) { return expanded.load(); }
uint32_t nd_control_suppressed_pad_buttons(void) {return suppressed_buttons.load();}
int nd_control_fps_limit(void) { return fps.load(); }
static void toggle() {
    expanded=!expanded.load();
    suppressed_buttons.fetch_or(held_buttons.load());
    runtime_input_clear();
}
int nd_control_event(const SDL_Event *event, SDL_Window *window) {
    static bool back, start;
    if(event->type==SDL_EVENT_GAMEPAD_BUTTON_DOWN || event->type==SDL_EVENT_GAMEPAD_BUTTON_UP) {
        bool down=event->type==SDL_EVENT_GAMEPAD_BUTTON_DOWN;
        if(event->gbutton.button<32) {
            uint32_t bit=1u<<event->gbutton.button;
            if(down) held_buttons.fetch_or(bit);
            else {held_buttons.fetch_and(~bit);suppressed_buttons.fetch_and(~bit);}
            if(expanded.load()) suppressed_buttons.fetch_or(held_buttons.load());
        }
        if(event->gbutton.button==SDL_GAMEPAD_BUTTON_BACK) back=down;
        if(event->gbutton.button==SDL_GAMEPAD_BUTTON_START) start=down;
        if(down && back && start) { toggle(); return 1; }
    }
    if(event->type==SDL_EVENT_KEY_DOWN && event->key.scancode==SDL_SCANCODE_F1 && !event->key.repeat) { toggle(); return 1; }
    if(event->type==SDL_EVENT_WINDOW_FOCUS_LOST || event->type==SDL_EVENT_GAMEPAD_REMOVED) {
        back=start=false;
        held_buttons=0;suppressed_buttons=0;
        reset_input=true;
        std::lock_guard<std::mutex> guard(lock); events.clear();
        return 0;
    }
    SDL_Event copy=*event;
    bool pointer=event->type==SDL_EVENT_MOUSE_MOTION || event->type==SDL_EVENT_MOUSE_BUTTON_DOWN || event->type==SDL_EVENT_MOUSE_BUTTON_UP;
    bool hit=false;
    if(pointer) {
        int w,h,pw,ph; SDL_GetWindowSize(window,&w,&h); SDL_GetWindowSizeInPixels(window,&pw,&ph);
        float sx=w>0 ? (float)pw/w : 1, sy=h>0 ? (float)ph/h : 1;
        float px,py;
        if(event->type==SDL_EVENT_MOUSE_MOTION) { copy.motion.x*=sx; copy.motion.y*=sy; px=copy.motion.x; py=copy.motion.y; }
        else { copy.button.x*=sx; copy.button.y*=sy; px=copy.button.x; py=copy.button.y; }
        std::lock_guard<std::mutex> guard(lock); hit=px>=x0 && py>=y0 && px<x1 && py<y1;
    }
    bool captured=nd_control_captured();
    bool values=pointer || event->type==SDL_EVENT_KEY_DOWN || event->type==SDL_EVENT_KEY_UP ||
        event->type==SDL_EVENT_GAMEPAD_BUTTON_DOWN || event->type==SDL_EVENT_GAMEPAD_BUTTON_UP;
    bool release=event->type==SDL_EVENT_KEY_UP || event->type==SDL_EVENT_GAMEPAD_BUTTON_UP || event->type==SDL_EVENT_MOUSE_BUTTON_UP;
    if(((captured || hit) && values) || release) {
        std::lock_guard<std::mutex> guard(lock);
        if(events.size()<256) events.push_back(copy);
        else { events.clear(); expanded=false; reset_input=true;suppressed_buttons.fetch_or(held_buttons.load()); }
    }
    return (captured || hit) && (values || event->type==SDL_EVENT_GAMEPAD_AXIS_MOTION || event->type==SDL_EVENT_MOUSE_WHEEL);
}

void nd_control_apply_window(SDL_Window *window) {
    int w=request_w.exchange(0), h=request_h.exchange(0);
    if(w && h && !SDL_SetWindowSize(window,w,h)) fprintf(stderr,"[control] resolution change failed: %s\n",SDL_GetError());
}

static ImGuiKey key(const SDL_Event &event) {
    if(event.type==SDL_EVENT_GAMEPAD_BUTTON_DOWN || event.type==SDL_EVENT_GAMEPAD_BUTTON_UP) {
        switch(event.gbutton.button) {
        case SDL_GAMEPAD_BUTTON_SOUTH:return ImGuiKey_GamepadFaceDown;
        case SDL_GAMEPAD_BUTTON_EAST:return ImGuiKey_GamepadFaceRight;
        case SDL_GAMEPAD_BUTTON_DPAD_UP:return ImGuiKey_GamepadDpadUp;
        case SDL_GAMEPAD_BUTTON_DPAD_DOWN:return ImGuiKey_GamepadDpadDown;
        case SDL_GAMEPAD_BUTTON_DPAD_LEFT:return ImGuiKey_GamepadDpadLeft;
        case SDL_GAMEPAD_BUTTON_DPAD_RIGHT:return ImGuiKey_GamepadDpadRight;
        default:return ImGuiKey_None;
        }
    }
    switch(event.key.scancode) {
    case SDL_SCANCODE_UP:return ImGuiKey_UpArrow; case SDL_SCANCODE_DOWN:return ImGuiKey_DownArrow;
    case SDL_SCANCODE_LEFT:return ImGuiKey_LeftArrow; case SDL_SCANCODE_RIGHT:return ImGuiKey_RightArrow;
    case SDL_SCANCODE_RETURN:return ImGuiKey_Enter; case SDL_SCANCODE_ESCAPE:return ImGuiKey_Escape;
    default:return ImGuiKey_None;
    }
}

static void drain(ImGuiIO &io) {
    if(reset_input.exchange(false)) { io.ClearInputKeys(); io.ClearInputMouse(); }
    std::vector<SDL_Event> pending;
    {std::lock_guard<std::mutex> guard(lock); pending.swap(events);}
    for(const SDL_Event &event:pending) {
        if(event.type==SDL_EVENT_MOUSE_MOTION) io.AddMousePosEvent(event.motion.x,event.motion.y);
        else if(event.type==SDL_EVENT_MOUSE_BUTTON_DOWN || event.type==SDL_EVENT_MOUSE_BUTTON_UP) {
            io.AddMousePosEvent(event.button.x,event.button.y);
            if(event.button.button==SDL_BUTTON_LEFT) io.AddMouseButtonEvent(0,event.type==SDL_EVENT_MOUSE_BUTTON_DOWN);
        } else {
            ImGuiKey k=key(event);
            if(k!=ImGuiKey_None) io.AddKeyEvent(k,event.type==SDL_EVENT_KEY_DOWN || event.type==SDL_EVENT_GAMEPAD_BUTTON_DOWN);
        }
    }
}

// Preferences contain no guest addresses or private assets. Rename is same-volume.
static void preferences(bool save) {
    const char *data=getenv("XDG_CONFIG_HOME"), *home=getenv("HOME");
    char folder[4096],path[4096];
    if((!data || *data!='/') && (!home || *home!='/')) return;
    int n=data && *data=='/' ? snprintf(folder,sizeof folder,"%s/totk-native",data) :
        snprintf(folder,sizeof folder,"%s/.config/totk-native",home?home:".");
    if(n<0 || (size_t)n>=sizeof folder) return;
    // Parent .config normally exists on SteamOS; never create files in cwd on failure.
    mkdir(folder,0700);
    n=snprintf(path,sizeof path,"%s/control.ini",folder);
    if(n<0 || (size_t)n>=sizeof path) return;
    if(!save) {
        int a,rate,enabled,up,sharp;
        if(nd_control_preferences_read_extended(path,&a,&rate,&enabled,&up,&sharp)) {
            anchor=a; fps=rate; gyro=enabled!=0;nd_fsr_configure(up,sharp); runtime_hid_feedback_flag("gyro",gyro);
        }
        return;
    }
    char temp[4096]; n=snprintf(temp,sizeof temp,"%s.new-XXXXXX",path);
    if(n<0 || (size_t)n>=sizeof temp) return;
    int fd=mkstemp(temp); if(fd<0) return;
    FILE *f=fdopen(fd,"w"); if(!f) {close(fd);unlink(temp);return;}
    bool ok=fprintf(f,"anchor=%d\nfps=%d\ngyro=%d\nupscaler=%d\nsharpness=%d\n",anchor,fps.load(),gyro,nd_fsr_enabled(),nd_fsr_sharpness())>0;
    if(fflush(f) || fsync(fd)) ok=false;
    if(fclose(f)) ok=false;
    if(!ok || rename(temp,path)) unlink(temp);
}

static PFN_vkVoidFunction load(const char *name, void *) {
    auto address=vk.vkGetDeviceProcAddr(vkc.device,name);
    if(address) return address;
    auto get=vk.vkGetInstanceProcAddr;
    address=get ? get(vkc.instance,name) : nullptr;
    if(!address) fprintf(stderr,"[control] Vulkan entry point unavailable: %s\n",name);
    return address;
}
void nd_control_device_reset(void) {
    if(!context) return;
    ImGui::SetCurrentContext(context);
    if(ImGui::GetIO().BackendRendererUserData) ImGui_ImplVulkan_Shutdown();
    if(descriptors) vk.vkDestroyDescriptorPool(vkc.device,descriptors,nullptr);
    descriptors=VK_NULL_HANDLE; backend_ready=false;
}

void nd_control_draw(VkCommandBuffer command,VkImageView target,VkFormat format,uint32_t width,uint32_t height) {
    if(width<240 || height<200) return;
    if(!context) {
        context=ImGui::CreateContext();
        ImGuiIO &io=ImGui::GetIO(); io.IniFilename=nullptr;
        io.ConfigFlags|=ImGuiConfigFlags_NavEnableGamepad | ImGuiConfigFlags_NavEnableKeyboard;
        io.BackendFlags|=ImGuiBackendFlags_HasGamepad;
        fonts(io); ImGui::StyleColorsDark();
        ImGui::GetStyle().WindowRounding=8;ImGui::GetStyle().FrameRounding=4;
        preferences(false);
    }
    ImGui::SetCurrentContext(context);
    if(backend_ready && backend_format!=format) nd_control_device_reset();
    if(!backend_ready) {
        VkDescriptorPoolSize size={VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,64};
        VkDescriptorPoolCreateInfo pool={}; pool.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
        pool.flags=VK_DESCRIPTOR_POOL_CREATE_FREE_DESCRIPTOR_SET_BIT;pool.maxSets=64;pool.poolSizeCount=1;pool.pPoolSizes=&size;
        if(vk.vkCreateDescriptorPool(vkc.device,&pool,nullptr,&descriptors)!=VK_SUCCESS) return;
        if(!ImGui_ImplVulkan_LoadFunctions(VK_API_VERSION_1_3,load)) {nd_control_device_reset();return;}
        ImGui_ImplVulkan_InitInfo info={}; info.ApiVersion=VK_API_VERSION_1_3;
        info.Instance=vkc.instance;info.PhysicalDevice=vkc.gpu;info.Device=vkc.device;
        info.QueueFamily=vkc.family;info.Queue=vkc.queue;info.DescriptorPool=descriptors;
        info.MinImageCount=2;info.ImageCount=2;info.MSAASamples=VK_SAMPLE_COUNT_1_BIT;info.UseDynamicRendering=true;
        info.PipelineRenderingCreateInfo.sType=VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO;
        info.PipelineRenderingCreateInfo.colorAttachmentCount=1;
        backend_format=format;
        info.PipelineRenderingCreateInfo.pColorAttachmentFormats=&backend_format;
        if(!ImGui_ImplVulkan_Init(&info)) {nd_control_device_reset();return;}
        backend_ready=true;backend_format=format;
        // Font upload uses the shared graphics queue internally.
        vk_queue_lock(); bool fonts_ready=ImGui_ImplVulkan_CreateFontsTexture(); vk_queue_unlock();
        if(!fonts_ready) {nd_control_device_reset();return;}
    }
    ImGuiIO &io=ImGui::GetIO(); io.DisplaySize=ImVec2((float)width,(float)height);
    static uint64_t last;uint64_t now=SDL_GetTicksNS();
    io.DeltaTime=last && now>last ? (float)((now-last)*1e-9) : 1.f/60;last=now;
    io.FontGlobalScale=scalable_font?std::min(1.f,height/720.f):(height>=720?1.6f:1.3f);
    drain(io); ImGui_ImplVulkan_NewFrame(); ImGui::NewFrame();
    bool open=expanded.load();
    static int old_anchor=-1;static bool old_open;
    if(!moving_panel || old_anchor!=anchor || old_open!=open) {
        ImVec2 p=anchors[anchor];
        ImGui::SetNextWindowPos(ImVec2(12+p.x*(width-24),12+p.y*(height-24)),ImGuiCond_Always,p);
        old_anchor=anchor;old_open=open;
    }
    ImGui::SetNextWindowBgAlpha(.96f);
    ImGui::SetNextWindowSizeConstraints(ImVec2(std::min(open?330.f:0.f,(float)width-24),0),ImVec2(width-24,height-24));
    ImGui::Begin("##deck-control",nullptr,ImGuiWindowFlags_AlwaysAutoResize|ImGuiWindowFlags_NoTitleBar|ImGuiWindowFlags_NoSavedSettings);
    if(ImGui::Button(open?label("Collapse [-]","收起 [-]"):label("Settings [+]","设置 [+]"),ImVec2(150,40))) {toggle();preferences(true);}
    if(open) {
        ImGui::SameLine(); ImGui::TextUnformatted(label("TOTK / DECK","王国之泪"));ImGui::Separator();
        ImGui::TextUnformatted(label("A: confirm   B: back","A 确认    B 返回"));
        static const char *rates[]={"30","40","45","60","90","120"};
        static const int values[]={30,40,45,60,90,120};int selected=3;
        for(int i=0;i<6;++i) if(fps.load()==values[i]) selected=i;
        if(ImGui::Combo(label("Frame cap","帧率上限"),&selected,rates,6)) {fps=values[selected];preferences(true);}
        const char *sizes[]={"960 x 540","1280 x 720","1280 x 800","1920 x 1080"};
        const int ws[]={960,1280,1280,1920},hs[]={540,720,800,1080};static int size=2;
        if(ImGui::Combo(label("Output size","输出尺寸"),&size,sizes,4)) {request_h=hs[size];request_w=ws[size];}
        if(ImGui::Checkbox(label("Native sensor motion","原生陀螺仪"),&gyro)) {runtime_hid_feedback_flag("gyro",gyro);preferences(true);}
        if(ImGui::Button(label("Recenter motion","重新居中"))) runtime_motion_start();
        ImGui::Separator();
        int upscaler=nd_fsr_enabled();const char *upscalers[]={label("Bilinear","双线性"),"AMD FSR 1 (EASU / RCAS)"};
        if(ImGui::Combo(label("Presentation upscaling","画面上采样"),&upscaler,upscalers,2)) {nd_fsr_configure(upscaler,nd_fsr_sharpness());preferences(true);}
        if(upscaler) {
            int sharp=nd_fsr_sharpness();
            if(ImGui::SliderInt(label("Sharpness","锐化"),&sharp,0,100)) {nd_fsr_configure(1,sharp);preferences(true);}
            if(nd_fsr_status()<0) ImGui::TextWrapped("%s",label("FSR unavailable; bilinear fallback active","FSR 不可用；已使用双线性"));
        }
        ImGui::TextDisabled("%s",label("Anti-aliasing: game's default","抗锯齿：使用游戏默认"));
        ImGui::TextDisabled("%s",label("FSR 3 / 4: unavailable","FSR 3 / 4：目前不可用"));
        ImGui::TextDisabled("%s",label("Frame generation: unavailable","帧生成：目前不可用"));
        nd_draw_amiibo_library("totk-native",chinese);
        nd_draw_atmosphere("totk-native",chinese);
        ImGui::Separator(); ImGui::TextUnformatted(label("Cheats","金手指"));
        if(!nd_cheats_count()) ImGui::TextDisabled("%s",label("No compatible presets imported","未导入匹配版本的预设"));
        for(size_t i=0;i<nd_cheats_count();i++) {
            bool on=nd_cheats_enabled(i)!=0;
            if(ImGui::Checkbox(nd_cheats_name(i),&on)) nd_cheats_request(i,on);
        }
        if(*nd_cheats_error()) ImGui::TextWrapped("%s",nd_cheats_error());
        const char *docks[]={label("Top left","左上"),label("Top","上边"),label("Top right","右上"),label("Right","右边"),label("Bottom right","右下"),label("Bottom","下边"),label("Bottom left","左下"),label("Left","左边")};
        if(ImGui::Combo(label("Dock","停靠"),&anchor,docks,8)) preferences(true);
        ImGui::TextDisabled("%s",label("F1 / Minus+Plus opens this panel","F1 / Minus+Plus 打开设置"));
        if(ImGui::IsKeyPressed(ImGuiKey_GamepadFaceRight) || ImGui::IsKeyPressed(ImGuiKey_Escape)) {toggle();preferences(true);}
    }
    ImVec2 position=ImGui::GetWindowPos(),size=ImGui::GetWindowSize();
    {std::lock_guard<std::mutex> guard(lock);x0=position.x;y0=position.y;x1=x0+size.x;y1=y0+size.y;}
    if(ImGui::IsWindowHovered() && ImGui::IsMouseClicked(0) && !ImGui::IsAnyItemHovered()) moving_panel=true;
    if(moving_panel && ImGui::IsMouseReleased(0)) {
        moving_panel=false;
        ImVec2 drag=ImGui::GetMouseDragDelta(0);
        if(drag.x*drag.x+drag.y*drag.y>100) {
            float best=1e30f;
            for(int i=0;i<8;++i) {
                float dx=(position.x+size.x*.5f)/width-anchors[i].x,dy=(position.y+size.y*.5f)/height-anchors[i].y;
                float d=dx*dx+dy*dy;if(d<best) {best=d;anchor=i;}
            }
            old_anchor=-1;preferences(true);
        }
    }
    ImGui::End(); ImGui::Render();
    VkRenderingAttachmentInfo color={};color.sType=VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO;
    color.imageView=target;color.imageLayout=VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    color.loadOp=VK_ATTACHMENT_LOAD_OP_LOAD;color.storeOp=VK_ATTACHMENT_STORE_OP_STORE;
    VkRenderingInfo rendering={};rendering.sType=VK_STRUCTURE_TYPE_RENDERING_INFO;
    rendering.renderArea.extent={width,height};rendering.layerCount=1;rendering.colorAttachmentCount=1;rendering.pColorAttachments=&color;
    vk.vkCmdBeginRendering(command,&rendering);
    ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(),command);
    vk.vkCmdEndRendering(command);
}
