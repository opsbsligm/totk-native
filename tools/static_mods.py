# SPDX-License-Identifier: MIT
"""Bind TOTK code patches to checked originals, native HLE and AOT outputs.

The format/snapshot layers are shared first-party NativeDeck MIT code. Prepared
NSOs exist only in bounded temporary directories, never one retained tree per SHA.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import tempfile
import time
import uuid

from code_mods import PreparedMods, decode_nso, prepare_modules
from mods_snapshot import directory, manifest, read_file, snapshot_exefs, snapshot_patches

ROOT = Path(__file__).resolve().parents[1]
RECORD = 'static-mods.json'


def lifter_module(name):
    # Do not change sys.path or the generator's existing "nso"/"lifter" modules.
    spec = importlib.util.spec_from_file_location('_static_totk_'+name, ROOT/'tools/lifter'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def host_symbols(work):
    """Use the real Linux compile commands, including wrappers and #if branches.

    Only preprocessing runs. No executable, archive, object or GPU context is
    created. Registry names come from expanded HleImplEntry initializers, not a
    guess based on source strings or a user-supplied list.
    """
    started = time.monotonic()
    def command(args, cwd=ROOT):
        remaining = 120-(time.monotonic()-started)
        if remaining <= 0:
            raise ValueError('Native HLE registry inspection exceeded its time budget')
        result = subprocess.run(list(map(str, args)), cwd=cwd, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=min(30, remaining))
        if result.returncode or len(result.stdout.encode()) > 16*1024**2:
            raise ValueError('Native HLE registry preprocessing failed or exceeded its output budget')
        return result.stdout
    initializer = re.compile(r'\bHleImplEntry\s+\w+\s*(?:\[[^]]*\])?\s*=\s*\{')
    named = re.compile(r'\bHleImplEntry\s+\w+\s*=\s*\{\s*((?:"(?:\\.|[^"\\])*"\s*)+),')
    names = set()
    with tempfile.TemporaryDirectory(prefix='.hle-registry-', dir=work) as temporary:
        out = Path(temporary)
        command([sys.executable, ROOT/'tools/build_linux.py', '--target', 'runtime',
                 '--out', out, '--generate-only'])
        entries = json.loads(command(['ninja', '-f', out/'build.ninja', '-t', 'compdb', 'cc', 'cxx', 'cxxui']))
        if not 1 <= len(entries) <= 256:
            raise ValueError('Invalid native HLE compilation inventory')
        for entry in entries:
            source = Path(entry['file']).resolve()
            if ROOT not in source.parents or source.suffix not in ('.c', '.cpp'):
                raise ValueError('Unexpected native HLE compilation source')
            args, clean, at = shlex.split(entry['command']), [], 0
            while at < len(args):
                arg = args[at]
                if arg in ('-MF', '-o'):
                    at += 2
                elif arg in ('-MD', '-MMD', '-c'):
                    at += 1
                else:
                    clean.append(arg); at += 1
            text = command([*clean, '-E', '-P'], entry['directory'])
            matches = named.findall(text)
            if len(initializer.findall(text)) != len(matches):
                raise ValueError('Unrecognized native HLE registration; refusing incomplete protection')
            for value in matches:
                symbol = ''.join(ast.literal_eval(token) for token in re.findall(r'"(?:\\.|[^"\\])*"', value))
                if not symbol or '\0' in symbol or len(symbol.encode()) > 4096:
                    raise ValueError('Invalid native HLE registration name')
                names.add(symbol)
    if not 1 <= len(names) <= 16384:
        raise ValueError('Empty or oversized native HLE registry')
    return names


def read_encoded(image, offset, encoding, base):
    # Same documented DWARF encodings used by the production function discovery.
    form, application = encoding & 15, encoding & 0x70
    formats = {0x0b: '<i', 3: '<I', 0x0c: '<q', 4: '<Q'}
    if form not in formats or application not in (0, 0x10, 0x30):
        raise ValueError('Unsupported original exception-table encoding')
    kind = formats[form]; size = struct.calcsize(kind)
    value, = struct.unpack_from(kind, image, offset)
    return value+(offset if application == 0x10 else base if application == 0x30 else 0), size


def reserved_ranges(raw, name, symbols):
    """Protect loader metadata, relocations, HLE bodies and native clock sites."""
    api = lifter_module('nso')
    nso = api.Nso(name, raw=raw)
    image = decode_nso(raw)
    ranges = []
    def add(start, size):
        if not size:
            return
        if start < 0 or size < 0 or start+size > len(image.data)-0x100:
            raise ValueError('Original module metadata exceeds its loaded image: '+name)
        ranges.append((start+0x100, start+size+0x100))
    add(0, 8); add(nso.u32(4), 28)
    cursor = nso.dynamic
    while cursor+16 <= len(nso.image):
        tag = nso.u64(cursor); cursor += 16
        if tag == api.DT_NULL:
            break
    else:
        raise ValueError('Original dynamic table has no terminator')
    add(nso.dynamic, cursor-nso.dynamic)
    if api.DT_STRTAB in nso.dyn:
        if api.DT_STRSZ not in nso.dyn:
            raise ValueError('Original string-table size is missing')
        add(nso.dyn[api.DT_STRTAB], nso.dyn[api.DT_STRSZ])
    if api.DT_SYMTAB in nso.dyn:
        add(nso.dyn[api.DT_SYMTAB], 24*len(nso.syms))
    if api.DT_HASH in nso.dyn:
        start = nso.dyn[api.DT_HASH]
        add(start, 8+4*(nso.u32(start)+nso.u32(start+4)))
    if api.DT_GNU_HASH in nso.dyn:
        start = nso.dyn[api.DT_GNU_HASH]
        buckets, first, bloom = struct.unpack_from('<III', nso.image, start)
        add(start, 16+8*bloom+4*buckets+4*max(0, len(nso.syms)-first))
    for start_tag, size_tag in ((api.DT_RELA, api.DT_RELASZ), (api.DT_JMPREL, api.DT_PLTRELSZ),
                                (api.DT_RELR, api.DT_RELRSZ)):
        if start_tag in nso.dyn:
            add(nso.dyn[start_tag], nso.dyn.get(size_tag, 0))
    for field in (0x90, 0x98):
        offset, size = struct.unpack_from('<II', raw, field)
        if size:
            add(nso.rodata[0]+offset, size)
    if nso.eh_start:
        hdr = nso.eh_start
        add(hdr, nso.eh_end-hdr)
        _, pointer, counter, table = nso.image[hdr:hdr+4]
        _, size = read_encoded(nso.image, hdr+4, pointer, hdr)
        at = hdr+4+size
        count, size = read_encoded(nso.image, at, counter, hdr); at += size
        if not 0 <= count <= len(nso.image)//8:
            raise ValueError('Original exception-table count exceeds its image')
        for _ in range(count):
            _, size = read_encoded(nso.image, at, table, hdr); at += size
            fde, size = read_encoded(nso.image, at, table, hdr); at += size
            cie = fde+4-nso.u32(fde+4)
            for record in (fde, cie):
                length = nso.u32(record)
                if length == 0xffffffff:
                    raise ValueError('64-bit exception records are not supported')
                add(record, length+4)
        add(hdr, at-hdr)
    for offset, *_ in nso.relocs:
        if any(left <= offset+0x100 and offset+0x108 <= right for left, right in image.spans):
            add(offset, 8)
    functions = sorted({v for _, _, shndx, v, _ in nso.syms
                        if shndx and nso.text[0] <= v < sum(nso.text)})
    for symbol, info, shndx, value, size in nso.syms:
        if shndx and symbol in symbols and value in functions:
            end = value+size if size else next((v for v in functions if v > value), sum(nso.text))
            add(value, end-value)
    if name == 'main':
        _, guards = lifter_module('native_clock').instruction_profile()
        for offset in guards:
            add(offset, 4)
        for start, end in lifter_module('native_camera').reserved_ranges():
            add(start, end-start)
        from linux_inputs import BASES
        for address in lifter_module('patches').PATCHES:
            add(address-BASES['main'][0], 4)
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return tuple(merged)


@dataclass(frozen=True)
class ModContext:
    prepared: PreparedMods
    host_hle_sha256: str


def prepare(exefs, mods, *, work):
    from linux_inputs import expected
    originals = snapshot_exefs(exefs, expected()['EXEFS'])
    symbols = host_symbols(work)
    protected = {name: reserved_ranges(raw, name, symbols) for name, raw in originals.items()}
    prepared = prepare_modules(originals, snapshot_patches(mods), protected=protected)
    identity = hashlib.sha256(json.dumps(sorted(symbols), separators=(',', ':')).encode()).hexdigest()
    return ModContext(prepared, identity)


def record(context):
    return {**manifest(context.prepared), 'kind': 'totk-static-mods', 'game': 'TOTK',
            'version': '1.4.3', 'host_hle_sha256': context.host_hle_sha256}


def phase_inputs(context):
    if context is None:
        return None
    raw = json.dumps(record(context), sort_keys=True, separators=(',', ':')).encode()
    return {'static_mods_sha256': hashlib.sha256(raw).hexdigest()}


def publish_context(context, generated):
    with directory(generated) as parent:
        temporary = '.static-mods-'+uuid.uuid4().hex
        try:
            child = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600, dir_fd=parent)
            with os.fdopen(child, 'w') as stream:
                json.dump(record(context), stream, sort_keys=True, indent=2)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, RECORD, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def verify_context(generated, exefs, mods):
    generated = Path(generated)
    context = prepare(exefs, mods, work=generated.parent)
    with directory(generated) as fd:
        actual = json.loads(read_file(fd, RECORD, 2**20))
    if actual != record(context):
        raise ValueError('Static mod inputs differ; regenerate and recompile')
    return context


@contextmanager
def temporary_exefs(context, work):
    with tempfile.TemporaryDirectory(prefix='.mod-exefs-', dir=work) as name:
        path = Path(name)
        for module, raw in context.prepared.modules.items():
            target = path/module
            target.write_bytes(raw); target.chmod(0o600)
        yield path
        with directory(path) as fd:
            if set(os.listdir(fd)) != set(context.prepared.modules):
                raise ValueError('Prepared ExeFS inventory changed during use')
            for module, raw in context.prepared.modules.items():
                if read_file(fd, module, len(raw)) != raw:
                    raise ValueError('Prepared ExeFS changed during use: '+module)
