"""Version-bound native FOV hooks; instruction metadata only, no game assets.

Site identities cross-checked against valentderah/totk-pc-recomp
0ae47a578285cde080642c9e6c40316c99171ef1 runtime/resolution.c and the
original 1.4.3 module. Preserve each load before adjusting its S0 result.
"""
import hashlib

BUILD_ID = '277178b7dba1b6d4949a84778d4abc58b31b34f5'
# (load RVA, original word, SHA-256 of the surrounding 64 bytes)
SITES = (
    (0x628c3c, 0xbd413e60, '969384ce33cb95ecf3e58cc964fe359ef3745d413be12d250fe515a392b10283'),
    (0xb4342c, 0xbd4066c0, '06ef7721288b741c2dff6fa8514b8e9331804fde6646184f306796250904c094'),
)


def reserved_ranges():
    return tuple((offset-32, offset+32) for offset, _, _ in SITES)


def configure(module, patches):
    """Validate the whole profile before publishing any production AOT patch."""
    if (module.name != 'main' or module.base != 0x800000000
            or module.nso.build_id != BUILD_ID):
        raise ValueError('Native camera requires the verified TOTK 1.4.3 main module')
    prepared = {}
    for offset, word, digest in SITES:
        address = module.base+offset
        start, end = offset-32, offset+32
        if (not module.in_text(module.base+start) or not module.in_text(module.base+end-4)
                or hashlib.sha256(module.nso.image[start:end]).hexdigest() != digest
                or module.word(address) != word or module.word(address+4) != 0x1e210808
                or address in patches):
            raise ValueError(f'Native camera context mismatch at {offset:#x}')
        original = module.lifter.lift(word, address)
        if original.kind != 'op':
            raise ValueError('Native camera load must use portable C lifting')
        prepared[address] = original.code
    emitted = set()
    def emit(generator, address):
        emitted.add(address)
        return (prepared[address] + ' { extern void nd_totk_camera_apply(void *); '
                'nd_totk_camera_apply(&c->v[0]); }')
    patches.update({address:emit for address in prepared})
    return emitted


def require_emitted(emitted):
    if emitted != {0x800000000+offset for offset, _, _ in SITES}:
        raise ValueError('Native camera hooks were not both emitted')
