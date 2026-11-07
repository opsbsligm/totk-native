# SPDX-License-Identifier: MIT
#!/usr/bin/env python3
"""Read-only FLYT/FLAN 9.0 parsing and geometry library; standard library only.
All offsets are absolute byte offsets in the indicated original small file.
No texture decoding, patching, SSH, credentials, archive extraction or rendering.
"""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import re
import struct

PROPS = ['translation_x','translation_y','translation_z','rotation_x','rotation_y','rotation_z','scale_x','scale_y','width','height']
PANES = {'pan1','pic1','txt1','wnd1','prt1','bnd1','ali1','scr1'}
SOURCES = ['https://github.com/Tyulis/3DSkit/blob/master/doc/BFLYT.md', 'https://github.com/Tyulis/3DSkit/blob/master/doc/BFLAN.md']

def digest(b): return hashlib.sha256(b).hexdigest()

class Reader:
    def __init__(self,b):
        self.b=b
        assert b[4:6] in (b'\xff\xfe',b'\xfe\xff'), 'BOM'
        self.e='<' if b[4:6]==b'\xff\xfe' else '>'
    def u(self,f,o):
        assert 0<=o and o+struct.calcsize(self.e+f)<=len(self.b), (f,o,len(self.b))
        v=struct.unpack_from(self.e+f,self.b,o)
        return v[0] if len(v)==1 else list(v)
    def s(self,o,n=None):
        assert 0<=o<=len(self.b)
        q=self.b[o:o+n] if n is not None else self.b[o:]
        return q.split(b'\0',1)[0].decode('utf-8',errors='replace')
    def section(self,o,limit):
        t=self.b[o:o+4].decode('ascii'); n=self.u('I',o+4)
        assert n>=8 and n%4==0 and o+n<=limit,(t,o,n,limit)
        return dict(tag=t,offset=o,size=n,raw_hex=self.b[o:o+n].hex())
    def sections(self):
        assert self.b[:4] in (b'FLYT',b'FLAN') and self.u('I',12)==len(self.b)
        assert self.u('I',8)==0x09000000, 'Only observed version 9 supported'
        p=self.u('H',6); out=[]
        for _ in range(self.u('H',16)):
            s=self.section(p,len(self.b));out.append(s);p+=s['size']
        assert p==len(self.b), 'Unaccounted trailer'
        return out

def names(r,o):
    n=r.u('I',o+8);base=o+12
    return [r.s(base+r.u('I',base+i*4)) for i in range(n)]

def userdata(r,o):
    out=[]
    for i in range(r.u('H',o+8)):
        a=o+12+12*i;no,do,n,t,_=r.u('IIHBB',a);p=a+do
        d=dict(name=r.s(a+no),type=t,count=n,offset=p)
        if t in (1,2): d['values']=[r.u('i' if t==1 else 'f',p+4*j) for j in range(n)]
        elif t==0:d['value']=r.s(p,n)
        elif t==3:
            # Switch extended strings: offsets relative to data+8, not section.
            base=p+8;subtype=r.u('I',p+8);d['subtype']=subtype
            if subtype==0:
                cnt=r.u('I',p+12)
                d['values']=[r.s(base+r.u('I',p+16+4*j)) for j in range(cnt)]
            elif subtype==2:
                d['bitfield_raw']=r.u('I',p+12)
            else:
                d['unresolved_extended_data']=r.b[p:a+no].hex()
        else:d['unresolved_type']=True
        out.append(d)
    return out

def pane(r,s,parent=None):
    o=s['offset'];t=s['tag'];v=r.u('10f',o+44)
    p=dict(name=r.s(o+12,32),tag=t,offset=o,parent=parent,flags=r.u('B',o+8),origin_flags=r.u('B',o+9),alpha=r.u('B',o+10),pane_magnify_flags=r.u('B',o+11),values=dict(zip(PROPS,v)),field_offsets={k:o+44+i*4 for i,k in enumerate(PROPS)},children=[],userdata=[])
    if t=='pic1':
        p.update(material_index=r.u('H',o+100),material_index_offset=o+100,vertex_rgba=[r.u('4B',o+84+i*4) for i in range(4)],uvs=[r.u('8f',o+104+i*32) for i in range(r.u('B',o+102))])
    if t=='txt1':
        p.update(text_buffer_bytes=r.u('H',o+84),text_bytes=r.u('H',o+86),material_index=r.u('H',o+88),font_index=r.u('H',o+90),material_index_offset=o+88,text_offset=o+r.u('I',o+100),text_alignment=r.u('B',o+92),line_alignment=r.u('B',o+93),font_size=r.u('2f',o+112),character_spacing=r.u('f',o+120),line_spacing=r.u('f',o+124))
        a=p['text_offset'];end=o+s['size'];raw=bytearray()
        while a+2<=end and r.b[a:a+2]!=b'\0\0':raw.extend(r.b[a:a+2]);a+=2
        p['text']=bytes(raw).decode('utf-16-le' if r.e=='<' else 'utf-16-be',errors='replace')
        call=r.u('I',o+128);p['text_call_name']=r.s(o+call) if call else None
    if t=='wnd1':
        a=o+r.u('I',o+104);base=o+r.u('I',o+108);n=r.u('B',o+100)
        p.update(stretch=r.u('4H',o+84),custom=r.u('4H',o+92),window_flags=r.u('B',o+101),material_index=r.u('H',a+16),material_index_offset=a+16,uvs=[r.u('8f',a+20+i*32) for i in range(r.u('B',a+18))],frames=[])
        for i in range(n):
            a=o+r.u('I',base+4*i);p['frames'].append(dict(material_index=r.u('H',a),texture_flip=r.u('B',a+2),offset=a))
    if t=='prt1':
        n=r.u('I',o+84);p.update(parts_scale=r.u('2f',o+88),part_entries=[],layout_ref=r.s(o+96+40*n),layout_ref_offset=o+96+40*n)
        for i in range(n):
            a=o+96+40*i;po,uo,eo=r.u('III',a+28)
            q=dict(name=r.s(a,24),flags=r.u('4B',a+24),offset=a,pane_offset=o+po if po else None,userdata_offset=o+uo if uo else None,extra_offset=o+eo if eo else None)
            if po:
                sub=r.section(o+po,o+s['size']);q['pane']=pane(r,sub)
            if uo:q['userdata']=userdata(r,o+uo)
            if eo:q['extra_raw_hex']=r.b[o+eo:o+eo+48].hex()
            p['part_entries'].append(q)
    if t=='ali1':p['alignment_raw']={'words':r.u('III',o+84),'floats':r.u('3f',o+84),'semantics':'runtime alignment unresolved; stored transform only'}
    return p

def materials(r,s,textures):
    o=s['offset'];n=r.u('I',o+8);offs=[o+r.u('I',o+12+4*i) for i in range(n)]+[o+s['size']];out=[]
    for i,a in enumerate(offs[:-1]):
        end=offs[i+1];flags=r.u('I',a+28);q=dict(index=i,name=r.s(a,28),offset=a,size=end-a,flags=hex(flags),unknown_header=r.b[a+32:a+36].hex(),foreground=r.u('4B',a+36),background=r.u('4B',a+40),textures=[],texture_srt=[],mapping=[],raw_hex=r.b[a:end].hex());p=a+44
        for j in range(flags&3):
            ti,ws,wt=r.u('HBB',p);assert ti<len(textures)
            q['textures'].append(dict(slot=j,index=ti,name=textures[ti],index_offset=p,wrap_s=ws,wrap_t=wt));p+=4
        for j in range((flags>>2)&3):q['texture_srt'].append(dict(offset=p,values=r.u('5f',p)));p+=20
        for j in range((flags>>4)&3):q['mapping'].append(dict(offset=p,raw_hex=r.b[p:p+16].hex(),method=r.u('B',p+1)));p+=16
        # Preserve complex combiner/blend/projection bytes exactly; do not invent v9 semantics.
        assert p<=end
        q['uninterpreted_render_state']={'offset':p,'size':end-p,'hex':r.b[p:end].hex()};out.append(q)
    return out

def parse_layout(b):
    r=Reader(b);secs=r.sections();d=dict(version=hex(r.u('I',8)),sections=secs,panes=[],textures=[],fonts=[],materials=[],groups=[],animation_metadata=[]);stack=[];last=None;owner=None;gstack=[];lastg=None
    for s in secs:
        t=s['tag'];o=s['offset']
        if t=='lyt1':d['layout']={'draw_from_middle':r.u('B',o+8),'size':r.u('2f',o+12),'max_parts_size':r.u('2f',o+20),'name':r.s(o+28)}
        elif t=='txl1':d['textures']=names(r,o)
        elif t=='fnl1':d['fonts']=names(r,o)
        elif t=='mat1':d['materials']=materials(r,s,d['textures'])
        elif t in PANES:
            p=pane(r,s,stack[-1] if stack else None);p['id']=len(d['panes']);d['panes'].append(p);last=p['id'];owner=last
            if stack:d['panes'][stack[-1]]['children'].append(last)
        elif t=='pas1':assert last is not None;stack.append(last)
        elif t=='pae1':assert stack;stack.pop()
        elif t=='usd1':
            u=userdata(r,o);s['entries']=u;s['owner_pane_id']=owner
            if owner is not None:d['panes'][owner]['userdata'].extend(u)
            else:d.setdefault('userdata',[]).extend(u)
        elif t=='grp1':
            n=r.u('H',o+42);g=dict(name=r.s(o+8,34),parent=gstack[-1] if gstack else None,panes=[r.s(o+44+24*i,24) for i in range(n)]);d['groups'].append(g);lastg=len(d['groups'])-1
        elif t=='grs1':gstack.append(lastg)
        elif t=='gre1':assert gstack;gstack.pop()
        elif t=='cnt1':
            name,main,np,na,pt,at=r.u('IIHHII',o+8)
            q=dict(name=r.s(o+name),parts_count=np,animations_count=na,parts=[],animations=[])
            if np:q['parts']=[r.s(o+pt+r.u('I',o+pt+4*i)) for i in range(np)]
            if na:q['animations']=[r.s(o+at+r.u('I',o+at+4*i)) for i in range(na)]
            d['animation_metadata'].append(q)
        else:s['semantics']='uninterpreted; exact payload retained'
    assert not stack and not gstack
    for p in d['panes']:
        p['path']=(d['panes'][p['parent']]['path']+'/' if p['parent'] is not None else '')+p['name']
        for q in [p]+p.get('frames',[]):
            if 'material_index' in q:assert q['material_index']<len(d['materials']);q['material']=d['materials'][q['material_index']]['name']
    return d

def parse_animation(b):
    r=Reader(b);secs=r.sections();d=dict(version=hex(r.u('I',8)),sections=secs,entries=[],textures=[])
    for s in secs:
        o=s['offset']
        if s['tag']=='pat1':
            d['pattern']={'order':r.u('H',o+8),'name':r.s(o+r.u('I',o+12)),'groups':[r.s(o+r.u('I',o+16)+36*i,36) for i in range(r.u('H',o+10))], 'range_raw':r.u('8B',o+20)}
        elif s['tag']=='pai1':
            d.update(frame_size=r.u('H',o+8),flags=r.u('B',o+10));nt,ne=r.u('HH',o+12);base=o+20;d['textures']=[r.s(base+r.u('I',base+4*i)) for i in range(nt)];tab=o+r.u('I',o+16)
            for i in range(ne):
                a=o+r.u('I',tab+4*i);nc,typ=r.u('BB',a+28);en=dict(name=r.s(a,28),target_type=typ,offset=a,channels=[])
                for j in range(nc):
                    z=a+r.u('I',a+32+4*j)
                    if typ==2:z+=4
                    tag=r.b[z:z+4].decode('ascii');num=r.u('B',z+4)
                    for k in range(num):
                        c=z+r.u('I',z+8+4*k);idx,target,dt,nk,_,ko=r.u('BBHHHI',c)
                        q=dict(tag=tag,index=idx,target=target,data_type=dt,offset=c,keys=[])
                        if tag=='FLPA' and target<len(PROPS):q['property']=PROPS[target]
                        else:q['property']={'FLVI':'visible','FLTP':'texture_index','FLVC':'vertex_color_or_alpha','FLMC':'material_color'}.get(tag,'unresolved')
                        assert dt in (1,2),(tag,dt)
                        for h in range(nk):
                            ka=c+ko+h*(12 if dt==2 else 8);key=dict(frame=r.u('f',ka),value=r.u('f' if dt==2 else 'H',ka+4),offset=ka,value_offset=ka+4)
                            if dt==2:key['slope']=r.u('f',ka+8)
                            if tag=='FLTP':assert key['value']<nt;key['texture']=d['textures'][key['value']]
                            q['keys'].append(key)
                        q['duplicate_frame_boundaries']=[dict(frame=f,keys=[k for k in q['keys'] if k['frame']==f]) for f,n in collections.Counter(k['frame'] for k in q['keys']).items() if n>1]
                        en['channels'].append(q)
                d['entries'].append(en)
    return d

def identity():return [[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]
def mul(a,b):return [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def point(m,x,y):return [round(m[0][0]*x+m[0][1]*y+m[0][2],6),round(m[1][0]*x+m[1][1]*y+m[1][2],6)]
def eval_channel(c,f):
    ks=c['keys'];assert ks
    exact=[k for k in ks if k['frame']==f]
    if exact:return exact[-1]['value']  # explicit right-continuous model, not runtime proof
    if f<=ks[0]['frame']:return ks[0]['value']
    if f>=ks[-1]['frame']:return ks[-1]['value']
    for a,b in zip(ks,ks[1:]):
        if a['frame']<=f<b['frame']:
            if c['data_type']==1:return a['value']
            span=b['frame']-a['frame'];u=(f-a['frame'])/span
            return (2*u**3-3*u**2+1)*a['value']+(u**3-2*u**2+u)*span*a['slope']+(-2*u**3+3*u**2)*b['value']+(u**3-u**2)*span*b['slope']

def geometry(d,anim=None,frame=0):
    overrides=collections.defaultdict(dict)
    if anim:
        for e in anim['entries']:
            if e['target_type']==0:
                for c in e['channels']:
                    if c['tag']=='FLPA':overrides[e['name']][c['property']]=eval_channel(c,frame)
    out=[];mats=[];vals=[]
    for p in d['panes']:
        v=dict(p['values']);v.update(overrides[p['name']]);vals.append(v)
        assert v['rotation_x']==v['rotation_y']==0,'3D transform not supported by 2D solver'
        f=p['origin_flags'];px=(f>>4)&3;py=(f>>6)&3
        assert max(f&3,(f>>2)&3,px,py)<3,'Unsupported origin'
        x=v['translation_x'];y=v['translation_y'];parent=p['parent']
        if parent is not None:
            pv=vals[parent];x+= [0,-.5,.5][px]*pv['width'];y+=[0,.5,-.5][py]*pv['height']
        a=math.radians(v['rotation_z']);c=math.cos(a);s=math.sin(a);local=[[c*v['scale_x'],-s*v['scale_y'],x],[s*v['scale_x'],c*v['scale_y'],y],[0,0,1]];m=mul(mats[parent],local) if parent is not None else local;mats.append(m)
        # Vertices relative to pane origin, Y up. Parent origin is independent.
        w=v['width'];h=v['height'];left=[-w/2,0,-w][f&3];top=[h/2,0,h][(f>>2)&3]
        corners=[point(m,left,top),point(m,left+w,top),point(m,left,top-h),point(m,left+w,top-h)]
        out.append(dict(pane_id=p['id'],name=p['name'],path=p['path'],values=v,matrix=m,origin=point(m,0,0),center=point(m,left+w/2,top-h/2),corners_tl_tr_bl_br=corners,centerline_horizontal=[point(m,left,top-h/2),point(m,left+w,top-h/2)],centerline_vertical=[point(m,left+w/2,top),point(m,left+w/2,top-h)],stored_visible=bool(p['flags']&1),caveat='stored transforms; no runtime ali1 alignment, capture filter, animation blending or screen projection'))
    return out
