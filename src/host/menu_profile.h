/* Fixed TOTK 1.4.3 local static type metadata; original adapter, MIT. */
#pragma once
#include <stdint.h>
typedef struct { uint64_t vtable,name_address,descriptor,getter; const char *name; } NdMenuClass;
/* The 1.4.3 world HUD's bottom movement/control guide remains open while
   walking and climbing. Its is-open state does not make it an input menu. */
#define ND_TOTK_WORLD_CTRL_GUIDE_VTABLE 0x803726538ull
/* UIMapScreen also renders the resident minimap in the world. The actual
   full-screen map's modal owner is UIAppMenuOverlayScreen. */
#define ND_TOTK_WORLD_MAP_VTABLE 0x80372b158ull
static const NdMenuClass nd_menu_classes[]={
    {0x8037222b0ull,0x802c60592ull,0x8037225c0ull,0x80212ed28ull,"UIActionGuideWithPictScreen"},
    {0x803722a48ull,0x802c711d3ull,0x803722d50ull,0x802132efcull,"UIAmiiboWindowScreen"},
    {0x803722e00ull,0x802c2f062ull,0x803723110ull,0x802134d00ull,"UIAppMenuOverlayScreen"},
    {0x8037232c0ull,0x802c15f8aull,0x8037235c8ull,0x8021350f8ull,"UIAppOpenDemoWindowScreen"},
    {0x803725170ull,0x802c4ffcaull,0x803725478ull,0x80213f878ull,"UICameraSystemWindowScreen"},
    {0x803725e58ull,0x802c60634ull,0x803726160ull,0x8021479d4ull,"UICharaDirectoryScreen"},
    {0x803726538ull,0x802c26a4full,0x803726848ull,0x802148354ull,"UICtrlGuideScreen"},
    {0x803726ff0ull,0x802c89cb4ull,0x8037272f8ull,0x80214ae0cull,"UIDyeShopMenuScreen"},
    {0x803728678ull,0x802c04eabull,0x803728980ull,0x80214c2b0ull,"UIGameOverScreen"},
    {0x803728ce8ull,0x802c58bf7ull,0x803728ff0ull,0x80214fb3cull,"UIGetWindowScreen"},
    {0x803729d18ull,0x802c68b5full,0x80372a020ull,0x802151d44ull,"UIHouseShopMenuScreen"},
    {0x80372b158ull,0x802c712ccull,0x80372b468ull,0x80215e678ull,"UIMapScreen"},
    {0x80372bbe8ull,0x802c36ddeull,0x80372bf28ull,0x80216111cull,"MessageDialogScreen"},
    {0x80372d0b0ull,0x802c712f8ull,0x80372d3b8ull,0x8021670bcull,"UIParasailPatternChangeScreen"},
    {0x80372d748ull,0x802cbaffeull,0x80372da50ull,0x8021679ecull,"UIPauseMenuOverlayScreen"},
    {0x80372f150ull,0x802c68c32ull,0x80372f458ull,0x80217a96cull,"UIPouchScreen"},
    {0x8037304f0ull,0x802c79875ull,0x8037307f8ull,0x802180cf8ull,"UIShopMenuScreen"},
    {0x803732638ull,0x802c36e5aull,0x803732940ull,0x80218b940ull,"UISystemLoadListScreen"},
    {0x803732970ull,0x802c58d59ull,0x803732c78ull,0x80218d580ull,"UISystemOptionScreen"},
    {0x803732cc0ull,0x802c16110ull,0x803732fd0ull,0x80218d608ull,"UISystemSaveLoadScreen"},
    {0x803733000ull,0x802c1e830ull,0x803733308ull,0x80218dca8ull,"UISystemWindowScreen"},
    {0x803733a28ull,0x802c36ea8ull,0x803733d30ull,0x80218ea7cull,"UITitleScreen"},
};
