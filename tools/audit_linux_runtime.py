"""Link every production runtime object; only real game tables may be unresolved.

The audit library is never executed and must never be packaged as the game.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess

EXPECTED = {module + '_fn_' + field for module in ('main', 'subsdk0', 'sdk')
            for field in ('addrs', 'ptrs', 'count')}
PACKAGES = ('sdl3', 'vulkan', 'opus', 'vpx', 'openssl', 'libzstd')


def inspect_report(report):
    missing = set(re.findall(r'undefined symbol: (\w+)', report))
    if missing != EXPECTED:
        raise ValueError('Unexpected link dependencies: ' + repr(sorted(missing ^ EXPECTED)))
    if 'not found' in report:
        raise ValueError('Missing native dependency')
    for line in report.splitlines():
        if '=>' in line and re.search(r'wine|proton|dxvk|box64|qemu|fex', line, re.I):
            raise ValueError('Compatibility runtime found: ' + line)
    return sorted(missing)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, required=True)
    p.add_argument('--evidence', type=Path, required=True)
    a = p.parse_args()
    build = a.build.resolve()
    archive = build / 'libultratears-runtime.a'
    library = build / 'libultratears-runtime-audit.so'
    flags = shlex.split(subprocess.check_output(['pkg-config', '--libs', *PACKAGES], text=True))
    subprocess.run(['clang++', '-shared', '-o', str(library), '-Wl,--whole-archive', str(archive),
                    '-Wl,--no-whole-archive', *flags, '-pthread', '-ldl', '-lm'], check=True)
    header = library.read_bytes()[:20]
    if header[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', header, 16) != (3, 62):
        raise ValueError('Expected ELF64 Linux x86-64 shared library')
    env = dict(os.environ)
    paths = [f[2:] for f in flags if f.startswith('-L')]
    env['LD_LIBRARY_PATH'] = os.pathsep.join(paths + [env.get('LD_LIBRARY_PATH', '')])
    result = subprocess.run(['ldd', '-r', str(library)], env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
    a.evidence.mkdir(parents=True, exist_ok=True)
    (a.evidence / 'runtime-link-audit.txt').write_text(result.stdout)
    missing = inspect_report(result.stdout)
    evidence = dict(runtime_link_validated=True, game_playability_validated=False,
                    elf='ELF64 x86-64 shared library (audit only)', missing_game_tables=missing)
    (a.evidence / 'runtime-link-audit.json').write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
