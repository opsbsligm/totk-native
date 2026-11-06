/* SPDX-License-Identifier: MIT */
#pragma once
#include <string.h>
static inline const char *nd_ui_message(const char *text,bool zh) {
    if(!zh || !text || !*text) return text?text:"";
    static const struct {const char *en,*zh;} messages[]={
        {"Address overflow","地址溢出，已停止"},
        {"Unaligned memory access","内存地址未对齐，已停止"},
        {"Outside writable game data/heap; code patches need a rebuild","超出游戏可写内存；修改代码需重新编译"},
        {"Guest memory is not accessible; cheat stopped","游戏内存尚不可访问，已停止此项"},
        {"This guarded cheat backend requires Linux","此受保护的金手指后端需要 Linux"},
        {"Heading only","分类标题"},
        {"Truncated opcode","指令不完整"},
        {"Unsupported opcode or width","不支持此指令或数据宽度"},
        {"Unsupported address region/arithmetic","不支持此地址区域或运算"},
        {"Unsupported operand variant or reserved bits","不支持此操作数或保留位"},
        {"Invalid control-flow opcode","控制流指令无效"},
        {"Invalid comparison","比较指令无效"},
        {"Control nesting exceeds 32","条件嵌套超过上限"},
        {"Unbalanced condition/else","条件结构不匹配"},
        {"Unbalanced loop","循环结构不匹配"},
        {"AOT code/rodata patch requires rebuilding this game","此项修改代码或只读数据，需要重新编译游戏"},
        {"Unterminated condition/loop","条件或循环未结束"},
        {"Disable every Atmosphere cheat before reloading","请先全部关闭，再重新加载"},
        {"Game build ID is not bound","等待游戏模块加载，尚未绑定版本"},
        {"Invalid data folder","数据目录无效"},
        {"No matching build-ID cheat file; open the folder shown below","尚无此游戏版本的金手指文件，请查看下方目录"},
        {"Cheat file must be owned, mode 0600, regular and <=64 KiB","文件须归本人所有、权限为 0600，且不超过 64 KiB"},
        {"Game or cheat state changed during import; result discarded","加载期间版本或状态已改变，已丢弃旧结果"},
        {"Invalid cheat file; previous definitions preserved","金手指文件格式错误，已保留原有项目"},
        {"Unsupported game profile","不支持此游戏配置"},
        {"Cannot initialize import worker","无法初始化后台加载器"},
        {"Cannot start import worker","无法启动后台加载器"},
        {"Per-frame VM instruction budget exceeded","单帧执行超过上限，已停止此项"},
        {"Choose a local NTAG215 .bin file","请选择本地 NTAG215 标签文件"},
        {"Cannot open tag file (no symlinks)","无法打开标签文件，不接受符号链接"},
        {"Tag must be an owned regular 540-byte NTAG215 dump","标签须为本人所有的 540 字节普通文件"},
        {"Invalid NTAG215 capability container or UID checksum","标签格式或身份校验错误"},
        {"Invalid tag UID","标签身份无效"},
        {"Tag contains no valid figure identity","标签缺少有效公仔身份"},
        {"Remove the current tag before loading another","请先移开当前标签，再选择另一枚"},
        {"This figure needs application-area saves (not supported)","此公仔需要应用区存档，目前尚不支持"},
        {"System random source unavailable; scan cancelled","系统随机源不可用，本次刷入已取消"},
        {"Cross-page write rejected before changing memory","已拒绝跨页写入，原内存未改变"},
        {"Infinite health","无限生命"},
        {"Infinite stamina","无限体力"},
        {"Rupees 999999","卢比设为 999999"},
        {"Moon jump (hold in-game jump)","月步（按住游戏跳跃键）"},
        {"Invalid memory width","数据宽度无效，已停止"},
        {"No built-in presets match the complete game build ID","内置预设与当前完整游戏版本不匹配"}
    };
    for(const auto &m:messages) if(!strcmp(text,m.en)) return m.zh;
    return text;
}
