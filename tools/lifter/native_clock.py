"""Verified 1.4.3 instruction profile with measured time steps (18 guarded sites).

Adapted from the GPL Linux port and the MIT MacNativeGames timing profile.
Only instruction identities and transformation rules are present; no game data.
"""

def require(condition, message='Native 60fps profile validation failed'):
    if not condition:
        raise ValueError(message)


def configure(m, PATCHES):
    if m.name != 'main' or m.base != 0x800000000:
        raise ValueError('60fps profile requires the verified 1.4.3 main module')
    base = m.base
    fps = {0x2db204:(0x6b08015f,0x7100055f),0x2db208:(0x1a89b10a,0x1a9fa52a),
           0x2db22c:(0xb940468a,0xd503201f),0x2db360:(0x6b0801bf,0x710005bf),
           0x2db36c:(0x1a88c1ac,0x1a9fc5ac),0x2db340:(0xb9400288,0x52800028),
           0x2db34c:(0x2a0a03f5,0x1a9fa555)}
    guard = {0x3e5658:0x1e210808,0x2daa54:0xbd425260,0x2daa58:0x52a84e08,
             0x2daa6c:0x5e21d800,0x2daa70:0x1e201820,0x2daa74:0x1e2c1001,0x2daa78:0x1e210800,
             0x246eac:0x1e200940,0x345904:0x1e210801,0x24944c:0x94015e7d,0x28bc98:0x9400546a}
    for off, (old, _) in fps.items(): guard[off] = old
    for off, old in guard.items():
        require(m.word(base+off) == old, f'Unexpected v1.4.3 instruction at {off:#x}')
    
    for off,(_,new) in fps.items():
        ins=m.lifter.lift(new,base+off)
        require(ins.kind=='op', 'High-fps validation failed')
        PATCHES[base+off]=lambda gen,a,code=ins.code:code
    for off in [0x2daa58,0x2daa6c,0x2daa70,0x2daa74,0x2daa78]:
        PATCHES[base+off]=lambda gen,a:'; /* replaced by measured frame ratio */'
    PATCHES[base+0x2daa54]=lambda gen,a:'FP_SETS(0, nd_totk_step(30.0f));'
    original=m.lifter.lift(guard[0x3e5658],base+0x3e5658).code
    PATCHES[base+0x3e5658]=lambda gen,a:'FP_SETS(0, nd_totk_step(60.0f)); '+original
    PATCHES[base+0x246eac]=lambda gen,a:('{ float factor=nd_totk_reg(c,10); '
        'FP_SETS(0,nd_totk_step(30.0f)*factor); ST32(c->sp+0x364,VS32(0)); '
        'FP_SETS(0,nd_totk_step(1.0f)*factor); }')
    PATCHES[base+0x345904]=lambda gen,a:('{ float factor=nd_totk_reg(c,0); '
        'FP_SETS(1,nd_totk_step(30.0f)*factor); ST32(c->sp+0x114,VS32(1)); '
        'FP_SETS(1,nd_totk_step(1.0f)*factor); }')
    for off in [0x24944c,0x28bc98]:
        PATCHES[base+off]=lambda gen,a:('FP_SETS(2,nd_totk_reg(c,2)*nd_totk_step(30.0f)); '
           'FP_SETS(3,nd_totk_reg(c,3)*nd_totk_step(30.0f)); '
           f'c->x[30]={a+4:#x}ull; f_8002a0e40(c);')
