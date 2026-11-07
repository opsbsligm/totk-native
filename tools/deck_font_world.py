"""Private world/menu font separation and checked Deck help geometry. MIT.

All game inputs stay outside this source tree. Only complete, pinned 1.4.3
resources are accepted. Existing SARC member bytes are preserved individually;
allocation-table entries grow with the corresponding private archives.
"""
# SPDX-License-Identifier: MIT
import binascii
import hashlib
import struct
import sys
from pathlib import Path

from deck_font_glyphs import swap_outlines

COMMON = 'UI/LayoutArchive/Common.Product.140.Nin_NX_NVN.blarc.zs'
RESTBL = 'System/Resource/ResourceSizeTable.Product.143.Nin_NX_NVN.rsizetable.zs'
RESTBL_SHA = 'cd61b042367ca49b5b80cb9af156c696aede092ada0c7f6917b09990bae040f0'
COMMON_SHA = '613af5ec5547e27a025d0b603ef91fa48912c5109c1fffb7917276d1fd98d424'
WORLD_LAYOUTS = ('PaControllerKey_00', 'PaGuideKeySmoke_00', 'PaGuideKeySmokeSpecial_00',
                 'PaAttachTargetSelectCommand_00', 'PaAttachTargetSelectCommandLeft_00')


def sarc_pack(files):
    """Build the observed little-endian SARC subset, checking every member."""
    from deck_font_prompts import members
    if not files or len(files) > 65535:
        raise ValueError('Unsupported archive member count')
    def name_hash(name):
        value = 0
        for c in name.encode('utf-8'):
            value = (value * 0x65 + c) & 0xffffffff
        return value
    ordered = sorted(files, key=lambda n: (name_hash(n), n))
    if len({name_hash(n) for n in ordered}) != len(ordered):
        raise ValueError('Refusing unsupported SARC name-hash collision')
    names, payload, nodes = bytearray(), bytearray(), []
    for name in ordered:
        if not name or '\0' in name or name.startswith('/') or '..' in name.split('/'):
            raise ValueError('Invalid archive path')
        attr = 0x1000000 + len(names) // 4
        names.extend(name.encode('utf-8') + b'\0'); names.extend(b'\0' * (-len(names) % 4))
        payload.extend(b'\0' * (-len(payload) % 16)); lo = len(payload)
        payload.extend(files[name]); nodes.append((name_hash(name), attr, lo, len(payload)))
    start = (20 + 12 + 16 * len(nodes) + 8 + len(names) + 15) & ~15
    out = bytearray(struct.pack('<4sHHIIHH', b'SARC', 20, 0xfeff, start + len(payload), start, 0x100, 0))
    out.extend(struct.pack('<4sHHI', b'SFAT', 12, len(nodes), 0x65))
    for node in nodes: out.extend(struct.pack('<4I', *node))
    out.extend(struct.pack('<4sHH', b'SFNT', 8, 0)); out.extend(names)
    out.extend(b'\0' * (start - len(out))); out.extend(payload)
    result = bytes(out)
    check = members(result)
    if set(check) != set(files) or any(result[a:b] != files[n] for n, (a, b) in check.items()):
        raise ValueError('SARC member roundtrip differs')
    return result


def font_archive(original, patched):
    from deck_font_prompts import members, font_body
    before = members(original); after = members(patched)
    if before != after:
        raise ValueError('Unexpected initial font recipe layout')
    files = {n: patched[a:b] for n, (a, b) in after.items()}
    for name, (lo, hi) in before.items():
        if name != 'scft/External.bfotf' and files[name] != original[lo:hi]:
            raise ValueError('Initial font recipe changed another member')
    font, key = font_body(files['scft/External.bfotf'])
    world = bytearray(swap_outlines(font, 6, 7))
    for at in range(0, len(world) - len(world) % 4, 4):
        struct.pack_into('<I', world, at, struct.unpack_from('<I', world, at)[0] ^ key)
    config = files.get('fcpx/External_00.bfcpx', b'')
    if len(config) != 112 or config[:4] != b'FCPX' or config[96:] != b'External.bfotf\0\0':
        raise ValueError('Unsupported External font link')
    if 'fcpx/DeckWrld_00.bfcpx' in files or 'scft/DeckWrld.bfotf' in files:
        raise ValueError('World font already exists')
    files['fcpx/DeckWrld_00.bfcpx'] = config[:96] + b'DeckWrld.bfotf\0\0'
    files['scft/DeckWrld.bfotf'] = files['scft/External.bfotf'][:8] + world
    return sarc_pack(files)


def sections(data):
    if len(data) < 20 or data[:6] != b'FLYT\xff\xfe' or struct.unpack_from('<I', data, 12)[0] != len(data):
        raise ValueError('Invalid layout')
    at = struct.unpack_from('<H', data, 6)[0]
    if at < 20: raise ValueError('Invalid layout header')
    for _ in range(struct.unpack_from('<H', data, 16)[0]):
        if at + 8 > len(data): raise ValueError('Truncated section')
        size = struct.unpack_from('<I', data, at + 4)[0]
        if size < 8 or at + size > len(data): raise ValueError('Invalid section range')
        yield data[at:at + 4], at, size
        at += size
    if at != len(data): raise ValueError('Unexpected layout trailer')


def world_font_ref(data):
    out = bytearray(data); changed = 0
    for tag, at, size in sections(data):
        if tag != b'fnl1': continue
        count = struct.unpack_from('<I', data, at + 8)[0]
        if 12 + count * 4 > size: raise ValueError('Truncated font names')
        for i in range(count):
            pos = at + 12 + struct.unpack_from('<I', data, at + 12 + i * 4)[0]
            if not at + 12 + count * 4 <= pos < at + size: raise ValueError('Invalid font name')
            end = data.find(b'\0', pos, at + size)
            if end < 0: raise ValueError('Unterminated font name')
            if data[pos:end] == b'External_00.fcpx':
                out[pos:end] = b'DeckWrld_00.fcpx'; changed += 1
    if changed != 1 or len(out) != len(data): raise ValueError('Expected one world font reference')
    return bytes(out)


def dim_letters(data):
    out = bytearray(data); changed = set(); labels = {'T_B_00': ('B', 'A'), 'T_X_00': ('X', 'Y'), 'T_Y_00': ('Y', 'X')}
    for tag, at, size in sections(data):
        if tag != b'txt1' or size < 172: continue
        name = data[at + 12:at + 36].split(b'\0')[0].decode('ascii')
        if name not in labels: continue
        off = struct.unpack_from('<I', data, at + 100)[0]
        if name in changed or not 168 <= off <= size - 4 or data[at + off:at + off + 4] != (labels[name][0] + '\0').encode('utf-16-le'):
            raise ValueError('Unexpected dim button label')
        struct.pack_into('<H', out, at + off, ord(labels[name][1])); changed.add(name)
    if changed != set(labels): raise ValueError('Missing dim button labels')
    return bytes(out)


def controller_geometry(files):
    directory = str(Path(__file__).parent / 'deck_layout')
    if directory not in sys.path: sys.path.insert(0, directory)
    import build_controller_patch as solver
    import resource_layout as p
    layout = p.parse_layout(files[solver.LAYOUT]); child = p.parse_layout(files['blyt/PaController_00.bflyt'])
    child['static_geometry'] = p.geometry(child)
    anims = {Path(n).stem: p.parse_animation(b) for n, b in files.items() if n.startswith('anim/PaSystemController_00_') and n.endswith('.bflan')}
    def pt(x, y): return [.96 * x + 13, .75 * y + 72]
    points = {'left_trigger': [58, 50], 'right_trigger': [522, 50],
              'left_bumper': pt(58, 30), 'right_bumper': pt(522, 30),
              'view': pt(126, 53), 'menu': pt(451, 53),
              'left_stick': pt(88, 88), 'right_stick': pt(470, 88), 'dpad_center': pt(38, 79),
              'face_south': pt(517, 106), 'face_east': pt(535, 89),
              'face_west': pt(499, 89), 'face_north': pt(517, 71)}
    doc = dict(width=580, height=340, anchors=[dict(id=n, pixel=v, coverage_radius=9 if n.startswith('face_') else 19) for n, v in points.items()])
    anchors = solver.validate_anchors(doc)
    solutions, contexts, groups = solver.solve(layout, child, anims, anchors, list(solver.CONTROLS), doc)
    raw = bytearray(files[solver.LAYOUT]); panes = {x['name']: x for x in layout['panes']}
    for name, fields in solutions[0].items():
        for key, value in fields.items(): struct.pack_into('<f', raw, panes[name]['field_offsets'][key], value)
    updated, _ = solver.patch_animation(files[solver.PATTERN], anims['PaSystemController_00_Pattern'], solutions)
    new_layout = p.parse_layout(bytes(raw)); new_pattern = p.parse_animation(updated)
    # Recompute all ten markers and fixed label ends for every mode and horse state.
    for context in contexts:
        values = solver.overrides(new_pattern, context['mode'])
        for n, v in solver.overrides(anims['PaSystemController_00_IsHorse'], context['is_horse']).items(): values[n].update(v)
        geometry = p.geometry(new_layout, solver.synthetic(values))
        for record in context['groups']:
            mark = geometry[panes[record['marker']]['id']]['center']
            line = geometry[panes[record['horizontal']]['id']]['origin']
            if any(abs(a-b) > .002 for a,b in zip(mark, record['target_layout'])) or any(abs(a-b) > .002 for a,b in zip(line, record['label_end_layout'])):
                raise ValueError('Controller marker or label endpoint differs')
    return {solver.LAYOUT: bytes(raw), solver.PATTERN: updated}


def common_archive(raw, archive):
    from deck_font_prompts import members
    if hashlib.sha256(raw).hexdigest() != COMMON_SHA:
        raise ValueError('Unsupported original Common archive')
    files = {n: archive[a:b] for n, (a, b) in members(archive).items()}
    changed = controller_geometry(files)
    for stem in WORLD_LAYOUTS:
        name = 'blyt/' + stem + '.bflyt'; changed[name] = world_font_ref(files[name])
    name = 'blyt/DoCommand_00.bflyt'; changed[name] = dim_letters(files[name])
    return sarc_pack(dict(files, **changed))


def allocation_table(data, growth):
    """Patch only existing CRC/collision allocations. No new table entries.

    RESTBL v1 layout is documented by dt-12345/totktools and its restbl fork.
    This independent bounded editor keeps ordering and every other byte intact.
    """
    if len(data) < 22 or data[:6] != b'RESTBL': raise ValueError('Invalid RESTBL')
    version, width, count, collisions = struct.unpack_from('<4I', data, 6)
    if version != 1 or not 1 <= width <= 4096 or 22 + count * 8 + collisions * (width + 4) != len(data):
        raise ValueError('Unsupported RESTBL ranges')
    targets = {binascii.crc32(n.removesuffix('.zs').encode()): (n.removesuffix('.zs'), g) for n, g in growth.items()}
    if len(targets) != len(growth): raise ValueError('Resource CRC collision')
    out = bytearray(data); seen = set(); previous = -1
    for i in range(count):
        at = 22 + 8 * i; crc, value = struct.unpack_from('<2I', data, at)
        if crc <= previous: raise ValueError('Unsorted RESTBL hashes')
        previous = crc
        if crc in targets:
            name, extra = targets[crc]
            if not 0 < extra <= 2**20 or value > 0xffffffff - extra: raise ValueError('Invalid allocation growth')
            struct.pack_into('<I', out, at + 4, value + extra); seen.add(name)
    for i in range(collisions):
        at = 22 + count * 8 + i * (width + 4); raw = data[at:at + width]
        end = raw.find(b'\0')
        if end < 0: raise ValueError('Invalid collision name')
        name = raw[:end].decode('utf-8')
        if name in {n.removesuffix('.zs') for n in growth}:
            raise ValueError('Pinned resource has a collision-table entry; manual profile required')
    if seen != {n.removesuffix('.zs') for n in growth}: raise ValueError('Missing resource allocation entry')
    return bytes(out)
