"""Own synthetic SFNT/CFF fixture: outline/metric identity and exact size/checksums."""
from pathlib import Path
import importlib.util,struct,unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import deck_font_shoulders as shoulders
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
    def test_growing_index_preserves_other_glyphs_tables_and_private_addresses(self):
        original = fixture()
        replacement = {8: shoulders.outline('R2')}
        patched = m.replace_outlines(original, replacement)
        self.assertGreater(len(patched), len(original))
        m.verify_checksums(patched)
        before, after = m.charstrings(original)[0], m.charstrings(patched)[0]
        self.assertEqual(len(before), len(after))
        for i, value in enumerate(before):
            self.assertEqual(after[i], replacement.get(i, value))
        old, new = m.tables(original), m.tables(patched)
        self.assertEqual(old.keys(), new.keys())
        for tag in old:
            a, n = old[tag][1:]; b, size = new[tag][1:]
            if tag == b'CFF ':
                old_cff, new_cff = original[a:a+n], patched[b:b+size]
                _, _, at, _ = m.cff_index(old_cff, old_cff[2])
                top, start, end, _ = m.cff_index(old_cff, at)
                self.assertEqual(old_cff[:start], new_cff[:start])
                self.assertEqual(old_cff[end:], new_cff[end:n])
                new_top = m.cff_index(new_cff, at)[0][0]
                self.assertEqual(m.cff_dict(new_top), m.cff_dict(top[0]) | {17: [n]})
            elif tag == b'head':
                self.assertEqual(original[a:a+8]+original[a+12:a+n], patched[b:b+8]+patched[b+12:b+size])
            else:
                self.assertEqual(original[a:a+n], patched[b:b+size])

    def test_replacement_rejects_bad_checksum_and_bad_indices(self):
        original = fixture()
        broken = bytearray(original); broken[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            m.replace_outlines(broken, {8: b'\x0e'})
        for replacements in ({}, {True: b'\x0e'}, {-1: b'\x0e'}, {10: b'\x0e'}, {8: b''}, {8: b'x' * 2049}):
            with self.assertRaises(ValueError):
                m.replace_outlines(original, replacements)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            m.cff_dict(b'\x8b\x11\x8b\x11')

    def test_authored_shoulders_decode_to_bounded_closed_paths_and_exact_width(self):
        seen = set()
        for label in shoulders.LABELS:
            code = shoulders.outline(label)
            self.assertNotIn(code, seen); seen.add(code)
            stack = []; at = 0; x = y = 0; contours = []; points = None; widths = []
            while at < len(code):
                b = code[at]; at += 1
                if b == 28:
                    stack.append(int.from_bytes(code[at:at+2], 'big', signed=True)); at += 2
                elif 32 <= b <= 246:
                    stack.append(b - 139)
                elif 247 <= b <= 254:
                    value = code[at]; at += 1
                    stack.append((b-247)*256+value+108 if b <= 250 else -(b-251)*256-value-108)
                elif b == 21:
                    if not contours:
                        widths.append(stack.pop(0) + 707)
                    self.assertEqual(len(stack), 2)
                    x += stack[0]; y += stack[1]; stack = []
                    points = [(x, y)]; contours.append(points)
                elif b == 5:
                    self.assertLessEqual(len(stack), 48); self.assertEqual(len(stack) % 2, 0)
                    for dx, dy in zip(stack[::2], stack[1::2]):
                        x += dx; y += dy; points.append((x, y))
                    stack = []
                else:
                    self.assertEqual(b, 14); self.assertEqual(at, len(code)); self.assertFalse(stack)
            self.assertEqual(widths, [720])
            self.assertEqual(len(contours), 4 if label[0] == 'R' else 3)
            for i, polygon in enumerate(contours):
                self.assertEqual(polygon[0], polygon[-1])
                self.assertTrue(all(0 <= a <= 720 and 0 <= b <= 717 for a, b in polygon))
                area = sum(a*d-b*c for (a,b),(c,d) in zip(polygon, polygon[1:]))
                self.assertEqual(area > 0, i in (0, 3))
        with self.assertRaises(ValueError): shoulders.outline('ZR')

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
