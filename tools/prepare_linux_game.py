"""Prepare checked local 1.4.3 input for the native Linux build (no decryption).

Each stage is explicit: check, lift, romfs. Run only when existing games are idle.
"""
import argparse
from contextlib import nullcontext
import os
from pathlib import Path
import subprocess
import sys

from linux_inputs import BASES, ROOT, check_exefs, expected, seal_generated


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dump', type=Path, required=True)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--stage', choices=('check', 'lift', 'romfs'), default='check')
    p.add_argument('--code-mods', type=Path, help='Read-only version-bound ExeFS patches before AOT')
    a = p.parse_args()
    try:
        check_exefs(a.dump / 'exefs')
        packed = (a.dump / 'romfs/romfs.bin').is_file()
        if packed:
            from packed_inputs import rows_for
            rows_for(a.dump / 'romfs')
        if not packed and not (a.dump / 'romfs/Pack/ZsDic.pack.zs').is_file():
            p.error('Missing extracted TOTK RomFS (Pack/ZsDic.pack.zs)')
        context = None
        if a.code_mods is not None and a.stage != 'romfs':
            from static_mods import prepare
            a.data.mkdir(parents=True, exist_ok=True)
            context = prepare(a.dump/'exefs', a.code_mods, work=a.data)
        if a.stage == 'check':
            print('TOTK 1.4.3 code identity verified; RomFS content validation requires --stage romfs')
            return
        a.data.mkdir(parents=True, exist_ok=True)
        if a.stage == 'lift':
            out = a.data / 'generated'
            out.mkdir(exist_ok=True)
            (out / 'manifest-linux.json').unlink(missing_ok=True)
            if context is None:
                (out/'static-mods.json').unlink(missing_ok=True)
            from static_mods import temporary_exefs, publish_context
            inputs = temporary_exefs(context, a.data) if context is not None else nullcontext(a.dump/'exefs')
            with inputs as exefs:
                for module, (base, _) in BASES.items():
                    directory = out / module
                    directory.mkdir(exist_ok=True)
                    with (out / (module + '.log')).open('w') as log:
                        subprocess.run([sys.executable, '-X', 'faulthandler', str(ROOT/'tools/lifter/gen.py'),
                                        module, str((exefs/module).resolve()), hex(base), str(directory),
                                        '--simd', 'c', *(['--native-60fps', '--native-camera'] if module == 'main' else [])], stdout=log, stderr=subprocess.STDOUT, check=True)
                    print('Lifted ' + module, flush=True)
            if context is not None:
                publish_context(context, out)
            files = seal_generated(out, a.dump / 'exefs', a.code_mods)
            print('Verified generated source files:', len(files))
        else:
            if packed:
                from packed_inputs import import_packed
                import_packed(a.dump / 'romfs', a.data / 'romfs', expected())
                subprocess.run([sys.executable, str(ROOT / 'tools/make_romfs_index.py'), str(a.data / 'romfs')], check=True)
                print('Packed RomFS full content fingerprint verified')
                return
            from pack_romfs import pack
            n, size, content = pack(a.dump / 'romfs', a.data / 'romfs', threads=1, progress=print)
            want = expected()
            if n != want['ROMFS_FILES'] or size < want['ROMFS_BYTES'] or content != want['ROMFS_CONTENT']:
                p.error('RomFS differs from upstream 1.4.3 content fingerprint')
            print('RomFS content verified:', content)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        p.exit(1, str(e) + '\n')


if __name__ == '__main__':
    main()
