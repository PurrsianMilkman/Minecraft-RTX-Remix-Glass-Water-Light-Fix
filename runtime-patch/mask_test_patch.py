"""DIAGNOSTIC: make the main bounce ray query of an indirect raygen module see every instance (cull mask 0xFF).

Hypothesis under test: bounce rays traced with a mask that excludes glass pass through it untinted.
Only modules that have the 'unordered' second query (ray flags = %uint_64, CullOpaque) are touched, and only the
first OpRayQueryInitializeKHR before it, which is the main bounce trace.

Usage: mask_test_patch.py in.dis out.dis
"""
import json
import re
import sys


def main():
    src, dst = sys.argv[1], sys.argv[2]
    lines = open(src, encoding='utf-8').read().split('\n')
    flag_idx = next((m.group(1) for l in lines for m in [re.match(
        r'\s*OpMemberName %RaytraceArgs_natural (\d+) "enableTransmissionApproximationInIndirectRays"', l)] if m), None)
    if flag_idx is None or not any(re.search(r'OpAccessChain \S+ %cb %int_' + flag_idx + r'\s*$', l) for l in lines):
        open(dst, 'w', encoding='utf-8').write('\n'.join(lines))
        print(json.dumps({'mask_sites': 0}))
        return
    inits = [(i, l.split()) for i, l in enumerate(lines) if 'OpRayQueryInitializeKHR' in l]
    unordered = [k for k, (i, w) in enumerate(inits) if len(w) > 3 and w[3] == '%uint_64']
    t_uint = None
    for l in lines:
        m = re.match(r'\s*(%\S+) = OpTypeInt 32 0\s*$', l)
        if m:
            t_uint = m.group(1)
            break
    if not unordered or unordered[0] == 0 or not t_uint:
        open(dst, 'w', encoding='utf-8').write('\n'.join(lines))
        print(json.dumps({'mask_sites': 0}))
        return
    i, w = inits[unordered[0] - 1]
    # OpRayQueryInitializeKHR rq accel flags cullMask origin tmin dir tmax
    old = w[4]
    w[4] = '%pqm_ff'
    lines[i] = '               ' + ' '.join(w)
    first_func = next(k for k, l in enumerate(lines) if re.match(r'\s*%\S+ = OpFunction ', l))
    lines.insert(first_func, f'%pqm_ff = OpConstant {t_uint} 255')
    open(dst, 'w', encoding='utf-8').write('\n'.join(lines))
    print(json.dumps({'mask_sites': 1, 'old_mask': old, 'line': i + 1}))


if __name__ == '__main__':
    main()
