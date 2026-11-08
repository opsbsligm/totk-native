#include "control_preferences.h"
// SDL's event thread only queues bounded value events. ImGui and Vulkan belong
// exclusively to the presentation thread. The panel never maps game buttons.
#include "control_bar.h"
#include "native_cheats.h"
#include "native_touch.h"
#include "native_ui_glyphs.h"
#include "imgui.h"
#include "native_imgui_input.h"
#include "native_sidebar_ui.h"
#include "native_amiibo_catalog.h"
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
// Owned only by SDL's event thread; publish capture to the game thread.
static NdPointer pointer={};
static std::atomic<bool> pointer_active{false};
static std::atomic<int> fps{-1}, request_w{0}, request_h{0};
static std::atomic<uint32_t> held_buttons{0}, suppressed_buttons{0};
static std::atomic<bool> reset_input{false};
static float hit_left, hit_top, hit_right, hit_bottom, touch_width, touch_height;
static int anchor=4;
static bool gyro=true;
static ImGuiContext *context;
static VkDescriptorPool descriptors;
static VkFormat backend_format;
static bool backend_ready;

static bool chinese, scalable_font;

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
            builder.AddRanges(io.Fonts->GetGlyphRangesChineseSimplifiedCommon());
            builder.AddText("画面功能说明高级数据补丁画面扩展控制重新加载匹配的金手指文件与支持范围权限只数据堆内存默认全部关闭后停止写入已经改变可能保留刷新本地标签库已读取检测到等待扫描器空闲移开文件选择将自有的放入此目录然后与支持范围身份应用区存档写画面上采样双线性锐化扩展设置收起王国之泪确认返回帧率上限输出尺寸原生陀螺仪重新居中抗锯齿使用游戏默认目前不可用生成金手指未导入匹配版本的预设停靠左上右下边菜单触屏拖动选择位置保存数据已改变拒绝写入打开：");
            builder.AddText(nd_ui_zh_glyphs);
            for(const auto &figure:nd_virtual_figures) builder.AddText(figure.zh);
            builder.BuildRanges(&ranges);ImFontConfig config;config.MergeMode=true;
            if(!io.Fonts->AddFontFromMemoryTTF(data,bytes,22,&config,ranges.Data)) {ImGui::MemFree(data);chinese=false;}
        } else chinese=false;
    }
}

int nd_control_captured(void) { return expanded.load() || pointer_active.load(); }
uint32_t nd_control_suppressed_pad_buttons(void) {return suppressed_buttons.load();}
int nd_control_fps_limit(void) { return fps.load(); }
static void toggle() {
    expanded=!expanded.load();
    suppressed_buttons.fetch_or(held_buttons.load());
    runtime_input_clear();
}
// The caller holds lock. A dropped DOWN/UP must not leave an owner or pressed
// ImGui state alive after the bounded event queue is discarded.
static void enqueue(const SDL_Event &event) {
    if(events.size()<256) {events.push_back(event);return;}
    events.clear();expanded=false;reset_input=true;
    nd_pointer_reset(&pointer);pointer_active=false;
    suppressed_buttons.fetch_or(held_buttons.load());runtime_input_clear();
}
static void publish_pointer_capture() {
    bool active=nd_pointer_active(&pointer);
    bool previous=pointer_active.exchange(active);
    if(active && !previous) {
        suppressed_buttons.fetch_or(held_buttons.load());
        runtime_input_clear();
    }
}
int nd_control_event(const SDL_Event *event, SDL_Window *window) {
    if(event->type==SDL_EVENT_FINGER_DOWN || event->type==SDL_EVENT_FINGER_MOTION ||
       event->type==SDL_EVENT_FINGER_UP || event->type==SDL_EVENT_FINGER_CANCELED) {
        std::lock_guard<std::mutex> guard(lock);
        float w=touch_width,h=touch_height,px=event->tfinger.x*w,py=event->tfinger.y*h;
        int type=event->type==SDL_EVENT_FINGER_DOWN?ND_TOUCH_DOWN:event->type==SDL_EVENT_FINGER_MOTION?ND_TOUCH_MOVE:
                 event->type==SDL_EVENT_FINGER_UP?ND_TOUCH_UP:ND_TOUCH_CANCEL;
        NdTouchResult r=nd_pointer_touch(&pointer,type,event->tfinger.touchID,event->tfinger.fingerID,
                                     event->tfinger.x,event->tfinger.y,w,h,px>=hit_left && py>=hit_top && px<hit_right && py<hit_bottom,expanded.load());
        if(r.emit) {
            SDL_Event copy=*event;copy.tfinger.x=r.x;copy.tfinger.y=r.y;
            if(r.cancel) copy.type=SDL_EVENT_FINGER_CANCELED;
            enqueue(copy);
        }
        publish_pointer_capture();
        return r.consumed;
    }
    if((event->type==SDL_EVENT_MOUSE_MOTION && event->motion.which==SDL_TOUCH_MOUSEID) ||
       ((event->type==SDL_EVENT_MOUSE_BUTTON_DOWN || event->type==SDL_EVENT_MOUSE_BUTTON_UP) && event->button.which==SDL_TOUCH_MOUSEID)) return 1;
    if(event->type==SDL_EVENT_MOUSE_MOTION ||
       ((event->type==SDL_EVENT_MOUSE_BUTTON_DOWN || event->type==SDL_EVENT_MOUSE_BUTTON_UP) && event->button.button==SDL_BUTTON_LEFT)) {
        int w=0,h=0,pw=0,ph=0;
        bool dimensions=SDL_GetWindowSize(window,&w,&h) && SDL_GetWindowSizeInPixels(window,&pw,&ph) && w>0 && h>0 && pw>0 && ph>0;
        float sx=w>0?(float)pw/w:1,sy=h>0?(float)ph/h:1;
        bool motion=event->type==SDL_EVENT_MOUSE_MOTION;
        float x=dimensions?(motion?event->motion.x:event->button.x)*sx:NAN;
        float y=dimensions?(motion?event->motion.y:event->button.y)*sy:NAN;
        int type=motion?ND_TOUCH_MOVE:event->type==SDL_EVENT_MOUSE_BUTTON_DOWN?ND_TOUCH_DOWN:ND_TOUCH_UP;
        uint64_t device=motion?event->motion.which:event->button.which;
        std::lock_guard<std::mutex> guard(lock);
        NdTouchResult r=nd_pointer_mouse(&pointer,type,device,x,y,touch_width,touch_height,
                                       x>=hit_left && y>=hit_top && x<hit_right && y<hit_bottom,expanded.load());
        if(r.emit) {
            SDL_Event copy=*event;
            if(r.cancel) copy.type=SDL_EVENT_FINGER_CANCELED;
            else if(motion) {copy.motion.x=r.x;copy.motion.y=r.y;}
            else {copy.button.x=r.x;copy.button.y=r.y;}
            enqueue(copy);
        }
        publish_pointer_capture();return r.consumed;
    }
    if(event->type==SDL_EVENT_MOUSE_REMOVED) {
        std::lock_guard<std::mutex> guard(lock);
        bool owned=nd_pointer_remove_mouse(&pointer,event->mdevice.which);
        if(owned) {SDL_Event cancel={};cancel.type=SDL_EVENT_FINGER_CANCELED;enqueue(cancel);}
        publish_pointer_capture();return owned;
    }
    // The UI has one left pointer. Other mouse buttons/wheels cannot change
    // an existing touch or steal that pointer's pressed state.
    if(event->type==SDL_EVENT_MOUSE_BUTTON_DOWN || event->type==SDL_EVENT_MOUSE_BUTTON_UP || event->type==SDL_EVENT_MOUSE_WHEEL)
        return nd_control_captured();
    if(event->type==SDL_EVENT_GAMEPAD_BUTTON_DOWN || event->type==SDL_EVENT_GAMEPAD_BUTTON_UP) {
        bool down=event->type==SDL_EVENT_GAMEPAD_BUTTON_DOWN;
        if(event->gbutton.button<32) {
            uint32_t bit=1u<<event->gbutton.button;
            if(down) held_buttons.fetch_or(bit);
            else {held_buttons.fetch_and(~bit);suppressed_buttons.fetch_and(~bit);}
            if(nd_control_captured()) suppressed_buttons.fetch_or(held_buttons.load());
        }
    }
    if(event->type==SDL_EVENT_WINDOW_FOCUS_LOST || event->type==SDL_EVENT_GAMEPAD_REMOVED) {
        std::lock_guard<std::mutex> guard(lock);
        nd_pointer_reset(&pointer);pointer_active=false;
        held_buttons=0;suppressed_buttons=0;
        reset_input=true;
        events.clear();
        return 0;
    }
    bool captured=nd_control_captured();
    bool values=event->type==SDL_EVENT_KEY_DOWN || event->type==SDL_EVENT_KEY_UP ||
        event->type==SDL_EVENT_GAMEPAD_BUTTON_DOWN || event->type==SDL_EVENT_GAMEPAD_BUTTON_UP;
    bool release=event->type==SDL_EVENT_KEY_UP || event->type==SDL_EVENT_GAMEPAD_BUTTON_UP;
    if((captured && values) || release) {
        std::lock_guard<std::mutex> guard(lock);
        enqueue(*event);
    }
    return captured && (values || event->type==SDL_EVENT_GAMEPAD_AXIS_MOTION);
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
    bool reset;
    std::vector<SDL_Event> pending;
    {std::lock_guard<std::mutex> guard(lock);reset=reset_input.exchange(false);pending.swap(events);}
    if(reset) nd_imgui_reset_input(io);
    for(const SDL_Event &event:pending) {
        if(event.type==SDL_EVENT_FINGER_DOWN || event.type==SDL_EVENT_FINGER_MOTION || event.type==SDL_EVENT_FINGER_UP) {
            io.AddMouseSourceEvent(ImGuiMouseSource_TouchScreen);
            io.AddMousePosEvent(event.tfinger.x,event.tfinger.y);
            if(event.type!=SDL_EVENT_FINGER_MOTION) io.AddMouseButtonEvent(0,event.type==SDL_EVENT_FINGER_DOWN);
        } else if(event.type==SDL_EVENT_FINGER_CANCELED) nd_imgui_cancel_pointer(io);
        else if(event.type==SDL_EVENT_MOUSE_MOTION) {io.AddMouseSourceEvent(ImGuiMouseSource_Mouse);io.AddMousePosEvent(event.motion.x,event.motion.y);}
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
    {std::lock_guard<std::mutex> guard(lock);touch_width=(float)width;touch_height=(float)height;}
    ImGuiIO &io=ImGui::GetIO(); io.DisplaySize=ImVec2((float)width,(float)height);
    static uint64_t last;uint64_t now=SDL_GetTicksNS();
    io.DeltaTime=last && now>last ? (float)((now-last)*1e-9) : 1.f/60;last=now;
    io.FontGlobalScale=scalable_font?std::min(1.f,height/720.f):(height>=720?1.6f:1.3f);
    drain(io); ImGui_ImplVulkan_NewFrame(); ImGui::NewFrame();
    bool open=expanded.load(),want_toggle=false,dirty=false;
    static NdSidebar sidebar;
    bool content=nd_sidebar_begin(sidebar,open,anchor,label("Tears of the Kingdom","王国之泪"),chinese,&want_toggle);
    if(content) {
        if(sidebar.page==0) {
            nd_ui_status(label("Live presentation settings","即时画面设置"));
            ImGui::Text(label("Current output: %u x %u","当前输出：%u × %u"),width,height);
            nd_ui_label(label("Frame cap","帧率上限"));
            static const char *rates[]={"30","40","45","60","90","120"};
            static const int values[]={30,40,45,60,90,120};int selected=3;
            for(int i=0;i<6;++i) if(fps.load()==values[i]) selected=i;
            if(nd_ui_choice("##frame-cap",&selected,rates,6)) {fps=values[selected];dirty=true;}
            nd_ui_label(label("Presentation upscaling","画面上采样"));
            int up=nd_fsr_enabled();const char *methods[]={label("Bilinear","双线性"),"AMD FSR 1"};
            if(nd_ui_choice("##upscaler",&up,methods,2)) {nd_fsr_configure(up,nd_fsr_sharpness());dirty=true;}
            if(up) {
                nd_ui_label(label("Sharpness","锐化强度"));int sharp=nd_fsr_sharpness();
                if(ImGui::SliderInt("##sharpness",&sharp,0,100,"%d%%")) nd_fsr_configure(1,sharp);
                if(ImGui::IsItemDeactivatedAfterEdit()) dirty=true;
                int status=nd_fsr_status();
                nd_ui_status(status>0?label("FSR backend ready","FSR 后端已就绪"):status<0?label("FSR failed; bilinear fallback","FSR 不可用，已回退双线性"):label("Awaiting presentation frame","等待呈现帧应用"),status);
            }
            ImGui::TextWrapped("%s",label("FSR scales the presented image. It does not change game rendering resolution.","FSR 缩放最终画面，不改变游戏内部渲染分辨率。"));
            if(ImGui::TreeNode(label("Window size / capabilities","窗口尺寸与能力说明"))) {
                nd_ui_label(label("Window size (windowed mode)","窗口尺寸（窗口模式）"));
                const char *sizes[]={"960 x 540","1280 x 720","1280 x 800","1920 x 1080"};
                const int ws[]={960,1280,1280,1920},hs[]={540,720,800,1080};static int size=2;
                if(nd_ui_choice("##window-size",&size,sizes,4)) {request_h=hs[size];request_w=ws[size];}
                ImGui::TextWrapped("%s",label("Fullscreen output follows the display. Anti-aliasing uses the game default. FSR 3 / 4 and frame generation are unavailable.","全屏输出跟随显示器。抗锯齿使用游戏默认，FSR 3 / 4 与帧生成尚不可用。"));
                ImGui::TreePop();
            }
        } else if(sidebar.page==1) {
            nd_ui_status(label("Native device controls","原生设备控制"));
            if(ImGui::Checkbox(label("Native sensor motion","原生陀螺仪"),&gyro)) {runtime_hid_feedback_flag("gyro",gyro);dirty=true;}
            if(ImGui::Button(label("Recenter motion","重新居中陀螺仪"),ImVec2(-1,50))) runtime_motion_start();
            ImGui::TextWrapped("%s",label("Game bindings stay unchanged. App menus use A to confirm and B to go back.","游戏操作保持原绑定。应用菜单使用 A 确认、B 返回。"));
            nd_ui_label(label("Edge / corner","边框与角落"));
            const char *docks[]={label("Top left","左上"),label("Top","上边"),label("Top right","右上"),label("Right","右边"),label("Bottom right","右下"),label("Bottom","下边"),label("Bottom left","左下"),label("Left","左边")};
            dirty|=nd_ui_choice("##dock",&anchor,docks,8);
            ImGui::TextWrapped("%s",label("Tap the edge handle to open. Drag the short bar below the title to move and snap.","点击边缘的设置入口展开。拖动标题下方的短条，松手后吸附至边框或角落。"));
        } else if(sidebar.page==2) nd_draw_amiibo_library("totk-native",chinese);
        else nd_draw_atmosphere("totk-native",chinese);
        if(ImGui::IsKeyPressed(ImGuiKey_GamepadFaceRight) || ImGui::IsKeyPressed(ImGuiKey_Escape)) want_toggle=true;
    }
    ImVec2 lower,upper;
    dirty|=nd_sidebar_end(sidebar,open,&anchor,chinese,&lower,&upper);
    {std::lock_guard<std::mutex> guard(lock);hit_left=lower.x;hit_top=lower.y;hit_right=upper.x;hit_bottom=upper.y;}
    if(want_toggle) {toggle();dirty=true;}
    if(dirty) preferences(true);
    ImGui::Render();
    VkRenderingAttachmentInfo color={};color.sType=VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO;
    color.imageView=target;color.imageLayout=VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    color.loadOp=VK_ATTACHMENT_LOAD_OP_LOAD;color.storeOp=VK_ATTACHMENT_STORE_OP_STORE;
    VkRenderingInfo rendering={};rendering.sType=VK_STRUCTURE_TYPE_RENDERING_INFO;
    rendering.renderArea.extent={width,height};rendering.layerCount=1;rendering.colorAttachmentCount=1;rendering.pColorAttachments=&color;
    vk.vkCmdBeginRendering(command,&rendering);
    ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(),command);
    vk.vkCmdEndRendering(command);
}
