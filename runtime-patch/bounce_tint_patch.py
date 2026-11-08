"""Boost the glass tint applied to BOUNCE rays (indirect path tracing), in one SPIR-V module (disassembly text).

In the indirect-ray translucent resolve the runtime multiplies the path throughput by the surface's transmittance
colour once per hit:  clamp(albedoTexel * scale + bias, 0, 1) ^ gamma  (TranslucentMaterialArgs members 0 and 1).
For stained glass that colour is a hue, not a measured transmittance (a red pane is about (0.33, 0.006, 0.006)), so
light that crosses it, such as a sea lantern's, ends up as a dark patch. Here the brightest channel of that colour is
raised to --bounce-clear (never lowered) and the other channels keep their ratio, so the hue survives at full strength.

With --live-flag the result is selected by the same live switch the shadow-ray patch uses
(ViewDistanceArgs.noiseScale > 20.0005), and the shipped value is kept otherwise.

Usage: bounce_tint_patch.py in.dis out.dis --bounce-clear 0.9 [--live-flag]
Prints a JSON summary on stdout.
"""
import json
import re
import sys

ARGS = sys.argv
CLEAR = float(ARGS[ARGS.index('--bounce-clear') + 1]) if '--bounce-clear' in ARGS else 0.9
LIVE = '--live-flag' in ARGS
SAT = '--sat-slider' in ARGS   # with --live-flag: glass saturation 0.25..2 read from noiseScale = 20.001 + 0.01 * s
TELL = '--telltale' in ARGS  # with --live-flag: bounce light that crosses a patched site turns green (0.05, 1, 0.05)
FADE_MIN_ON_ABOVE = 358.4005   # same second key as the shadow-ray telltale (rtx.viewDistance.distanceFadeMin)
VD_MEMBER, NOISE_MEMBER, NOISE_ON_ABOVE = 8, 4, 20.0005
TRANSLUCENT_CHAIN = 'OpAccessChain %_ptr_Uniform_TranslucentMaterialArgs_natural %cb %int_7'


def main():
    src, dst = ARGS[1], ARGS[2]
    lines = open(src, encoding='utf-8').read().split('\n')

    def first(pattern):
        for l in lines:
            m = re.match(r'\s*(%\S+) = ' + pattern + r'\s*$', l)
            if m:
                return m.group(1)
        return None

    glsl = None
    for l in lines:
        m = re.match(r'\s*(%\S+) = OpExtInstImport "GLSL.std.450"', l)
        if m:
            glsl = m.group(1)
    t_float, t_bool = first(r'OpTypeFloat 32'), first(r'OpTypeBool')
    t_v3 = first(r'OpTypeVector ' + re.escape(t_float) + ' 3') if t_float else None
    t_int = first(r'OpTypeInt 32 1')
    if not all([glsl, t_float, t_bool, t_v3]):
        open(dst, 'w', encoding='utf-8').write('\n'.join(lines))
        print(json.dumps({'bounce_sites': 0, 'note': 'missing types'}))
        return

    # only INDIRECT-ray shaders: they read RaytraceArgs.enableTransmissionApproximationInIndirectRays. The primary-view
    # (gbuffer) shaders contain the same colour code and must keep the shipped look of the glass seen directly.
    flag_idx = next((m.group(1) for l in lines for m in [re.match(
        r'\s*OpMemberName %RaytraceArgs_natural (\d+) "enableTransmissionApproximationInIndirectRays"', l)] if m), None)
    indirect = flag_idx is not None and any(re.search(r'OpAccessChain \S+ %cb %int_' + flag_idx + r'\s*$', l) for l in lines)
    if not indirect and '--any-module' not in ARGS:
        open(dst, 'w', encoding='utf-8').write('\n'.join(lines))
        print(json.dumps({'bounce_sites': 0, 'note': 'not an indirect-ray module'}))
        return

    def_line = {}
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\S+) = ', l)
        if m:
            def_line[m.group(1)] = i

    # anchor: %res = OpFConvert v3float %p ; %p = OpExtInst v3half Pow ... ; the translucent scale/bias chain just before
    sites = []
    for i, l in enumerate(lines):
        m = re.match(r'\s*(%\S+) = OpFConvert ' + re.escape(t_v3) + r' (%\S+)\s*$', l)
        if not m:
            continue
        res, p = m.groups()
        pi = def_line.get(p)
        if pi is None or not re.search(r'OpExtInst %\S+ ' + re.escape(glsl) + r' Pow ', lines[pi]):
            continue
        has_chain = any(TRANSLUCENT_CHAIN in lines[j] for j in range(max(0, i - 30), i))
        uses = [j for j, x in enumerate(lines) if j != i and re.search(re.escape(res) + r'(?![\w.])', x)
                and not re.match(r'\s*Op(Name|Decorate)', x)]
        # the colour feeds either the throughput multiply (OpStore) or the exact Beer-Lambert sigma (Log)
        if len(uses) != 1 or not (re.match(r'\s*OpStore \S+ ' + re.escape(res) + r'\s*$', lines[uses[0]]) or
                                  re.match(r'\s*%\S+ = OpExtInst %\S+ ' + re.escape(glsl) + r' Log ' + re.escape(res) + r'\s*$',
                                           lines[uses[0]])):
            continue
        # Log sites that are not built from the scale/bias chain (the stained glass lerp(0.97, albedo, alpha) and its kin):
        # patch them only when the very next instructions divide by a measurement distance, and then only for glass
        # (distance below GLASS_MAX_DISTANCE), so water and fog media keep their shipped colour.
        dist = None
        if not has_chain:
            if not re.match(r'\s*%\S+ = OpExtInst', lines[uses[0]]):
                continue
            for j in range(uses[0] + 1, min(uses[0] + 6, len(lines))):
                mm = re.match(r'\s*%\S+ = OpCompositeConstruct ' + re.escape(t_v3) + r' (%\S+) (%\S+) (%\S+)\s*$', lines[j])
                if mm and not (mm.group(1) == mm.group(2) == mm.group(3)):
                    mm = None
                if mm:
                    dist = mm.group(1)
                    break
            if dist is None:
                continue
        sites.append((i, res, p, dist))

    # DIAGNOSTIC (--nee-marker, with --live-flag --telltale): the module's indirect diffuse output is drawn magenta, to show
    # whether the untinted light comes from this pass.
    nee_lines = []
    if '--nee-marker' in ARGS and LIVE and TELL:
        for i, l in enumerate(lines):
            mm = re.match(r'\s*(%\S+) = OpLoad ' + re.escape(first(r'OpTypeVector ' + re.escape(t_float) + ' 4') or '%v4float')
                          + r' %indirectDiffuseOutput\s*$', l)
            if mm:
                nee_lines.append((i, mm.group(1)))

    # DIAGNOSTIC (--cache-marker, with --live-flag --telltale): the radiance of a NEE-cache sample is drawn blue (same
    # brightness), so blue on the wall means cache light reaches it; if it then arrives tinted by the glass it darkens.
    cache_lines = []
    if ('--cache-marker' in ARGS or '--cache-kill' in ARGS) and LIVE and TELL:
        pkt = first(r'OpTypePointer StorageBuffer %NeeCache_PackedSample_natural')
        sample_ptrs = set()
        for l in lines:
            mm = re.match(r'\s*(%\S+) = OpAccessChain ' + re.escape(pkt or '%none') + r' %NeeCacheSample ', l)
            if mm:
                sample_ptrs.add(mm.group(1))
        light_ptrs = set()
        for l in lines:
            mm = re.match(r'\s*(%\S+) = OpAccessChain %\S+ (%\S+) %int_1\s*$', l)
            if mm and mm.group(2) in sample_ptrs:
                light_ptrs.add(mm.group(1))
        light_vals = set()
        for l in lines:
            mm = re.match(r'\s*(%\S+) = OpLoad %v4uint (%\S+)\s*$', l)
            if mm and mm.group(2) in light_ptrs:
                light_vals.add(mm.group(1))
        for i, l in enumerate(lines):
            mm = re.match(r'\s*(%\S+) = OpCompositeExtract %uint (%\S+) 1\s*$', l)
            if mm and mm.group(2) in light_vals:
                for j in range(i + 1, min(i + 10, len(lines))):
                    m3 = re.match(r'\s*(%\S+) = OpCompositeInsert ' + re.escape(t_v3) + r' (%\S+) (%\S+) 2\s*$', lines[j])
                    if m3:
                        cache_lines.append((j, m3.group(1), m3.group(2), m3.group(3)))
                        break

    if not sites and not nee_lines and not cache_lines:
        open(dst, 'w', encoding='utf-8').write('\n'.join(lines))
        print(json.dumps({'bounce_sites': 0}))
        return

    n = [0]

    def nid(tag):
        n[0] += 1
        return f'%pqb_{tag}_{n[0]}'

    g = [f'%pqb_c1 = OpConstant {t_float} 1', f'%pqb_ceps = OpConstant {t_float} 0.0009765625',
         f'%pqb_cclear = OpConstant {t_float} {CLEAR!r}', f'%pqb_cglassmax = OpConstant {t_float} 0.5',
         f'%pqb_v1 = OpConstantComposite {t_v3} %pqb_c1 %pqb_c1 %pqb_c1',
         f'%pqb_veps = OpConstantComposite {t_v3} %pqb_ceps %pqb_ceps %pqb_ceps']
    cbvar = flag_ok = pf = None
    if LIVE:
        cb_ptr = first(r'OpTypePointer Uniform %RaytraceArgs_natural')
        for l in lines:
            m = re.match(r'\s*(%\S+) = OpVariable (%\S+) Uniform\s*$', l)
            if m and m.group(2) == cb_ptr:
                cbvar = m.group(1)
                break
        st = next((l for l in lines if re.match(r'\s*%RaytraceArgs_natural = OpTypeStruct ', l)), None)
        flag_ok = bool(t_int and cbvar and st and st.split()[VD_MEMBER + 3] == '%ViewDistanceArgs_natural')
        if flag_ok:
            pf = first(r'OpTypePointer Uniform ' + re.escape(t_float))
            if not pf:
                pf = '%pqb_pf'
                g.append(f'{pf} = OpTypePointer Uniform {t_float}')
            if TELL:
                g += [f'%pqb_cfmin = OpConstant {t_int} 2', f'%pqb_cthr2 = OpConstant {t_float} {FADE_MIN_ON_ABOVE!r}',
                      f'%pqb_c0 = OpConstant {t_float} 0.05', f'%pqb_vgreen = OpConstantComposite {t_v3} %pqb_c0 %pqb_c1 %pqb_c0']
            g += [f'%pqb_cvd = OpConstant {t_int} {VD_MEMBER}', f'%pqb_cns = OpConstant {t_int} {NOISE_MEMBER}',
                  f'%pqb_cthr = OpConstant {t_float} {NOISE_ON_ABOVE!r}']
            if SAT:
                g += [f'%pqb_sbase = OpConstant {t_float} 20.001', f'%pqb_s100 = OpConstant {t_float} 100',
                      f'%pqb_smin = OpConstant {t_float} 0.25', f'%pqb_smax = OpConstant {t_float} 2',
                      f'%pqb_w0 = OpConstant {t_float} 0.2126', f'%pqb_w1 = OpConstant {t_float} 0.7152',
                      f'%pqb_w2 = OpConstant {t_float} 0.0722',
                      f'%pqb_vlum = OpConstantComposite {t_v3} %pqb_w0 %pqb_w1 %pqb_w2']
        else:
            g.append(f'%pqb_ctrue = OpConstantTrue {t_bool}')

    insert_at = {}
    replace = {}
    for i, res, p, dist in sites:
        raw = nid('raw')
        cx, cy, cz, mxy, mx, sc, sc1, tcl, tsc, tcap = [nid(x) for x in
            ('x', 'y', 'z', 'mxy', 'mx', 'sc', 'sc1', 'tcl', 'tsc', 'tcap')]
        mn1, mn, rr, sat, dd, dl, sc2 = [nid(x) for x in ('mn1', 'mn', 'rr', 'sat', 'dd', 'dl', 'sc2')]
        if SAT and LIVE and flag_ok:
            # glass colour saturation (live slider) applied before the brightness renormalisation; glass only when the
            # site has a measurement distance, otherwise (scale/bias chain sites) as the boost itself
            tcl0, sp, sv, s0, s1, s2, lum, lv, df, sd, ts, tx, tn = [nid(x) for x in (
                'tc0', 'sp', 'sv', 's0', 's1', 's2', 'lum', 'lv', 'df', 'sd', 'ts', 'tx', 'tn')]
            code = [
                f'{raw} = OpFConvert {t_v3} {p}',
                f'{tcl0} = OpExtInst {t_v3} {glsl} FMax {raw} %pqb_veps',
                f'{sp} = OpAccessChain {pf} {cbvar} %pqb_cvd %pqb_cns', f'{sv} = OpLoad {t_float} {sp}',
                f'{s0} = OpFSub {t_float} {sv} %pqb_sbase', f'{s1} = OpFMul {t_float} {s0} %pqb_s100',
                f'{s2} = OpExtInst {t_float} {glsl} FClamp {s1} %pqb_smin %pqb_smax',
                f'{lum} = OpDot {t_float} {tcl0} %pqb_vlum', f'{lv} = OpCompositeConstruct {t_v3} {lum} {lum} {lum}',
                f'{df} = OpFSub {t_v3} {tcl0} {lv}', f'{sd} = OpVectorTimesScalar {t_v3} {df} {s2}',
                f'{ts} = OpFAdd {t_v3} {lv} {sd}',
                f'{tx} = OpExtInst {t_v3} {glsl} FMax {ts} %pqb_veps', f'{tn} = OpExtInst {t_v3} {glsl} FMin {tx} %pqb_v1',
            ]
            if dist is not None:
                isg0, tg = nid('isg0'), nid('tg')
                code += [f'{isg0} = OpFOrdLessThan {t_bool} {dist} %pqb_cglassmax',
                         f'{tg} = OpSelect {t_v3} {isg0} {tn} {tcl0}']
                tn = tg
            code += [f'{tcl} = OpCopyObject {t_v3} {tn}']
        else:
            code = [
                f'{raw} = OpFConvert {t_v3} {p}',
                f'{tcl} = OpExtInst {t_v3} {glsl} FMax {raw} %pqb_veps',
            ]
        code += [
            f'{cx} = OpCompositeExtract {t_float} {tcl} 0', f'{cy} = OpCompositeExtract {t_float} {tcl} 1',
            f'{cz} = OpCompositeExtract {t_float} {tcl} 2',
            f'{mxy} = OpExtInst {t_float} {glsl} FMax {cx} {cy}', f'{mx} = OpExtInst {t_float} {glsl} FMax {mxy} {cz}',
            f'{sc} = OpFDiv {t_float} %pqb_cclear {mx}', f'{sc1} = OpExtInst {t_float} {glsl} FMax {sc} %pqb_c1',
            # lift only SATURATED glass (hue at full brightness); neutral dark glass (min == max) is left dark
            f'{mn1} = OpExtInst {t_float} {glsl} FMin {cx} {cy}', f'{mn} = OpExtInst {t_float} {glsl} FMin {mn1} {cz}',
            f'{rr} = OpFDiv {t_float} {mn} {mx}', f'{sat} = OpFSub {t_float} %pqb_c1 {rr}',
            f'{dd} = OpFSub {t_float} {sc1} %pqb_c1', f'{dl} = OpFMul {t_float} {dd} {sat}',
            f'{sc2} = OpFAdd {t_float} %pqb_c1 {dl}',
            f'{tsc} = OpVectorTimesScalar {t_v3} {tcl} {sc2}',
            f'{tcap} = OpExtInst {t_v3} {glsl} FMin {tsc} %pqb_v1',
        ]
        if dist is not None:
            isg, gsel = nid('isg'), nid('gsel')
            code += [f'{isg} = OpFOrdLessThan {t_bool} {dist} %pqb_cglassmax', f'{gsel} = OpSelect {t_v3} {isg} {tcap} {raw}']
            tcap = gsel
        if LIVE and flag_ok:
            fp, fv, fb = nid('fp'), nid('fv'), nid('fb')
            code += [f'{fp} = OpAccessChain {pf} {cbvar} %pqb_cvd %pqb_cns', f'{fv} = OpLoad {t_float} {fp}',
                     f'{fb} = OpFOrdGreaterThan {t_bool} {fv} %pqb_cthr']
            if TELL:
                dp, dv, db, both, tt = nid('dp'), nid('dv'), nid('db'), nid('both'), nid('tt')
                code += [f'{dp} = OpAccessChain {pf} {cbvar} %pqb_cvd %pqb_cfmin', f'{dv} = OpLoad {t_float} {dp}',
                         f'{db} = OpFOrdGreaterThan {t_bool} {dv} %pqb_cthr2', f'{both} = OpLogicalAnd {t_bool} {fb} {db}',
                         f'{tt} = OpSelect {t_v3} {both} %pqb_vgreen {tcap}']
                tcap = tt
            code += [f'{res} = OpSelect {t_v3} {fb} {tcap} {raw}']
        elif LIVE:
            code += [f'{res} = OpSelect {t_v3} %pqb_ctrue {tcap} {raw}']
        else:
            code += [f'{res} = OpCopyObject {t_v3} {tcap}']
        replace[i] = code

    if nee_lines and flag_ok:
        t_v4 = first(r'OpTypeVector ' + re.escape(t_float) + ' 4')
        g += [f'%pqb_c0z = OpConstant {t_float} 0']
        for i, res in nee_lines:
            raw, fp, fv, fb, dp, dv, db, both = [nid(x) for x in ('nraw', 'nfp', 'nfv', 'nfb', 'ndp', 'ndv', 'ndb', 'nboth')]
            r_, g_, b_, a_, mk = [nid(x) for x in ('nr', 'ng', 'nb', 'na', 'nmk')]
            replace[i] = [
                f'{raw} = OpLoad {t_v4} %indirectDiffuseOutput',
                f'{fp} = OpAccessChain {pf} {cbvar} %pqb_cvd %pqb_cns', f'{fv} = OpLoad {t_float} {fp}',
                f'{fb} = OpFOrdGreaterThan {t_bool} {fv} %pqb_cthr',
                f'{dp} = OpAccessChain {pf} {cbvar} %pqb_cvd %pqb_cfmin', f'{dv} = OpLoad {t_float} {dp}',
                f'{db} = OpFOrdGreaterThan {t_bool} {dv} %pqb_cthr2', f'{both} = OpLogicalAnd {t_bool} {fb} {db}',
                f'{r_} = OpCompositeExtract {t_float} {raw} 0', f'{b_} = OpCompositeExtract {t_float} {raw} 2',
                f'{a_} = OpCompositeExtract {t_float} {raw} 3',
                f'{mk} = OpCompositeConstruct {t_v4} {r_} %pqb_c0z {b_} {a_}',
                f'{res} = OpSelect {t_v4} {both} {mk} {raw}',
            ]

    if cache_lines and flag_ok:
        g += [f'%pqb_c0c = OpConstant {t_float} 0', f'%pqb_third = OpConstant {t_float} 0.3333333']
        for i, res, a_, b_ in cache_lines:
            raw, fp, fv, fb, dp, dv, db, both, x, y, z, s1, s2, lum, mk = [nid(q) for q in (
                'craw', 'cfp', 'cfv', 'cfb', 'cdp', 'cdv', 'cdb', 'cboth', 'cx', 'cy', 'cz', 's1', 's2', 'clum', 'cmk')]
            replace[i] = [
                f'{raw} = OpCompositeInsert {t_v3} {a_} {b_} 2',
                f'{fp} = OpAccessChain {pf} {cbvar} %pqb_cvd %pqb_cns', f'{fv} = OpLoad {t_float} {fp}',
                f'{fb} = OpFOrdGreaterThan {t_bool} {fv} %pqb_cthr',
                f'{dp} = OpAccessChain {pf} {cbvar} %pqb_cvd %pqb_cfmin', f'{dv} = OpLoad {t_float} {dp}',
                f'{db} = OpFOrdGreaterThan {t_bool} {dv} %pqb_cthr2', f'{both} = OpLogicalAnd {t_bool} {fb} {db}',
                f'{x} = OpCompositeExtract {t_float} {raw} 0', f'{y} = OpCompositeExtract {t_float} {raw} 1',
                f'{z} = OpCompositeExtract {t_float} {raw} 2',
                f'{s1} = OpFAdd {t_float} {x} {y}', f'{s2} = OpFAdd {t_float} {s1} {z}',
                f'{lum} = OpFMul {t_float} {s2} %pqb_third',
                (f'{mk} = OpCompositeConstruct {t_v3} %pqb_c0c %pqb_c0c %pqb_c0c' if '--cache-kill' in ARGS
                 else f'{mk} = OpCompositeConstruct {t_v3} %pqb_c0c %pqb_c0c {lum}'),
                f'{res} = OpSelect {t_v3} {both} {mk} {raw}',
            ]

    first_func = next(i for i, l in enumerate(lines) if re.match(r'\s*%\S+ = OpFunction ', l))
    out = []
    for i, l in enumerate(lines):
        if i == first_func:
            out.extend(g)
        if i in replace:
            out.extend(replace[i])
        else:
            out.append(l)
    open(dst, 'w', encoding='utf-8').write('\n'.join(out))
    print(json.dumps({'bounce_sites': len(sites), 'cache_sites': len(cache_lines), 'lines': [s[0] + 1 for s in sites]}))


if __name__ == '__main__':
    main()
