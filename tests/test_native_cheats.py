"""Run the real patch engine against bounded synthetic game memory."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
HOST=ROOT/'src/host'


class NativeCheats(unittest.TestCase):
    def test_version_bounds_cas_and_reversible_changes(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);source=root/'main.c';binary=root/'check'
            source.write_text(r'''
#define _POSIX_C_SOURCE 200809L
#include "native_cheats.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static uint32_t words[4]={10,20,30,40};
static void bind(void) { nd_cheats_bind("synthetic","abc",(uintptr_t)words,(uintptr_t)words,sizeof words); }
static void fixture(const char *name,const char *body) {
    FILE *f=fopen(name,"w");assert(f);fputs(body,f);assert(fclose(f)==0);assert(chmod(name,0600)==0);
}
int main(int argc,char **argv) {
    assert(argc==2);const char *p=argv[1];bind();
    fixture(p,"NATIVE_CHEATS_V1 wrong abc\nPatch 0 a b\n");assert(nd_cheats_load(p)<0);assert(words[0]==10);
    fixture(p,"NATIVE_CHEATS_V1 synthetic wrong-build\nPatch 0 a b\n");assert(nd_cheats_load(p)<0);
    fixture(p,"NATIVE_CHEATS_V1 synthetic abc\nBad 10 28 32\n");assert(nd_cheats_load(p)<0);
    fixture(p,"NATIVE_CHEATS_V1 synthetic abc\nBad 1 a b\n");assert(nd_cheats_load(p)<0);
    fixture(p,"NATIVE_CHEATS_V1 synthetic abc\nOne 0 a b\nTwo 0 a c\n");assert(nd_cheats_load(p)<0);assert(nd_cheats_count()==0);
    fixture(p,"NATIVE_CHEATS_V1 synthetic abc\nPatch 0 a b\n");assert(chmod(p,0644)==0);assert(nd_cheats_load(p)<0);
    assert(chmod(p,0600)==0);assert(nd_cheats_load(p)==0);assert(nd_cheats_count()==1);
    nd_cheats_request(0,1);assert(words[0]==10);nd_cheats_apply_pending();assert(words[0]==11);assert(nd_cheats_enabled(0));
    nd_cheats_request(0,0);nd_cheats_apply_pending();assert(words[0]==10);assert(!nd_cheats_enabled(0));
    nd_cheats_request(0,1);nd_cheats_apply_pending();words[0]=12;
    nd_cheats_request(0,0);nd_cheats_apply_pending();assert(words[0]==12);assert(strstr(nd_cheats_error(),"changed"));
    assert(words[1]==20 && words[2]==30 && words[3]==40);
    bind();unlink(p);assert(symlink("no-such-file",p)==0);assert(nd_cheats_load(p)==0);assert(nd_cheats_count()==0);
    return 0;
}
''')
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pthread','-I',str(HOST),str(source),str(HOST/'native_cheats.c'),'-o',str(binary)],check=True)
            subprocess.run([str(binary),str(root/'presets.txt')],check=True)
