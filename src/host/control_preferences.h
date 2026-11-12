/* Original control-bar settings parser, MIT. Bounded, nonblocking local input. */
#pragma once
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static inline bool nd_control_pref_number(char **cursor,const char *key,int *value) {
    char *p=*cursor,*end;size_t n=strlen(key);
    if(strncmp(p,key,n)) return false;
    p+=n;if(*p<'0' || *p>'9') return false;
    errno=0;long v=strtol(p,&end,10);
    if(errno || v>INT_MAX || (*end!='\n' && *end!=0)) return false;
    *value=(int)v;*cursor=*end?end+1:end;return true;
}
static inline bool nd_control_preferences_read_extended(const char *path,int *anchor,int *fps,int *gyro,int *upscaler,int *sharpness,int *perf,int *aniso) {
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
    if(fd<0) return false;
    struct stat st;char text[129];size_t used=0;bool ok=false;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() ||
       (st.st_mode&0077) || st.st_size<0 || st.st_size>128) {close(fd);return false;}
    while(used<sizeof text-1) {
        ssize_t n=read(fd,text+used,sizeof text-1-used);
        if(n<0) {if(errno==EINTR) continue;close(fd);return false;}
        if(!n) {ok=true;break;}
        used+=(size_t)n;
    }
    close(fd);
    if(!ok || memchr(text,0,used)) return false;
    text[used]=0;char *p=text;int a,f,g;
    if(!nd_control_pref_number(&p,"anchor=",&a)) return false;
    // The untouched UI cap inherits the launcher (-1). Accept only this exact
    // signed sentinel; all other fields and numeric caps remain unsigned.
    if(!strncmp(p,"fps=-1\n",7)) {f=-1;p+=7;}
    else if(!nd_control_pref_number(&p,"fps=",&f)) return false;
    int u=0,s=50,pr=0,an=0;
    if(!nd_control_pref_number(&p,"gyro=",&g)) return false;
    if(*p && (!nd_control_pref_number(&p,"upscaler=",&u) || !nd_control_pref_number(&p,"sharpness=",&s))) return false;
    if(*p && !nd_control_pref_number(&p,"perf=",&pr)) return false;
    if(*p && !nd_control_pref_number(&p,"aniso=",&an)) return false;
    if(*p || a>=8 || g>1 || u>1 || s>100 || pr>2 || an>4 ||
       !(f==-1 || f==30 || f==40 || f==45 || f==60 || f==90 || f==120 || f==144)) return false;
    *anchor=a;*fps=f;*gyro=g;*upscaler=u;*sharpness=s;*perf=pr;*aniso=an;return true;
}

static inline bool nd_control_preferences_read(const char *path,int *anchor,int *fps,int *gyro) {
    int up,sharp,perf,an;return nd_control_preferences_read_extended(path,anchor,fps,gyro,&up,&sharp,&perf,&an);
}
