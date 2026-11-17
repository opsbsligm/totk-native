"""Actual authored HUD masks preserve gameplay and menu face-button semantics."""
from pathlib import Path
import struct,subprocess,tempfile,unittest,zlib
ROOT=Path(__file__).resolve().parents[1]
class PromptMasks(unittest.TestCase):
    def test_context_labels_shape_bounds_and_coverage(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            exe=Path(d)/'prompt-masks'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'src/gfx'),str(ROOT/'tests/deck_prompt_masks_test.c'),'-lm','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=60)

    def test_review_sheet_renders_every_prompt(self):
        # The sheet is how a person checks the artwork; a broken generator must fail here, not in game.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            out=Path(d)/'sheet'
            subprocess.run(['python3','-B',str(ROOT/'tools'/'deck_prompt_sheet.py'),'--output',str(out)],
                           check=True,cwd=ROOT,timeout=120)
            for context in ('world','menu'):
                png=out/f'deck-prompts-{context}.png'
                self.assertTrue(png.is_file(),str(png))
                width,height,pixels=self._decode(png)
                self.assertEqual((width,height),(6*(40*4+10)+10,40*4+2*10))
                # Every face plate colour has to reach the image, which means all six prompts drew.
                for wanted in ((214,58,58),(60,120,232),(58,178,96),(228,168,44)):
                    self.assertIn(wanted,{tuple(pixels[i:i+3]) for i in range(0,len(pixels),3)},
                                  f'{context}: plate {wanted} missing')
                # And the cut-outs stay dark, so no letter silently filled its own plate.
                self.assertLess(min(pixels),30)

    @staticmethod
    def _decode(path):
        data=path.read_bytes()
        pos, idat, size = 8, b'', None
        while pos<len(data):
            (length,)=struct.unpack('>I',data[pos:pos+4]); kind=data[pos+4:pos+8]; body=data[pos+8:pos+8+length]
            if kind==b'IHDR': size=struct.unpack('>II',body[:8])
            if kind==b'IDAT': idat+=body
            pos+=12+length
        width,height=size
        raw=zlib.decompress(idat); stride=width*3+1
        assert len(raw)==stride*height, 'unexpected PNG rows'
        assert all(raw[row*stride]==0 for row in range(height)), 'unexpected PNG filter'
        return width,height,b''.join(raw[row*stride+1:(row+1)*stride+1] for row in range(height))
