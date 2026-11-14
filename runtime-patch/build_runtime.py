#!/usr/bin/env python3
"""Build a patched copy of the RTX Remix for Minecraft runtime (remix-sdk/d3d9.dll).

Two patches are applied to the SPIR-V shaders embedded in the DLL, each strictly size-preserving:

  1. shadow rays: order-independent, depth-dependent Beer-Lambert absorption through thick translucent
     materials (glass, water). See shadow_ray_patch.py and docs/TECHNICAL.md.
  2. composite pass: the distance fade-to-sky no longer overwrites sky seen *through* glass or water.

Only the exact runtime build below is supported. Your original file is never modified.

    python build_runtime.py --dll remix-sdk/d3d9.dll --out d3d9.patched.dll --spirv-tools <dir> [--k 0.5]

--spirv-tools is a folder containing spirv-as, spirv-dis and spirv-val (Khronos SPIRV-Tools, 2025.x tested).
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PATCHER = os.path.join(HERE, 'shadow_ray_patch.py')
BOUNCE_PATCHER = os.path.join(HERE, 'bounce_tint_patch.py')
MASK_TEST_PATCHER = os.path.join(HERE, 'mask_test_patch.py')
GBUF_PATCHER = os.path.join(HERE, 'gbuf_patch.py')
PSR_WATER_PATCHER = os.path.join(HERE, 'psr_water_patch.py')
WATER_REFLECT_PATCHER = os.path.join(HERE, 'water_reflect_patch.py')
SSS_PSR_PATCHER = os.path.join(HERE, 'sss_psr_patch.py')
NEE_RESERVOIR_PATCHER = os.path.join(HERE, 'nee_reservoir_patch.py')

# Supported runtime (md5 of the pristine d3d9.dll); only the latest NVIDIA release is supported. Every patch is found by content,
# never by a fixed offset.
SUPPORTED_BUILDS = {
    '1ae89b5ebcd2a4dad175d96b1806d5f0': 'RTX Remix for Minecraft 0.1.1 (309,016,064 bytes)',
}
SPIRV_MAGIC = b'\x03\x02\x23\x07'
SPIRV_1_5 = struct.pack('<I', 0x00010500)


def true_size(blob):
    """Byte length of the SPIR-V module starting at blob[0]: walk instructions to the last OpFunctionEnd."""
    w = struct.unpack('<%dI' % (len(blob) // 4), blob[:len(blob) // 4 * 4])
    i, end = 5, None
    while i < len(w):
        wc, op = w[i] >> 16, w[i] & 0xffff
        if wc == 0 or i + wc > len(w):
            break
        i += wc
        if op == 56:                                  # OpFunctionEnd
            end = i
            if i >= len(w) or (w[i] & 0xffff) != 54:  # next is not OpFunction: module is over
                break
    return end * 4 if end else 0


def find_modules(data):
    """Offsets and sizes of every embedded SPIR-V 1.5 module (skips candidates inside an earlier module)."""
    mods, pos, floor = [], 0, 0
    while True:
        pos = data.find(SPIRV_MAGIC + SPIRV_1_5, pos)
        if pos < 0:
            return mods
        if pos >= floor:
            size = true_size(data[pos:pos + 4 * 1024 * 1024])
            if size > 100:
                mods.append({'off': pos, 'size': size})
                floor = pos + size
        pos += 4


class Tools:
    def __init__(self, folder):
        def exe(name):
            for cand in (name + '.exe', name):
                p = os.path.join(folder, cand) if folder else shutil.which(cand)
                if p and os.path.isfile(p):
                    return p
            sys.exit(f'{name} not found (use --spirv-tools)')
        self.dis, self.asm = exe('spirv-dis'), exe('spirv-as')
        # spirv-val is optional (RenderDoc ships spirv-as/dis but not spirv-val): without it the module is only checked by a
        # disassembly round trip, which catches malformed binaries but NOT type or logic errors
        try:
            self.val = exe('spirv-val')
        except SystemExit:
            self.val = None
            print('WARNING: spirv-val not found, modules are NOT validated (round-trip check only)')


def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(os.path.basename(args[0]) + ': ' + (r.stderr or r.stdout)[-800:])
    return r.stdout


def assemble(tools, text, path):
    open(path + '.dis', 'w', encoding='utf-8').write(text)
    run([tools.asm, '--target-env', 'vulkan1.2', path + '.dis', '-o', path])
    return os.path.getsize(path)


def fit_and_validate(tools, text_lines, size, path):
    """Strip debug names, pad to exactly `size` bytes, validate. Returns the module bytes."""
    text = [l for l in text_lines if not re.match(r'\s*Op(Member)?Name ', l)]
    first_anno = next(i for i, l in enumerate(text) if re.match(r'\s*Op(Decorate|MemberDecorate) ', l))
    new = assemble(tools, '\n'.join(text), path)
    deficit = size - new
    if deficit < 0:
        raise RuntimeError(f'patched module still {-deficit} bytes too large')
    words = deficit // 4
    if words == 1:
        raise RuntimeError('1-word deficit, cannot pad')
    if words >= 2:
        text.insert(first_anno, 'OpModuleProcessed "' + 'p' * (4 * (words - 1) - 1) + '"')
        new = assemble(tools, '\n'.join(text), path)
    if new != size:
        raise RuntimeError(f'size mismatch {new} != {size}')
    if tools.val:
        run([tools.val, '--target-env', 'vulkan1.2', '--scalar-block-layout', path])
    else:
        run([tools.dis, '--no-header', path, '-o', path + '.rt.dis'])
    return open(path, 'rb').read()


NEE_PASS_OFFSETS = (0x11e4cf60, 0x11ea2470)   # 'integrate_nee' modules of the supported build
MISS_PROBE = False   # set by --miss-probe: DIAGNOSTIC colours for the primary-ray miss branch (needs --pane-depth)
PANE_DEPTH = False   # set by --pane-depth: thin glass seen directly absorbs as if K*d thick, K live from distanceFadeMin
WATER_REFLECT = False  # set by --water-reflect: water hit by indirect (reflection/bounce) rays is tinted half as hard per surface
NEE_RESERVOIR = False  # set by --nee-reservoir: NEE samples handed to ReSTIR GI carry the glass/water tint of the shadow ray
SSS_PSR = False      # set by --sss-psr: subsurface materials seen through water/glass/mirrors take their light from RIS, not a mis-projected RTXDI pixel
PSR_WATER = False    # set by --psr-water: water keeps its reflection when seen through glass (PSTR secondary incident approximation off for non-glass)
SAT_SLIDER = False   # set by --sat-slider: glass colour saturation read live from noiseScale = 20.001 + 0.01 * saturation


def patch_shadow_module(tools, work, mod, blob, k, telltale, glass_clear, live, bounce_clear=0.0, mask_test=False, nee_marker=False, cache_marker=False):
    off = mod['off']
    base = os.path.join(work, f'm_{off:08x}')
    open(base + '.orig.spv', 'wb').write(blob)
    run([tools.dis, '--no-header', '--no-indent', base + '.orig.spv', '-o', base + '.orig.dis'])
    args = [sys.executable, '-I', PATCHER, base + '.orig.dis', base + '.p.dis', '--k', repr(k)]
    if telltale:
        args.append('--telltale')
    if live:
        args.append('--live-flag')
    if glass_clear > 0:
        args += ['--glass-clear', repr(glass_clear)]
    if SAT_SLIDER and live:
        args.append('--sat-slider')
    info = json.loads(run(args).strip().splitlines()[-1])
    info['off'] = off
    patched = base + '.p.dis'
    if bounce_clear > 0:
        bargs = [sys.executable, '-I', BOUNCE_PATCHER, patched, base + '.b.dis', '--bounce-clear', repr(bounce_clear)]
        if cache_marker:
            bargs.append('--cache-kill' if cache_marker == 'kill' else '--cache-marker')
        if nee_marker and off in NEE_PASS_OFFSETS:
            bargs.append('--nee-marker')
        if info.get('sites'):
            bargs.append('--any-module')   # e.g. integrate_direct: bounce-style glass colour without the indirect-ray flag
        if live:
            bargs.append('--live-flag')
            if SAT_SLIDER:
                bargs.append('--sat-slider')
            if telltale:
                bargs.append('--telltale')
        binfo = json.loads(run(bargs).strip().splitlines()[-1])
        info['bounce_sites'] = binfo.get('bounce_sites', 0)
        info['chain_sites'] = binfo.get('chain_sites', 0)
        if info['bounce_sites']:
            patched = base + '.b.dis'
    if mask_test:
        minfo = json.loads(run([sys.executable, '-I', MASK_TEST_PATCHER, patched, base + '.m.dis']).strip().splitlines()[-1])
        info['mask_sites'] = minfo.get('mask_sites', 0)
        if info['mask_sites']:
            patched = base + '.m.dis'
    if PANE_DEPTH and live:
        gargs = [sys.executable, '-I', GBUF_PATCHER, patched, base + '.g.dis'] + (['--miss-probe'] if MISS_PROBE else [])
        ginfo = json.loads(run(gargs).strip().splitlines()[-1])
        info['gbuf_sites'] = ginfo.get('gbuf_sites', 0)
        if info['gbuf_sites']:
            patched = base + '.g.dis'
    if PSR_WATER and live:
        wargs = [sys.executable, '-I', PSR_WATER_PATCHER, patched, base + '.w.dis']
        winfo = json.loads(run(wargs).strip().splitlines()[-1])
        info['psr_water_sites'] = winfo.get('psr_water_sites', 0)
        info['psr_medium_restores'] = winfo.get('psr_medium_restores', 0)
        if info['psr_water_sites']:
            patched = base + '.w.dis'
    if WATER_REFLECT and live:
        rinfo = json.loads(run([sys.executable, '-I', WATER_REFLECT_PATCHER, patched, base + '.r.dis']).strip().splitlines()[-1])
        info['water_reflect_sites'] = rinfo.get('water_reflect_sites', 0)
        info['water_refract_sites'] = rinfo.get('approx_tests', 0)
        if info['water_reflect_sites']:
            patched = base + '.r.dis'
    if SSS_PSR and live:
        sinfo = json.loads(run([sys.executable, '-I', SSS_PSR_PATCHER, patched, base + '.s.dis']).strip().splitlines()[-1])
        info['sss_psr_sites'] = sinfo.get('sss_psr_sites', 0)
        if info['sss_psr_sites']:
            patched = base + '.s.dis'
    if NEE_RESERVOIR and live:
        ninfo = json.loads(run([sys.executable, '-I', NEE_RESERVOIR_PATCHER, patched, base + '.n.dis']).strip().splitlines()[-1])
        info['nee_reservoir_sites'] = ninfo.get('nee_reservoir_sites', 0)
        if info['nee_reservoir_sites']:
            patched = base + '.n.dis'
    if not info.get('sites') and not info.get('bounce_sites') and not info.get('mask_sites') and not info.get('gbuf_sites') and not info.get('psr_water_sites') and not info.get('water_reflect_sites') and not info.get('sss_psr_sites') and not info.get('nee_reservoir_sites'):
        return info, None
    text = open(patched, encoding='utf-8').read().split('\n')
    return info, fit_and_validate(tools, text, mod['size'], base + '.new.spv')


# Live switch for the composite fix: ViewDistanceArgs.noiseScale (rtx.viewDistance.noiseScale, shipped value 20) above
# this threshold turns the sky-fade fix on. The mod writes 20.001 for ON and exactly 20 for OFF.
NOISE_SCALE_ON_ABOVE = 20.0005


def find_composite(data):
    """Offset of the composite compute shader: the largest module that uses CompositeArgs and the primary linear view Z."""
    best = None
    for m in find_modules(bytes(data)):
        blob = bytes(data[m['off']:m['off'] + m['size']])
        if b'CompositeArgs_natural' in blob and b'PrimaryLinearViewZ' in blob and b'primaryMiss' in blob:
            if best is None or m['size'] > best['size']:
                best = m
    if best is None:
        raise RuntimeError('composite shader not found (unsupported runtime build?)')
    return best['off']


def patch_composite(tools, work, data, live=False):
    off = find_composite(data)
    blob = bytes(data[off:off + 400000])
    size = true_size(blob)
    blob = blob[:size]
    open(os.path.join(work, 'comp.orig.spv'), 'wb').write(blob)
    run([tools.dis, '--no-header', '--no-indent', os.path.join(work, 'comp.orig.spv'),
         '-o', os.path.join(work, 'comp.orig.dis')])
    text = open(os.path.join(work, 'comp.orig.dis'), encoding='utf-8').read().split('\n')
    # anchor, by structure (ids differ between builds): in the branch taken when ViewDistanceArgs.distanceMode == 3 the shader stores
    # !primaryMiss, i.e.  %N = OpLogicalNot %bool %P   with   %P = OpLoad %bool %primaryMiss
    miss_loads = {m.group(1) for l in text for m in [re.match(r'(%\S+) = OpLoad %bool %primaryMiss\s*$', l.strip())] if m}
    idx = []
    for i, l in enumerate(text):
        m = re.match(r'(%\S+) = OpLogicalNot %bool (%\S+)\s*$', l.strip())
        if m and m.group(2) in miss_loads and text[i - 1].strip().endswith('= OpLabel') and text[i + 1].strip().startswith('OpStore') \
                and any('OpIEqual %bool' in x and x.strip().endswith('%uint_3') for x in text[max(0, i - 12):i]):
            idx.append(i)
    if len(idx) != 1:
        raise RuntimeError('composite anchor not found (unsupported runtime build?)')
    N_ID, P_ID = re.match(r'(%\S+) = OpLogicalNot %bool (%\S+)\s*$', text[idx[0]].strip()).groups()
    # E = (primary linear view Z == miss sentinel): the fetched view Z (.x of an ImageFetch of PrimaryLinearViewZ) compared with a uniform float
    viewz_loads = {m.group(1) for l in text for m in [re.match(r'(%\S+) = OpLoad \S+ %PrimaryLinearViewZ\s*$', l.strip())] if m}
    fetch = {m.group(1) for l in text for m in [re.match(r'(%\S+) = OpImageFetch %v4float (%\S+) ', l.strip())] if m and m.group(2) in viewz_loads}
    xs = {m.group(1) for l in text for m in [re.match(r'(%\S+) = OpCompositeExtract %float (%\S+) 0\s*$', l.strip())] if m and m.group(2) in fetch}
    eq = [m.group(1) for l in text for m in [re.match(r'(%\S+) = OpFOrdEqual %bool (%\S+) (%\S+)\s*$', l.strip())] if m and m.group(2) in xs]
    if not eq:
        raise RuntimeError('composite: view-Z miss comparison not found')
    E_ID = eq[0]
    # %848 = (primary view Z == miss sentinel): also skip the sky fade for rays that passed through a surface
    if not live:
        text[idx[0]:idx[0] + 1] = [f'%pq_or = OpLogicalOr %bool {P_ID} {E_ID}', f'{N_ID} = OpLogicalNot %bool %pq_or']
    else:
        def find(pat):
            for l in text:
                m = re.match(r'(%\S+) = ' + pat + r'\s*$', l)
                if m:
                    return m.group(1)
            return None
        t_int, t_float = find(r'OpTypeInt 32 1'), find(r'OpTypeFloat 32')
        if not (t_int and t_float and find(r'OpVariable \S+ Uniform') and any(l.startswith('%cb = OpVariable') for l in text)):
            raise RuntimeError('composite: types or cb variable not found')
        pf = find(r'OpTypePointer Uniform ' + re.escape(t_float))
        glob = [f'%pq_i5 = OpConstant {t_int} 5', f'%pq_i4 = OpConstant {t_int} 4',
                f'%pq_thr = OpConstant {t_float} {NOISE_SCALE_ON_ABOVE!r}']
        if not pf:
            pf = '%pq_pf'
            glob.append(f'{pf} = OpTypePointer Uniform {t_float}')
        text[idx[0]:idx[0] + 1] = [
            f'%pq_np = OpAccessChain {pf} %cb %pq_i5 %pq_i4', f'%pq_nv = OpLoad {t_float} %pq_np',
            '%pq_on = OpFOrdGreaterThan %bool %pq_nv %pq_thr', f'%pq_and = OpLogicalAnd %bool {E_ID} %pq_on',
            f'%pq_or = OpLogicalOr %bool {P_ID} %pq_and', f'{N_ID} = OpLogicalNot %bool %pq_or']
        first_func = next(i for i, l in enumerate(text) if re.match(r'%\S+ = OpFunction ', l))
        text[first_func:first_func] = glob
    return off, size, fit_and_validate(tools, text, size, os.path.join(work, 'comp.new.spv'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dll', required=True, help='original remix-sdk/d3d9.dll')
    ap.add_argument('--out', required=True, help='where to write the patched copy')
    ap.add_argument('--spirv-tools', default=None, help='folder with spirv-as/dis/val (default: PATH)')
    ap.add_argument('--k', type=float, default=1.0,
                    help='light absorption scale for shadow rays: 1.0 physical, lower lets more light through (0.5 used by the author)')
    ap.add_argument('--glass-clear', type=float, default=0.9,
                    help='glass tint renormalisation: brightest channel of a glass material is raised to this value per '
                         'measurement distance so coloured glass gives coloured light instead of a dark shadow (0 = off)')
    ap.add_argument('--bounce-clear', type=float, default=0.9,
                    help='same renormalisation for BOUNCE rays (indirect path tracing through glass), e.g. light from a sea lantern '
                         '(0 = off)')
    ap.add_argument('--nee-marker', action='store_true', help='DIAGNOSTIC (needs --live-flag --telltale): integrate_nee output drawn magenta')
    ap.add_argument('--cache-marker', nargs='?', const='blue', default=None, choices=['blue', 'kill'],
                    help='DIAGNOSTIC (needs --live-flag --telltale): NEE-cache sample radiance drawn blue, or removed with kill')
    ap.add_argument('--mask-test', action='store_true', help='DIAGNOSTIC: main bounce rays see all instances')
    ap.add_argument('--live-flag', action='store_true',
                    help='gate the new shadow-ray behaviour on rtx.subsurface.enableHeuristicSingleScatteringTransmission so it can be switched at runtime')
    ap.add_argument('--pane-depth', action='store_true',
                    help='with --live-flag: stronger depth effect for thin glass (panes) seen directly, strength K read live from '
                         'distanceFadeMin = 358.4 + 0.001 * K (K = 0 is the shipped look)')
    ap.add_argument('--miss-probe', action='store_true',
                    help='DIAGNOSTIC (needs --pane-depth): primary-ray miss branch result that would be black is drawn pink (glass) or green (water)')
    ap.add_argument('--sat-slider', action='store_true',
                    help='with --live-flag: glass colour saturation (0.25..2.0) is read live from noiseScale = 20.001 + 0.01 * saturation')
    ap.add_argument('--psr-water', action='store_true',
                    help='with --live-flag: the reflection of water seen through glass is kept (see psr_water_patch.py)')
    ap.add_argument('--water-reflect', action='store_true',
                    help='with --live-flag: water seen in reflections/bounce light is tinted half as hard per surface (see water_reflect_patch.py)')
    ap.add_argument('--sss-psr', action='store_true',
                    help='with --live-flag: no second, over-refracted shadow set on subsurface materials (sand) seen through water (see sss_psr_patch.py)')
    ap.add_argument('--nee-reservoir', action='store_true',
                    help='with --live-flag: emissive NEE samples stored into ReSTIR GI keep the tint of the glass and water they crossed (see nee_reservoir_patch.py)')
    ap.add_argument('--no-composite', action='store_true', help='skip the sky-fade fix')
    ap.add_argument('--telltale', action='store_true', help='debug: turn light red wherever a thick translucent is hit')
    ap.add_argument('--jobs', type=int, default=12)
    a = ap.parse_args()
    global SAT_SLIDER, PANE_DEPTH, MISS_PROBE, PSR_WATER, WATER_REFLECT, SSS_PSR, NEE_RESERVOIR
    SAT_SLIDER = a.sat_slider
    PANE_DEPTH = a.pane_depth
    MISS_PROBE = a.miss_probe
    PSR_WATER = a.psr_water
    WATER_REFLECT = a.water_reflect
    SSS_PSR = a.sss_psr
    NEE_RESERVOIR = a.nee_reservoir

    data = bytearray(open(a.dll, 'rb').read())
    md5 = hashlib.md5(data).hexdigest()
    if md5 not in SUPPORTED_BUILDS:
        sys.exit(f'unsupported d3d9.dll (md5 {md5}); this tool supports: ' + '; '.join(f'{k} = {v}' for k, v in SUPPORTED_BUILDS.items()))
    print('runtime build:', SUPPORTED_BUILDS[md5])
    tools = Tools(a.spirv_tools)
    work = tempfile.mkdtemp(prefix='remixpatch_')
    try:
        mods = find_modules(bytes(data))
        print(f'{len(mods)} embedded SPIR-V modules found')
        manifest, errors = [], []
        with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
            futs = {ex.submit(patch_shadow_module, tools, work, m,
                              bytes(data[m['off']:m['off'] + m['size']]), a.k, a.telltale, a.glass_clear, a.live_flag, a.bounce_clear, a.mask_test, a.nee_marker, a.cache_marker): m
                    for m in mods}
            for f in cf.as_completed(futs):
                m = futs[f]
                try:
                    info, out = f.result()
                except Exception as e:  # noqa: BLE001
                    errors.append(f'{m["off"]:#x}: {e}')
                    continue
                if out is not None:
                    assert len(out) == m['size']
                    data[m['off']:m['off'] + m['size']] = out
                manifest.append(info)
        if errors:
            sys.exit('ERRORS:\n' + '\n'.join(errors))
        hit = [x for x in manifest if x.get('sites')]
        print(f'shadow rays: {len(hit)} modules, {sum(x["sites"] for x in hit)} sites patched (k={a.k})')
        mh = [x for x in manifest if x.get('mask_sites')]
        if a.mask_test:
            print(f'mask test: {len(mh)} modules')
        bh = [x for x in manifest if x.get('bounce_sites')]
        print(f'bounce rays: {len(bh)} modules, {sum(x["bounce_sites"] for x in bh)} sites patched (clear={a.bounce_clear}); '
              f'scale/bias chain sites {sum(x.get("chain_sites", 0) for x in bh)}')
        gh = [x for x in manifest if x.get('gbuf_sites')]
        if a.pane_depth:
            print(f'primary-view glass depth: {len(gh)} modules, {sum(x["gbuf_sites"] for x in gh)} sites patched')
        wh = [x for x in manifest if x.get('psr_water_sites')]
        if a.psr_water:
            print(f'water reflection through glass: {len(wh)} modules, {sum(x["psr_water_sites"] for x in wh)} sites patched; medium state restored at {sum(x.get("psr_medium_restores", 0) for x in wh)} of them')
        rh = [x for x in manifest if x.get('water_reflect_sites')]
        if a.water_reflect:
            print(f'water in reflections: {len(rh)} modules, {sum(x["water_reflect_sites"] for x in rh)} sites patched; approximation switched off for water at {sum(x.get("water_refract_sites", 0) for x in rh)} tests')
        sh = [x for x in manifest if x.get('sss_psr_sites')]
        if a.sss_psr:
            print(f'subsurface light through water/glass: {len(sh)} modules, {sum(x["sss_psr_sites"] for x in sh)} sites patched')
        nh = [x for x in manifest if x.get('nee_reservoir_sites')]
        if a.nee_reservoir:
            print(f'NEE samples for ReSTIR GI carry the glass/water tint: {len(nh)} modules, {sum(x["nee_reservoir_sites"] for x in nh)} sites patched')
        if not a.no_composite:
            off, size, out = patch_composite(tools, work, data, a.live_flag)
            data[off:off + size] = out
            print('composite sky fade: patched')
        open(a.out, 'wb').write(data)
        print('wrote', a.out, 'md5', hashlib.md5(data).hexdigest())
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
