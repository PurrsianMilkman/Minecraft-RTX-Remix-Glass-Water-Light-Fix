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

SUPPORTED_MD5 = 'cbe2d49f543b608a7ac45d6b2c6631ae'   # remix-main+71a581da, 309,009,920 bytes
COMPOSITE_OFFSET = 0x12430950                         # composite compute shader inside that build
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
        self.dis, self.asm, self.val = exe('spirv-dis'), exe('spirv-as'), exe('spirv-val')


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
    run([tools.val, '--target-env', 'vulkan1.2', '--scalar-block-layout', path])
    return open(path, 'rb').read()


def patch_shadow_module(tools, work, mod, blob, k, telltale):
    off = mod['off']
    base = os.path.join(work, f'm_{off:08x}')
    open(base + '.orig.spv', 'wb').write(blob)
    run([tools.dis, '--no-header', '--no-indent', base + '.orig.spv', '-o', base + '.orig.dis'])
    args = [sys.executable, '-I', PATCHER, base + '.orig.dis', base + '.p.dis', '--k', repr(k)]
    if telltale:
        args.append('--telltale')
    info = json.loads(run(args).strip().splitlines()[-1])
    info['off'] = off
    if not info.get('sites'):
        return info, None
    text = open(base + '.p.dis', encoding='utf-8').read().split('\n')
    return info, fit_and_validate(tools, text, mod['size'], base + '.new.spv')


def patch_composite(tools, work, data):
    blob = bytes(data[COMPOSITE_OFFSET:COMPOSITE_OFFSET + 400000])
    size = true_size(blob)
    blob = blob[:size]
    open(os.path.join(work, 'comp.orig.spv'), 'wb').write(blob)
    run([tools.dis, '--no-header', '--no-indent', os.path.join(work, 'comp.orig.spv'),
         '-o', os.path.join(work, 'comp.orig.dis')])
    text = open(os.path.join(work, 'comp.orig.dis'), encoding='utf-8').read().split('\n')
    old = '%18556 = OpLogicalNot %bool %1039'     # distanceMode == 3 && !primaryMiss
    idx = [i for i, l in enumerate(text) if l.strip() == old]
    if len(idx) != 1:
        raise RuntimeError('composite anchor not found (unsupported runtime build?)')
    # %848 = (primary view Z == miss sentinel): also skip the sky fade for rays that passed through a surface
    text[idx[0]:idx[0] + 1] = ['%pq_or = OpLogicalOr %bool %1039 %848', '%18556 = OpLogicalNot %bool %pq_or']
    return size, fit_and_validate(tools, text, size, os.path.join(work, 'comp.new.spv'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dll', required=True, help='original remix-sdk/d3d9.dll')
    ap.add_argument('--out', required=True, help='where to write the patched copy')
    ap.add_argument('--spirv-tools', default=None, help='folder with spirv-as/dis/val (default: PATH)')
    ap.add_argument('--k', type=float, default=1.0,
                    help='light absorption scale for shadow rays: 1.0 physical, lower lets more light through (0.5 used by the author)')
    ap.add_argument('--no-composite', action='store_true', help='skip the sky-fade fix')
    ap.add_argument('--telltale', action='store_true', help='debug: turn light red wherever a thick translucent is hit')
    ap.add_argument('--jobs', type=int, default=12)
    a = ap.parse_args()

    data = bytearray(open(a.dll, 'rb').read())
    md5 = hashlib.md5(data).hexdigest()
    if md5 != SUPPORTED_MD5:
        sys.exit(f'unsupported d3d9.dll (md5 {md5}); this tool only supports {SUPPORTED_MD5}')
    tools = Tools(a.spirv_tools)
    work = tempfile.mkdtemp(prefix='remixpatch_')
    try:
        mods = find_modules(bytes(data))
        print(f'{len(mods)} embedded SPIR-V modules found')
        manifest, errors = [], []
        with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
            futs = {ex.submit(patch_shadow_module, tools, work, m,
                              bytes(data[m['off']:m['off'] + m['size']]), a.k, a.telltale): m
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
        if not a.no_composite:
            size, out = patch_composite(tools, work, data)
            data[COMPOSITE_OFFSET:COMPOSITE_OFFSET + size] = out
            print('composite sky fade: patched')
        open(a.out, 'wb').write(data)
        print('wrote', a.out, 'md5', hashlib.md5(data).hexdigest())
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
