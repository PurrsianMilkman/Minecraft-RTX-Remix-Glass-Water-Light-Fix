"""Let the reflection of a see-through surface survive when another see-through surface (glass, water) is in front of it.

In the primary-ray (gbuffer) shaders every see-through interface is handled by primary surface transmission replacement
(PSTR): the ray is followed through the surface and the surface behind it becomes the visible one. For an interface the
ray ENTERS the shader has an approximation, RaytraceArgs.enablePSTRSecondaryIncidentSplitApproximation (option
rtx.enablePSTRSecondaryIncidentSplitApproximation): with it on the interface is crossed as a pure transmission and its
reflection is dropped. Stock Remix therefore hides the reflection of a water surface seen through glass, through water, or
through any stack of them; turning the option off brings it back.

This patch keeps the option as shipped for the FIRST interface the ray meets (the glass or water that is in front of
everything) and for every later interface that is not a roughly horizontal surface (walls and panes), and turns the
approximation off for a later interface whose normal points UP (the top face of a water surface or glass roof, seen from above), so that surface is shaded as a visible
surface and shows its own reflection:
    approximation = shipped_flag && !(live_fix_on && interface_count > 1 && normal.y > 0.7)
interface_count is the shader's own per-ray counter of replaced interfaces (the variable compared with
RaytraceArgs.pstrMaxBounces); normal is the interface's surface normal that the same code feeds to Refract. Ending the
replacement at a wall or pane that still has more see-through layers behind it loses the reflection of those layers and
renders the wall with the bluer non-replacement water path, so only up-facing interfaces end it. (Looking UP through glass at water above, the
ray enters the water through its bottom face, normal pointing down: that must stay as shipped, otherwise the water looks too blue.)
The patch is gated by the same live flag as the others (ViewDistanceArgs.noiseScale > 20.0005), so OFF is the shipped shader.

(Version 1 tested a "measurement distance" to single out water; the value it read was not that distance. Version 2 ended the
replacement at every later interface, which fixed one glass or one water layer but not stacks.)

Only modules that read that option are touched. Usage: psr_water_patch.py in.dis out.dis  (prints a JSON summary).
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

    def member(name):
        for l in L:
            m = re.match(r'\s*OpMemberName %RaytraceArgs_natural (\d+) "' + name + '"', l)
            if m:
                return m.group(1)
        return None

    m_sec, m_pstr = member('enablePSTRSecondaryIncidentSplitApproximation'), member('pstrMaxBounces')
    if m_sec is None or m_pstr is None:
        return done({'psr_water_sites': 0, 'note': 'option not present'})

    def tid(p):
        for l in L:
            m = re.match(r'\s*(%\S+) = ' + p + r'\s*$', l)
            if m:
                return m.group(1)
        return None

    fl, bo, i32, u8 = tid('OpTypeFloat 32'), tid('OpTypeBool'), tid(r'OpTypeInt 32 1'), tid(r'OpTypeInt 8 0')
    glsl = next((re.match(r'\s*(%\S+) = OpExtInstImport "GLSL.std.450"', l).group(1)
                 for l in L if re.match(r'\s*%\S+ = OpExtInstImport "GLSL.std.450"', l)), None)
    v3 = tid('OpTypeVector ' + re.escape(fl or '%none') + ' 3')
    cb = next((re.match(r'\s*(%\S+) = OpVariable %_ptr_Uniform_RaytraceArgs_natural Uniform', l).group(1)
               for l in L if re.match(r'\s*%\S+ = OpVariable %_ptr_Uniform_RaytraceArgs_natural Uniform', l)), None)
    st = next((l for l in L if re.match(r'\s*%RaytraceArgs_natural = OpTypeStruct ', l)), None)
    one = tid('OpConstant ' + re.escape(u8 or '%none') + ' 1')
    if not all([fl, bo, i32, u8, cb, st, one, glsl, v3]) or st.split()[3 + VD_MEMBER] != '%ViewDistanceArgs_natural':
        return done({'psr_water_sites': 0, 'note': 'missing types / constants / viewDistanceArgs'})

    defs = {}
    for i, l in enumerate(L):
        m = re.match(r'\s*(%\S+) = (Op\w+) (.*)$', l)
        if m:
            defs[m.group(1)] = (i, m.group(2), m.group(3))

    # the interface counter: the Function variable that is loaded right before the pstrMaxBounces comparison
    counters = set()
    for i, l in enumerate(L):
        m = re.match(r'\s*(%\S+) = OpLoad ' + re.escape(u8) + r' (%\S+)\s*$', l)
        if m and any(re.match(r'\s*%\S+ = OpAccessChain %\S+ ' + re.escape(cb) + r' (%\S+)\s*$', L[j])
                     and defs.get(re.match(r'.* (%\S+)\s*$', L[j]).group(1), (0, '', ''))[1] == 'OpConstant'
                     and defs[re.match(r'.* (%\S+)\s*$', L[j]).group(1)][2].split()[1] == m_pstr
                     for j in range(i + 1, min(i + 4, len(L)))):
            counters.add(m.group(2))
    if len(counters) != 1:
        return done({'psr_water_sites': 0, 'note': 'interface counter not unique: %r' % sorted(counters)})
    counter = counters.pop()

    # the interface normal: the value that is normalised and handed to Refract (loaded once at the top of each interface)
    normals = set()
    for l in L:
        m = re.match(r'\s*%\S+ = OpExtInst ' + re.escape(v3) + ' ' + re.escape(glsl) + r' Refract (%\S+) (%\S+) (%\S+)\s*$', l)
        if m:
            nd = defs.get(m.group(2))
            mm = re.match(r'OpExtInst ' + re.escape(v3) + ' ' + re.escape(glsl) + r' Normalize (%\S+)\s*$', ' '.join(['OpExtInst', nd[2]])) if nd and nd[1] == 'OpExtInst' else None
            if mm and defs.get(mm.group(1), (0, '', ''))[1] == 'OpLoad':
                normals.add(mm.group(1))
    if len(normals) != 1:
        return done({'psr_water_sites': 0, 'note': 'interface normal not unique: %r' % sorted(normals)})
    normal = normals.pop()

    # sites: %A = OpAccessChain %ptr %cb %int_<m_sec> ; %B = OpLoad %uint %A ; %C = OpINotEqual %bool %B %uint_0
    sites = []
    for i, l in enumerate(L):
        m = re.match(r'\s*(%\S+) = OpAccessChain %\S+ ' + re.escape(cb) + r' (%\S+)\s*$', l)
        if not m:
            continue
        c = defs.get(m.group(2))
        if not c or c[1] != 'OpConstant' or c[2].split()[1] != m_sec:
            continue
        a = m.group(1)
        for j in range(i + 1, min(i + 6, len(L))):
            m2 = re.match(r'\s*(%\S+) = OpINotEqual ' + re.escape(bo) + r' (%\S+) (%\S+)\s*$', L[j])
            if m2 and defs.get(m2.group(2), (0, '', ''))[1] == 'OpLoad' and (a in defs[m2.group(2)][2]):
                sites.append((j, m2.group(1), m2.group(2), m2.group(3)))
                break
    if not sites:
        return done({'psr_water_sites': 0, 'note': 'no read of the option'})

    pf = tid(r'OpTypePointer Uniform ' + re.escape(fl)) or '%pw_pf'
    glob = []
    if pf == '%pw_pf':
        glob.append(f'%pw_pf = OpTypePointer Uniform {fl}')
    glob += [f'%pw_c8 = OpConstant {i32} {VD_MEMBER}', f'%pw_c4 = OpConstant {i32} {NOISE_MEMBER}',
             f'%pw_thr = OpConstant {fl} {NOISE_ON_ABOVE!r}', f'%pw_up = OpConstant {fl} 0.7']

    # Version 5: when the rule ends the replacement, also undo the "entered a medium" bookkeeping of that same interface.
    # Right after the continuation decision the resolver records the medium it just entered (state flag bit 1 = inside medium,
    # mediumMaterialIndex = this surface's material) whether or not the ray continues. Ending the replacement at the water top
    # therefore left the pixel marked as already INSIDE the water, and the water top was shaded as if seen from underneath
    # (total internal reflection of the sky: the royal blue top of water under glass). Pattern of that bookkeeping:
    #     %a = OpLogicalNot %bool %OLD ; OpSelectionMerge ; OpBranchConditional %a %t %f ;
    #     %f = OpLabel ; OpStore %V %false ; OpBranch ; %t = OpLabel ; %x = OpLoad %ushort FLAGS ; %y = OpUConvert %uint %x ;
    #     %z = OpBitwiseAnd %uint %y %uint_2 ...
    # Just before it the state flag is put back to OLD when the rule fired in this iteration.
    ush, u32 = tid(r'OpTypeInt 16 0'), tid(r'OpTypeInt 32 0')
    pbool = tid(r'OpTypePointer Function ' + re.escape(bo))
    cfalse = next(
        (re.match(r'\s*(%\S+) = OpConstantFalse ' + re.escape(bo) + r'\s*$', l).group(1) for l in L
         if re.match(r'\s*%\S+ = OpConstantFalse ' + re.escape(bo) + r'\s*$', l)), None)
    restore = {}   # line index of the "%a = OpLogicalNot %OLD" -> (site number, OLD, FLAGS var)
    if ush and u32 and pbool and cfalse:
        for n, (j, res, b, zero) in enumerate(sites, 1):
            for k in range(j + 1, len(L) - 9):
                ma = re.match(r'\s*(%\S+) = OpLogicalNot ' + re.escape(bo) + r' (%\S+)\s*$', L[k])
                if not ma:
                    continue
                w = [x for x in L[k + 1:k + 60] if not x.startswith('OpLine') and not x.startswith('OpNoLine')][:14]
                if (len(w) >= 11 and w[0].startswith('OpSelectionMerge') and w[1].startswith('OpBranchConditional ' + ma.group(1))
                        and re.match(r'%\S+ = OpLabel', w[2]) and re.match(r'OpStore %\S+ ' + re.escape(cfalse), w[3])
                        and w[4].startswith('OpBranch') and re.match(r'%\S+ = OpLabel', w[5])):
                    ml = re.match(r'\s*%\S+ = OpLoad ' + re.escape(ush) + r' (%\S+)\s*$', w[6])
                    mu = re.match(r'\s*%\S+ = OpUConvert ' + re.escape(u32) + r' %\S+\s*$', w[7])
                    mb = re.match(r'\s*%\S+ = OpBitwiseAnd ' + re.escape(u32) + r' %\S+ (%\S+)\s*$', w[8])
                    if ml and mu and mb and defs.get(mb.group(1), (0, '', ''))[2].split()[-1:] == ['2']:
                        restore[k] = (n, ma.group(2), ml.group(1))
                        break
    if len(restore) != len(sites):
        restore = {}   # all or nothing: never leave a half-applied rule

    glob2 = []
    if restore:
        glob2 = [f'%pw_u2 = OpConstant {u32} 2', f'%pw_uc = OpConstant {u32} 4294967293', f'%pw_u0 = OpConstant {u32} 0']
    fired_var = '%pw_fired'

    by_line = {j: (n, res, b, zero) for n, (j, res, b, zero) in enumerate(sites, 1)}
    first_fn = next(i for i, l in enumerate(L) if re.match(r'\s*%\S+ = OpFunction ', l))
    # the Function variable that remembers "the rule fired in this iteration" goes after the entry block's OpVariables
    entry_end = None
    if restore:
        i = first_fn + 1
        while i < len(L) and not re.match(r'\s*%\S+ = OpLabel', L[i]):
            i += 1
        i += 1
        while i < len(L) and re.match(r'\s*%\S+ = OpVariable ', L[i]):
            i += 1
        entry_end = i
    out = []
    for i, l in enumerate(L):
        if i == first_fn:
            out += glob + glob2
        if i == entry_end:
            out += [f'{fired_var} = OpVariable {pbool} Function', f'OpStore {fired_var} {cfalse}']
        r = restore.get(i)
        if r:
            n, old, flags = r
            fl0, fu, cl, ob, rs, fd, sl, nw = [f'%pw_r{x}{n}' for x in 'fl fu cl ob rs fd sl nw'.split()]
            out += [f'{fd} = OpLoad {bo} {fired_var}',
                    f'{fl0} = OpLoad {ush} {flags}', f'{fu} = OpUConvert {u32} {fl0}',
                    f'{cl} = OpBitwiseAnd {u32} {fu} %pw_uc', f'{ob} = OpSelect {u32} {old} %pw_u2 %pw_u0',
                    f'{rs} = OpBitwiseOr {u32} {cl} {ob}', f'{sl} = OpSelect {u32} {fd} {rs} {fu}',
                    f'{nw} = OpUConvert {ush} {sl}', f'OpStore {flags} {nw}']
        s = by_line.get(i)
        if s:
            n, res, b, zero = s
            c0, p, v, fb, cn, later, off, ok, nn, ny, hz, lh = [f'%pw_{x}{n}' for x in 'c0 p v fb cn later off ok nn ny hz lh'.split()]
            out += [f'{c0} = OpINotEqual {bo} {b} {zero}',
                    f'{p} = OpAccessChain {pf} {cb} %pw_c8 %pw_c4', f'{v} = OpLoad {fl} {p}',
                    f'{fb} = OpFOrdGreaterThan {bo} {v} %pw_thr',
                    f'{cn} = OpLoad {u8} {counter}',
                    f'{later} = OpUGreaterThan {bo} {cn} {one}',
                    f'{nn} = OpExtInst {v3} {glsl} Normalize {normal}', f'{ny} = OpCompositeExtract {fl} {nn} 1',
                    f'{hz} = OpFOrdGreaterThan {bo} {ny} %pw_up',
                    f'{lh} = OpLogicalAnd {bo} {later} {hz}',
                    f'{off} = OpLogicalAnd {bo} {fb} {lh}', f'{ok} = OpLogicalNot {bo} {off}',
                    f'{res} = OpLogicalAnd {bo} {c0} {ok}']
            if restore:
                out.append(f'OpStore {fired_var} {off}')
            continue
        out.append(l)
    return done({'psr_water_sites': len(by_line), 'psr_medium_restores': len(restore)}, out)


if __name__ == '__main__':
    main()
