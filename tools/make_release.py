"""Maintainer tool: build the one-click installer package (a zip with Make-Patched-Mod.bat) for a GitHub release.

The package holds our scripts and the compiled classes that differ from NVIDIA's jar (the modified copies of NVIDIA's Apache-2.0
classes plus our own helpers and the companion mod). It does NOT hold NVIDIA's DLL or jar: the installer downloads those from NVIDIA.

Inputs (all built from this repository with mod-patch/patch_jar.py and a plain javac build of toggle-mod/):
  --build VERSION PRISTINE PATCHED   repeatable: NVIDIA's original jar of that mod version (to find which classes differ) and the
                                     jar patch_jar.py produced from it, e.g. --build 0.1.1 orig011.jar patched011.jar
  --toggle    the companion mod jar built from toggle-mod/ (same for every version)
Usage: python tools/make_release.py --build 0.1.1 A.jar B.jar --toggle T.jar --out dist/RemixGlassFix-Installer.zip --bat dist/X.bat
"""
import argparse
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {'fabric.mod.json', 'native/remix-sdk-win64/d3d9.dll'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', nargs=3, action='append', metavar=('VERSION', 'PRISTINE', 'PATCHED'), required=True)
    ap.add_argument('--toggle', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--bat', help='also write the single-file installer (everything embedded in one .bat)')
    a = ap.parse_args()

    prebuilt = {}
    for version, pristine, patched in a.build:
        with zipfile.ZipFile(pristine) as p, zipfile.ZipFile(patched) as q:
            crc = {i.filename: i.CRC for i in p.infolist()}
            changed = {}
            for i in q.infolist():
                if i.filename in SKIP or i.filename.endswith('/'):
                    continue
                if crc.get(i.filename) != i.CRC:
                    changed[i.filename] = q.read(i)
        print('mod %s: classes differing from NVIDIA\'s jar: %d' % (version, len(changed)))
        for n in sorted(changed):
            print('  ', n)
            prebuilt[version + '/' + n] = changed[n]
    common = {}
    with zipfile.ZipFile(a.toggle) as t:
        for i in t.infolist():
            n = i.filename
            if n.startswith('purrsian/') and n.endswith('.class') or n.startswith('assets/translucent-light-fix-toggle/') and not n.endswith('/'):
                prebuilt['common/' + n] = t.read(i)
                common[n] = 1
    if not any(n.startswith('purrsian/') for n in common):
        sys.exit('no companion mod classes found in the toggle jar')

    top = 'RemixGlassFix'
    files = [('Make-Patched-Mod.bat', os.path.join(ROOT, 'installer', 'Make-Patched-Mod.bat')),
             ('installer/install.ps1', os.path.join(ROOT, 'installer', 'install.ps1')),
             ('installer/build_patched_jar.py', os.path.join(ROOT, 'installer', 'build_patched_jar.py')),
             ('installer/extract_conda.py', os.path.join(ROOT, 'installer', 'extract_conda.py')),
             ('installer/fastdl.py', os.path.join(ROOT, 'installer', 'fastdl.py')),
             ('README-INSTALL.txt', os.path.join(ROOT, 'installer', 'README-INSTALL.txt')),
             ('LICENSE', os.path.join(ROOT, 'LICENSE')), ('NOTICE', os.path.join(ROOT, 'NOTICE'))]
    for f in sorted(os.listdir(os.path.join(ROOT, 'runtime-patch'))):
        if f.endswith('.py'):
            files.append(('runtime-patch/' + f, os.path.join(ROOT, 'runtime-patch', f)))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with zipfile.ZipFile(a.out, 'w', zipfile.ZIP_DEFLATED) as z:
        for arc, path in files:
            z.write(path, top + '/' + arc)
        for n, data in sorted(prebuilt.items()):
            z.writestr(top + '/prebuilt/' + n, data)
    print('wrote', a.out, os.path.getsize(a.out), 'bytes')
    if a.bat:
        write_single_bat(a.out, a.bat)


BAT_LINES = [
    '@echo off',
    'title RTX Remix for Minecraft - glass and water light fix',
    'set "RGF_BAT=%~f0"',
    'set "RGF_OUT=%~dp0"',
    'echo.',
    'echo  Making the patched mod. This window stays open until it is finished.',
    'echo.',
    'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference=\'Stop\'; '
    '$lines=[IO.File]::ReadAllLines($env:RGF_BAT); $i=[Array]::IndexOf($lines,\'::PAYLOAD\'); '
    '$b64=-join $lines[($i+1)..($lines.Length-1)]; '
    '$dir=Join-Path $env:RGF_OUT \'RemixGlassFix-files\'; New-Item -ItemType Directory -Force $dir | Out-Null; '
    '$zip=Join-Path $dir \'payload.zip\'; [IO.File]::WriteAllBytes($zip,[Convert]::FromBase64String($b64)); '
    'Expand-Archive -Force $zip $dir; '
    '& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dir \'RemixGlassFix\\installer\\install.ps1\'); '
    'exit $LASTEXITCODE"',
    'echo.',
    'pause',
    'exit /b',
    '::PAYLOAD',
]


def write_single_bat(zip_path, bat_path):
    """One self-contained .bat: a batch header, then the installer zip as base64 after the ::PAYLOAD line (never executed)."""
    import base64
    b64 = base64.b64encode(open(zip_path, 'rb').read()).decode('ascii')
    lines = BAT_LINES + [b64[i:i + 76] for i in range(0, len(b64), 76)]
    with open(bat_path, 'wb') as f:
        f.write(('\r\n'.join(lines) + '\r\n').encode('ascii'))
    print('wrote', bat_path, os.path.getsize(bat_path), 'bytes')


if __name__ == '__main__':
    main()
