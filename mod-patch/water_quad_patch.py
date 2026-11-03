"""NOP out the reversed (downward-facing) water top quad in BlockQuadEmitter.class.

Usage: classpatch.py in.class out.class
Pattern inside one method: setPos4; writeFluidQuad; setPos4; [... iconst_m1 ...] writeFluidQuad
The range after the first writeFluidQuad statement through the second one is replaced by NOPs.
"""
import struct
import sys

# instruction lengths (excluding tableswitch/lookupswitch/wide, handled specially)
LEN = {}
for op in range(0x00, 0x10): LEN[op] = 1          # nop..dconst_1
LEN.update({0x10: 2, 0x11: 3, 0x12: 2, 0x13: 3, 0x14: 3})
for op in range(0x15, 0x1a): LEN[op] = 2          # xload idx
for op in range(0x1a, 0x36): LEN[op] = 1
for op in range(0x36, 0x3b): LEN[op] = 2          # xstore idx
for op in range(0x3b, 0x84): LEN[op] = 1
LEN[0x84] = 3                                     # iinc
for op in range(0x85, 0x99): LEN[op] = 1
for op in range(0x99, 0xa9): LEN[op] = 3          # if*, goto, jsr
LEN[0xa9] = 2                                     # ret
for op in range(0xac, 0xb2): LEN[op] = 1          # returns
for op in range(0xb2, 0xb9): LEN[op] = 3          # field/invoke
LEN.update({0xb9: 5, 0xba: 5, 0xbb: 3, 0xbc: 2, 0xbd: 3, 0xbe: 1, 0xbf: 1, 0xc0: 3, 0xc1: 3,
            0xc2: 1, 0xc3: 1, 0xc5: 4, 0xc6: 3, 0xc7: 3, 0xc8: 5, 0xc9: 5})
BRANCH16 = set(range(0x99, 0xa9)) | {0xc6, 0xc7}


def main():
    data = bytearray(open(sys.argv[1], 'rb').read())
    p = 10
    n = struct.unpack_from('>H', data, 8)[0]
    cp = [None] * n
    i = 1
    while i < n:
        tag = data[p]
        if tag == 1:
            ln = struct.unpack_from('>H', data, p + 1)[0]
            cp[i] = ('utf8', data[p + 3:p + 3 + ln].decode('utf-8', 'replace')); p += 3 + ln
        elif tag in (3, 4):
            p += 5
        elif tag in (5, 6):
            p += 9; i += 1
        elif tag in (7, 8, 16, 19, 20):
            cp[i] = (tag, struct.unpack_from('>H', data, p + 1)[0]); p += 3
        elif tag in (9, 10, 11, 12, 17, 18):
            a, b = struct.unpack_from('>HH', data, p + 1); cp[i] = (tag, a, b); p += 5
        elif tag == 15:
            p += 4
        else:
            sys.exit(f'bad cp tag {tag}')
        i += 1

    def method_name(idx):
        e = cp[idx]
        if not e or e[0] not in (10, 11):
            return None
        nat = cp[e[2]]
        return cp[nat[1]][1]

    p += 6
    ifc = struct.unpack_from('>H', data, p)[0]; p += 2 + 2 * ifc
    def skip_members(p):
        cnt = struct.unpack_from('>H', data, p)[0]; p += 2
        out = []
        for _ in range(cnt):
            name = cp[struct.unpack_from('>H', data, p + 2)[0]][1]
            ac = struct.unpack_from('>H', data, p + 6)[0]; q = p + 8
            attrs = []
            for _ in range(ac):
                an = cp[struct.unpack_from('>H', data, q)[0]][1]
                al = struct.unpack_from('>I', data, q + 2)[0]
                attrs.append((an, q + 6, al)); q += 6 + al
            out.append((name, attrs)); p = q
        return p, out
    p, _ = skip_members(p)
    p, methods = skip_members(p)

    hits = []
    for name, attrs in methods:
        for an, ap, al in attrs:
            if an != 'Code':
                continue
            code_len = struct.unpack_from('>I', data, ap + 4)[0]
            cs = ap + 8
            code = data[cs:cs + code_len]
            insns, targets = [], set()
            pc = 0
            while pc < code_len:
                op = code[pc]
                if op == 0xaa:
                    q = (pc + 4) & ~3
                    d, lo, hi = struct.unpack_from('>iii', code, q)
                    targets.add(pc + d)
                    for k in range(hi - lo + 1):
                        targets.add(pc + struct.unpack_from('>i', code, q + 12 + 4 * k)[0])
                    ln = q + 12 + 4 * (hi - lo + 1) - pc
                elif op == 0xab:
                    q = (pc + 4) & ~3
                    d, np_ = struct.unpack_from('>ii', code, q)
                    targets.add(pc + d)
                    for k in range(np_):
                        targets.add(pc + struct.unpack_from('>i', code, q + 8 + 8 * k + 4)[0])
                    ln = q + 8 + 8 * np_ - pc
                elif op == 0xc4:
                    ln = 6 if code[pc + 1] == 0x84 else 4
                else:
                    ln = LEN[op]
                if op in BRANCH16:
                    targets.add(pc + struct.unpack_from('>h', code, pc + 1)[0])
                if op in (0xc8, 0xc9):
                    targets.add(pc + struct.unpack_from('>i', code, pc + 1)[0])
                insns.append((pc, op, ln))
                pc += ln
            # exception table + StackMapTable frame offsets
            q = cs + code_len
            el = struct.unpack_from('>H', data, q)[0]
            for k in range(el):
                s, e, h, _ = struct.unpack_from('>HHHH', data, q + 2 + 8 * k)
                targets.update((s, e, h))
            q += 2 + 8 * el
            sub = struct.unpack_from('>H', data, q)[0]; q += 2
            for _ in range(sub):
                sn = cp[struct.unpack_from('>H', data, q)[0]][1]
                sl = struct.unpack_from('>I', data, q + 2)[0]
                if sn == 'StackMapTable':
                    targets.add(-1)  # marker: frames exist; checked below via decoded offsets
                    frames = stackmap_offsets(data, q + 6)
                    targets.update(frames)
                q += 6 + sl
            calls = [(k, method_name(struct.unpack_from('>H', code, pc + 1)[0]))
                     for k, (pc, op, ln) in enumerate(insns) if op in (0xb6, 0xb7, 0xb8, 0xb9)]
            for j in range(len(calls) - 4):
                names = [c[1] for c in calls[j:j + 5]]
                if names == ['setPos4', 'setUv4', 'writeFluidQuad', 'setPos4', 'writeFluidQuad']:
                    kB, kD = calls[j + 2][0], calls[j + 4][0]
                    kC = calls[j + 3][0]
                    seg = insns[kC:kD]
                    start = insns[kB + 1][0]
                    if insns[kB + 1][1] in (0x57, 0x58):             # pop result of first call
                        start = insns[kB + 2][0]
                    endk = kD + 1
                    if insns[endk][1] in (0x57, 0x58):
                        endk += 1
                    end = insns[endk][0]
                    hits.append((name, cs, start, end, targets))
    if len(hits) != 1:
        sys.exit(f'expected exactly one site, found {len(hits)}: {[h[0] for h in hits]}')
    name, cs, start, end, targets = hits[0]
    inside = [t for t in targets if start < t < end]
    if inside:
        sys.exit(f'branch/frame targets inside range: {inside}')
    for k in range(start, end):
        data[cs + k] = 0x00
    open(sys.argv[2], 'wb').write(data)
    print(f'method {name}: NOPed code bytes [{start}, {end}) = {end - start} bytes')


def stackmap_offsets(data, q):
    n = struct.unpack_from('>H', data, q)[0]; q += 2
    off, out = -1, []
    def vt(q):
        t = data[q]
        return q + (3 if t in (7, 8) else 1)
    for _ in range(n):
        ft = data[q]; q += 1
        if ft < 64:
            delta = ft
        elif ft < 128:
            delta = ft - 64; q = vt(q)
        elif ft == 247:
            delta = struct.unpack_from('>H', data, q)[0]; q = vt(q + 2)
        elif 248 <= ft <= 251:
            delta = struct.unpack_from('>H', data, q)[0]; q += 2
        elif 252 <= ft <= 254:
            delta = struct.unpack_from('>H', data, q)[0]; q += 2
            for _ in range(ft - 251): q = vt(q)
        else:
            delta = struct.unpack_from('>H', data, q)[0]; q += 2
            nl = struct.unpack_from('>H', data, q)[0]; q += 2
            for _ in range(nl): q = vt(q)
            ns = struct.unpack_from('>H', data, q)[0]; q += 2
            for _ in range(ns): q = vt(q)
        off = off + delta + 1
        out.append(off)
    return out


if __name__ == '__main__':
    main()
