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

# Glass tint renormalisation (0 = off). The material colour is a hue, not a measured transmittance: after the
# runtime's gamma step a red pane is about (0.33, 0.006, 0.006), which leaves a block of it a dark shadow, not
# red light. For glass-like materials (measurement distance under GLASS_MAX_DISTANCE) the brightest channel is
# raised to this value per measurement distance and the others keep their ratio, so the light keeps the hue.
GLASS_CLEAR = float(sys.argv[sys.argv.index('--glass-clear') + 1]) if '--glass-clear' in sys.argv else 0.0
GLASS_MAX_DISTANCE = 0.5

# Live switch (--live-flag): the new behaviour runs only while ViewDistanceArgs.noiseScale (runtime option
# rtx.viewDistance.noiseScale, shipped value 20) is above NOISE_SCALE_ON_ABOVE. The mod writes 20.001 for ON and
# exactly 20 for OFF, and with it at 20 every patched site is the shipped code, so the mod can toggle at runtime.
LIVE = '--live-flag' in sys.argv
VD_MEMBER = 8        # RaytraceArgs.viewDistanceArgs
NOISE_MEMBER = 4     # ViewDistanceArgs.noiseScale
NOISE_SCALE_ON_ABOVE = 20.0005
# --sat-slider (with --live-flag): glass colour saturation 0.25..2.0 read live from the same option,
# noiseScale = 20.001 + 0.01 * saturation (so 20.011 = 100%).
SAT_SLIDER = '--sat-slider' in sys.argv
# --telltale with --live-flag: the red also needs ViewDistanceArgs.distanceFadeMin (rtx.viewDistance.distanceFadeMin,
# shipped value 358.4 here) above this, so a second key can switch the red off while the fix stays on.
FADE_MIN_ON_ABOVE = 358.4005

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
                      'P': P, 'R': R, 'rq': rq, 'loop': loop, 'tmax_ptr': tmax_ptr, 'dist': dist})

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
        return '%pq_' + tag + '_' + str(n[0])

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
    if GLASS_CLEAR > 0:
        globals_new += [f'%pq_cclear = OpConstant {t_float} {GLASS_CLEAR!r}',
                        f'%pq_cglassmax = OpConstant {t_float} {GLASS_MAX_DISTANCE!r}']
    uint0 = None
    for l in lines:
        m = re.match(r'\s*(%\S+) = OpConstant ' + re.escape(t_uint) + r' 0\s*$', l)
        if m:
            uint0 = m.group(1)
            break
    if not uint0:
        uint0 = '%pq_u0'
        globals_new.append(f'{uint0} = OpConstant {t_uint} 0')

    flag_ok = False
    if LIVE:
        t_int = type_id(r'OpTypeInt 32 1')
        cbvar = None
        cb_ptr = type_id(r'OpTypePointer Uniform %RaytraceArgs_natural')
        for l in lines:
            m = re.match(r'\s*(%\S+) = OpVariable (%\S+) Uniform\s*$', l)
            if m and m.group(2) == cb_ptr:
                cbvar = m.group(1)
                break
        st = next((l for l in lines if re.match(r'\s*%RaytraceArgs_natural = OpTypeStruct ', l)), None)
        if t_int and cbvar and st and st.split()[VD_MEMBER + 3] == '%ViewDistanceArgs_natural':
            pf = type_id(r'OpTypePointer Uniform ' + re.escape(t_float))
            if not pf:
                pf = '%pq_pf'
                globals_new.append(f'{pf} = OpTypePointer Uniform {t_float}')
            globals_new += [f'%pq_cvd = OpConstant {t_int} {VD_MEMBER}', f'%pq_cns = OpConstant {t_int} {NOISE_MEMBER}',
                            f'%pq_cthr = OpConstant {t_float} {NOISE_SCALE_ON_ABOVE!r}']
            if telltale:
                globals_new += [f'%pq_cfmin = OpConstant {t_int} 2',
                                f'%pq_cthr2 = OpConstant {t_float} {FADE_MIN_ON_ABOVE!r}']
            flag_ok = True
            if SAT_SLIDER:
                globals_new += [f'%pq_sbase = OpConstant {t_float} 20.001', f'%pq_s100 = OpConstant {t_float} 100',
                                f'%pq_smin = OpConstant {t_float} 0.25', f'%pq_smax = OpConstant {t_float} 2',
                                f'%pq_c02126 = OpConstant {t_float} 0.2126', f'%pq_c07152 = OpConstant {t_float} 0.7152',
                                f'%pq_c00722 = OpConstant {t_float} 0.0722',
                                f'%pq_vlum = OpConstantComposite {t_v3} %pq_c02126 %pq_c07152 %pq_c00722']
    if LIVE and not flag_ok:
        globals_new += [f'%pq_ctrue = OpConstantTrue {t_bool}']

    def flag():
        """(lines, id) producing the live-switch bool at the current point."""
        if not LIVE:
            return [], None
        if not flag_ok:
            return [], '%pq_ctrue'
        p_, v_, b_ = nid('fp'), nid('fv'), nid('fb')
        return [f'{p_} = OpAccessChain {pf} {cbvar} %pq_cvd %pq_cns', f'{v_} = OpLoad {t_float} {p_}',
                f'{b_} = OpFOrdGreaterThan {t_bool} {v_} %pq_cthr'], b_

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
                     f'{hit} = OpFOrdGreaterThan {t_bool} {anyc} {C_eps}']
            if LIVE and flag_ok:
                p2, v2, b2, h2 = nid('tp'), nid('tv'), nid('tb'), nid('th')
                code += [f'{p2} = OpAccessChain {pf} {cbvar} %pq_cvd %pq_cfmin', f'{v2} = OpLoad {t_float} {p2}',
                         f'{b2} = OpFOrdGreaterThan {t_bool} {v2} %pq_cthr2', f'{h2} = OpLogicalAnd {t_bool} {hit} {b2}']
                hit = h2
            code += [f'{sel} = OpSelect {t_v3} {hit} %pq_red {e1}']
            e1 = sel
        code += [f'{r0} = OpLoad {t_v3} {R}', f'{r1} = OpFMul {t_v3} {r0} {e1}', f'OpStore {R} {r1}']
        ins_after.setdefault(k, []).extend(code)

        for s in ss:
            # clamp T before Log
            tcl = nid('Tc')
            ll = lines[s['log_line']]
            if SAT_SLIDER and LIVE and flag_ok:
                # glass colour saturation: lerp toward / away from the luminance grey by the live slider value, glass only
                tcl0, sp, sv, s0, s1, s2, lum, lv, df, sd, ts, tx, tn, isg2 = [nid(x) for x in (
                    'Tc0', 'sp', 'sv', 's0', 's1', 's2', 'lum', 'lv', 'df', 'sd', 'ts', 'tx', 'tn', 'isg2')]
                pre = [f'{tcl0} = OpExtInst {t_v3} {glsl} FMax {s["T"]} {V_eps}',
                       f'{sp} = OpAccessChain {pf} {cbvar} %pq_cvd %pq_cns', f'{sv} = OpLoad {t_float} {sp}',
                       f'{s0} = OpFSub {t_float} {sv} %pq_sbase', f'{s1} = OpFMul {t_float} {s0} %pq_s100',
                       f'{s2} = OpExtInst {t_float} {glsl} FClamp {s1} %pq_smin %pq_smax',
                       # hue-safe saturation (2026-11-12), see bounce_tint_patch.py: strongest channel fixed, others ^s
                       f'{lum}x = OpCompositeExtract {t_float} {tcl0} 0', f'{lum}y = OpCompositeExtract {t_float} {tcl0} 1',
                       f'{lum}z = OpCompositeExtract {t_float} {tcl0} 2', f'{lum}a = OpExtInst {t_float} {glsl} FMax {lum}x {lum}y',
                       f'{lum} = OpExtInst {t_float} {glsl} FMax {lum}a {lum}z', f'{lv} = OpCompositeConstruct {t_v3} {lum} {lum} {lum}',
                       f'{df} = OpFDiv {t_v3} {tcl0} {lv}', f'{sd} = OpCompositeConstruct {t_v3} {s2} {s2} {s2}',
                       f'{sd}p = OpExtInst {t_v3} {glsl} Pow {df} {sd}', f'{ts} = OpFMul {t_v3} {sd}p {lv}',
                       f'{tx} = OpExtInst {t_v3} {glsl} FMax {ts} {V_eps}', f'{tn} = OpExtInst {t_v3} {glsl} FMin {tx} {V_1}',
                       f'{isg2} = OpFOrdLessThan {t_bool} {s["dist"]} %pq_cglassmax',
                       f'{tcl} = OpSelect {t_v3} {isg2} {tn} {tcl0}']
            else:
                pre = [f'{tcl} = OpExtInst {t_v3} {glsl} FMax {s["T"]} {V_eps}']
            operand = tcl
            if GLASS_CLEAR > 0:
                cx, cy, cz, mxy, mx, sc, sc1, tsc, tcap, isg, tsel = [nid(x) for x in (
                    'gx', 'gy', 'gz', 'gmxy', 'gmx', 'gsc', 'gsc1', 'gtsc', 'gtcap', 'gisg', 'gtsel')]
                mn1, mn, rr, sat, dd, dl, sc2 = [nid(x) for x in ('gmn1', 'gmn', 'grr', 'gsat', 'gdd', 'gdl', 'gsc2')]
                pre += [
                    f'{cx} = OpCompositeExtract {t_float} {tcl} 0',
                    f'{cy} = OpCompositeExtract {t_float} {tcl} 1',
                    f'{cz} = OpCompositeExtract {t_float} {tcl} 2',
                    f'{mxy} = OpExtInst {t_float} {glsl} FMax {cx} {cy}',
                    f'{mx} = OpExtInst {t_float} {glsl} FMax {mxy} {cz}',
                    f'{sc} = OpFDiv {t_float} %pq_cclear {mx}',
                    f'{sc1} = OpExtInst {t_float} {glsl} FMax {sc} {C_1}',
                    # the lift only applies to SATURATED glass (keeps the hue at full brightness); a neutral dark glass
                    # (black, grey: min == max) is not brightened at all, so it stays dark
                    f'{mn1} = OpExtInst {t_float} {glsl} FMin {cx} {cy}',
                    f'{mn} = OpExtInst {t_float} {glsl} FMin {mn1} {cz}',
                    f'{rr} = OpFDiv {t_float} {mn} {mx}',
                    f'{sat} = OpFSub {t_float} {C_1} {rr}',
                    f'{dd} = OpFSub {t_float} {sc1} {C_1}',
                    f'{dl} = OpFMul {t_float} {dd} {sat}',
                    f'{sc2} = OpFAdd {t_float} {C_1} {dl}',
                    f'{tsc} = OpVectorTimesScalar {t_v3} {tcl} {sc2}',
                    f'{tcap} = OpExtInst {t_v3} {glsl} FMin {tsc} {V_1}',
                    f'{isg} = OpFOrdLessThan {t_bool} {s["dist"]} %pq_cglassmax',
                    f'{tsel} = OpSelect {t_v3} {isg} {tcap} {tcl}',
                ]
                operand = tsel
            if LIVE:
                fl, fid = flag()
                osel = nid('lsel')
                pre = fl + pre + [f'{osel} = OpSelect {t_v3} {fid} {operand} {s["T"]}']
                operand = osel
            ins_after.setdefault(s['log_line'] - 1, []).extend(pre)
            replace[s['log_line']] = re.sub(re.escape(s['T']) + r'\s*$', operand, ll)
            t, ff, sg, st, a0, a1, a2, c0, c1, c2 = [nid(x) for x in
                ('t', 'ff', 'sg', 'st', 'a0', 'a1', 'a2', 'c0', 'c1', 'c2')]
            fl, fid = flag()
            a2g, c2g = nid('a2g'), nid('c2g')
            sg0 = sg
            ins_after.setdefault(s['sig_line'], []).extend(fl + [
                f'{t} = OpRayQueryGetIntersectionTKHR {t_float} {s["rq"]} {uint0}',
                f'{ff} = OpRayQueryGetIntersectionFrontFaceKHR {t_bool} {s["rq"]} {uint0}',
                f'{sg0} = OpSelect {t_float} {ff} {C_km1} {C_k1}',
            ] + [
                f'{st} = OpFMul {t_float} {sg} {t}',
                f'{a0} = OpLoad {t_v3} {A}', f'{a1} = OpVectorTimesScalar {t_v3} {s["sig"]} {st}',
                f'{a2} = OpFAdd {t_v3} {a0} {a1}'] + ([f'{a2g} = OpSelect {t_v3} {fid} {a2} {a0}'] if LIVE else []) + [
                f'OpStore {A} {a2g if LIVE else a2}',
                f'{c0} = OpLoad {t_v3} {C}', f'{c1} = OpVectorTimesScalar {t_v3} {s["sig"]} {sg}',
                f'{c2} = OpFAdd {t_v3} {c0} {c1}'] + ([f'{c2g} = OpSelect {t_v3} {fid} {c2} {c0}'] if LIVE else []) + [
                f'OpStore {C} {c2g if LIVE else c2}',
            ])
            if LIVE:
                mst = re.match(r'\s*OpStore (%\S+) (%\S+)\s*$', lines[s['store_line']])
                ssel = nid('ssel')
                ins_after.setdefault(s['store_line'] - 1, []).append(f'{ssel} = OpSelect {t_v3} {fid} {V_1} {mst.group(2)}')
                replace[s['store_line']] = f'OpStore {s["P"]} {ssel}'
            else:
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
