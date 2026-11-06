/* SPDX-License-Identifier: MIT */
/* Authored Deck mask geometry. Host-side replacement only; no game pixels. */
#pragma once
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
static inline char nd_deck_face_label(unsigned code,int menu) {
    static const char world[]="BAYX",menus[]="ABYX";
    return code<4?(menu?menus:world)[code]:0;
}
static inline float nd_glyph_segment(float x,float y,float ax,float ay,float bx,float by) {
    float dx=bx-ax,dy=by-ay,t=((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy);
    t=fmaxf(0,fminf(1,t));return hypotf(x-ax-t*dx,y-ay-t*dy);
}
static inline float nd_glyph_stroke(char letter,float x,float y) {
    float d=10;
    #define S(ax,ay,bx,by) d=fminf(d,nd_glyph_segment(x,y,ax,ay,bx,by))
    switch(letter) {
    case 'A':S(-.15f,.19f,0,-.20f);S(0,-.20f,.15f,.19f);S(-.10f,.055f,.10f,.055f);break;
    case 'B':S(-.13f,-.20f,-.13f,.20f);S(-.13f,-.20f,.035f,-.20f);S(.035f,-.20f,.13f,-.12f);S(.13f,-.12f,.035f,0);S(.035f,0,-.13f,0);S(.035f,0,.15f,.09f);S(.15f,.09f,.12f,.17f);S(.12f,.17f,.035f,.20f);S(.035f,.20f,-.13f,.20f);break;
    case 'X':S(-.14f,-.20f,.14f,.20f);S(.14f,-.20f,-.14f,.20f);break;
    case 'Y':S(-.15f,-.20f,0,0);S(.15f,-.20f,0,0);S(0,0,0,.20f);break;
    case 'L':S(-.13f,-.20f,-.13f,.20f);S(-.13f,.20f,.13f,.20f);break;
    case '1':S(-.07f,-.12f,.03f,-.20f);S(.03f,-.20f,.03f,.20f);S(-.08f,.20f,.13f,.20f);break;
    case '2':S(-.13f,-.14f,-.06f,-.20f);S(-.06f,-.20f,.08f,-.20f);S(.08f,-.20f,.14f,-.13f);S(.14f,-.13f,.12f,-.04f);S(.12f,-.04f,-.13f,.20f);S(-.13f,.20f,.14f,.20f);break;
    }
    #undef S
    return d;
}
static inline int nd_deck_glyph_mask(unsigned code,int menu,uint8_t *out,size_t bytes,unsigned w) {
    if(!out || !w || w>256 || bytes<(size_t)w*w || code>5) return 0;
    for(unsigned y=0;y<w;y++) for(unsigned x=0;x<w;x++) {
        float X=(x+.5f)/w-.5f,Y=(y+.5f)/w-.5f;
        float body=code<4?.43f-hypotf(X,Y):fminf(.46f-fabsf(X),.31f-fabsf(Y));
        float ink=code<4?nd_glyph_stroke(nd_deck_face_label(code,menu),X,Y):
            fminf(nd_glyph_stroke('L',X+.19f,Y),nd_glyph_stroke(code==4?'1':'2',X-.16f,Y));
        float coverage=fmaxf(0,fminf(1,.5f+body*w));
        float cut=fmaxf(0,fminf(1,.5f+(.028f-ink)*w));
        out[(size_t)y*w+x]=(uint8_t)lroundf(255*coverage*(1-cut));
    }
    return 1;
}
