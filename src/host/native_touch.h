/* SPDX-License-Identifier: MIT */
/* One physical touch owns a complete UI gesture. No SDL/ImGui state crosses threads. */
#pragma once
#include <stdint.h>
#include <math.h>
typedef struct {uint64_t device,finger;int active;} NdTouch;
typedef struct {int consumed,emit,down,cancel;float x,y;} NdTouchResult;
enum {ND_TOUCH_DOWN,ND_TOUCH_MOVE,ND_TOUCH_UP,ND_TOUCH_CANCEL};
static inline void nd_touch_reset(NdTouch *s) {s->active=0;}
static inline NdTouchResult nd_touch_route(NdTouch *s,int type,uint64_t device,uint64_t finger,
                                          float x,float y,float width,float height,int hit,int open) {
    NdTouchResult r={0,0,0,0,0,0};
    int valid=isfinite(x) && isfinite(y) && width>0 && height>0;
    if(type==ND_TOUCH_DOWN) {
        if(s->active) {r.consumed=1;return r;}
        if(!valid || x<0 || y<0 || x>1 || y>1 || (!hit && !open)) return r;
        s->active=1;s->device=device;s->finger=finger;
    } else if(!s->active || s->device!=device || s->finger!=finger) {
        r.consumed=s->active || open;return r;
    }
    r.consumed=r.emit=1;r.down=type==ND_TOUCH_DOWN;
    r.cancel=type==ND_TOUCH_CANCEL || !valid;
    r.x=valid?fminf(fmaxf(x,0),1)*width:0;
    r.y=valid?fminf(fmaxf(y,0),1)*height:0;
    if(type==ND_TOUCH_UP || r.cancel) s->active=0;
    return r;
}
