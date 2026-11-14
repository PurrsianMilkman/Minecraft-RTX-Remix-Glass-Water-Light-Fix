"""Stronger depth effect for thin glass (panes) seen DIRECTLY, in one gbuffer SPIR-V module (disassembly text).

In the primary-ray (gbuffer) shaders the colour of a ray that crosses a translucent medium is
    exp(-sigma * T),   sigma = -ln(transmittance) / measurementDistance,   T = distance travelled in the medium.
A stained glass pane is 2/16 block thick, so with the glass measurement distance of 0.35 a pane shows only
transmittance^(0.125/0.35) = transmittance^0.36 of its colour, while a glass block (1.0 thick) shows ^2.86.
Here, for glass only (measurement distance below GLASS_MAX_DISTANCE), the travelled distance becomes
    max(T, K * measurementDistance)
so a head-on pane absorbs as if it were K * d thick. Anything at least that thick (blocks while K <= 1/d) is untouched,
and the change is continuous (no seam at oblique angles).

K is read live from the same option as the live flag and the glass saturation, ViewDistanceArgs.noiseScale
(rtx.viewDistance.noiseScale, shipped 20): noiseScale = 20 + m / 2^19 with m = 512 + 64 * saturation% + p, p = 0..63,
so p = (m - 512) & 63 and K = p * 0.05, clamped to 0..K_MAX; p = 0 means shipped behaviour. (It was first carried in
ViewDistanceArgs.distanceFadeMin, which the automatic view-distance layer also writes below 32 chunks of render distance,
and then in RaytraceArgs.hairCardRoughnessScale, which stock shaders multiply into the translucent colour scale, so it turned
glass white. noiseScale is read by nothing else.) The patch is also
gated by the live fix flag (noiseScale > 20.0005), exactly like the other patches, so OFF is the shipped shader.

Only modules that contain the OpName "PrimaryAttenuation" (the gbuffer shaders) are touched; the integrate_* shaders
contain the same chain and keep their own, separately patched, behaviour.

Usage: gbuf_patch.py in.dis out.dis
Prints a JSON summary on stdout.
"""
import json
import re
import sys

# DIAGNOSTIC (--miss-probe): in the primary-ray MISS branch (no further hit, the ray is treated as inside an infinite
# medium and the attenuation is black wherever the medium absorbs) a result that would be fully black is drawn
# pink (1,0,1) when that medium is glass-like (measurement distance < 0.5) and green (0,1,0) otherwise (water, fog),
# while the live flag is on. It shows WHICH medium the shader believes a ray that escapes to the sky is still inside.
MISS_PROBE = '--miss-probe' in sys.argv
NOISE_ON_ABOVE = 20.0005
GLASS_MAX_DISTANCE = 0.5     # water (1.0) and fog media are not glass
K_MAX = 2.8                  # keeps a 1.0-thick block unchanged while K * 0.35 <= 1
VD_MEMBER, NOISE_MEMBER = 8, 4


def main():
    src, dst = sys.argv[1], sys.argv[2]
    L = open(src, encoding='utf-8').read().split('\n')

    def done(info):
        print(json.dumps(info))

    if not any(re.match(r'\s*OpName %\S+ "PrimaryAttenuation"', l) for l in L):
        open(dst, 'w', encoding='utf-8').write('\n'.join(L))
        return done({'gbuf_sites': 0, 'note': 'not a gbuffer module'})

    def tid(p):
        for l in L:
            m = re.match(r'\s*(%\S+) = ' + p + r'\s*$', l)
            if m:
                return m.group(1)
        return None

    glsl = next((re.match(r'\s*(%\S+) = OpExtInstImport "GLSL.std.450"', l).group(1)
                 for l in L if re.match(r'\s*%\S+ = OpExtInstImport "GLSL.std.450"', l)), None)
    fl, bo, i32 = tid('OpTypeFloat 32'), tid('OpTypeBool'), tid(r'OpTypeInt 32 1')
    v3 = tid('OpTypeVector ' + re.escape(fl or '%none') + ' 3')
    if not all([glsl, fl, bo, v3, i32]):
        open(dst, 'w', encoding='utf-8').write('\n'.join(L))
        return done({'gbuf_sites': 0, 'note': 'missing types'})

    defs = {}
    for i, l in enumerate(L):
        m = re.match(r'\s*(%\S+) = (Op\w+) (.*)$', l)
        if m:
            defs[m.group(1)] = (i, m.group(2), m.group(3))

    # chain: Log -> FNegate -> FDiv(.., CompositeConstruct d d d) -> FNegate -> VectorTimesScalar(.., T) -> Exp
    sites = []
    for i, l in enumerate(L):
        m = re.match(r'\s*(%\S+) = OpVectorTimesScalar ' + re.escape(v3) + r' (%\S+) (%\S+)\s*$', l)
        if not m or i + 1 >= len(L):
            continue
        res, n2, t_id = m.groups()
        if not re.match(r'\s*%\S+ = OpExtInst ' + re.escape(v3) + ' ' + re.escape(glsl) + ' Exp ' + re.escape(res) + r'\s*$',
                        L[i + 1]):
            continue
        d1 = defs.get(n2)
        if not d1 or d1[1] != 'OpFNegate':
            continue
        dv = defs.get(d1[2].split()[1])
        if not dv or dv[1] != 'OpFDiv':
            continue
        a, b = dv[2].split()[1:3]
        na, bb = defs.get(a), defs.get(b)
        if not na or na[1] != 'OpFNegate' or not bb or bb[1] != 'OpCompositeConstruct':
            continue
        lg = defs.get(na[2].split()[1])
        if not lg or 'Log' not in lg[2]:
            continue
        parts = bb[2].split()
        if len(parts) != 4 or not (parts[1] == parts[2] == parts[3]):
            continue
        sites.append({'line': i, 'T': t_id, 'dist': parts[1]})

    miss_sites = []
    if MISS_PROBE:
        for i, l in enumerate(L):
            m = re.match(r'\s*(%\S+) = OpExtInst ' + re.escape(v3) + ' ' + re.escape(glsl) + ' FMix ', l)
            if not m or i + 1 >= len(L):
                continue
            if not re.match(r'\s*OpStore %\S+ ' + re.escape(m.group(1)) + r'\s*$', L[i + 1]):
                continue
            back = L[max(0, i - 10):i]
            div = next((x for x in back if re.search(r'= OpFDiv ' + re.escape(v3), x)), None)
            ccon = next((x for x in back if re.search(r'= OpCompositeConstruct ' + re.escape(v3), x)), None)
            if not div or not ccon or not any('OpFOrdEqual' in x for x in back):
                continue
            parts = ccon.split()
            # %id = OpCompositeConstruct %type %d %d %d
            d_id = parts[4]
            miss_sites.append({'store': i + 1, 'res': m.group(1), 'dist': d_id})

    if not sites and not miss_sites:
        open(dst, 'w', encoding='utf-8').write('\n'.join(L))
        return done({'gbuf_sites': 0, 'note': 'no attenuation site'})

    st = next((l for l in L if re.match(r'\s*%RaytraceArgs_natural = OpTypeStruct ', l)), None)
    cb_ptr = '%_ptr_Uniform_RaytraceArgs_natural'
    cb = next((re.match(r'\s*(%\S+) = OpVariable ' + re.escape(cb_ptr) + r' Uniform', l).group(1)
               for l in L if re.match(r'\s*%\S+ = OpVariable ' + re.escape(cb_ptr) + r' Uniform', l)), None)
    if not st or not cb or st.split()[3 + VD_MEMBER] != '%ViewDistanceArgs_natural':
        open(dst, 'w', encoding='utf-8').write('\n'.join(L))
        return done({'gbuf_sites': 0, 'note': 'no RaytraceArgs.viewDistanceArgs'})

    pf = tid(r'OpTypePointer Uniform ' + re.escape(fl)) or '%pg_pf'
    glob = []
    if pf == '%pg_pf':
        glob.append(f'%pg_pf = OpTypePointer Uniform {fl}')
    glob += [f'%pg_c8 = OpConstant {i32} {VD_MEMBER}', f'%pg_c4 = OpConstant {i32} {NOISE_MEMBER}',
             f'%pg_i512 = OpConstant {i32} 512', f'%pg_i6 = OpConstant {i32} 6', f'%pg_i63 = OpConstant {i32} 63',
             f'%pg_c20 = OpConstant {fl} 20.0', f'%pg_2p19 = OpConstant {fl} 524288.0', f'%pg_k05 = OpConstant {fl} 0.05',
             f'%pg_thr = OpConstant {fl} {NOISE_ON_ABOVE!r}', f'%pg_glass = OpConstant {fl} {GLASS_MAX_DISTANCE!r}',
                          f'%pg_k0 = OpConstant {fl} 0', f'%pg_kmax = OpConstant {fl} {K_MAX!r}']
    if miss_sites:
        glob += [f'%pg_one = OpConstant {fl} 1', f'%pg_pink = OpConstantComposite {v3} %pg_one %pg_k0 %pg_one',
                 f'%pg_green = OpConstantComposite {v3} %pg_k0 %pg_one %pg_k0']

    by_line = {s['line']: s for s in sites}
    miss_by_line = {s['store']: s for s in miss_sites}
    first_fn = next(i for i, l in enumerate(L) if re.match(r'\s*%\S+ = OpFunction ', l))
    out = []
    n = 0
    for i, l in enumerate(L):
        if i == first_fn:
            out += glob
        ms = miss_by_line.get(i)
        if ms:
            k = len(miss_by_line) and i
            p, v, fb, dd, blk, g, col, pr, outv = [f'%pg_m{x}_{i}' for x in 'p v fb dd blk g col pr out'.split()]
            out += [f'{p} = OpAccessChain {pf} {cb} %pg_c8 %pg_c4', f'{v} = OpLoad {fl} {p}',
                    f'{fb} = OpFOrdGreaterThan {bo} {v} %pg_thr',
                    f'{dd} = OpDot {fl} {ms["res"]} {ms["res"]}', f'{blk} = OpFOrdEqual {bo} {dd} %pg_k0',
                    f'{g} = OpFOrdLessThan {bo} {ms["dist"]} %pg_glass',
                    f'{col} = OpSelect {v3} {g} %pg_pink %pg_green', f'{pr} = OpLogicalAnd {bo} {fb} {blk}',
                    f'{outv} = OpSelect {v3} {pr} {col} {ms["res"]}']
            l = re.sub(re.escape(ms['res']) + r'\s*$', outv, l)
        s = by_line.get(i)
        if s:
            n += 1
            p, v, fb, q, w, kr, k, dk, mx, g, ok, te = [f'%pg_{x}{n}' for x in
                                                            'p v fb q w kr k dk mx g ok te'.split()]
            out += [f'{p} = OpAccessChain {pf} {cb} %pg_c8 %pg_c4', f'{v} = OpLoad {fl} {p}',
                    f'{fb} = OpFOrdGreaterThan {bo} {v} %pg_thr',
                    f'{w} = OpFSub {fl} {v} %pg_c20', f'{q} = OpFMul {fl} {w} %pg_2p19', f'{q}i = OpConvertFToS {i32} {q}',
                    f'{q}j = OpISub {i32} {q}i %pg_i512', f'{q}k = OpBitwiseAnd {i32} {q}j %pg_i63',
                    f'{q}f = OpConvertSToF {fl} {q}k', f'{kr} = OpFMul {fl} {q}f %pg_k05',
                    f'{k} = OpExtInst {fl} {glsl} FClamp {kr} %pg_k0 %pg_kmax',
                    f'{dk} = OpFMul {fl} {s["dist"]} {k}',
                    f'{mx} = OpExtInst {fl} {glsl} FMax {s["T"]} {dk}',
                    f'{g} = OpFOrdLessThan {bo} {s["dist"]} %pg_glass', f'{ok} = OpLogicalAnd {bo} {fb} {g}',
                    f'{te} = OpSelect {fl} {ok} {mx} {s["T"]}']
            l = re.sub(re.escape(s['T']) + r'\s*$', te, l)
        out.append(l)
    open(dst, 'w', encoding='utf-8').write('\n'.join(out))
    return done({'gbuf_sites': n, 'miss_sites': len(miss_sites)})


if __name__ == '__main__':
    main()
