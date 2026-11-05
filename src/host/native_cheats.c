/* SPDX-License-Identifier: MIT */
/* Version-specific, reversible data-only cheats. No host/code/text patches,
 * pointer chains, downloaded codes or arbitrary interpreter are accepted.
 * Requests are applied by the game presentation thread, not the UI thread. */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include "native_cheats.h"
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define LIMIT 32
typedef struct { char name[49]; uint32_t *word, before, after; int enabled, wanted; } Cheat;
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static Cheat entries[LIMIT];
static size_t count;
static char game[32],build[65],error[160];
static uint64_t base,start,bytes;

static int fail(const char *message) { snprintf(error,sizeof error,"%s",message); return -1; }
const char *nd_cheats_error(void) {
    static _Thread_local char result[sizeof error];
    pthread_mutex_lock(&mutex);memcpy(result,error,sizeof error);pthread_mutex_unlock(&mutex);return result;
}
void nd_cheats_bind(const char *id,const char *hash,uint64_t module_base,uint64_t data_start,uint64_t data_bytes) {
    pthread_mutex_lock(&mutex);
    count=0; memset(entries,0,sizeof entries); error[0]=0;
    base=module_base;start=data_start;bytes=data_bytes;
    snprintf(game,sizeof game,"%s",id);snprintf(build,sizeof build,"%s",hash);
    pthread_mutex_unlock(&mutex);
}
static int hex_value(const char *text,uint64_t *out) {
    if(!text || !*text) return 0;
    if(text[0]=='0' && (text[1]=='x' || text[1]=='X')) text+=2;
    if(!*text) return 0;
    uint64_t value=0;
    while(*text) {
        unsigned char c=(unsigned char)*text++;unsigned d;
        if(c>='0' && c<='9') d=c-'0';
        else if(c>='a' && c<='f') d=c-'a'+10;
        else if(c>='A' && c<='F') d=c-'A'+10;
        else return 0;
        if(value>(UINT64_MAX-d)/16) return 0;
        value=value*16+d;
    }
    *out=value;return 1;
}
int nd_cheats_load(const char *path) {
    pthread_mutex_lock(&mutex);
    if(count) {pthread_mutex_unlock(&mutex);return 0;} // never replace live definitions
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    struct stat st;
    if(fd<0) {pthread_mutex_unlock(&mutex);return 0;}
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() || (st.st_mode&0077) || st.st_size>16384) {
        close(fd);fail("Cheat file must be owner-only, regular and at most 16 KiB");pthread_mutex_unlock(&mutex);return -1;
    }
    FILE *f=fdopen(fd,"r");if(!f) {close(fd);pthread_mutex_unlock(&mutex);return -1;}
    char line[256],g[32],b[65],extra;int good=1;
    if(!fgets(line,sizeof line,f) || sscanf(line,"NATIVE_CHEATS_V1 %31s %64s %c",g,b,&extra)!=2 ||
       !game[0] || strcmp(game,g) || strcmp(build,b)) {fail("Cheat game/build ID does not match this loaded game");good=0;}
    size_t loaded=0;
    while(good && fgets(line,sizeof line,f)) {
        if(line[0]=='#' || line[0]=='\n') continue;
        if(!strchr(line,'\n') && !feof(f)) {fail("Cheat line is too long");good=0;break;}
        char *next=NULL,*label=strtok_r(line," \t\r\n",&next);
        if(!label) continue;
        char *address=strtok_r(NULL," \t\r\n",&next),*expected=strtok_r(NULL," \t\r\n",&next),*replacement=strtok_r(NULL," \t\r\n",&next);
        uint64_t offset,before,after;
        if(loaded>=LIMIT || strlen(label)>48 || strspn(label,"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")!=strlen(label) ||
           strtok_r(NULL," \t\r\n",&next) || !hex_value(address,&offset) || !hex_value(expected,&before) || !hex_value(replacement,&after) || before>UINT32_MAX || after>UINT32_MAX ||
           offset>UINT64_MAX-base || base+offset<start || bytes<4 || base+offset-start>bytes-4 || ((base+offset)&3)) {
            fail("Unsupported cheat line or address outside the game's writable data");good=0;break;
        }
        uint32_t *word=(uint32_t *)(uintptr_t)(base+offset);
        for(size_t i=0;i<loaded;i++) if(entries[i].word==word || !strcmp(entries[i].name,label)) good=0;
        if(!good) {fail("Overlapping or duplicate cheat definitions");break;}
        Cheat *e=&entries[loaded++];snprintf(e->name,sizeof e->name,"%s",label);
        e->word=word;e->before=before;e->after=after;e->enabled=e->wanted=0;
    }
    if(ferror(f)) {fail("Cannot read cheat file");good=0;}
    fclose(f);
    count=good?loaded:0;
    if(!good) memset(entries,0,sizeof entries);
    pthread_mutex_unlock(&mutex);return good?0:-1;
}
size_t nd_cheats_count(void) {pthread_mutex_lock(&mutex);size_t n=count;pthread_mutex_unlock(&mutex);return n;}
const char *nd_cheats_name(size_t index) {
    static _Thread_local char name[49];pthread_mutex_lock(&mutex);
    snprintf(name,sizeof name,"%s",index<count?entries[index].name:"");pthread_mutex_unlock(&mutex);return name;
}
int nd_cheats_enabled(size_t index) {pthread_mutex_lock(&mutex);int on=index<count&&entries[index].enabled;pthread_mutex_unlock(&mutex);return on;}
void nd_cheats_request(size_t index,int on) {pthread_mutex_lock(&mutex);if(index<count) entries[index].wanted=on!=0;pthread_mutex_unlock(&mutex);}
void nd_cheats_apply_pending(void) {
    pthread_mutex_lock(&mutex);
    for(size_t i=0;i<count;i++) {
        Cheat *e=&entries[i];if(e->enabled==e->wanted) continue;
        uint32_t expected=e->wanted?e->before:e->after,value=e->wanted?e->after:e->before;
        if(__atomic_compare_exchange_n(e->word,&expected,value,0,__ATOMIC_SEQ_CST,__ATOMIC_SEQ_CST)) {
            e->enabled=e->wanted;error[0]=0;
        } else {e->wanted=e->enabled;fail("Cheat rejected: expected data changed; no overwrite was made");}
    }
    pthread_mutex_unlock(&mutex);
}
