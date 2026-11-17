"""Actual authored HUD masks preserve gameplay and menu face-button semantics."""
from pathlib import Path
import collections,struct,subprocess,tempfile,unittest,zlib
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

    def test_sheet_downscale_covers_the_whole_source(self):
        # The review sheet is what a person judges the artwork with. If its downsampler reads only a
        # leading block of the mask, the reviewer sees a clipped disc and the test still passes, so
        # the coverage rule is asserted here: light only the last row and column of the source, and
        # the lit pixels have to arrive as exactly the last row and column of the output. An
        # integer-step sampler reads 80 of the 108 rows at 40px and would return an all-zero image.
        import importlib.util
        spec=importlib.util.spec_from_file_location('deck_prompt_sheet',str(ROOT/'tools'/'deck_prompt_sheet.py'))
        sheet=importlib.util.module_from_spec(spec); spec.loader.exec_module(sheet)
        source=108
        for size in (40,48,27):
            mask=bytes(255 if (row==source-1 or column==source-1) else 0
                       for row in range(source) for column in range(source))
            small=sheet.downscale(mask,size,source)
            self.assertEqual(len(small),size*size)
            lit={i for i,v in enumerate(small) if v}
            wanted={i for i in range(size*size)
                    if i//size==size-1 or i%size==size-1}
            self.assertEqual(lit,wanted,f'{size}px: downsampler dropped part of the source edge')
            self.assertGreater(small[-1],small[size-1],f'{size}px: the shared corner should be brightest')

    def test_sheet_pairs_each_plate_with_the_letter_that_context_draws(self):
        # The preview names each mask after the letter it actually drew, and in the menu context the
        # game swaps confirm and cancel. Naming the files by code instead of by drawn letter paired
        # every menu column with another code's mask, which left the two sheets byte-identical while
        # still looking like six clean prompts. So assert the colour that dominates each cell — the
        # colour comes from the letter, so a mispaired mask shows up as the wrong plate.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            out=Path(d)/'sheet'
            subprocess.run(['python3','-B',str(ROOT/'tools'/'deck_prompt_sheet.py'),'--output',str(out)],
                           check=True,cwd=ROOT,timeout=120)
            sheets={context:self._decode(out/f'deck-prompts-{context}.png') for context in ('world','menu')}
            self.assertNotEqual(sheets['world'][2],sheets['menu'][2],'menu context drew the world layout')
            import importlib.util
            spec=importlib.util.spec_from_file_location('deck_prompt_sheet',str(ROOT/'tools'/'deck_prompt_sheet.py'))
            sheet=importlib.util.module_from_spec(spec); spec.loader.exec_module(sheet)
            cell,upscale,gutter=40,4,10
            for context,(width,_height,pixels) in sheets.items():
                for code in range(4):
                    x0=gutter+code*(cell*upscale+gutter); x1=x0+cell*upscale
                    y0=gutter; y1=y0+cell*upscale
                    seen=collections.Counter()
                    for y in range(y0,y1):
                        row=y*width*3
                        for x in range(x0,x1):
                            px=tuple(pixels[row+3*x:row+3*x+3])
                            if px in sheet.PLATES.values(): seen[px]+=1
                    wanted=sheet.PLATES[sheet.prompt_name(code,context)]
                    self.assertGreater(seen[wanted],0,f'{context} code {code}: {wanted} plate absent')
                    self.assertEqual(max(seen,key=seen.get),wanted,
                                     f'{context} code {code}: plate colour does not match its letter')

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
