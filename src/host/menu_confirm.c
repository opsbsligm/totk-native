/* Original native menu policy and bounded screen-state reader, MIT. */
#include "menu_confirm.h"
#include <string.h>
uint64_t nd_menu_confirm(NdMenuConfirm *s, bool active, unsigned held,
                         uint64_t east_actions, uint64_t south_actions) {
    held &= 3;
    if (s->active != active) s->blocked |= held;
    s->active = active;
    s->blocked &= held;
    unsigned available = held & ~s->blocked;
    return ((available & 1) ? (active ? 2 : east_actions) : 0) |
           ((available & 2) ? (active ? 1 : south_actions) : 0);
}
#include "menu_profile.h"
static bool get(NdMenuRead read,void *u,uint64_t p,void *out,size_t n) {
    const uint64_t lo=0x800000000ull,hi=0x8000000000ull;
    return p>=lo && p<hi && n<=hi-p && read(u,p,out,n);
}
static bool pointer(uint64_t p) {return p>=0x800000000ull && p<0x8000000000ull-0x200 && !(p&7);}
bool nd_totk_menu_context(NdMenuRead read,void *u) {
    if(!read) return false;
    /* The package loader pins every module. Also validate local RTTI/name pins
       before interpreting this fixed 1.4.3 layout. String addresses may be odd. */
    static const unsigned pins[]={12,15,20,21,22};
    for(size_t i=0;i<sizeof pins/sizeof *pins;i++) {
        const NdMenuClass *p=&nd_menu_classes[pins[i]];char name[64];uint64_t fn=0;
        size_t n=strlen(p->name)+1;
        if(n>sizeof name || !get(read,u,p->name_address,name,n) || memcmp(name,p->name,n) ||
           !get(read,u,p->descriptor+0x10,&fn,8) || fn!=p->getter) return false;
    }
    uint64_t mgr,arr,again,check_array,objects[512];uint32_t count,check_count;
    if(!get(read,u,0x803acf960ull,&mgr,8) || !pointer(mgr) ||
       !get(read,u,mgr+8,&count,4) || !count || count>512 ||
       !get(read,u,mgr+0x10,&arr,8) || !pointer(arr) || !get(read,u,arr,objects,8*count)) return false;
    bool active=false;
    for(uint32_t i=0;i<count;i++) {
        uint64_t obj=objects[i],vt;
        if(!obj) continue;
        if(!pointer(obj) || !get(read,u,obj,&vt,8)) return false;
        /* World control hints and the resident minimap remain open without
           taking menu input. Full-screen map input is owned by the separate
           UIAppMenuOverlayScreen, which is still checked below. */
        if(vt==ND_TOTK_WORLD_CTRL_GUIDE_VTABLE || vt==ND_TOTK_WORLD_MAP_VTABLE) continue;
        for(size_t j=0;j<sizeof nd_menu_classes/sizeof *nd_menu_classes;j++) {
            if(vt!=nd_menu_classes[j].vtable) continue;
            signed char state[2];uint64_t owner;
            if(!get(read,u,obj+0x20,&owner,8) || owner!=mgr || !get(read,u,obj+0x16d,state,2)) return false;
            /* The game's own is-open predicate main+0x28ff680. */
            if(state[0]>=0 && state[1]==2) active=true;
            break;
        }
    }
    return get(read,u,0x803acf960ull,&again,8) && again==mgr &&
        get(read,u,mgr+8,&check_count,4) && check_count==count &&
        get(read,u,mgr+0x10,&check_array,8) && check_array==arr && active;
}
