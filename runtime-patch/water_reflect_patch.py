"""Bounce rays treat WATER as a real surface (refract, reflect, absorb by depth) instead of flying straight through it.

With rtx.enableTransmissionApproximationInIndirectRays on (the shipped value, kept by the mod) the indirect-ray translucent
resolve does NOT return a hit for a translucent surface: it multiplies the path throughput by the surface colour and sends the
ray straight on ("translucent objects hit by indirect rays will not alter ray direction"). Water in a reflection (for example
a water column reflected by a water surface seen through glass) is therefore a tinted window onto whatever is behind it, the
sky above the column: blue, with no refraction, no total internal reflection and no absorption by depth.

This patch makes the approximation false for hits on WATER only (resolveMode bit 6, resolveModeTranslucencyTransmissionApprox,
both tests of it in the resolve). The water is then returned as an ordinary hit and the integrator does what stock Remix does
with the option off: the ray refracts and reflects at the surface, tracks the medium and is absorbed by distance. Glass keeps
the approximation (cheap, and its tint for bounce light is handled by bounce_tint_patch). The per-hit colour multiply is skipped
for converted water hits.

WATER is recognised from the surface material the shader has just loaded: MemoryPolymorphicSurfaceMaterial.data[1].y holds, in
its high 16 bits, the refractive index as a half float (TranslucentSurfaceMaterial.refractiveIndex). The mod's water material
has IOR 1.33, every glass-like material 1.52, so 1.1 < IOR < 1.425 is water. (Version 1 and 2 tested the animated-water surface
flag; nothing in this setup ever sets it, so they never fired.)

Gated by the live flag (ViewDistanceArgs.noiseScale > 20.0005), so OFF is the shipped shader. Only modules that read
enableTransmissionApproximationInIndirectRays (the indirect-ray shaders) are touched.

Usage: water_reflect_patch.py in.dis out.dis [--show]   (prints a JSON summary)
"""
import json
import re
import sys

VD_MEMBER, NOISE_MEMBER, NOISE_ON_ABOVE = 8, 4, 20.0005
IOR_LOW, IOR_HIGH = 1.1, 1.425


def main():
    src, dst = sys.argv[1], sys.argv[2]
    L = open(src, encoding='utf-8').read().split('\n')

    def done(info, lines=None):
        open(dst, 'w', encoding='utf-8').write('\n'.join(lines if lines is not None else L))
        print(json.dumps(info))

    def tid(p):
        for l in L:
            m = re.match(r'\s*(%\S+) = ' + p + r'\s*$', l)
            if m:
                return m.group(1)
        return None

    fl, bo, i32, u32 = tid('OpTypeFloat 32'), tid('OpTypeBool'), tid(r'OpTypeInt 32 1'), tid(r'OpTypeInt 32 0')
    u8 = tid(r'OpTypeInt 8 0')
    v3 = tid('OpTypeVector ' + re.escape(fl or '%none') + ' 3')
    v4u = tid('OpTypeVector ' + re.escape(u32 or '%none') + ' 4')
    glsl = next((re.match(r'\s*(%\S+) = OpExtInstImport "GLSL.std.450"', l).group(1)
                 for l in L if re.match(r'\s*%\S+ = OpExtInstImport "GLSL.std.450"', l)), None)
    cb = next((re.match(r'\s*(%\S+) = OpVariable %_ptr_Uniform_RaytraceArgs_natural Uniform', l).group(1)
               for l in L if re.match(r'\s*%\S+ = OpVariable %_ptr_Uniform_RaytraceArgs_natural Uniform', l)), None)
    st = next((l for l in L if re.match(r'\s*%RaytraceArgs_natural = OpTypeStruct ', l)), None)
    c64 = tid('OpConstant ' + re.escape(u8) + ' 64') if u8 else None
    c0u8 = tid('OpConstant ' + re.escape(u8) + ' 0') if u8 else None
    int1 = tid('OpConstant ' + re.escape(i32 or '%none') + ' 1')
    if not all([fl, bo, i32, u32, u8, v3, v4u, glsl, cb, st, c64, c0u8, int1]) or st.split()[3 + VD_MEMBER] != '%ViewDistanceArgs_natural':
        return done({'water_reflect_sites': 0, 'note': 'missing types / constants'})

    # only INDIRECT-ray shaders read the option; the primary-view (gbuffer) shaders never set resolve mode bit 6
    flag_idx = next((m.group(1) for l in L for m in [re.match(
        r'\s*OpMemberName %RaytraceArgs_natural (\d+) "enableTransmissionApproximationInIndirectRays"', l)] if m), None)
    if flag_idx is None or not any(re.search(r'OpAccessChain \S+ ' + re.escape(cb) + r' %int_' + flag_idx + r'\s*$', l) for l in L):
        return done({'water_reflect_sites': 0, 'note': 'not an indirect-ray module'})

    # material data loads: %base = OpAccessChain %_ptr_StorageBuffer__arr_v4uint_int_4 ... ;
    #   %a = OpAccessChain %_ptr_StorageBuffer_v4uint %base %int_1 ; %d1 = OpLoad %v4uint %a     (data[1])
    groups = []   # (line of the base definition, id of data[1])
    clean = [(i, l) for i, l in enumerate(L) if not l.startswith('OpLine') and not l.startswith('OpNoLine')]
    pos_of = {i: n for n, (i, _) in enumerate(clean)}
    for n, (i, l) in enumerate(clean):
        mb = re.match(r'\s*(%\S+) = OpAccessChain %_ptr_StorageBuffer__arr_v4uint_int_4 \S+ \S+\s*$', l)
        if not mb:
            continue
        base = mb.group(1)
        for k in range(n + 1, min(n + 14, len(clean) - 1)):
            ma = re.match(r'\s*(%\S+) = OpAccessChain %_ptr_StorageBuffer_v4uint ' + re.escape(base) + ' ' + re.escape(int1) + r'\s*$', clean[k][1])
            ml = re.match(r'\s*(%\S+) = OpLoad ' + re.escape(v4u) + r' ' + re.escape(ma.group(1)) + r'\s*$', clean[k + 1][1]) if ma else None
            if ml:
                groups.append((i, ml.group(1)))
                break
    if not groups:
        return done({'water_reflect_sites': 0, 'note': 'no material data loads'})

    # sites: %f = OpLoad %float F ; %c = OpLoad %v3float C ; %m = OpVectorTimesScalar %v3float %c %f ; %t = OpLoad v3 T ; %r = OpFMul v3 %t %m ; OpStore T %r
    sites = []
    for i in range(len(L) - 5):
        m1 = re.match(r'\s*(%\S+) = OpLoad ' + re.escape(fl) + r' (%\S+)\s*$', L[i])
        m2 = re.match(r'\s*(%\S+) = OpLoad ' + re.escape(v3) + r' (%\S+)\s*$', L[i + 1])
        if not m1 or not m2:
            continue
        m3 = re.match(r'\s*(%\S+) = OpVectorTimesScalar ' + re.escape(v3) + ' ' + re.escape(m2.group(1)) + ' ' + re.escape(m1.group(1)) + r'\s*$', L[i + 2])
        m4 = re.match(r'\s*(%\S+) = OpLoad ' + re.escape(v3) + r' (%\S+)\s*$', L[i + 3])
        m5 = re.match(r'\s*(%\S+) = OpFMul ' + re.escape(v3) + ' ' + re.escape(m4.group(1)) + ' ' + re.escape(m3.group(1)) + r'\s*$', L[i + 4]) if (m3 and m4) else None
        m6 = re.match(r'\s*OpStore ' + re.escape(m4.group(2)) + ' ' + re.escape(m5.group(1)) + r'\s*$', L[i + 5]) if m5 else None
        if not m6:
            continue
        site_line = i + 2
        # the two approximation tests ahead of the site: %a = OpBitwiseAnd %uchar MODE %uchar_64 ; %b = OpINotEqual %bool %a %uchar_0
        tests = []
        for j in range(max(0, site_line - 80), site_line):
            ma = re.match(r'\s*(%\S+) = OpBitwiseAnd ' + re.escape(u8) + r' %\S+ ' + re.escape(c64) + r'\s*$', L[j])
            mb = re.match(r'\s*(%\S+) = OpINotEqual ' + re.escape(bo) + r' (%\S+) ' + re.escape(c0u8) + r'\s*$', L[j + 1]) if ma else None
            if mb and mb.group(2) == ma.group(1):
                tests.append((j + 1, mb.group(1)))
        if not tests:
            continue
        first = min([t[0] for t in tests] + [site_line])
        prior = [g for g in groups if g[0] < first]
        if not prior:
            continue
        sites.append({'site': site_line, 'c': m2.group(1), 'f': m1.group(1), 'tests': tests, 'd1': prior[-1][1], 'gap': first - prior[-1][0]})
    if not sites:
        return done({'water_reflect_sites': 0, 'note': 'no per-hit multiply with approximation tests'})
    if '--show' in sys.argv:
        for s in sites:
            print('site line %d: tests %s, data[1] = %s (%d lines before)' % (s['site'] + 1, [t[0] + 1 for t in s['tests']], s['d1'], s['gap']), file=sys.stderr)

    v2 = tid('OpTypeVector ' + re.escape(fl) + ' 2')
    pf = tid(r'OpTypePointer Uniform ' + re.escape(fl)) or '%pr_pf'
    glob = []
    if not v2:
        v2 = '%pr_v2'
        glob.append(f'{v2} = OpTypeVector {fl} 2')
    if pf == '%pr_pf':
        glob.append(f'%pr_pf = OpTypePointer Uniform {fl}')
    glob += [f'%pr_c8 = OpConstant {i32} {VD_MEMBER}', f'%pr_c4 = OpConstant {i32} {NOISE_MEMBER}',
             f'%pr_thr = OpConstant {fl} {NOISE_ON_ABOVE!r}',
             f'%pr_iorlo = OpConstant {fl} {IOR_LOW!r}', f'%pr_iorhi = OpConstant {fl} {IOR_HIGH!r}',
             f'%pr_f1 = OpConstant {fl} 1', f'%pr_one3 = OpConstantComposite {v3} %pr_f1 %pr_f1 %pr_f1']

    def water_code(tag, d1):
        """Instructions computing %pr_off<tag>: 'the live fix is on and this surface is water', from data[1]."""
        w, h, ior, lo, hi, isw, p, v, fb, off = [f'%pr_{x}{tag}' for x in 'w h ior lo hi isw p v fb off'.split()]
        return [f'{w} = OpCompositeExtract {u32} {d1} 1', f'{h} = OpExtInst {v2} {glsl} UnpackHalf2x16 {w}',
                f'{ior} = OpCompositeExtract {fl} {h} 1',
                f'{lo} = OpFOrdGreaterThan {bo} {ior} %pr_iorlo', f'{hi} = OpFOrdLessThan {bo} {ior} %pr_iorhi',
                f'{isw} = OpLogicalAnd {bo} {lo} {hi}',
                f'{p} = OpAccessChain {pf} {cb} %pr_c8 %pr_c4', f'{v} = OpLoad {fl} {p}',
                f'{fb} = OpFOrdGreaterThan {bo} {v} %pr_thr', f'{off} = OpLogicalAnd {bo} {isw} {fb}'], off

    site_at = {s['site']: (n, s) for n, s in enumerate(sites, 1)}
    test_at = {}
    for n, s in enumerate(sites, 1):
        for k, (j, res) in enumerate(s['tests']):
            test_at[j] = (n, k, res, s['d1'])
    first_fn = next(i for i, l in enumerate(L) if re.match(r'\s*%\S+ = OpFunction ', l))
    out = []
    for i, l in enumerate(L):
        if i == first_fn:
            out += glob
        t = test_at.get(i)
        if t:
            # approx' = approx && !(live && isWater); the first test of a site keeps its original value as %pr_ao<n>
            n, k, res, d1 = t
            code, off = water_code(f'{n}_{k}', d1)
            ao = f'%pr_ao{n}' if k == 0 else f'%pr_ao{n}_{k}'
            ok = f'%pr_ok{n}_{k}'
            out += [l.replace(res + ' = ', ao + ' = ', 1)] + code + [f'{ok} = OpLogicalNot {bo} {off}', f'{res} = OpLogicalAnd {bo} {ao} {ok}']
            continue
        s = site_at.get(i)
        if s:
            n, info = s
            code, off = water_code(f'{n}', info['d1'])
            c, f = info['c'], info['f']
            cv, ce = f'%pr_cv{n}', f'%pr_ce{n}'
            # a water hit that WOULD have been approximated is now a real surface hit: refraction and distance absorption
            # tint it, so the per-hit colour is not applied on top (it would be if the separate-unordered mode were off)
            out += code + [f'{cv} = OpLogicalAnd {bo} {off} %pr_ao{n}', f'{ce} = OpSelect {v3} {cv} %pr_one3 {c}']
            l = re.sub(re.escape(c) + r' ' + re.escape(f) + r'\s*$', ce + ' ' + f, l)
        out.append(l)
    return done({'water_reflect_sites': len(sites), 'approx_tests': sum(len(s['tests']) for s in sites),
                 'max_gap': max(s['gap'] for s in sites)}, out)


if __name__ == '__main__':
    main()
