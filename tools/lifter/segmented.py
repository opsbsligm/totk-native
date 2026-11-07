"""Bound complete indirect dispatch graphs without changing guest instruction coverage."""
# SPDX-License-Identifier: MIT

SEGMENT_BYTES = 1024
MIN_SPLIT_BYTES = 4096


def emit(module, entry, end, tables):
    from gen import fname
    from lifter import Unsupported, emit_asm_batch, hx

    starts = list(range(entry, end, SEGMENT_BYTES))
    names = {start: f'{fname(entry)}_part_{start:x}' for start in starts}
    dispatch = fname(entry) + '_resume'
    declaration = 'static __attribute__((noinline)) void '
    out = [declaration + name + '(Cpu *c);' for name in [dispatch, *names.values()]]
    refs = set()
    out += [f'void {fname(entry)}(Cpu *c) {{', f'    FN_ENTER({hx(entry)});',
            f'    c->pc = {hx(entry)};',
            f'    __attribute__((musttail)) return {names[entry]}(c);', '}']

    def local_target(target):
        return entry <= target < end and (target - entry) % 4 == 0

    def resume(target):
        if local_target(target):
            start = entry + ((target - entry) // SEGMENT_BYTES) * SEGMENT_BYTES
            return f'c->pc = {hx(target)}; __attribute__((musttail)) return {names[start]}(c);'
        if module.in_text(target):
            refs.add(target)
            return f'__attribute__((musttail)) return {fname(target)}(c);'
        return f'c->pc = {hx(target)}; __attribute__((musttail)) return rt_dispatch(c);'

    for start in starts:
        stop = min(start + SEGMENT_BYTES, end)
        out.append(declaration + names[start] + '(Cpu *c) {')
        cases = ' '.join(f'case {hx(pc)}: goto L_{pc:x};' for pc in range(start, stop, 4))
        out += [f'    switch (c->pc) {{ {cases} default: break; }}',
                f'    __attribute__((musttail)) return {dispatch}(c);']
        batch = []

        def flush():
            if batch:
                out.append('    ' + emit_asm_batch(batch))
                batch.clear()

        def jump(target):
            return f'goto L_{target:x};' if start <= target < stop else resume(target)

        last = None
        for pc in range(start, stop, 4):
            flush()  # Every instruction remains an independently reachable destination.
            out.append(f'L_{pc:x}:;')
            ins = module.lift(pc)
            kind = ins.kind
            if kind == 'asm':
                batch.append(ins.asm)
                try:
                    emit_asm_batch(batch)
                except Unsupported:
                    raise
            elif kind in ('op', 'trap'):
                out.append('    ' + ins.code)
            elif kind == 'b':
                out.append('    ' + jump(ins.target))
            elif kind == 'bcond':
                out.append(f'    if ({ins.cond}) {{ {jump(ins.target)} }}')
            elif kind == 'bl':
                if module.in_text(ins.target):
                    refs.add(ins.target)
                    out.append(f'    c->x[30] = {hx(pc + 4)}; {fname(ins.target)}(c);')
                else:
                    out.append(f'    c->x[30] = {hx(pc + 4)}; c->pc = {hx(ins.target)}; rt_dispatch(c);')
            elif kind == 'blr':
                out.append(f'    c->pc = {ins.target}; c->x[30] = {hx(pc + 4)}; rt_dispatch(c);')
            elif kind == 'br':
                table = tables.get(pc)
                if table and table != 'all':
                    cases = ' '.join(f'case {hx(target)}: {{ {jump(target)} }}' for target in table)
                    out.append(f'    switch ({ins.target}) {{ {cases} default: break; }}')
                out.append(f'    c->pc = {ins.target}; __attribute__((musttail)) return {dispatch}(c);')
            elif kind == 'ret':
                out.append('    return;')
            else:
                raise Unsupported(kind)
            last = kind
        flush()
        if last not in ('b', 'br', 'ret', 'trap'):
            out.append('    ' + resume(stop) if stop < module.hi else f'    rt_udf(c, {hx(stop)});')
        out.append('}')

    out.append(declaration + dispatch + '(Cpu *c) {')
    out.append(f'    if (c->pc >= {hx(entry)} && c->pc < {hx(end)} && (c->pc & 3) == 0) {{')
    out.append(f'        switch ((c->pc - {hx(entry)}) / {SEGMENT_BYTES}) {{')
    for index, start in enumerate(starts):
        out.append(f'        case {index}: __attribute__((musttail)) return {names[start]}(c);')
    out += ['        }', '    }', '    __attribute__((musttail)) return rt_dispatch(c);', '}']
    module._refs = refs
    return out
