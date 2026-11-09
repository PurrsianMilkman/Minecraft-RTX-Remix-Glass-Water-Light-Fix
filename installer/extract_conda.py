"""Take spirv-as / spirv-dis / spirv-val (and the DLLs next to them) out of a conda-forge spirv-tools package (.conda).

A .conda file is a zip that holds pkg-*.tar.zst. Decompressing zstd needs Python 3.14 (compression.zstd), which is why the
installer downloads the 3.14 embeddable Python.

Usage: python extract_conda.py spirv-tools.conda <output folder>
"""
import io
import os
import sys
import tarfile
import zipfile


def main():
    pkg, out = sys.argv[1], sys.argv[2]
    try:
        from compression import zstd
    except ImportError:
        sys.exit('this needs Python 3.14 or newer (compression.zstd)')
    os.makedirs(out, exist_ok=True)
    with zipfile.ZipFile(pkg) as z:
        inner = [n for n in z.namelist() if n.startswith('pkg-') and n.endswith('.tar.zst')]
        if len(inner) != 1:
            sys.exit('unexpected package layout: %r' % z.namelist())
        raw = zstd.decompress(z.read(inner[0]))
    wanted = {'spirv-as.exe', 'spirv-dis.exe', 'spirv-val.exe'}
    got = set()
    with tarfile.open(fileobj=io.BytesIO(raw)) as t:
        for m in t.getmembers():
            base = os.path.basename(m.name)
            if m.isfile() and (m.name.replace('\\', '/').startswith('Library/bin/') and (base in wanted or base.lower().endswith('.dll'))):
                data = t.extractfile(m).read()
                with open(os.path.join(out, base), 'wb') as f:
                    f.write(data)
                if base in wanted:
                    got.add(base)
    missing = wanted - got
    if missing:
        sys.exit('missing from the package: %s' % ', '.join(sorted(missing)))
    print('extracted', ', '.join(sorted(got)))


if __name__ == '__main__':
    main()
