/* SPDX-License-Identifier: MIT */
/* VM opcode execution adapted from valentderah/totk-pc-recomp/runtime/cheats.c
 * @0ae47a578285cde080642c9e6c40316c99171ef1, Copyright (c) 2026 Valiantsin Dzerakh.
 * Original bounded importer, memory policy, UI snapshots and fault isolation.
 * Every entry starts OFF, including master codes. Never writes AOT code/rodata.
 */
#define _GNU_SOURCE 1
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include "native_atmosphere.h"
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>
#ifdef __linux__
#include <sys/uio.h>
#endif
enum { LIMIT=64, WORDS=1024, OPS_PER_RUN=4096 };
typedef struct {NdAtmInfo info;uint32_t words[WORDS];int n;} Cheat;
static Cheat cheats[LIMIT],staged[LIMIT];static size_t count;
static uint64_t main_base,data_start,data_bytes;static NdAtmHeap heap_bounds;
static char build[17],error[160],filename[4096];
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static int fault;static const char *fault_note;
static int within(uint64_t a,size_t n,uint64_t start,uint64_t size) {return a>=start && n<=size && a-start<=size-n;}
static uint64_t add(uint64_t a,uint64_t b) {if(b>UINT64_MAX-a) {fault=1;fault_note="Address overflow";return 0;}return a+b;}
static uint64_t region(int m) {uint64_t b=0,n=0;if(m==0) return main_base;if(m==1 && heap_bounds) heap_bounds(&b,&n);return b;}
static int transfer(uint64_t a,int width,void *data,int write) {
    if(fault) return 0;
    if(width<1 || width>8 || (a&((unsigned)width-1))) {fault=1;fault_note="Unaligned memory access";return 0;}
    uint64_t hb=0,hs=0;if(heap_bounds) heap_bounds(&hb,&hs);
    int allowed=write?within(a,(size_t)width,data_start,data_bytes):within(a,(size_t)width,main_base,data_start-main_base+data_bytes);
    if(!allowed && hb) allowed=within(a,(size_t)width,hb,hs);
    if(!a || !allowed) {fault=1;fault_note="Outside writable game data/heap; code patches need a rebuild";return 0;}
#ifdef __linux__
    // Kernel copies return EFAULT for an unmapped/frozen page; no guest pointer is dereferenced on the UI/host thread.
    struct iovec local={data,(size_t)width},remote={(void *)(uintptr_t)a,(size_t)width};
    ssize_t n=write?process_vm_writev(getpid(),&local,1,&remote,1,0):process_vm_readv(getpid(),&local,1,&remote,1,0);
    if(n==width) return 1;
    fault=1;fault_note="Guest memory is not accessible; cheat stopped";return 0;
#else
    (void)data;fault=1;fault_note="This guarded cheat backend requires Linux";return 0;
#endif
}
static int rd(uint64_t a,int width,uint64_t *v) {*v=0;return transfer(a,width,v,0);}
static void wr(uint64_t a,int width,uint64_t value) {(void)transfer(a,width,&value,1);}
static int op_len(const uint32_t *w, int left) {
    uint32_t f = w[0];
    int t = f >> 28, width = (f >> 24) & 0xF, n;
    switch (t) {
    case 0: case 1: n = width == 8 ? 4 : 3; break;
    case 2: case 8: n = 1; break;
    case 3: n = width == 0 ? 2 : 1; break;
    case 4: case 6: n = 3; break;
    case 5: case 7: n = 2; break;
    case 9: n = 1 + (((f >> 8) & 0xF) ? (width == 8 ? 2 : 1) : 0); break;
    case 0xA: n = ((f >> 8) & 0xF) == 2 || ((f >> 8) & 0xF) == 4 || ((f >> 8) & 0xF) == 5 ? 2 : 1; break;
    default: n = 1; break;
    }
    return n <= left ? n : 0;
}

static uint64_t masked(int width, uint64_t v) { return width >= 8 ? v : v & ((1ull << (8 * width)) - 1); }

static uint64_t arith(int op, uint64_t a, uint64_t b) {
    switch (op) {
    case 0: return a + b;
    case 1: return a - b;
    case 2: return a * b;
    case 3: return b < 64 ? a << b : 0;
    case 4: return b < 64 ? a >> b : 0;
    case 5: return a & b;
    case 6: return a | b;
    case 7: return ~a;
    case 8: return a ^ b;
    default: return a;   // 9: move
    }
}

static int compare(int cond, uint64_t a, uint64_t b) {
    switch (cond) {
    case 1: return a > b;
    case 2: return a >= b;
    case 3: return a < b;
    case 4: return a <= b;
    case 5: return a == b;
    case 6: return a != b;
    default: return 0;
    }
}

// From i (after a failed condition, or an else reached while running), the opcode to continue at: after the
// matching else (else_ok) or end.
static int skip(const uint32_t *w, int n, int i, int else_ok) {
    int depth = 0;
    while (i < n) {
        int len = op_len(w + i, n - i);
        if (!len) return n;
        uint32_t f = w[i];
        int t = f >> 28;
        i += len;
        if (t == 1 || t == 8) depth++;
        else if (t == 2 && ((f >> 24) & 0xF) == 0 && depth-- == 0) return i;
        else if (t == 2 && depth == 0 && else_ok) return i;
    }
    return n;
}

static uint64_t imm64(const uint32_t *w) { return (uint64_t)w[0] << 32 | w[1]; }

static int run(const Cheat *c, uint64_t keys,int *shared_budget) {
    uint64_t r[16] = {0};
    int loop[16] = {0};
    const uint32_t *w = c->words;
    int n = c->n;
    for (int i = 0; i < n && !fault && (*shared_budget)-- > 0;) {
        int len = op_len(w + i, n - i);
        if (!len) return 0;
        uint32_t f = w[i];
        int t = f >> 28, width = (f >> 24) & 0xF, x = (f >> 20) & 0xF, y = (f >> 16) & 0xF, z = (f >> 12) & 0xF;
        uint64_t rel = ((uint64_t)(f & 0xFF) << 32) | (len > 1 ? w[i + 1] : 0), v;
        switch (t) {
        case 0:   // 0TMR00AA AAAAAAAA V..: store a value at region M + A + register R
            wr(add(add(region(x),rel),r[y]), width, width == 8 ? imm64(w + i + 2) : w[i + 2]);
            break;
        case 1:   // 1TMC00AA AAAAAAAA V..: if (region M + A) <cond C> V
            if (!rd(add(add(region(x),rel),z?r[(f>>8)&15]:0), width, &v) || !compare(y, v, width == 8 ? imm64(w + i + 2) : w[i + 2])) {
                i = skip(w, n, i + len, 1);
                continue;
            }
            break;
        case 2:   // 20000000 end, 21000000 else: an else reached while running skips to the end
            if (width == 1) {
                i = skip(w, n, i + len, 0);
                continue;
            }
            break;
        case 3:   // 300R0000 VVVVVVVV loop start, 310R0000 loop end
            if (width == 0) {
                r[y] = w[i + 1];
                loop[y] = i + len;
                if(!r[y]) {int depth=1,j=i+len;while(j<n && depth) {uint32_t op=w[j];int k=op_len(w+j,n-j);if((op>>28)==3) depth+=((op>>24)&15)?-1:1;j+=k;}i=j;continue;}
            } else if (r[y] && --r[y]) {
                i = loop[y];
                continue;
            }
            break;
        case 4:   // 400R0000 V V: register R = V
            r[y] = imm64(w + i + 1);
            break;
        case 5:   // 5TMRI0AA AAAAAAAA: R = (I ? R : region M) + A, read
            if (!rd(z ? add(r[y],rel) : add(region(x),rel), width, &v)) return 0;   // a broken pointer chain: nothing more
            r[y] = v;
            break;
        case 6: {   // 6T0RIor0 V V: store V at R (+ register r); I: R += width
            uint64_t a = add(r[y],(((f >> 8) & 0xF)?r[(f >> 4)&0xF]:0));
            wr(a, width, imm64(w + i + 1));
            if (z) r[y] = add(r[y],(uint64_t)width);
            break;
        }
        case 7:   // 7T0RC000 VVVVVVVV: R = R <op C> V
            r[y] = masked(width, arith(z, r[y], w[i + 1]));
            break;
        case 8:   // 8kkkkkkk: if the buttons are held
            if ((keys & (f & 0x0FFFFFFF)) != (f & 0x0FFFFFFF)) {
                i = skip(w, n, i + len, 1);
                continue;
            }
            break;
        case 9: {   // 9TCRS0s0 / 9TCRS100 V..: R = S <op C> (s or V)
            uint64_t b = (f >> 8) & 0xF ? (width == 8 ? imm64(w + i + 1) : w[i + 1]) : r[(f >> 4) & 0xF];
            r[y] = masked(width, arith(x, r[z], b));
            break;
        }
        case 0xA: {   // ATSRIOxa (aaaaaaaa): store register S at an address of type O
            int o = (f >> 8) & 0xF, m = (f >> 4) & 0xF;
            uint64_t imm = ((uint64_t)(f & 0xF) << 32) | (len > 1 ? w[i + 1] : 0), a;
            switch (o) {
            case 0: a = r[y]; break;
            case 1: a = add(r[y],r[m]); break;
            case 2: a = add(r[y],imm); break;
            case 3: a = add(region(m),r[y]); break;
            case 4: a = add(region(m),imm); break;
            default: a = add(region(m),add(r[y],imm)); break;
            }
            wr(a, width, r[x]);
            if (z) r[y] = add(r[y],(uint64_t)width);
            break;
        }
        default:
            return 0;
        }
        i += len;
    }
    return !fault && *shared_budget>=0;
}

static void note(Cheat *c,const char *text) {c->info.supported=0;snprintf(c->info.note,sizeof c->info.note,"%s",text);}
static void validate(Cheat *c) {
    int stack[32],reg[32],seen_else[32],depth=0;c->info.supported=c->n>0;
    if(!c->n) {note(c,"Heading only");return;}
    for(int i=0;i<c->n;) {
        uint32_t f=c->words[i];int type=f>>28,width=(f>>24)&15,len=op_len(c->words+i,c->n-i);
        if(!len) {note(c,"Truncated opcode");return;}
        if(type>10 || ((type<=1 || type==5 || type==6 || type==7 || type==9 || type==10) && width!=1 && width!=2 && width!=4 && width!=8)) {note(c,"Unsupported opcode or width");return;}
        if(((type==0 || type==1 || type==5) && ((f>>20)&15)>1) || (type==5 && ((f>>12)&15)>1) || (type==9 && (((f>>20)&15)>9 || ((f>>8)&15)>1)) ||
           (type==7 && ((f>>12)&15)>4) || (type==10 && (((f>>8)&15)>5 || (((f>>8)&15)>=3 && ((f>>4)&15)>1)))) {note(c,"Unsupported address region/arithmetic");return;}
        int x=(f>>20)&15,z=(f>>12)&15,o=(f>>8)&15;
        if((type==0 && (f&0x0000ff00u)) || (type==1 && z>1) ||
           (type==2 && (f&0x00ffffffu)) || (type==3 && (f&0x00f0ffffu)) ||
           (type==4 && (f&0x0ff0ffffu)) || (type==5 && (o || (z && x))) ||
           (type==6 && (x || z>1 || o>1 || (f&15))) || (type==7 && (x || (f&0xfff))) ||
           (type==9 && ((f&15) || (o && (f&255)))) ||
           (type==10 && (z>1 || ((o==0 || o==1 || o==3) && (f&15))))) {
            note(c,"Unsupported operand variant or reserved bits");return;
        }
        if((type==2 || type==3) && width>1) {note(c,"Invalid control-flow opcode");return;}
        if(type==1 && (((f>>16)&15)<1 || ((f>>16)&15)>6)) {note(c,"Invalid comparison");return;}
        if(type==1 || type==8 || (type==3 && !width)) {
            if(depth==32) {note(c,"Control nesting exceeds 32");return;}
            stack[depth]=type==3?3:1;reg[depth]=(f>>16)&15;seen_else[depth++]=0;
        } else if(type==2) {
            if(!depth || stack[depth-1]!=1 || (width && seen_else[depth-1])) {note(c,"Unbalanced condition/else");return;}
            if(width) seen_else[depth-1]=1;else depth--;
        } else if(type==3) {
            if(!depth || stack[depth-1]!=3 || reg[depth-1]!=(int)((f>>16)&15)) {note(c,"Unbalanced loop");return;}
            depth--;
        }
        // Static text/rodata stores cannot affect lifted machine code.
        if(type==0 && ((f>>20)&15)==0) {
            uint64_t offset=((uint64_t)(f&255)<<32)|c->words[i+1];
            if(offset<data_start-main_base) {note(c,"AOT code/rodata patch requires rebuilding this game");return;}
        }
        i+=len;
    }
    if(depth) note(c,"Unterminated condition/loop");
}
void nd_atm_bind(const char *id,uint64_t base,uint64_t start,uint64_t size,NdAtmHeap heap) {
    pthread_mutex_lock(&mutex);memset(cheats,0,sizeof cheats);count=0;build[0]=error[0]=filename[0]=0;
    main_base=base;data_start=start;data_bytes=size;heap_bounds=heap;
    if(id && strlen(id)==64 && strspn(id,"0123456789abcdefABCDEF")==64 && start>=base && size<=UINT64_MAX-start) {
        for(int i=0;i<16;i++) {build[i]=(char)((id[i]>='a' && id[i]<='f')?id[i]-32:id[i]);}
        build[16]=0;
    }
    pthread_mutex_unlock(&mutex);
}
static int fail(const char *message) {snprintf(error,sizeof error,"%s",message);return -1;}
int nd_atm_reload(const char *game) {
    pthread_mutex_lock(&mutex);
    // Reload cannot silently replace running programs or leave previous freezes active.
    for(size_t i=0;i<count;i++) if(cheats[i].info.enabled) {int x=fail("Disable every Atmosphere cheat before reloading");pthread_mutex_unlock(&mutex);return x;}
    const char *base=getenv("XDG_DATA_HOME"),*home=getenv("HOME");int length=-1;
    if(strcmp(game,"totk-native") && strcmp(game,"botw-native")) goto invalid;
    if(!build[0]) goto invalid;
    if(base && *base=='/') length=snprintf(filename,sizeof filename,"%s/%s/cheats/%s.txt",base,game,build);
    else if(home && *home=='/') length=snprintf(filename,sizeof filename,"%s/.local/share/%s/cheats/%s.txt",home,game,build);
    if(length<0 || (size_t)length>=sizeof filename) goto invalid;
    int fd=open(filename,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);struct stat st;char text[65537];size_t used=0;
    if(fd<0) {fail("No matching build-ID cheat file; open the folder shown below");pthread_mutex_unlock(&mutex);return -1;}
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() || (st.st_mode&0077) || st.st_size<0 || st.st_size>65536) {close(fd);fail("Cheat file must be owned, mode 0600, regular and <=64 KiB");pthread_mutex_unlock(&mutex);return -1;}
    while(used<sizeof text-1) {ssize_t n=read(fd,text+used,sizeof text-1-used);if(n<0 && errno==EINTR) continue;if(n<0) {close(fd);goto invalid;}if(!n) break;used+=(size_t)n;}
    close(fd);if(used!=(size_t)st.st_size || memchr(text,0,used)) goto invalid;text[used]=0;
    memset(staged,0,sizeof staged);size_t loaded=0;char *next=NULL,*begin=text;
    if(used>=3 && !memcmp(begin,"\xef\xbb\xbf",3)) begin+=3;
    for(char *line=strtok_r(begin,"\n",&next);line;line=strtok_r(NULL,"\n",&next)) {
        while(*line==' ' || *line=='\t') line++;
        size_t n=strlen(line);while(n && (line[n-1]=='\r' || line[n-1]==' ' || line[n-1]=='\t')) line[--n]=0;
        if(!n || line[0]=='#' || line[0]==';') continue;
        if((line[0]=='[' && line[n-1]==']') || (line[0]=='{' && line[n-1]=='}')) {
            if(loaded==LIMIT || n<3 || n-2>=sizeof staged[0].info.name) goto invalid;
            line[n-1]=0;snprintf(staged[loaded++].info.name,sizeof staged[0].info.name,"%s",line+1);continue;
        }
        if(!loaded) goto invalid;
        Cheat *c=&staged[loaded-1];char *word_next=NULL;
        for(char *word=strtok_r(line," \t",&word_next);word;word=strtok_r(NULL," \t",&word_next)) {
            if(word[0]=='#' || word[0]==';') break;
            if(strlen(word)!=8 || strspn(word,"0123456789abcdefABCDEF")!=8 || c->n==WORDS) goto invalid;
            c->words[c->n++]=(uint32_t)strtoul(word,NULL,16);
        }
    }
    for(size_t i=0;i<loaded;i++) validate(&staged[i]);
    memcpy(cheats,staged,sizeof cheats);count=loaded;error[0]=0;pthread_mutex_unlock(&mutex);return 0;
invalid:
    fail("Invalid or unbound cheat file; previous definitions preserved");pthread_mutex_unlock(&mutex);return -1;
}
size_t nd_atm_count(void) {pthread_mutex_lock(&mutex);size_t n=count;pthread_mutex_unlock(&mutex);return n;}
void nd_atm_info(size_t i,NdAtmInfo *out) {pthread_mutex_lock(&mutex);memset(out,0,sizeof *out);if(i<count) *out=cheats[i].info;pthread_mutex_unlock(&mutex);}
void nd_atm_request(size_t i,int on) {pthread_mutex_lock(&mutex);if(i<count && cheats[i].info.supported) cheats[i].info.enabled=on!=0;pthread_mutex_unlock(&mutex);}
void nd_atm_frame(uint64_t keys) {
    pthread_mutex_lock(&mutex);int budget=OPS_PER_RUN;
    for(size_t i=0;i<count;i++) if(cheats[i].info.enabled) {
        fault=0;fault_note="Per-frame VM instruction budget exceeded";
        if(!run(&cheats[i],keys,&budget)) {cheats[i].info.enabled=0;snprintf(cheats[i].info.note,sizeof cheats[i].info.note,"%s",fault_note);}
        if(budget<0) break;
    }
    pthread_mutex_unlock(&mutex);
}
const char *nd_atm_error(void) {static _Thread_local char copy[160];pthread_mutex_lock(&mutex);memcpy(copy,error,sizeof copy);pthread_mutex_unlock(&mutex);return copy;}
const char *nd_atm_file(void) {static _Thread_local char copy[4096];pthread_mutex_lock(&mutex);memcpy(copy,filename,sizeof copy);pthread_mutex_unlock(&mutex);return copy;}
