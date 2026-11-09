/* SPDX-License-Identifier: MIT */
/* Original implementation. NTAG layout/NFP ABI cross-checked with libnx and
 * valentderah/totk-pc-recomp@0ae47a5 (MIT). Only public figure identity is read;
 * encrypted application areas, writes and NFC hardware emulation are unsupported. */
#define _DEFAULT_SOURCE 1
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include "native_amiibo.h"
#include "native_amiibo_catalog.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/random.h>
#include <unistd.h>
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static NdAmiiboSnapshot state={.virtual_index=-1};
static unsigned char tag[540];
static void (*notification)(int);
void nd_amiibo_set_notify(void (*fn)(int)) {pthread_mutex_lock(&mutex);notification=fn;pthread_mutex_unlock(&mutex);}
void nd_amiibo_snapshot(NdAmiiboSnapshot *out) {pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);}
void nd_amiibo_initialize(int on) {
    pthread_mutex_lock(&mutex);state.initialized=on!=0;state.state=0;state.generation++;
    pthread_mutex_unlock(&mutex);
}
static int fail(const char *message) {
    pthread_mutex_lock(&mutex);snprintf(state.error,sizeof state.error,"%s",message);pthread_mutex_unlock(&mutex);return -1;
}
int nd_amiibo_load(const char *path) {
    if(!path || !*path) return fail("Choose a local NTAG215 .bin file");
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
    if(fd<0) return fail("Cannot open tag file (no symlinks)");
    struct stat st;unsigned char data[541];size_t used=0;int good=1;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() || st.st_size!=540) good=0;
    while(good && used<sizeof data) {
        ssize_t n=read(fd,data+used,sizeof data-used);
        if(n<0) {if(errno==EINTR) continue;good=0;break;}
        if(!n) break;
        used+=(size_t)n;
    }
    close(fd);
    if(!good || used!=540) return fail("Tag must be an owned regular 540-byte NTAG215 dump");
    const unsigned char cc[]={0xf1,0x10,0xff,0xee};
    if(memcmp(data+12,cc,4) || data[3]!=(unsigned char)(0x88^data[0]^data[1]^data[2]) ||
       data[8]!=(unsigned char)(data[4]^data[5]^data[6]^data[7])) return fail("Invalid NTAG215 capability container or UID checksum");
    unsigned nonzero=0,nonff=0;const int uid[]={0,1,2,4,5,6,7};
    for(unsigned i=0;i<7;i++) {nonzero|=data[uid[i]];nonff|=data[uid[i]]^255;}
    if(!nonzero || !nonff) return fail("Invalid tag UID");
    unsigned identity=0,identity_ff=0;for(int i=0;i<8;i++) {identity|=data[0x54+i];identity_ff|=data[0x54+i]^255;}
    if(!identity || !identity_ff) return fail("Tag contains no valid figure identity");
    pthread_mutex_lock(&mutex);
    // Do not replace a mounted tag beneath a game operation. Remove it first.
    if(state.state==4 || state.state==2) {pthread_mutex_unlock(&mutex);return fail("Remove the current tag before loading another");}
    memcpy(tag,data,sizeof tag);state.virtual_index=-1;state.loaded=1;state.current_identity_read=0;state.error[0]=0;state.generation++;
    const char *name=strrchr(path,'/');snprintf(state.name,sizeof state.name,"%s",name?name+1:path);
    int activate=state.initialized && state.state==1;
    if(activate) state.state=2;
    void (*fn)(int)=notification;pthread_mutex_unlock(&mutex);
    if(activate && fn) fn(1);
    return 0;
}
void nd_amiibo_remove(void) {
    pthread_mutex_lock(&mutex);int active=state.state==2 || state.state==4;
    state.loaded=0;state.virtual_index=-1;state.current_identity_read=0;memset(tag,0,sizeof tag);state.name[0]=0;state.state=state.initialized?3:0;state.generation++;
    void (*fn)(int)=notification;pthread_mutex_unlock(&mutex);if(active && fn) fn(0);
}
unsigned nd_amiibo_start(void) {
    pthread_mutex_lock(&mutex);
    if(!state.initialized) {pthread_mutex_unlock(&mutex);return ND_NFP_NOT_FOUND;}
    if(state.state==2 || state.state==4) {pthread_mutex_unlock(&mutex);return 0;}
    int activate=state.loaded;
    state.state=state.loaded?2:1;state.generation++;
    void (*fn)(int)=notification;pthread_mutex_unlock(&mutex);if(activate && fn) fn(1);return 0;
}
unsigned nd_amiibo_stop(void) {
    pthread_mutex_lock(&mutex);int active=state.state==2 || state.state==4;
    state.state=active?3:0;state.generation++;void (*fn)(int)=notification;
    pthread_mutex_unlock(&mutex);if(active && fn) fn(0);return 0;
}
unsigned nd_amiibo_mount(void) {
    pthread_mutex_lock(&mutex);unsigned result=ND_NFP_NOT_FOUND;
    if(state.initialized && state.loaded && (state.state==2 || state.state==4)) {state.state=4;state.generation++;state.mounts++;result=0;}
    pthread_mutex_unlock(&mutex);return result;
}
unsigned nd_amiibo_unmount(void) {
    pthread_mutex_lock(&mutex);unsigned result=ND_NFP_NOT_FOUND;
    if(state.state==4 && state.loaded) {state.state=2;state.generation++;result=0;}
    pthread_mutex_unlock(&mutex);return result;
}
unsigned nd_amiibo_tag_info(void *out,size_t size) {
    if(!out || size<0x58) return ND_NFP_NOT_FOUND;
    pthread_mutex_lock(&mutex);unsigned result=ND_NFP_NOT_FOUND;
    if(state.loaded && (state.state==2 || state.state==4)) {
        unsigned char *p=out;memset(p,0,0x58);p[0]=tag[0];p[1]=tag[1];p[2]=tag[2];memcpy(p+3,tag+4,4);
        p[0xa]=7;p[0x20]=1;p[0x24]=2;state.tag_reads++;result=0;
    }
    pthread_mutex_unlock(&mutex);return result;
}
unsigned nd_amiibo_model_info(void *out,size_t size) {
    if(!out || size<0x40) return ND_NFP_NOT_FOUND;
    pthread_mutex_lock(&mutex);unsigned result=ND_NFP_NOT_FOUND;
    if(state.loaded && state.state==4) {
        unsigned char *p=out;memset(p,0,0x40);memcpy(p,tag+0x54,3);p[3]=tag[0x5a];p[4]=tag[0x59];p[5]=tag[0x58];p[6]=tag[0x57];state.model_reads++;state.current_identity_read=1;result=0;
    }
    pthread_mutex_unlock(&mutex);return result;
}
static int name_compare(const void *a,const void *b) {return strcmp(a,b);}
int nd_amiibo_library(const char *game,char folder[4096],char names[ND_AMIIBO_MAX_FILES][256]) {
    if(strcmp(game,"totk-native") && strcmp(game,"botw-native")) return -1;
    const char *base=getenv("XDG_DATA_HOME"),*home=getenv("HOME");int n;
    if(base && *base=='/') n=snprintf(folder,4096,"%s/%s/amiibo",base,game);
    else if(home && *home=='/') n=snprintf(folder,4096,"%s/.local/share/%s/amiibo",home,game);
    else {folder[0]=0;return -1;}
    if(n<0 || n>=4096) {folder[0]=0;return -1;}
    DIR *dir=opendir(folder);if(!dir) return 0;
    int directory_fd=dirfd(dir);if(directory_fd<0) {closedir(dir);return -1;}
    struct dirent *entry;int count=0,visited=0;
    while(count<ND_AMIIBO_MAX_FILES && visited++<1024 && (entry=readdir(dir))) {
        size_t len=strlen(entry->d_name);if(len<5 || len>=256 || strcmp(entry->d_name+len-4,".bin")) continue;
        struct stat st;
        if(fstatat(directory_fd,entry->d_name,&st,AT_SYMLINK_NOFOLLOW) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() || st.st_size!=540) continue;
        // Control characters in filenames must not alter the UI/log layout.
        int safe=1;for(size_t i=0;i<len;i++) if((unsigned char)entry->d_name[i]<32) safe=0;
        if(safe) snprintf(names[count++],256,"%s",entry->d_name);
    }
    closedir(dir);qsort(names,(size_t)count,256,name_compare);return count;
}

size_t nd_amiibo_virtual_count(void) {return sizeof nd_virtual_figures/sizeof nd_virtual_figures[0];}
const char *nd_amiibo_virtual_name(size_t index,int chinese) {
    if(index>=nd_amiibo_virtual_count()) return "";
    return chinese?nd_virtual_figures[index].zh:nd_virtual_figures[index].name;
}
int nd_amiibo_virtual_supported(size_t index) {
    return index<nd_amiibo_virtual_count() && !nd_virtual_figures[index].needs_application_area;
}
int nd_amiibo_scan_virtual(size_t index) {
    if(!nd_amiibo_virtual_supported(index)) return fail("This figure needs application-area saves (not supported)");
    unsigned char data[540]={0};data[0]=4;
    unsigned char random[6];
    if(getentropy(random,sizeof random)) return fail("System random source unavailable; scan cancelled");
    data[1]=random[0];data[2]=random[1];memcpy(data+4,random+2,4);
    data[3]=0x88^data[0]^data[1]^data[2];data[8]=data[4]^data[5]^data[6]^data[7];
    memcpy(data+12,"\xf1\x10\xff\xee",4);memcpy(data+0x54,nd_virtual_figures[index].id,8);
    pthread_mutex_lock(&mutex);
    int remove=state.state==2 || state.state==4;
    int activate=!remove && state.initialized && state.state==1;
    memcpy(tag,data,sizeof tag);state.loaded=1;state.virtual_index=(int)index;state.current_identity_read=0;state.error[0]=0;
    state.generation++;state.scans++;
    snprintf(state.name,sizeof state.name,"%s",nd_virtual_figures[index].name);
    // A mounted tag is removed once. The next StartDetection activates the new
    // identity; never signal both events immediately or pulse/beep every frame.
    if(remove) state.state=3;
    else if(activate) state.state=2;
    void (*fn)(int)=notification;pthread_mutex_unlock(&mutex);
    if(fn) {if(remove) fn(0);else if(activate) fn(1);}
    return 0;
}
