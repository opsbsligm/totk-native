"""Own synthetic SFNT/CFF fixture: outline/metric identity and exact size/checksums."""
from pathlib import Path
import importlib.util,struct,unittest
spec=importlib.util.spec_from_file_location('deck_font',Path(__file__).resolve().parents[1]/'tools/deck_font_glyphs.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def index(items):
    offsets=[1]
    for item in items:offsets.append(offsets[-1]+len(item))
    return len(items).to_bytes(2,'big')+b'\x01'+bytes(offsets)+b''.join(items)
def fixture():
    names=index([b'Synthetic']);dummy=index([b'\x8b\x11'])
    at=4+len(names)+len(dummy)+4
    cff=b'\x01\x00\x04\x01'+names+index([bytes([at+139,17])])+b'\0\0\0\0'+index([bytes([139+i,14]) for i in range(10)])
    head=bytearray(54);hhea=bytearray(36);struct.pack_into('>H',hhea,34,10)
    payload={b'CFF ':cff,b'head':head,b'hhea':hhea,b'hmtx':b''.join(struct.pack('>Hh',100+i,i) for i in range(10)),b'maxp':struct.pack('>IH',0x5000,10)}
    out=bytearray(struct.pack('>4sHHHH',b'OTTO',len(payload),0,0,0)+b'\0'*(16*len(payload)))
    for i,(tag,data) in enumerate(payload.items()):
        out+=b'\0'*(-len(out)%4);off=len(out);out+=data;struct.pack_into('>4sIII',out,12+i*16,tag,m.checksum(data),off,len(data))
    out+=b'\0'*(-len(out)%4);head=m.tables(out)[b'head'][1];struct.pack_into('>I',out,head+8,(0xb1b0afba-m.checksum(out))&0xffffffff)
    return bytes(out)
class FontGlyphs(unittest.TestCase):
    def test_exact_size_outline_metrics_checksum_and_involution(self):
        original=fixture();m.verify_checksums(original);patched=m.swap_outlines(original,8,9);m.verify_checksums(patched)
        self.assertEqual(len(original),len(patched));before,*_=m.charstrings(original);after,*_=m.charstrings(patched)
        self.assertEqual(before[:8],after[:8]);self.assertEqual(before[8:10],list(reversed(after[8:10])))
        self.assertEqual(m.swap_outlines(patched,8,9),original)
        d=m.tables(original)
        for tag in (b'hhea',b'maxp'):
            _,off,n=d[tag];self.assertEqual(original[off:off+n],patched[off:off+n])
        with self.assertRaises(ValueError):m.patch_external(original)
    def test_malformed_table_ranges_and_indices_fail_closed(self):
        original=fixture()
        for a,b in ((8,10),(8,8),(-1,9),(True,9)):
            with self.assertRaises(ValueError):m.swap_outlines(original,a,b)
        for broken in (original[:20],b'OTTO'+b'\0'*8):
            with self.assertRaises(ValueError):m.swap_outlines(broken,8,9)
        for data in (b'\0\1',b'\0\1\0',b'\0\1\1\2\1',b'\0\1\1\1\xff'):
            with self.assertRaises(ValueError):m.cff_index(data,0)
