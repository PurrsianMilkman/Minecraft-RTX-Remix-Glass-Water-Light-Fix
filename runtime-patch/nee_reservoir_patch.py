"""Emissive light that the first-bounce NEE cache hands to ReSTIR GI keeps the tint of the glass and water it crossed.

integrate_nee (the ReSTIR GI variant) takes a light sample from the NEE cache, traces ONE visibility ray to it (evalNEESecondary) and
multiplies the directly accumulated light by lightSampleThroughput * visibility.attenuation, so the glass or water between the surface
and the lamp tints it. The same sample is also written into the ReSTIR GI reservoir (when the ray was not blocked by an opaque surface)
as lightSample.radiance / lightSample.solidAnglePdf, the RAW emissive radiance, and ReSTIR GI's final shading applies that radiance with a
visibility test that cannot see glass or water (its ray mask has no translucent bit). That second route therefore delivered the lamp's
light white through coloured glass and untinted through water.

Patch: the reservoir radiance is built from lightSample.radiance * visibility.attenuation instead (live-gated: with the live flag off it is
the shipped value). The attenuation vector is the one the shader itself multiplies into diffuseLight / specularLight, found structurally:
    %q = OpVectorTimesScalar %v3float %ATT %s ; %r = OpFMul %v3float (OpLoad diffuseLight) %q ; OpStore %diffuseLight %r
and the reservoir site is  %d = OpFDiv %v3float %RAD (OpCompositeConstruct %v3float %pdf %pdf %pdf) ; OpExtInst FMin %d <float16 max>.
Only modules that contain both patterns exactly once are touched (the ReSTIR GI variant of integrate_nee).

Usage: nee_reservoir_patch.py in.dis out.dis  (prints a JSON summary)
"""
import json
import re
import sys

VD_MEMBER, NOISE_MEMBER, NOISE_ON_ABOVE = 8, 4, 20.0005


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

    if not any('OpName %diffuseLight "diffuseLight"' in l for l in L) or not any('RestirGIReservoirBuffer' in l for l in L):
        return done({'nee_reservoir_sites': 0, 'note': 'not the ReSTIR GI variant of integrate_nee'})
    fl, bo, i32 = tid('OpTypeFloat 32'), tid('OpTypeBool'), tid(r'OpTypeInt 32 1')
    v3 = tid('OpTypeVector ' + re.escape(fl or '%none') + ' 3')
    cb = next((re.match(r'\s*(%\S+) = OpVariable %_ptr_Uniform_RaytraceArgs_natural Uniform', l).group(1)
               for l in L if re.match(r'\s*%\S+ = OpVariable %_ptr_Uniform_RaytraceArgs_natural Uniform', l)), None)
    st = next((l for l in L if re.match(r'\s*%RaytraceArgs_natural = OpTypeStruct ', l)), None)
    if not all([fl, bo, i32, v3, cb, st]) or st.split()[3 + VD_MEMBER] != '%ViewDistanceArgs_natural':
        return done({'nee_reservoir_sites': 0, 'note': 'missing types / viewDistanceArgs'})
    f16max = tid('OpConstant ' + re.escape(fl) + ' 65504')
    vmaxes = set()   # the module may hold several identical (float16 max x 3) constants
    for l in L:
        m = re.match(r'\s*(%\S+) = OpConstantComposite ' + re.escape(v3) + ' ' + re.escape(f16max or '%none') + ' ' + re.escape(f16max or '%none') + ' ' + re.escape(f16max or '%none') + r'\s*$', l)
        if m:
            vmaxes.add(m.group(1))
    vmax = bool(vmaxes)
    glsl = next((re.match(r'\s*(%\S+) = OpExtInstImport "GLSL.std.450"', l).group(1)
                 for l in L if re.match(r'\s*%\S+ = OpExtInstImport "GLSL.std.450"', l)), None)
    if not (vmax and glsl):
        return done({'nee_reservoir_sites': 0, 'note': 'no float16-max vector'})

    defs = {}
    for i, l in enumerate(L):
        m = re.match(r'\s*(%\S+) = (Op\w+) (.*)$', l)
        if m:
            defs[m.group(1)] = (i, m.group(2), m.group(3))

    # 1. the attenuation vector: OpStore %diffuseLight %r with %r = FMul (Load %diffuseLight) %q, %q = VectorTimesScalar %ATT %s
    atts = set()
    for l in L:
        m = re.match(r'\s*OpStore %diffuseLight (%\S+)\s*$', l)
        if not m or m.group(1) not in defs or defs[m.group(1)][1] != 'OpFMul':
            continue
        ops = defs[m.group(1)][2].split()          # [type, a, b]
        for a, b in ((ops[1], ops[2]), (ops[2], ops[1])):
            if a in defs and defs[a][1] == 'OpLoad' and defs[a][2].split()[-1] == '%diffuseLight' and b in defs and defs[b][1] == 'OpVectorTimesScalar':
                atts.add(defs[b][2].split()[1])
    if len(atts) != 1:
        return done({'nee_reservoir_sites': 0, 'note': 'attenuation vector not unique: %r' % sorted(atts)})
    att = atts.pop()

    # 2. the reservoir radiance: %d = FDiv %RAD %c ; %c = CompositeConstruct %pdf %pdf %pdf ; %e = ExtInst FMin %d %vmax
    sites = []
    for i, l in enumerate(L):
        m = re.match(r'\s*(%\S+) = OpExtInst ' + re.escape(v3) + ' ' + re.escape(glsl) + r' FMin (%\S+) (%\S+)\s*$', l)
        if not m or m.group(3) not in vmaxes:
            continue
        d = m.group(2)
        if d not in defs or defs[d][1] != 'OpFDiv':
            continue
        ops = defs[d][2].split()                    # [type, rad, c]
        c = ops[2]
        if c in defs and defs[c][1] == 'OpCompositeConstruct' and len(set(defs[c][2].split()[1:])) == 1 and defs[d][0] == i - 1:
            sites.append((defs[d][0], d, ops[1], c))
    if len(sites) != 1:
        return done({'nee_reservoir_sites': 0, 'note': 'reservoir site not unique: %d' % len(sites)})
    line, d, rad, c = sites[0]
    if defs[att][0] > line:
        return done({'nee_reservoir_sites': 0, 'note': 'attenuation defined after the reservoir site'})

    pf = tid(r'OpTypePointer Uniform ' + re.escape(fl)) or '%nr_pf'
    glob = []
    if pf == '%nr_pf':
        glob.append(f'%nr_pf = OpTypePointer Uniform {fl}')
    glob += [f'%nr_c8 = OpConstant {i32} {VD_MEMBER}', f'%nr_c4 = OpConstant {i32} {NOISE_MEMBER}',
             f'%nr_thr = OpConstant {fl} {NOISE_ON_ABOVE!r}', f'%nr_f1 = OpConstant {fl} 1',
             f'%nr_one3 = OpConstantComposite {v3} %nr_f1 %nr_f1 %nr_f1']
    first_fn = next(i for i, l in enumerate(L) if re.match(r'\s*%\S+ = OpFunction ', l))
    out = []
    for i, l in enumerate(L):
        if i == first_fn:
            out += glob
        if i == line:
            out += ['%nr_p = OpAccessChain ' + pf + ' ' + cb + ' %nr_c8 %nr_c4', f'%nr_v = OpLoad {fl} %nr_p',
                    f'%nr_on = OpFOrdGreaterThan {bo} %nr_v %nr_thr', f'%nr_a = OpSelect {v3} %nr_on {att} %nr_one3',
                    f'%nr_rad = OpFMul {v3} {rad} %nr_a']
            l = l.replace(rad + ' ' + c, '%nr_rad ' + c)
            assert '%nr_rad' in l, l
        out.append(l)
    return done({'nee_reservoir_sites': 1, 'attenuation': att}, out)


if __name__ == '__main__':
    main()
