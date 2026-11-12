"""Remove the second, over-refracted set of shadows on subsurface (SSS) materials seen through water, glass or in a mirror.

Remix lights a material with a subsurface diffusion profile (in Minecraft with the RTX Remix Materials pack: sand, red sand,
sandstone, snow, end stone, glowstone, ...) by picking points on the surface around the shaded point and lighting each of
them (evalSssDiffusionProfile in rtx/algorithm/rtxcr/rtxcr_material.slangh, inlined into integrate_direct). With RTXDI on,
each point borrows its light sample from the RTXDI reservoir of "its" screen pixel, found by projecting the point's REAL
world position with the camera matrix:

    samplePixelCoordinate = cameraNDCToPixelCoordinate(camera, project(sssPoint));
    sampleInsideScreen    = projPos.w > 0 && ndc inside [-1, 1];
    if (cb.enableRtxdi && geometryFlags.primarySelectedIntegrationSurface && sampleInsideScreen)
        sampleLightRTXDI(samplePixelCoordinate, ...);      // reservoir of that pixel
    else
        sampleLightRIS(...);                               // own light selection

When the surface is seen through primary surface replacement (PSTR: through water or glass; PSRR: in a mirror-like
reflection), the pixel the real position projects to is NOT the pixel that shows the surface: refraction moved the image.
That pixel's reservoir belongs to another spot of the floor, so the subsurface light follows that spot's shadows: a second,
lighter set of shadows, shifted once more by the refraction (seen from above water: "the shadows refract twice as much").
Stock Remix only falls back to RIS when the point projects off screen (its comment mentions the PSR mirror case).

This patch also falls back to RIS for pixels where any PSR happened (GeometryFlags.performPSTR | performPSRR, bits 7 and 8
of the flags word whose bit 0 is primarySelectedIntegrationSurface):
    sampleInsideScreen' = sampleInsideScreen && !(live_fix_on && (flags & 0x180) != 0)
Gated by the same live flag as the others (ViewDistanceArgs.noiseScale > 20.0005), so OFF is the shipped shader.

Usage: sss_psr_patch.py in.dis out.dis  (prints a JSON summary; only modules that bind sssTLAS are touched).
"""
import json
import re
import sys

VD_MEMBER, NOISE_MEMBER, NOISE_ON_ABOVE = 8, 4, 20.0005
PSR_BITS = (1 << 7) | (1 << 8)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    L = open(src, encoding='utf-8').read().split('\n')

    def done(info, lines=None):
        open(dst, 'w', encoding='utf-8').write('\n'.join(lines if lines is not None else L))
        print(json.dumps(info))

    if not any('OpName %sssTLAS "sssTLAS"' in l for l in L):
        return done({'sss_psr_sites': 0, 'note': 'no sssTLAS'})

    m_rtxdi = next((re.match(r'\s*OpMemberName %RaytraceArgs_natural (\d+) "enableRtxdi"', l).group(1)
                    for l in L if re.match(r'\s*OpMemberName %RaytraceArgs_natural \d+ "enableRtxdi"', l)), None)

    def tid(p):
        for l in L:
            m = re.match(r'\s*(%\S+) = ' + p + r'\s*$', l)
            if m:
                return m.group(1)
        return None

    fl, bo, i32, u32 = tid('OpTypeFloat 32'), tid('OpTypeBool'), tid(r'OpTypeInt 32 1'), tid(r'OpTypeInt 32 0')
    cb = next((re.match(r'\s*(%\S+) = OpVariable %_ptr_Uniform_RaytraceArgs_natural Uniform', l).group(1)
               for l in L if re.match(r'\s*%\S+ = OpVariable %_ptr_Uniform_RaytraceArgs_natural Uniform', l)), None)
    st = next((l for l in L if re.match(r'\s*%RaytraceArgs_natural = OpTypeStruct ', l)), None)
    if not all([m_rtxdi, fl, bo, i32, u32, cb, st]) or st.split()[3 + VD_MEMBER] != '%ViewDistanceArgs_natural':
        return done({'sss_psr_sites': 0, 'note': 'missing types / enableRtxdi / viewDistanceArgs'})

    defs = {}
    for i, l in enumerate(L):
        m = re.match(r'\s*(%\S+) = (Op\w+) (.*)$', l)
        if m:
            defs[m.group(1)] = (i, m.group(2), m.group(3))

    # bool Function variables that hold an "inside the screen" test: OpStore %S %X with %X = OpAll %bool ...
    inside_vars = set()
    for l in L:
        m = re.match(r'\s*OpStore (%\S+) (%\S+)\s*$', l)
        if m and defs.get(m.group(2), (0, '', ''))[1] == 'OpAll':
            inside_vars.add(m.group(1))

    sites = []
    for i, l in enumerate(L):
        m = re.match(r'\s*(%\S+) = OpAccessChain %\S+ ' + re.escape(cb) + r' (%\S+)\s*$', l)
        if not m:
            continue
        c = defs.get(m.group(2))
        if not c or c[1] != 'OpConstant' or c[2].split()[1] != m_rtxdi:
            continue
        # within the enableRtxdi && primarySelectedIntegrationSurface test: %a = OpUConvert %uint %F ; Bitcast ; BitwiseAnd 1
        flags = None
        for j in range(i + 1, min(i + 16, len(L))):
            mu = re.match(r'\s*(%\S+) = OpUConvert ' + re.escape(u32) + r' (%\S+)\s*$', L[j])
            if mu and j + 2 < len(L) and re.match(r'\s*%\S+ = OpBitcast ' + re.escape(i32) + ' ' + re.escape(mu.group(1)) + r'\s*$', L[j + 1]) \
                    and re.match(r'\s*%\S+ = OpBitwiseAnd ' + re.escape(i32) + r' %\S+ %int_1\s*$', L[j + 2]):
                flags = mu.group(2)
                break
        if not flags:
            continue
        # then: %Z = OpLoad %bool %S with %S an inside-screen variable
        for j in range(i + 1, min(i + 32, len(L))):
            ml = re.match(r'\s*(%\S+) = OpLoad ' + re.escape(bo) + r' (%\S+)\s*$', L[j])
            if ml and ml.group(2) in inside_vars:
                sites.append((j, ml.group(1), ml.group(2), flags))
                break
    if not sites:
        return done({'sss_psr_sites': 0, 'note': 'no RTXDI/inside-screen test'})

    pf = tid(r'OpTypePointer Uniform ' + re.escape(fl)) or '%sp_pf'
    glob = []
    if pf == '%sp_pf':
        glob.append(f'%sp_pf = OpTypePointer Uniform {fl}')
    glob += [f'%sp_c8 = OpConstant {i32} {VD_MEMBER}', f'%sp_c4 = OpConstant {i32} {NOISE_MEMBER}',
             f'%sp_thr = OpConstant {fl} {NOISE_ON_ABOVE!r}',
             f'%sp_bits = OpConstant {u32} {PSR_BITS}', f'%sp_u0 = OpConstant {u32} 0']

    by_line = {j: (n, res, var, flags) for n, (j, res, var, flags) in enumerate(sites, 1)}
    first_fn = next(i for i, l in enumerate(L) if re.match(r'\s*%\S+ = OpFunction ', l))
    out = []
    for i, l in enumerate(L):
        if i == first_fn:
            out += glob
        s = by_line.get(i)
        if s:
            n, res, var, flags = s
            ld, fu, fm, psr, p, v, fb, off, ok = [f'%sp_{x}{n}' for x in 'ld fu fm psr p v fb off ok'.split()]
            out += [f'{ld} = OpLoad {bo} {var}',
                    f'{fu} = OpUConvert {u32} {flags}', f'{fm} = OpBitwiseAnd {u32} {fu} %sp_bits',
                    f'{psr} = OpINotEqual {bo} {fm} %sp_u0',
                    f'{p} = OpAccessChain {pf} {cb} %sp_c8 %sp_c4', f'{v} = OpLoad {fl} {p}',
                    f'{fb} = OpFOrdGreaterThan {bo} {v} %sp_thr',
                    f'{off} = OpLogicalAnd {bo} {fb} {psr}', f'{ok} = OpLogicalNot {bo} {off}',
                    f'{res} = OpLogicalAnd {bo} {ld} {ok}']
            continue
        out.append(l)
    return done({'sss_psr_sites': len(by_line)}, out)


if __name__ == '__main__':
    main()
