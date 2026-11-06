/* SPDX-License-Identifier: MIT */
#include "deck_prompt_masks.h"
#include <assert.h>
int main(void) {
    const char *world="BAYX",*menu="ABYX";
    for(unsigned c=0;c<4;c++) {assert(nd_deck_face_label(c,0)==world[c]);assert(nd_deck_face_label(c,1)==menu[c]);}
    unsigned char a[108*108+2],b[108*108];memset(a,0x6d,sizeof a);
    assert(!nd_deck_glyph_mask(6,0,a+1,sizeof a-2,108));assert(a[1]==0x6d);
    assert(!nd_deck_glyph_mask(0,0,a+1,5,108));assert(!nd_deck_glyph_mask(0,0,0,0,108));
    assert(nd_deck_glyph_mask(0,0,a+1,sizeof a-2,108));assert(a[0]==0x6d && a[sizeof a-1]==0x6d);
    assert(nd_deck_glyph_mask(1,1,b,sizeof b,108));assert(!memcmp(a+1,b,sizeof b));
    assert(nd_deck_glyph_mask(0,1,b,sizeof b,108));assert(memcmp(a+1,b,sizeof b));
    for(unsigned code=0;code<6;code++) {
        assert(nd_deck_glyph_mask(code,0,b,sizeof b,108));int solid=0,edge=0;
        for(unsigned i=0;i<sizeof b;i++) {solid+=b[i]==255;edge+=b[i]>0 && b[i]<255;}
        assert(solid>1000 && edge>100);assert(!b[0] && !b[107] && !b[sizeof b-1]);
    }
}
