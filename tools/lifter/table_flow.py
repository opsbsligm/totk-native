"""Bounded, path-joined address analysis for native indirect-branch emission.

Only immutable image reads become constants. Unknown values and exhausted
analysis budgets retain the generator's complete in-function dispatch fallback.
"""
from __future__ import annotations

import bisect
from collections import deque
from dataclasses import dataclass

import capstone
from capstone import arm64

MAX_VALUES = 4096
MAX_STEPS = 200000
MAX_GROWTH = 8
MASK64 = (1 << 64) - 1


@dataclass(frozen=True)
class State:
    values: tuple
    zero32: int = 0
    comparison: tuple | None = None


def register(name):
    if name in ('fp', 'lr'):
        return 29 if name == 'fp' else 30
    if name[:1] in ('x', 'w') and name[1:].isdigit() and int(name[1:]) < 31:
        return int(name[1:])
    return None


def joined(previous, incoming, growth):
    values = []
    for index, (left, right) in enumerate(zip(previous.values, incoming.values)):
        if left is None or right is None:
            values.append(None)
        else:
            combined = left | right
            if combined != left:
                growth[index] += 1
            values.append(combined if len(combined) <= MAX_VALUES and growth[index] <= MAX_GROWTH else None)
    comparison = previous.comparison if previous.comparison == incoming.comparison else None
    return State(tuple(values), previous.zero32 & incoming.zero32, comparison)


class AddressFlow:
    def __init__(self, module, entry, end):
        self.module, self.entry, self.end = module, entry, end
        self.decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
        self.decoder.detail = True
        self.instructions = {}
        self.states = {}
        self.growth = {}
        self.targets = {}
        self.incomplete = False
        self.relocations = sorted(item[0] for item in module.nso.relocs)

    def instruction(self, address):
        if address not in self.instructions:
            word = self.module.word(address).to_bytes(4, 'little')
            self.instructions[address] = next(self.decoder.disasm(word, address, count=1), None)
        return self.instructions[address]

    def read_register(self, state, name):
        if name in ('xzr', 'wzr'):
            return frozenset((0,))
        index = register(name)
        if index is None:
            return None
        values = state.values[index]
        if values is not None and name.startswith('w'):
            return frozenset(value & 0xffffffff for value in values)
        return values

    def operand(self, state, instruction, operand):
        if operand.type == arm64.ARM64_OP_IMM:
            values = frozenset((operand.imm & MASK64,))
        elif operand.type == arm64.ARM64_OP_REG:
            values = self.read_register(state, instruction.reg_name(operand.reg))
        else:
            return None
        if values is None:
            return None
        extensions = {
            arm64.ARM64_EXT_UXTB: (8, False), arm64.ARM64_EXT_UXTH: (16, False),
            arm64.ARM64_EXT_UXTW: (32, False), arm64.ARM64_EXT_UXTX: (64, False),
            arm64.ARM64_EXT_SXTB: (8, True), arm64.ARM64_EXT_SXTH: (16, True),
            arm64.ARM64_EXT_SXTW: (32, True), arm64.ARM64_EXT_SXTX: (64, True),
        }
        if operand.ext in extensions:
            width, signed = extensions[operand.ext]
            mask = (1 << width) - 1
            values = frozenset(((value & mask) - (1 << width) if signed and value & (1 << (width - 1))
                                else value & mask) for value in values)
        shift = operand.shift
        if shift.type:
            if shift.type == arm64.ARM64_SFT_LSL:
                values = frozenset((value << shift.value) & MASK64 for value in values)
            elif shift.type == arm64.ARM64_SFT_LSR:
                values = frozenset((value & MASK64) >> shift.value for value in values)
            else:
                return None
        return values

    def immutable_read(self, address, size, signed):
        offset = address - self.module.base
        image = self.module.nso.image
        ranges = (self.module.nso.text, self.module.nso.rodata)
        if not any(start <= offset and offset + size <= start + length for start, length in ranges):
            return None
        relocation = bisect.bisect_right(self.relocations, offset + size - 1)
        if relocation and self.relocations[relocation - 1] + 8 > offset:
            return None
        if offset < 0 or offset + size > len(image):
            return None
        return int.from_bytes(image[offset:offset + size], 'little', signed=signed) & MASK64

    def load(self, state, instruction):
        operands = instruction.operands
        name = instruction.mnemonic
        sizes = {'ldrb': (1, False), 'ldrh': (2, False), 'ldrsb': (1, True),
                 'ldrsh': (2, True), 'ldrsw': (4, True)}
        destination = instruction.reg_name(operands[0].reg)
        size, signed = sizes.get(name, (4 if destination.startswith('w') else 8, False))
        source = operands[1]
        if source.type == arm64.ARM64_OP_IMM:
            addresses = frozenset((source.imm,))
        elif source.type == arm64.ARM64_OP_MEM:
            base = self.read_register(state, instruction.reg_name(source.mem.base))
            index = self.read_register(state, instruction.reg_name(source.mem.index)) if source.mem.index else frozenset((0,))
            if base is None or index is None or len(base) * len(index) > MAX_VALUES:
                return None
            if source.ext not in (0, arm64.ARM64_EXT_UXTW, arm64.ARM64_EXT_UXTX):
                return None
            if source.ext == arm64.ARM64_EXT_UXTW:
                index = frozenset(value & 0xffffffff for value in index)
            if source.shift.type not in (0, arm64.ARM64_SFT_LSL):
                return None
            addresses = frozenset((value + (offset << source.shift.value) + source.mem.disp) & MASK64
                                  for value in base for offset in index)
        else:
            return None
        result = set()
        for address in addresses:
            value = self.immutable_read(address, size, signed)
            if value is None:
                return None
            result.add(value)
        return frozenset(result)

    def evaluate(self, state, instruction):
        operands = instruction.operands
        name = instruction.mnemonic
        if not operands or operands[0].type != arm64.ARM64_OP_REG:
            return None
        if name in ('adr', 'adrp'):
            return frozenset((operands[1].imm & MASK64,))
        if name in ('mov', 'movz'):
            return self.operand(state, instruction, operands[1])
        if name == 'movk':
            old = self.read_register(state, instruction.reg_name(operands[0].reg))
            if old is None:
                return None
            shift = operands[1].shift.value
            mask = ~(0xffff << shift) & MASK64
            return frozenset((value & mask) | (operands[1].imm << shift) for value in old)
        if name in ('ldr', 'ldrb', 'ldrh', 'ldrsb', 'ldrsh', 'ldrsw') and len(operands) == 2:
            return self.load(state, instruction)
        if name not in ('add', 'sub', 'adds', 'subs', 'and', 'orr', 'eor', 'lsl', 'lsr') or len(operands) != 3:
            return None
        left = self.operand(state, instruction, operands[1])
        right = self.operand(state, instruction, operands[2])
        if name == 'and' and left is None and right is not None and len(right) == 1:
            mask = next(iter(right))
            if mask < MAX_VALUES and mask & (mask + 1) == 0:
                return frozenset(range(mask + 1))
        if left is None or right is None or len(left) * len(right) > MAX_VALUES:
            return None
        shift_mask = 31 if instruction.reg_name(operands[0].reg).startswith('w') else 63
        operations = {'add': lambda first, second: first + second,
                      'adds': lambda first, second: first + second,
                      'sub': lambda first, second: first - second,
                      'subs': lambda first, second: first - second,
                      'and': lambda first, second: first & second,
                      'orr': lambda first, second: first | second,
                      'eor': lambda first, second: first ^ second,
                      'lsl': lambda first, second: first << (second & shift_mask),
                      'lsr': lambda first, second: first >> (second & shift_mask)}
        return frozenset(operations[name](first, second) & MASK64 for first in left for second in right)

    def step(self, state, instruction):
        values = list(state.values)
        zero32 = state.zero32
        comparison = state.comparison
        reads, writes = instruction.regs_access()
        if arm64.ARM64_REG_NZCV in writes:
            comparison = None
        for written in writes:
            name = instruction.reg_name(written)
            index = register(name)
            if index is None or instruction.mnemonic in ('cmp', 'cmn', 'tst', 'ccmp', 'ccmn'):
                continue
            values[index] = None
            zero32 = zero32 | (1 << index) if name.startswith('w') else zero32 & ~(1 << index)
            if comparison and comparison[0] == index:
                comparison = None
        operands = instruction.operands
        if instruction.mnemonic == 'cmp' and len(operands) == 2 and operands[0].type == arm64.ARM64_OP_REG and operands[1].type == arm64.ARM64_OP_IMM:
            name = instruction.reg_name(operands[0].reg)
            index = register(name)
            if index is not None:
                comparison = (index, operands[1].imm << operands[1].shift.value, 32 if name.startswith('w') else 64)
        destination = register(instruction.reg_name(operands[0].reg)) if operands and operands[0].type == arm64.ARM64_OP_REG else None
        if instruction.mnemonic not in ('cmp', 'cmn', 'tst', 'ccmp', 'ccmn') and destination is not None and any(register(instruction.reg_name(written)) == destination for written in writes):
            result = self.evaluate(state, instruction)
            if result is not None:
                name = instruction.reg_name(operands[0].reg)
                mask = 0xffffffff if name.startswith('w') else MASK64
                result = frozenset(value & mask for value in result)
                values[destination] = result
                if all(value <= 0xffffffff for value in result):
                    zero32 |= 1 << destination
        if instruction.mnemonic in ('bl', 'blr', 'svc'):
            for index in (*range(19), 30):
                values[index] = None
                zero32 &= ~(1 << index)
            comparison = None
        return State(tuple(values), zero32, comparison)

    def refine(self, state, condition, taken):
        if state.comparison is None:
            return state
        index, limit, width = state.comparison
        tests = {'hi': lambda value: value > limit, 'hs': lambda value: value >= limit,
                 'lo': lambda value: value < limit, 'ls': lambda value: value <= limit,
                 'eq': lambda value: value == limit, 'ne': lambda value: value != limit}
        if condition not in tests:
            return state
        values = state.values[index]
        mask = (1 << width) - 1
        if values is not None:
            narrowed = frozenset(value for value in values if tests[condition](value & mask) == taken)
        elif width == 32 and not state.zero32 & (1 << index):
            return state
        else:
            bound = limit + (1 if condition in ('hi', 'ls') else 0)
            finite = (condition in ('hi', 'hs') and not taken) or (condition in ('lo', 'ls') and taken)
            if finite and 0 <= bound <= MAX_VALUES:
                narrowed = frozenset(range(bound))
            elif (condition == 'eq' and taken) or (condition == 'ne' and not taken):
                narrowed = frozenset((limit & mask,))
            else:
                return state
        if not narrowed:
            return None
        output = list(state.values)
        output[index] = narrowed
        zero32 = state.zero32 | (1 << index) if all(value <= 0xffffffff for value in narrowed) else state.zero32
        return State(tuple(output), zero32, state.comparison)

    def solve(self):
        initial = State((None,) * 31)
        self.states[self.entry] = initial
        queue = deque((self.entry,))
        scheduled = {self.entry}
        steps = 0
        while queue:
            address = queue.popleft()
            scheduled.remove(address)
            steps += 1
            if steps > MAX_STEPS:
                return {}
            instruction = self.instruction(address)
            if instruction is None:
                return {}
            state = self.states[address]
            output = self.step(state, instruction)
            name = instruction.mnemonic
            operands = instruction.operands
            edges = []
            if name == 'br':
                values = self.read_register(state, instruction.reg_name(operands[0].reg))
                if values is None:
                    self.targets[address] = None
                    if self.module.computed_target(address, self.entry):
                        self.incomplete = True
                else:
                    inside = {value for value in values if self.entry <= value < self.end and value % 4 == 0}
                    prior = self.targets.get(address, set())
                    self.targets[address] = None if prior is None or len(inside) != len(values) else prior | inside
                    edges.extend((target, output) for target in inside)
            elif name == 'b':
                edges.append((operands[0].imm, output))
            elif name.startswith('b.'):
                condition = name[2:]
                edges.extend(((operands[0].imm, self.refine(output, condition, True)),
                              (address + 4, self.refine(output, condition, False))))
            elif name in ('cbz', 'cbnz', 'tbz', 'tbnz'):
                edges.extend(((operands[-1].imm, output), (address + 4, output)))
            elif name not in ('ret', 'eret', 'drps', 'brk', 'hlt', 'udf'):
                edges.append((address + 4, output))
            for target, incoming in edges:
                if incoming is None or not self.entry <= target < self.end or target % 4:
                    continue
                current = self.states.get(target)
                merged = incoming if current is None else joined(current, incoming, self.growth.setdefault(target, [0] * 31))
                if merged != current:
                    self.states[target] = merged
                    if target not in scheduled:
                        queue.append(target)
                        scheduled.add(target)
        if self.incomplete:
            return {}
        return {address: sorted(values) if values else None for address, values in self.targets.items()}


def resolve(module, entry, end):
    return AddressFlow(module, entry, end).solve()
