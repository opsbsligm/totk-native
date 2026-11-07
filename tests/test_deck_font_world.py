"""Resource preservation, strict identity and allocation bounds. MIT."""
from pathlib import Path
import binascii
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import deck_font_world as w
from deck_font_prompts import members


class WorldResources(unittest.TestCase):
    def test_sarc_roundtrip_preserves_members_names_and_unknown_bytes(self):
        files={'fcpx/ours.bfcpx':bytes(range(256)), 'scft/ours.bfotf':b'own synthetic font', 'unrelated':b'keep\0exact'}
        raw=w.sarc_pack(files)
        self.assertEqual({n:raw[a:b] for n,(a,b) in members(raw).items()},files)
        self.assertEqual(raw,w.sarc_pack(dict(reversed(list(files.items())))))
        for names in ({}, {'../escape':b''}, {'/absolute':b''}, {'nul\0name':b''}):
            with self.assertRaises(ValueError):w.sarc_pack(names)

    def test_font_reference_changes_only_the_selected_name(self):
        name=b'External_00.fcpx\0';name+=b'\0'*(-len(name)%4)
        section=struct.pack('<4sIII',b'fnl1',16+len(name),1,4)+name
        data=struct.pack('<4sHHIIHH',b'FLYT',0xfeff,20,0x9000000,20+len(section),1,0)+section
        result=w.world_font_ref(data)
        self.assertEqual(result,data.replace(b'External_00.fcpx',b'DeckWrld_00.fcpx'))
        with self.assertRaises(ValueError):w.world_font_ref(result)
        for broken in (data[:-1],b'',data[:12]):
            with self.assertRaises(ValueError):w.world_font_ref(broken)

    def test_allocations_change_only_requested_existing_entries(self):
        names=['Font/a.bfarc','Font/b.bfarc','unrelated']
        entries=sorted((binascii.crc32(n.encode()),0x12000+i) for i,n in enumerate(names))
        raw=b'RESTBL'+struct.pack('<4I',1,64,len(entries),0)+b''.join(struct.pack('<2I',*x) for x in entries)
        result=w.allocation_table(raw,{'Font/a.bfarc.zs':0x20000})
        self.assertEqual(len(raw),len(result))
        for i,(crc,size) in enumerate(entries):
            self.assertEqual(struct.unpack_from('<2I',result,22+8*i),(crc,size+(0x20000 if crc==binascii.crc32(names[0].encode()) else 0)))
        for growth in ({'missing.zs':1},{'Font/a.bfarc.zs':0},{'Font/a.bfarc.zs':2**20+1}):
            with self.assertRaises(ValueError):w.allocation_table(raw,growth)
        for broken in (raw[:-1],b'',raw[:20]):
            with self.assertRaises(ValueError):w.allocation_table(broken,{'Font/a.bfarc.zs':1})

    def test_unknown_common_is_refused_before_layout_read(self):
        with self.assertRaisesRegex(ValueError,'Unsupported original Common'):w.common_archive(b'unknown',b'not a layout')
