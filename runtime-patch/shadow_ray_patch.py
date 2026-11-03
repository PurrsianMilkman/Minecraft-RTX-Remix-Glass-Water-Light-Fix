"""Patch one SPIR-V module (disassembly text) so shadow rays get depth-dependent
Beer-Lambert attenuation through THICK translucent materials.

Usage: shadow_ray_patch.py in.dis out.dis [--k 0.5] [--telltale]
Prints a JSON summary on stdout.
"""
import json
import os
import re
import sys

# Light absorption scale for shadow rays (view-side glass look is untouched). 1.0 = physical, <1 = more light passes.
K = float(sys.argv[sys.argv.index('--k') + 1]) if '--k' in sys.argv else 1.0

ID = r'%[\w.]+'


def main():
    src, dst = sys.argv[1], sys.argv[2]
    telltale = '--telltale' in sys.argv
    lines = open(src, encoding='utf-8').read().split('\n')

    def find_def(name):
        for i, l in enumerate(lines):
            if l.lstrip().startswith(name + ' = '):
                return i
        return -1

    # ---- global ids
    glsl = None
    for l in lines:
        m = re.match(r'\s*(%\S+) = OpExtInstImport "GLSL.std.450"', l)
        if m:
            glsl = m.group(1)
    def type_id(pattern):
        for l in lines:
            m = re.match(r'\s*(%\S+) = ' + pattern + r'\s*$', l)
            if m:
                return m.group(1)
        return None
    t_float = type_id(r'OpTypeFloat 32')
    t_bool = type_id(r'OpTypeBool')
    t_uint = type_id(r'OpTypeInt 32 0')
    t_v3 = type_id(r'OpTypeVector ' + re.escape(t_float) + ' 3') if t_float else None
    t_pv3 = type_id(r'OpTypePointer Function ' + re.escape(t_v3)) if t_v3 else None
    if not all([glsl, t_float, t_bool, t_uint, t_v3]):
        open(dst, 'w', encoding='utf-8').write('\n'.join(lines))
        print(json.dumps({'sites': 0, 'note': 'no float/vec3 types'}))
        return 0

    # ---- loops: header line idx -> (merge label, rq id) for ray-query candidate loops
    label_line = {}
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\S+) = OpLabel\s*$', l)
        if m:
            label_line[m.group(1)] = i
    loops = []  # (header_idx, merge_label, merge_idx, rq or None)
    for i, l in enumerate(lines):
        m = re.match(r'\s*OpLoopMerge (%\S+) (%\S+)', l)
        if m:
            merge = m.group(1)
            rq = None
            for j in range(i + 1, min(i + 15, len(lines))):
                mm = re.match(r'\s*%\S+ = OpRayQueryProceedKHR %\S+ (%\S+)', lines[j])
                if mm:
                    rq = mm.group(1)
                    break
            loops.append((i, merge, label_line.get(merge, -1), rq))

    def innermost_loop(idx):
        best = None
        for (h, merge, mi, rq) in loops:
            if h < idx < mi and (best is None or h > best[0]):
                best = (h, merge, mi, rq)
        return best

    # ---- sites
    sites = []
    skipped = []
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\S+) = OpFDiv ' + re.escape(t_v3) + r' (%\S+) (%\S+)\s*$', l)
        if not m:
            continue
        sig, neg, d3 = m.groups()
        ni, di = find_def(neg), find_def(d3)
        if ni < 0 or di < 0:
            continue
        mneg = re.match(r'\s*%\S+ = OpFNegate %\S+ (%\S+)', lines[ni])
        md3 = re.match(r'\s*%\S+ = OpCompositeConstruct %\S+ (%\S+) \1 \1\s*$', lines[di])
        if not mneg or not md3:
            continue
        li = find_def(mneg.group(1))
        mlog = re.match(r'\s*(%\S+) = OpExtInst %\S+ %\S+ Log (%\S+)\s*$', lines[li]) if li >= 0 else None
        if not mlog:
            continue
        dist = md3.group(1)
        # thin-compare anchor: OpFOrdLessThan %bool <dist> %float_0 shortly before
        anchor = None
        for j in range(max(0, i - 400), i):
            if re.match(r'\s*%\S+ = OpFOrdLessThan ' + re.escape(t_bool) + ' ' + re.escape(dist) + r' %\S+\s*$', lines[j]):
                anchor = j
        if anchor is None:
            continue
        loop = innermost_loop(i)
        if not loop or not loop[3]:
            skipped.append({'line': i + 1, 'why': 'not directly inside a rayquery Proceed loop'})
            continue
        rq = loop[3]
        has_cand = any(re.search(r'OpRayQueryGetIntersectionTypeKHR %\S+ ' + re.escape(rq) + r' %uint_0', lines[k])
                       for k in range(loop[0], loop[2]))
        if not has_cand:
            skipped.append({'line': i + 1, 'why': 'loop has no candidate processing'})
            continue
        # per-hit store after sig in same block
        store = None
        for j in range(i + 1, min(i + 30, len(lines))):
            if 'OpLabel' in lines[j] or 'OpBranch' in lines[j]:
                break
            ms = re.match(r'\s*OpStore (%\S+) (%\S+)\s*$', lines[j])
            if ms:
                store = (j, ms.group(1))
                break
        if not store:
            skipped.append({'line': i + 1, 'why': 'no per-hit store'})
            continue
        P = store[1]
        # find accumulation into result: OpLoad v3 P ; OpLoad v3 R ; OpFMul ; OpStore R
        R = None
        for j in range(store[0], loop[2]):
            ml = re.match(r'\s*(%\S+) = OpLoad ' + re.escape(t_v3) + ' ' + re.escape(P) + r'\s*$', lines[j])
            if ml:
                for k in range(j + 1, min(j + 4, len(lines))):
                    mr = re.match(r'\s*(%\S+) = OpLoad ' + re.escape(t_v3) + r' (%\S+)\s*$', lines[k])
                    if mr:
                        mf = re.match(r'\s*(%\S+) = OpFMul ' + re.escape(t_v3) + r' (%\S+) (%\S+)\s*$', lines[k + 1])
                        ms2 = re.match(r'\s*OpStore (%\S+) (%\S+)\s*$', lines[k + 2])
                        if mf and ms2 and ms2.group(1) == mr.group(2) and ms2.group(2) == mf.group(1):
                            R = mr.group(2)
                        break
                if R:
                    break
        if not R:
            skipped.append({'line': i + 1, 'why': 'no result accumulation found'})
            continue
        # tMax pointer: from the OpRayQueryInitializeKHR for rq (last operand loaded from a pointer)
        tmax_ptr = None
        for j in range(loop[0], -1, -1):
            mi_ = re.match(r'\s*OpRayQueryInitializeKHR ' + re.escape(rq) + r' (.*)$', lines[j])
            if mi_:
                tm = mi_.group(1).split()[-1]
                tdi = find_def(tm)
                mt = re.match(r'\s*%\S+ = OpLoad ' + re.escape(t_float) + r' (%\S+)', lines[tdi]) if tdi >= 0 else None
                tmax_ptr = mt.group(1) if mt else None
                break
            if j < loop[0] - 200:
                break
        sites.append({'sig_line': i, 'log_line': li, 'T': mlog.group(2), 'sig': sig, 'store_line': store[0],
                      'P': P, 'R': R, 'rq': rq, 'loop': loop, 'tmax_ptr': tmax_ptr})

    if not sites:
        print(json.dumps({'sites': 0, 'skipped': skipped}))
        open(dst, 'w', encoding='utf-8').write('\n'.join(lines))
        return 0

    # ---- build edits as (line_index, kind, payload); apply from bottom up
    ins_after = {}   # idx -> list of new lines inserted after idx
    replace = {}     # idx -> new line
    n = [0]
    def nid(tag):
        n[0] += 1
        return '%pq_' + tag + str(n[0])

    C_m1, C_1, C_1024, C_eps = '%pq_cm1', '%pq_c1', '%pq_c1024', '%pq_ceps'
    C_km1, C_k1 = '%pq_ckm1', '%pq_ck1'
    V_0, V_1, V_eps = '%pq_v0', '%pq_v1', '%pq_veps'
    P_v3 = t_pv3 or '%pq_ptrv3'
    globals_new = []
    if not t_pv3:
        globals_new.append(f'{P_v3} = OpTypePointer Function {t_v3}')
    globals_new += [
        f'{C_m1} = OpConstant {t_float} -1',
        f'{C_km1} = OpConstant {t_float} {-K!r}',
        f'{C_k1} = OpConstant {t_float} {K!r}',
        f'{C_1} = OpConstant {t_float} 1',
        f'{C_1024} = OpConstant {t_float} 1024',
        f'{C_eps} = OpConstant {t_float} 0.0009765625',
        f'{V_0} = OpConstantNull {t_v3}',
        f'{V_1} = OpConstantComposite {t_v3} {C_1} {C_1} {C_1}',
        f'{V_eps} = OpConstantComposite {t_v3} {C_eps} {C_eps} {C_eps}',
    ]
    uint0 = None
    for l in lines:
        m = re.match(r'\s*(%\S+) = OpConstant ' + re.escape(t_uint) + r' 0\s*$', l)
        if m:
            uint0 = m.group(1)
            break
    if not uint0:
        uint0 = '%pq_u0'
        globals_new.append(f'{uint0} = OpConstant {t_uint} 0')

    first_func = next(i for i, l in enumerate(lines) if re.match(r'\s*%\S+ = OpFunction ', l))
    ins_after.setdefault(first_func - 1, []).extend(globals_new)

    # group sites by loop
    by_loop = {}
    for s in sites:
        by_loop.setdefault(s['loop'][0], []).append(s)

    loop_vars = {}
    for h, ss in by_loop.items():
        A, C = nid('A'), nid('C')
        loop_vars[h] = (A, C)
        # declare in first block of enclosing function
        fi = max(i for i in range(0, h) if re.match(r'\s*%\S+ = OpFunction ', lines[i]))
        lab = next(i for i in range(fi, h) if re.match(r'\s*%\S+ = OpLabel\s*$', lines[i]))
        ins_after.setdefault(lab, []).extend([f'{A} = OpVariable {P_v3} Function', f'{C} = OpVariable {P_v3} Function'])
        rq = ss[0]['rq']
        # reset after each initialize of rq preceding this loop (within 200 lines)
        for j in range(max(0, h - 200), h):
            if re.match(r'\s*OpRayQueryInitializeKHR ' + re.escape(rq) + ' ', lines[j]):
                ins_after.setdefault(j, []).extend([f'OpStore {A} {V_0}', f'OpStore {C} {V_0}'])
        # apply at merge
        merge_idx = ss[0]['loop'][2]
        k = merge_idx
        while k + 1 < len(lines) and 'OpPhi' in lines[k + 1]:
            k += 1
        R = ss[0]['R']
        tptr = ss[0]['tmax_ptr']
        a, c, nc, mx, tm, tc, ms, sm, ng, e, e1, r0, r1 = [nid(x) for x in
            ('a', 'c', 'nc', 'mx', 'tm', 'tc', 'ms', 'sm', 'ng', 'e', 'e1', 'r0', 'r1')]
        code = [f'{a} = OpLoad {t_v3} {A}', f'{c} = OpLoad {t_v3} {C}',
                f'{nc} = OpFNegate {t_v3} {c}', f'{mx} = OpExtInst {t_v3} {glsl} FMax {nc} {V_0}']
        if tptr:
            code += [f'{tm} = OpLoad {t_float} {tptr}', f'{tc} = OpExtInst {t_float} {glsl} FMin {tm} {C_1024}']
        else:
            tc = C_1024
        code += [f'{ms} = OpVectorTimesScalar {t_v3} {mx} {tc}', f'{sm} = OpFAdd {t_v3} {a} {ms}',
                 f'{ng} = OpFNegate {t_v3} {sm}', f'{e} = OpExtInst {t_v3} {glsl} Exp {ng}',
                 f'{e1} = OpExtInst {t_v3} {glsl} FMin {e} {V_1}']
        if telltale:
            # positive control: any thick translucent candidate on this ray turns the light pure red
            hit = nid('hit'); anyc = nid('any'); sel = nid('sel')
            code += [f'{hit} = OpFOrdNotEqual {t_bool} {nc} {nc}']  # placeholder replaced below
            code = code[:-1]
            code += [f'{anyc} = OpDot {t_float} {a} {a}',
                     f'{hit} = OpFOrdGreaterThan {t_bool} {anyc} {C_eps}',
                     f'{sel} = OpSelect {t_v3} {hit} %pq_red {e1}']
            e1 = sel
        code += [f'{r0} = OpLoad {t_v3} {R}', f'{r1} = OpFMul {t_v3} {r0} {e1}', f'OpStore {R} {r1}']
        ins_after.setdefault(k, []).extend(code)

        for s in ss:
            # clamp T before Log
            tcl = nid('Tc')
            ll = lines[s['log_line']]
            ins_after.setdefault(s['log_line'] - 1, []).append(f'{tcl} = OpExtInst {t_v3} {glsl} FMax {s["T"]} {V_eps}')
            replace[s['log_line']] = re.sub(re.escape(s['T']) + r'\s*$', tcl, ll)
            t, ff, sg, st, a0, a1, a2, c0, c1, c2 = [nid(x) for x in
                ('t', 'ff', 'sg', 'st', 'a0', 'a1', 'a2', 'c0', 'c1', 'c2')]
            ins_after.setdefault(s['sig_line'], []).extend([
                f'{t} = OpRayQueryGetIntersectionTKHR {t_float} {s["rq"]} {uint0}',
                f'{ff} = OpRayQueryGetIntersectionFrontFaceKHR {t_bool} {s["rq"]} {uint0}',
                f'{sg} = OpSelect {t_float} {ff} {C_km1} {C_k1}',
                f'{st} = OpFMul {t_float} {sg} {t}',
                f'{a0} = OpLoad {t_v3} {A}', f'{a1} = OpVectorTimesScalar {t_v3} {s["sig"]} {st}',
                f'{a2} = OpFAdd {t_v3} {a0} {a1}', f'OpStore {A} {a2}',
                f'{c0} = OpLoad {t_v3} {C}', f'{c1} = OpVectorTimesScalar {t_v3} {s["sig"]} {sg}',
                f'{c2} = OpFAdd {t_v3} {c0} {c1}', f'OpStore {C} {c2}',
            ])
            replace[s['store_line']] = f'OpStore {s["P"]} {V_1}'

    if telltale:
        globals_new_t = [f'%pq_red = OpConstantComposite {t_v3} {C_1} {"%pq_c0"} {"%pq_c0"}',
                         f'%pq_c0 = OpConstant {t_float} 0']
        ins_after[first_func - 1].extend([globals_new_t[1], globals_new_t[0]])

    out = []
    for i, l in enumerate(lines):
        out.append(replace.get(i, l))
        if i in ins_after:
            out.extend('               ' + x if not x.startswith('%') else '      ' + x for x in ins_after[i])
    open(dst, 'w', encoding='utf-8').write('\n'.join(out))
    print(json.dumps({'sites': len(sites), 'loops': len(by_loop), 'skipped': skipped,
                      'site_lines': [s['sig_line'] + 1 for s in sites],
                      'tmax_ptr_missing': sum(1 for s in sites if not s['tmax_ptr'])}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
