#!/usr/bin/env python3
"""Patch the RTX Remix for Minecraft mod jar (0.1.0-202610230634-170197a).

Changes BlockQuadEmitter.class only, and adds one helper class:
  1. water top face is emitted once instead of twice (the reversed copy is NOPed, see water_quad_patch.py)
  2. glass-like blocks keep the faces that touch an opaque block (GlassContactFaces + ASM hooks, see HookEmitter.java)

    python patch_jar.py --jar rtx-remix-renderer-0.1.0-202610230634-170197a.jar --out patched.jar \
        --intermediary <profile>/.fabric/remappedJars/minecraft-1.21.1-<loader>/client-intermediary.jar \
        --asm <folder with asm-9.x.jar and asm-tree-9.x.jar> [--jdk <JDK 21+ folder>]

The version marker inside the jar is untouched, so the mod will not re-extract (and overwrite) a patched runtime.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = 'com/nvidia/rtxremix/minecraft/terrain/capture'
EMITTER = PKG + '/BlockQuadEmitter.class'
HELPER = PKG + '/GlassContactFaces.class'


def exe(jdk, name):
    cand = [os.path.join(jdk, 'bin', name + '.exe'), os.path.join(jdk, 'bin', name)] if jdk else []
    for c in cand:
        if os.path.isfile(c):
            return c
    found = shutil.which(name)
    if not found:
        sys.exit(f'{name} not found (use --jdk)')
    return found


def run(args, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f'{os.path.basename(args[0])} failed:\n{r.stdout}\n{r.stderr}')
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--jar', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--intermediary', required=True, help='client-intermediary.jar from the profile .fabric folder')
    ap.add_argument('--asm', required=True, help='folder containing asm-9.x.jar and asm-tree-9.x.jar')
    ap.add_argument('--jdk', default=None, help='JDK 21+ home (default: javac/java on PATH)')
    a = ap.parse_args()

    asm = glob.glob(os.path.join(a.asm, '**', 'asm-9*.jar'), recursive=True)
    tree = glob.glob(os.path.join(a.asm, '**', 'asm-tree-9*.jar'), recursive=True)
    if not asm or not tree:
        sys.exit('asm-9.x.jar / asm-tree-9.x.jar not found under --asm')
    asm_cp = os.pathsep.join([sorted(asm)[-1], sorted(tree)[-1]])
    javac, java = exe(a.jdk, 'javac'), exe(a.jdk, 'java')

    work = tempfile.mkdtemp(prefix='modpatch_')
    try:
        with zipfile.ZipFile(a.jar) as z:
            if HELPER in z.namelist():
                sys.exit('jar already contains GlassContactFaces: start from the unmodified jar')
            original = z.read(EMITTER)
        # 1. water quad
        src_dir = os.path.join(work, 'orig')
        os.makedirs(os.path.join(src_dir, PKG))
        open(os.path.join(src_dir, EMITTER), 'wb').write(original)
        water = os.path.join(work, 'BlockQuadEmitter.water.class')
        print(run([sys.executable, '-I', os.path.join(HERE, 'water_quad_patch.py'),
                   os.path.join(src_dir, EMITTER), water]).strip())
        # 2. compile the helper against the intermediary-named game classes
        out_dir = os.path.join(work, 'helper')
        os.makedirs(out_dir)
        run([javac, '--release', '21', '-cp', os.pathsep.join([a.intermediary, src_dir]), '-d', out_dir,
             os.path.join(HERE, 'GlassContactFaces.java')])
        helper_bytes = open(os.path.join(out_dir, HELPER), 'rb').read()
        # 3. hook the emitter with ASM
        tool_dir = os.path.join(work, 'tool')
        os.makedirs(tool_dir)
        run([javac, '--release', '21', '-cp', asm_cp, '-d', tool_dir, os.path.join(HERE, 'HookEmitter.java')])
        final = os.path.join(work, 'BlockQuadEmitter.final.class')
        print(run([java, '-cp', os.pathsep.join([tool_dir, asm_cp]), 'HookEmitter', water, final]).strip())
        emitter_bytes = open(final, 'rb').read()
        # 4. write the new jar, every other entry copied as is
        with zipfile.ZipFile(a.jar) as zi, zipfile.ZipFile(a.out, 'w') as zo:
            for info in zi.infolist():
                data = emitter_bytes if info.filename == EMITTER else zi.read(info)
                zo.writestr(info, data, compress_type=info.compress_type)
                if info.filename == EMITTER:
                    zo.writestr(HELPER, helper_bytes, compress_type=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(a.out) as z:
            assert z.testzip() is None
            assert z.read(EMITTER) == emitter_bytes and z.read(HELPER) == helper_bytes
        print('wrote', a.out)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
