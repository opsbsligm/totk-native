"""Version and provenance checks for locally generated 1.4.3 game code.

No keys, encrypted packages, game bytes or generated code are distributed.
"""
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = '0c9ce8afd4c3ab81c33200917af51fb9807aeef0'
BASES = {'main': (0x0800000000, 0x0804000000),
         'subsdk0': (0x0804000000, 0x0805000000),
         'sdk': (0x0805000000, 0x0807000000)}


def expected():
    values = {}
    for node in ast.parse((ROOT / 'tools/setup_windows.py').read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('EXEFS', 'ROMFS_FILES', 'ROMFS_BYTES', 'ROMFS_CONTENT'):
                values[name] = ast.literal_eval(node.value)
    if len(values) != 4:
        raise ValueError('Missing upstream 1.4.3 fingerprints')
    return values


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def check_exefs(exefs):
    hashes = {}
    for name, want in expected()['EXEFS'].items():
        path = Path(exefs) / name
        if not path.is_file() or digest(path) != want:
            raise ValueError('Missing or incorrect TOTK 1.4.3 module: ' + str(path))
        hashes[name] = want
    return hashes


def generated_files(generated):
    generated = Path(generated)
    files = []
    for module, (lo, hi) in BASES.items():
        directory = generated / module
        table = directory / (module + '_table.c')
        if not table.is_file():
            raise ValueError('Missing game function table: ' + str(table))
        text = table.read_text()
        count = re.search(r'const uint64_t ' + module + r'_fn_count\s*=\s*(\d+)\s*;', text)
        if not count or int(count[1]) <= 0:
            raise ValueError('Empty or malformed game table: ' + module)
        addresses = re.search(module + r'_fn_addrs\[\]\s*=\s*\{(.*?)\};', text, re.S)
        pointers = re.search(module + r'_fn_ptrs\[\]\s*=\s*\{(.*?)\};', text, re.S)
        if not addresses or not pointers:
            raise ValueError('Missing game table arrays: ' + module)
        addrs = [int(s, 16) for s in re.findall(r'0x([0-9a-fA-F]+)', addresses[1])]
        ptrs = [int(s, 16) for s in re.findall(r'\bf_([0-9a-fA-F]+)\b', pointers[1])]
        if (len(addrs) != int(count[1]) or ptrs != addrs or addrs != sorted(set(addrs))
                or any(a < lo or a >= hi or a % 4 for a in addrs)):
            raise ValueError('Inconsistent game table: ' + module)
        chunks = sorted(p for p in directory.glob(module + '_*.c')
                        if re.fullmatch(re.escape(module) + r'_\d+\.c', p.name))
        if not chunks or any(p.stat().st_size == 0 for p in chunks):
            raise ValueError('Missing generated game functions: ' + module)
        files.extend([table, *chunks])
        if set(directory.glob('*.c')) != {table, *chunks}:
            raise ValueError('Unexpected C source in module: ' + module)
    return files


def lifter_fingerprints(code_mods=False):
    files = sorted((ROOT / 'tools/lifter').glob('*.py'))
    if code_mods:
        files += [ROOT/'tools'/name for name in ('code_mods.py', 'mods_snapshot.py', 'static_mods.py')]
    if not files:
        raise ValueError('Missing lifter sources')
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in files}


def seal_generated(generated, exefs, code_mods=None):
    hashes = check_exefs(exefs)
    context = None
    if code_mods is not None:
        from static_mods import verify_context
        context = verify_context(generated, exefs, code_mods)
    elif (Path(generated)/'static-mods.json').exists():
        raise ValueError('Static mod record present without --code-mods')
    files = generated_files(generated)
    payload = dict(schema=1, profile='native-60fps-v1', game='TOTK', version='1.4.3', upstream=UPSTREAM, exefs=hashes,
                   lifter=lifter_fingerprints(context is not None),
                   files={p.relative_to(generated).as_posix(): digest(p) for p in files})
    if context is not None:
        from static_mods import record
        payload['static_mods'] = record(context)
    manifest = Path(generated) / 'manifest-linux.json'
    temporary = manifest.with_suffix('.json.new')
    temporary.write_text(json.dumps(payload, indent=2) + '\n')
    temporary.replace(manifest)
    return files


def verify_generated_inputs(generated, exefs, code_mods=None):
    generated = Path(generated).resolve()
    hashes = check_exefs(exefs)
    context = None
    if code_mods is not None:
        from static_mods import verify_context
        context = verify_context(generated, exefs, code_mods)
    elif (generated/'static-mods.json').exists():
        raise ValueError('Static mod record present without --code-mods')
    data = json.loads((generated / 'manifest-linux.json').read_text())
    if (data.get('profile') != 'native-60fps-v1' or data.get('schema') != 1 or data.get('game') != 'TOTK' or data.get('version') != '1.4.3'
            or data.get('upstream') != UPSTREAM or data.get('exefs') != hashes
            or data.get('lifter') != lifter_fingerprints(context is not None)):
        raise ValueError('Generated code provenance differs; regenerate from checked 1.4.3 input')
    selected_mods = None
    if context is not None:
        from static_mods import record
        selected_mods = record(context)
    if data.get('static_mods') != selected_mods:
        raise ValueError('Generated static mod identity differs; regenerate and recompile')
    files = generated_files(generated)
    actual = {p.relative_to(generated).as_posix(): digest(p) for p in files}
    if data.get('files') != actual:
        raise ValueError('Generated files changed or are incomplete; regenerate them')
    return files, context


def verify_generated(generated, exefs, code_mods=None):
    return verify_generated_inputs(generated, exefs, code_mods)[0]
