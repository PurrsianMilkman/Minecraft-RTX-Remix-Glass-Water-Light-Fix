"""Build the patched RTX Remix for Minecraft jar: one file to drop into the mods folder.

Input : NVIDIA's own release jar (or the 0.1.0 release zip that contains it), never redistributed by this project.
        Supported: RTX Remix for Minecraft 0.1.1 and 0.1.0 (picked by the jar's md5).
Output: <out>/<original jar name>-LightFix.jar  (delete the original from the mods folder, put this one in)

What is done:
  1. the pristine jar is checked against its md5;
  2. the Windows runtime (native/remix-sdk-win64/d3d9.dll) is taken out of it, its embedded SPIR-V shaders are patched
     (runtime-patch/build_runtime.py, needs spirv-as / spirv-dis, spirv-val strongly recommended) and put back;
  3. the 7 changed classes and the added classes from prebuilt/ replace / join the original ones, the companion mod
     (translucent-light-fix settings, hotkeys, live switch) is merged in, fabric.mod.json gets its two extra entrypoints and a version
     suffix (the mod re-extracts its native files when the version changes, which is how the patched DLL reaches remix-sdk/).

Usage:
  python build_patched_jar.py --zip nvidia-release.zip   | --jar pristine.jar
                              --prebuilt <dir> --spirv-tools <dir> --out <dir> [--work <dir>]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile

# pristine jar md5 -> version label (also the sub-folder of prebuilt/ that holds that version's changed classes)
BUILDS = {
    '0b9c4d5f272fc4627d48ba6c636f2ef5': ('0.1.1', 'rtx-remix-renderer-0.1.1-202611060211-7d2ba9f.jar'),
    'c4551ac851988aa6ec5b6299c8cbd259': ('0.1.0', 'rtx-remix-renderer-0.1.0-202610230634-170197a.jar'),
}
ZIP_010_JAR_NAME = 'rtx-remix-renderer-0.1.0-202610230634-170197a.jar'
DLL_ENTRY = 'native/remix-sdk-win64/d3d9.dll'
VERSION_SUFFIX = '+glassfix1'
TOGGLE_ENTRYPOINTS = {'preLaunch': 'purrsian.translucentfix.TranslucentFixPreLaunch',
                      'client': 'purrsian.translucentfix.TranslucentFixToggle'}
DLL_ARGS = ['--k', '0.5', '--glass-clear', '0.9', '--bounce-clear', '0.9', '--live-flag', '--sat-slider', '--pane-depth', '--psr-water', '--water-reflect', '--sss-psr', '--nee-reservoir']
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def md5_of(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            h.update(chunk)
    return h.hexdigest()


def say(msg):
    print(msg, flush=True)


def get_pristine_jar(a, work):
    if a.jar:
        return a.jar
    target = os.path.join(work, 'pristine', ZIP_010_JAR_NAME)
    if os.path.isfile(target) and md5_of(target) in BUILDS:
        say('pristine jar already extracted')
        return target
    say('extracting the mod jar from NVIDIA\'s zip ...')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with zipfile.ZipFile(a.zip) as z:
        names = [n for n in z.namelist() if n.endswith('.jar') and 'rtx-remix-renderer' in n]
        if len(names) != 1:
            sys.exit('expected exactly one renderer jar in the zip, found %r' % names)
        with z.open(names[0]) as src, open(target, 'wb') as dst:
            while True:
                chunk = src.read(1 << 22)
                if not chunk:
                    break
                dst.write(chunk)
    return target


def collect_prebuilt(prebuilt, version):
    """{jar entry name: bytes}: prebuilt/common/ (companion mod) and prebuilt/<version>/ (the changed classes of that mod version)."""
    out = {}
    for sub in ('common', version):
        root = os.path.join(prebuilt, sub)
        if not os.path.isdir(root):
            sys.exit('prebuilt/%s is missing' % sub)
        for base, _, files in os.walk(root):
            for f in files:
                full = os.path.join(base, f)
                out[os.path.relpath(full, root).replace(os.sep, '/')] = open(full, 'rb').read()
    return out


def patch_manifest(raw):
    meta = json.loads(raw.decode('utf-8'))
    if meta.get('id') != 'rtx-remix-renderer':
        sys.exit('unexpected fabric.mod.json')
    if not meta['version'].endswith(VERSION_SUFFIX):
        meta['version'] += VERSION_SUFFIX
    ep = meta.setdefault('entrypoints', {})
    for key, cls in TOGGLE_ENTRYPOINTS.items():
        lst = ep.setdefault(key, [])
        if cls not in lst:
            lst.append(cls)
    return json.dumps(meta, indent=4).encode('utf-8')


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--zip')
    src.add_argument('--jar')
    ap.add_argument('--prebuilt', default=os.path.join(ROOT, 'prebuilt'))
    ap.add_argument('--spirv-tools', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--work', default=None)
    a = ap.parse_args()
    work = a.work or os.path.join(a.out, 'work')
    os.makedirs(work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)

    jar = get_pristine_jar(a, work)
    say('checking the mod jar ...')
    got = md5_of(jar)
    if got not in BUILDS:
        sys.exit('This is not a supported mod build (md5 %s).\n'
                 'Supported: RTX Remix for Minecraft 0.1.1 (rtx-remix-renderer-0.1.1-202611060211-7d2ba9f) and 0.1.0 '
                 '(rtx-remix-renderer-0.1.0-202610230634-170197a), the unmodified jars from NVIDIA.' % got)
    version, jar_name = BUILDS[got]
    say('mod version %s' % version)

    say('taking the runtime DLL out of the jar ...')
    dll_orig = os.path.join(work, 'd3d9.orig.dll')
    with zipfile.ZipFile(jar) as z, open(dll_orig, 'wb') as f:
        f.write(z.read(DLL_ENTRY))
    dll_patched = os.path.join(work, 'd3d9.patched.dll')
    say('patching the shaders in the runtime (about 1-2 minutes) ...')
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'runtime-patch', 'build_runtime.py'), '--dll', dll_orig, '--out', dll_patched,
                        '--spirv-tools', a.spirv_tools] + DLL_ARGS)
    if r.returncode != 0 or not os.path.isfile(dll_patched):
        sys.exit('the shader patch failed (see above); nothing was written')
    dll_bytes = open(dll_patched, 'rb').read()

    prebuilt = collect_prebuilt(a.prebuilt, version)
    out_jar = os.path.join(a.out, jar_name[:-4] + '-LightFix.jar')   # never the same name as NVIDIA's jar
    tmp_jar = out_jar + '.part'
    say('writing the patched jar (about 1 minute) ...')
    replaced = added = 0
    with zipfile.ZipFile(jar) as zi, zipfile.ZipFile(tmp_jar, 'w') as zo:
        seen = set()
        for info in zi.infolist():
            name = info.filename
            seen.add(name)
            if name == 'fabric.mod.json':
                data = patch_manifest(zi.read(info))
            elif name == DLL_ENTRY:
                data = dll_bytes
            elif name in prebuilt:
                data = prebuilt[name]
                replaced += 1
            else:
                data = zi.read(info)
            zo.writestr(info, data, compress_type=info.compress_type)
        for name, data in prebuilt.items():
            if name not in seen:
                zo.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
                added += 1
    with zipfile.ZipFile(tmp_jar) as z:
        bad = z.testzip()
        if bad:
            sys.exit('written jar is corrupt at %s' % bad)
        assert z.read(DLL_ENTRY) == dll_bytes
        assert json.loads(z.read('fabric.mod.json'))['version'].endswith(VERSION_SUFFIX)
    if os.path.exists(out_jar):
        os.remove(out_jar)
    os.replace(tmp_jar, out_jar)
    say('')
    say('DONE: %s' % out_jar)
    say('  %d classes replaced, %d files added, shaders patched, DLL md5 %s'
        % (replaced, added, hashlib.md5(dll_bytes).hexdigest()))


if __name__ == '__main__':
    main()
