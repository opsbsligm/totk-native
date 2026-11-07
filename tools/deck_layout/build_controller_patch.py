# SPDX-License-Identifier: MIT
#!/usr/bin/env python3
"""Build a unified SteamDeck inclined help layout for all ten controller groups.
Geometry module used by deck_font_world; standard library only.
Inputs are read-only. Output must be a new directory outside the input root.
All paths and renderer pixels are explicit inputs; no fixed projection or positions.
"""
import argparse
import collections
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
from anchor_contract import validate as validate_anchors, coverage_points

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('layout_parser',HERE/'resource_layout.py');P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
CONTROLS={'ZL':('left_trigger',),'ZR':('right_trigger',),'L':('left_bumper',),'R':('right_bumper',),'Minus_00':('view',),'Plus':('menu',),'LStick':('left_stick',),'RStick':('right_stick',),'CrossKey':('dpad_center',),'ABXY':('face_south','face_east','face_west','face_north')}
LAYOUT='blyt/PaSystemController_00.bflyt'
PATTERN='anim/PaSystemController_00_Pattern.bflan'
HORSE='anim/PaSystemController_00_IsHorse.bflan'
PROPS=P.PROPS

def sha(b):return hashlib.sha256(b).hexdigest()
def blob(r,c):
    end=max((k['offset']+(12 if c['data_type']==2 else 8) for k in c['keys']),default=c['offset']+12)
    return r[c['offset']:end]
def invpoint(m,p):
    a,b,tx=m[0];c,d,ty=m[1];det=a*d-b*c;assert abs(det)>1e-10
    x,y=p[0]-tx,p[1]-ty
    return [(d*x-b*y)/det,(-c*x+a*y)/det]
def world(m,p):return [m[0][0]*p[0]+m[0][1]*p[1]+m[0][2],m[1][0]*p[0]+m[1][1]*p[1]+m[1][2]]
def synthetic(overrides):
    return {'entries':[dict(name=n,target_type=0,channels=[dict(tag='FLPA',property=k,data_type=2,keys=[dict(frame=0,value=v,slope=0)]) for k,v in fields.items()]) for n,fields in overrides.items()]}
def overrides(a,f):
    out=collections.defaultdict(dict)
    for e in a['entries']:
        if e['target_type']==0:
            for c in e['channels']:
                if c['tag']=='FLPA':out[e['name']][c['property']]=P.eval_channel(c,f)
    return out

def points_for(control,anchors,document):
    ps=[anchors[i]['pixel'] for i in CONTROLS[control]]
    center=[sum(p[i] for p in ps)/len(ps) for i in range(2)]
    return center,[(p,0.) for p in coverage_points(control,anchors,document)]

def group_panes(l,anims,control):
    a=anims['PaSystemController_00_OnOff_'+control];pm={p['name']:p for p in l['panes']};roots=[pm[e['name']] for e in a['entries']];sub=[p for p in l['panes'] if any(p['path']==r['path'] or p['path'].startswith(r['path']+'/') for r in roots)]
    def one(prefix):
        ps=[p for p in sub if p['name'].startswith(prefix)];assert len(ps)==1,(control,prefix);return ps[0]
    return dict(horizontal=one('P_Horizon'),vertical=one('P_Verti'),marker=one(('P_Circle','W_Circle')),roots=[p['name'] for p in roots])

def solve(l,child,anims,anchors,selected,document):
    pm={p['name']:p for p in l['panes']};groups={c:group_panes(l,anims,c) for c in selected};solutions=[];contexts=[]
    for mode in range(3):
        perhorse=[]
        for riding in range(2):
            original=overrides(anims['PaSystemController_00_Pattern'],mode);horse=overrides(anims['PaSystemController_00_IsHorse'],riding)
            assert not {(n,k) for n,v in original.items() for k in v}&{(n,k) for n,v in horse.items() for k in v},'Animation precedence unresolved'
            for n,v in horse.items():original[n].update(v)
            g=P.geometry(l,synthetic(original));picture_part=pm['Pa_Controller_00'];part=g[picture_part['id']]['matrix'];sx,sy=picture_part['parts_scale'];part=P.mul(part,[[sx,0,0],[0,sy,0],[0,0,1]])
            cg=next(x for x in child['static_geometry'] if x['name']=='P_Controller_00');picture=P.mul(part,cg['matrix']);cp=next(p for p in child['panes'] if p['name']=='P_Controller_00');v=cp['values'];f=cp['origin_flags'];left=[-v['width']/2,0,-v['width']][f&3];top=[v['height']/2,0,v['height']][(f>>2)&3]
            def texture_pt(p):return world(picture,[left+p[0]/document['width']*v['width'],top-p[1]/document['height']*v['height']])
            patch={};records=[]
            for control,group in groups.items():
                h,ve,mark=group['horizontal'],group['vertical'],group['marker'];center,coverage=points_for(control,anchors,document);target=texture_pt(center);hg=g[h['id']];start=hg['origin'];parent=g[h['parent']]['matrix'];local_start=invpoint(parent,start);local_target=invpoint(parent,target);dx=local_target[0]-local_start[0];dy=local_target[1]-local_start[1];assert h['origin_flags']==1 and hg['values']['scale_x']==hg['values']['scale_y']==1
                length=math.hypot(dx,dy);assert length>0
                angle=math.degrees(math.atan2(dy,dx));patch[h['name']]={'width':length,'rotation_z':angle}
                patch[ve['name']]={'translation_x':length,'translation_y':0.,'height':0.}
                combined=copy.deepcopy(original)
                for n,vv in patch.items():combined[n].update(vv)
                interim=P.geometry(l,synthetic(combined));new_parent=interim[mark['parent']]['matrix'];old=g[mark['id']]['matrix'];det=new_parent[0][0]*new_parent[1][1]-new_parent[0][1]*new_parent[1][0]
                # Keep original world marker orientation despite rotating the line parent.
                ux=(new_parent[1][1]*old[0][0]-new_parent[0][1]*old[1][0])/det;uy=(-new_parent[1][0]*old[0][0]+new_parent[0][0]*old[1][0])/det
                mv=g[mark['id']]['values'];rotation=math.degrees(math.atan2(uy/mv['scale_x'],ux/mv['scale_x']));w,hgt=mv['width'],mv['height']
                if coverage:
                    cx,cy=target;lin=[[old[0][0],old[0][1],cx],[old[1][0],old[1][1],cy],[0,0,1]];extent=0.
                    for pt,radius in coverage:
                        q=invpoint(lin,texture_pt(pt));# circular button support through inverse linear map
                        icx=math.hypot(old[1][1],old[0][1])/abs(old[0][0]*old[1][1]-old[0][1]*old[1][0]);icy=math.hypot(old[1][0],old[0][0])/abs(old[0][0]*old[1][1]-old[0][1]*old[1][0]);extent=max(extent,abs(q[0])+radius*icx+2,abs(q[1])+radius*icy+2)
                    w=hgt=2*extent
                    # wnd1 frame custom insets must not overlap after resizing.
                    if mark['tag']=='wnd1':
                        custom=mark['custom'];w=max(w,custom[0]+custom[1]+4.);hgt=max(hgt,custom[2]+custom[3]+4.)
                flags=mark['origin_flags'];cx=[0,w/2,-w/2][flags&3];cy=[0,-hgt/2,hgt/2][(flags>>2)&3];a=math.radians(rotation);sx,sy=mv['scale_x'],mv['scale_y'];cx,cy=math.cos(a)*sx*cx-math.sin(a)*sy*cy,math.sin(a)*sx*cx+math.cos(a)*sy*cy;loc=invpoint(new_parent,target)
                fields={'translation_x':loc[0]-cx,'translation_y':loc[1]-cy,'rotation_z':rotation}
                if coverage:fields.update(width=w,height=hgt)
                patch[mark['name']]=fields
                records.append(dict(control=control,anchor_ids=list(CONTROLS[control]),target_pixel=center,target_layout=target,label_end_layout=start,horizontal=h['name'],vertical=ve['name'],marker=mark['name'],coverage_sources=coverage))
            perhorse.append(patch);contexts.append(dict(mode=mode,is_horse=riding,groups=records))
        assert perhorse[0].keys()==perhorse[1].keys()
        for n in perhorse[0]:
            for k,v in perhorse[0][n].items():assert abs(v-perhorse[1][n][k])<2e-5,(n,k,v,perhorse[1][n][k])
        solutions.append(perhorse[0])
    return solutions,contexts,groups

def curve_bytes(property,values):
    keys=[(0.,values[0]),(1.,values[0]),(1.,values[1]),(2.,values[1]),(2.,values[2])]
    return struct.pack('<BBHHHI',0,PROPS.index(property),2,len(keys),0,12)+b''.join(struct.pack('<fff',f,v,0.) for f,v in keys)

def tag_bytes(tag,channels,original_header=None):
    header=bytearray(original_header or (tag.encode()+b'\0'*4));header[4]=len(channels);out=bytearray(header);out.extend(b'\0'*(4*len(channels)))
    for i,b in enumerate(channels):
        struct.pack_into('<I',out,8+i*4,len(out));out.extend(b)
        while len(out)%4:out.append(0)
    return bytes(out)

def rebuild_entry(raw,e,fields,solutions):
    assert e['target_type']==0
    a=e['offset'];count=raw[a+28];blocks=[];seen=set()
    for j in range(count):
        z=a+struct.unpack_from('<I',raw,a+32+4*j)[0];tag=raw[z:z+4].decode();chs=[c for c in e['channels'] if c['tag']==tag];assert len(chs)==raw[z+4]
        data=[]
        for c in chs:
            if tag=='FLPA' and c['property'] in fields:
                data.append(curve_bytes(c['property'],[s[e['name']][c['property']] for s in solutions]));seen.add(c['property'])
            else:data.append(blob(raw,c))
        if tag=='FLPA':
            for prop in fields:
                if prop not in seen:data.append(curve_bytes(prop,[s[e['name']][prop] for s in solutions]));seen.add(prop)
        blocks.append(tag_bytes(tag,data,raw[z:z+8]))
    assert seen==set(fields),'All patched entries must already have FLPA tag'
    out=bytearray(raw[a:a+32]);out.extend(b'\0'*(4*count))
    for j,block in enumerate(blocks):struct.pack_into('<I',out,32+4*j,len(out));out.extend(block)
    return bytes(out)

def patch_animation(raw,a,solutions):
    secs=a['sections'];s=next(s for s in secs if s['tag']=='pai1');o=s['offset'];original=raw[o:o+s['size']];payload=bytearray(original);targets=solutions[0];new_offsets=[];changes=[]
    for e in a['entries']:
        if e['name'] in targets:
            new_offsets.append(len(payload));b=rebuild_entry(raw,e,targets[e['name']],solutions);payload.extend(b);changes.append(dict(pane=e['name'],old_entry_offset=e['offset'],new_entry_offset=o+new_offsets[-1],properties=list(targets[e['name']])))
        else:new_offsets.append(e['offset']-o)
    table=len(payload);payload.extend(b''.join(struct.pack('<I',v) for v in new_offsets));struct.pack_into('<I',payload,16,table);struct.pack_into('<I',payload,4,len(payload));out=bytearray(raw[:o]+payload+raw[o+s['size']:]);struct.pack_into('<I',out,12,len(out))
    # Original inactive bytes remain unchanged: only section size + table relocation.
    for i,(x,y) in enumerate(zip(original,payload[:len(original)])):
        if x!=y:assert i in set(range(4,8))|set(range(16,20))
    P.parse_animation(bytes(out))
    return bytes(out),changes
