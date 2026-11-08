#!/usr/bin/env python3
"""Patch the RTX Remix for Minecraft mod jar (0.1.0-202610230634-170197a).

Changes BlockQuadEmitter.class only, and adds one helper class:
  1. water top face is emitted once instead of twice (the reversed copy's call is routed through GlassContactFaces)
  2. glass-like blocks keep the faces that touch an opaque block (GlassContactFaces + ASM hooks, see HookEmitter.java)
  Both follow GlassContactFaces.enabled, so with it false the class behaves as shipped.

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
SETTINGS = 'com/nvidia/rtxremix/minecraft/settings'


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
    ap.add_argument('--extra-cp', default='', help='extra classpath for compiling the menu helpers (brigadier jar, needed to type-check Text chains)')
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
        src_dir = os.path.join(work, 'orig')
        os.makedirs(os.path.join(src_dir, PKG))
        open(os.path.join(src_dir, EMITTER), 'wb').write(original)
        water = os.path.join(src_dir, EMITTER)
        # 2. compile the helper against the intermediary-named game classes
        out_dir = os.path.join(work, 'helper')
        os.makedirs(out_dir)
        run([javac, '--release', '21', '-cp', os.pathsep.join([a.intermediary, a.jar]), '-d', out_dir,
             os.path.join(HERE, 'GlassContactFaces.java')])
        helper_bytes = open(os.path.join(out_dir, HELPER), 'rb').read()
        # this tool copies exactly one class file for the helper: a nested class (GlassContactFaces$X) would be missing
        # from the jar and break the helper at class-init time (NoClassDefFoundError). Fail the build instead.
        extra = [f for f in os.listdir(os.path.join(out_dir, PKG)) if f != 'GlassContactFaces.class']
        if extra:
            sys.exit('GlassContactFaces compiled to extra class files (nested class or enum?): ' + ', '.join(extra))
        # 3. hook the emitter with ASM
        tool_dir = os.path.join(work, 'tool')
        os.makedirs(tool_dir)
        run([javac, '--release', '21', '-cp', asm_cp, '-d', tool_dir, os.path.join(HERE, 'HookEmitter.java')])
        final = os.path.join(work, 'BlockQuadEmitter.final.class')
        print(run([java, '-cp', os.pathsep.join([tool_dir, asm_cp]), 'HookEmitter', water, final]).strip())
        emitter_bytes = open(final, 'rb').read()
        # 4. settings menu: a "Light Transform Modifications" category. The two enums are recompiled from the
        #    shipped source plus one constant each (nothing else switches on their order), the helper adds the
        #    settings, and RtxSettingsFactory.build calls the helper just before it wraps its list.
        sett_out = os.path.join(work, 'settings')
        os.makedirs(sett_out)
        run([javac, '--release', '21', '-cp', os.pathsep.join([a.intermediary, a.jar] + ([a.extra_cp] if a.extra_cp else [])), '-d', sett_out] +
            [os.path.join(HERE, 'settings', f) for f in ('SettingCategory.java', 'SettingGroup.java',
                                                         'LightTransformSettings.java', 'LightTransformUi.java',
                                                         'PercentSlider.java', 'KeyBindButton.java')])
        with zipfile.ZipFile(a.jar) as z:
            factory_orig = z.read(SETTINGS + '/RtxSettingsFactory.class')
        factory_in = os.path.join(work, 'RtxSettingsFactory.class')
        open(factory_in, 'wb').write(factory_orig)
        run([javac, '--release', '21', '-cp', asm_cp, '-d', tool_dir, os.path.join(HERE, 'HookSettings.java')])
        factory_out = os.path.join(work, 'RtxSettingsFactory.final.class')
        print(run([java, '-cp', os.pathsep.join([tool_dir, asm_cp]), 'HookSettings', factory_in, factory_out]).strip())
        # the category screen: addOptions asks LightTransformUi.groupFor for the group's settings, which lays out our
        # group (toggles, then the saturation slider beside its name) and leaves every other group alone
        with zipfile.ZipFile(a.jar) as z:
            screen_orig = z.read(SETTINGS + '/RtxSettingsCategoryScreen.class')
        screen_in = os.path.join(work, 'RtxSettingsCategoryScreen.class')
        open(screen_in, 'wb').write(screen_orig)
        run([javac, '--release', '21', '-cp', asm_cp, '-d', tool_dir, os.path.join(HERE, 'HookCategoryScreen.java')])
        screen_out = os.path.join(work, 'RtxSettingsCategoryScreen.final.class')
        print(run([java, '-cp', os.pathsep.join([tool_dir, asm_cp]), 'HookCategoryScreen', screen_in, screen_out]).strip())
        # the sun and moon size: LightManager.updateDistantLight takes the angular diameter as a parameter
        light_cls = 'com/nvidia/rtxremix/minecraft/light/LightManager.class'
        with zipfile.ZipFile(a.jar) as z:
            light_orig = z.read(light_cls)
        light_in = os.path.join(work, 'LightManager.class')
        open(light_in, 'wb').write(light_orig)
        run([javac, '--release', '21', '-cp', asm_cp, '-d', tool_dir, os.path.join(HERE, 'HookLight.java')])
        light_out = os.path.join(work, 'LightManager.final.class')
        print(run([java, '-cp', os.pathsep.join([tool_dir, asm_cp]), 'HookLight', light_in, light_out]).strip())
        # glass block depth: the glass transmittance measurement distance constant in the atlas material builders
        btm_cls = 'com/nvidia/rtxremix/minecraft/texture/BlockTextureManager.class'
        with zipfile.ZipFile(a.jar) as z:
            btm_orig = z.read(btm_cls)
        btm_in = os.path.join(work, 'BlockTextureManager.class')
        open(btm_in, 'wb').write(btm_orig)
        run([javac, '--release', '21', '-cp', asm_cp, '-d', tool_dir, os.path.join(HERE, 'HookMeasure.java')])
        btm_out = os.path.join(work, 'BlockTextureManager.final.class')
        print(run([java, '-cp', os.pathsep.join([tool_dir, asm_cp]), 'HookMeasure', btm_in, btm_out]).strip())
        replace = {EMITTER: emitter_bytes,
                   btm_cls: open(btm_out, 'rb').read(),
                   light_cls: open(light_out, 'rb').read(),
                   SETTINGS + '/RtxSettingsFactory.class': open(factory_out, 'rb').read(),
                   SETTINGS + '/RtxSettingsCategoryScreen.class': open(screen_out, 'rb').read()}
        for name in ('SettingCategory', 'SettingGroup'):
            replace[f'{SETTINGS}/{name}.class'] = open(os.path.join(sett_out, SETTINGS, name + '.class'), 'rb').read()
        add = {HELPER: helper_bytes,
               SETTINGS + '/LightTransformSettings.class':
                   open(os.path.join(sett_out, SETTINGS, 'LightTransformSettings.class'), 'rb').read(),
               SETTINGS + '/LightTransformUi.class':
                   open(os.path.join(sett_out, SETTINGS, 'LightTransformUi.class'), 'rb').read(),
               SETTINGS + '/PercentSlider.class':
                   open(os.path.join(sett_out, SETTINGS, 'PercentSlider.class'), 'rb').read(),
               SETTINGS + '/KeyBindButton.class':
                   open(os.path.join(sett_out, SETTINGS, 'KeyBindButton.class'), 'rb').read()}
        # 5. write the new jar, every other entry copied as is
        with zipfile.ZipFile(a.jar) as zi, zipfile.ZipFile(a.out, 'w') as zo:
            seen = set()
            for info in zi.infolist():
                seen.add(info.filename)
                data = replace.get(info.filename)
                zo.writestr(info, zi.read(info) if data is None else data, compress_type=info.compress_type)
            for name, data in add.items():
                assert name not in seen, name
                zo.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
            missing = [n for n in replace if n not in seen]
            assert not missing, missing
        with zipfile.ZipFile(a.out) as z:
            assert z.testzip() is None
            for n, d in list(replace.items()) + list(add.items()):
                assert z.read(n) == d, n
        print('wrote', a.out)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
