"""Texture blend/horizon fix, runtime side: cap the mip chain of marked Remix API memory textures (x86 patch of d3d9.dll).

Why: the mod copies Minecraft's whole stitched block atlas into 4096x4096 textures (albedo, emissive, normal, roughness, metallic,
SSS) and uploads them with createTextureFromMemory. The runtime then builds a full mip chain for every such texture
(mipLevels = 1 + floor(log2(max(w,h))), 13 for 4096) with a whole-image 2x2 downsample (DxvkContext::generateMipmaps) that knows
nothing about sprites. Wide ray cones (indirect rays with rtx.indirectRaySpreadAngleFactor > 0, distant terrain at grazing angles)
read the coarse levels, where unrelated sprites are averaged together: LabPBR normal/specular maps stitched next to the albedo make
GI and the horizon violet, warm neighbours make them red, and lava/fire/lamp sprites leak into the emissive atlas so distant quartz
and other blocks glow. Every sprite is padded to a multiple of 16 px and placed on a 16-px boundary, so levels 0..4 stay inside each
sprite; capping the chain at N = 5 levels keeps every level pure.

How: the function that creates API memory textures computes the level count once, into r12d, in a 48-byte loop (RVA 0x20eeea in the
0.1.1 runtime). This patch rewrites that loop, same size, so the count is capped at N only when the low 16 bits of the texture hash
equal MARK. The mod (GlassContactFaces.texHash, hooked into RemixTexture.doCreate) sets that marker on large atlas textures while
the master switch and the "Texture blend/horizon fix" setting are on, and makes sure no other texture carries it, so the toggle
lives entirely in the mod. Unmarked textures get the shipped full chain.

  mov eax,[rsi+0x20] ; cmp eax,[rsi+0x24] ; cmovb eax,[rsi+0x24]   eax = max(width, height)
  mov r12d,1 ; or edx,-1                                             levels = 1, cap = none
  cmp word [rsi],MARK ; jne +5 ; mov edx,N                           marked: cap = N
  nop5 ; top: shr eax,1 ; jz end ; inc r12d ; cmp r12d,edx ; jb top

rsi points at the texture info whose first qword is the hash (it is also the key of the runtime's texture map), +0x20 width,
+0x24 height. The original bytes are checked before anything is written.

Credit: the atlas cause (LabPBR maps stitched into the block atlas, read at coarse mips) was found by kazumasa200.

Usage: x86_mipcap.py in.dll out.dll [--levels 5]       (also importable: patch(bytearray, levels) -> info)
"""
import struct
import sys

RVA = 0x20eeea
LENGTH = 0x30
ORIG = bytes.fromhex('b920000000ba24000000448d61e18b4624394620'
                     '0f42ca8b0431413bc476110f1f8000000000d1e8'
                     '41ffc483f80177f6')
MARK = 0xB13D        # low 16 bits of a marked texture hash (must match GlassContactFaces.MIP_MARK)
DEFAULT_LEVELS = 5


def new_code(levels):
    assert 1 <= levels <= 0x7f
    code = bytes.fromhex(
        '8b4620'            # mov eax,[rsi+0x20]
        '3b4624'            # cmp eax,[rsi+0x24]
        '0f424624'          # cmovb eax,[rsi+0x24]
        '41bc01000000'      # mov r12d,1
        '83caff'            # or edx,-1
        '66813e' + struct.pack('<H', MARK).hex() +   # cmp word [rsi],MARK
        '7505'              # jne +5
        'ba' + struct.pack('<I', levels).hex() +     # mov edx,levels
        '0f1f440000'        # nop5
        'd1e8'              # top: shr eax,1
        '7408'              # jz end
        '41ffc4'            # inc r12d
        '4139d4'            # cmp r12d,edx
        '72f4')             # jb top
    assert len(code) == LENGTH, len(code)
    return code


def rva_to_offset(data, rva):
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    nsec = struct.unpack_from('<H', data, pe + 6)[0]
    opt = struct.unpack_from('<H', data, pe + 20)[0]
    sec = pe + 24 + opt
    for i in range(nsec):
        vsize, va, rsize, raw = struct.unpack_from('<IIII', data, sec + i * 40 + 8)
        if va <= rva < va + max(vsize, rsize):
            return raw + (rva - va)
    raise ValueError('RVA not in any section')


def model(w, h, hash_lo16, levels):
    m = max(w, h)
    n = 1
    while m > 1:
        m >>= 1
        n += 1
    return min(n, levels) if hash_lo16 == MARK else n


def emulate(code, w, h, hash_lo16):
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64
    from unicorn.x86_const import UC_X86_REG_RSI, UC_X86_REG_R12, UC_X86_REG_RSP, UC_X86_REG_RDX
    mu = Uc(UC_ARCH_X86, UC_MODE_64)
    mu.mem_map(RVA & ~0xfff, 0x2000)
    mu.mem_write(RVA, code)
    mu.mem_map(0x100000, 0x1000)
    mu.mem_map(0x200000, 0x1000)
    mu.mem_write(0x100000, struct.pack('<Q', 0x1234567800000000 | hash_lo16))
    mu.mem_write(0x100020, struct.pack('<II', w, h))
    mu.reg_write(UC_X86_REG_RSI, 0x100000)
    mu.reg_write(UC_X86_REG_RSP, 0x200800)
    mu.reg_write(UC_X86_REG_R12, 0xdead)
    mu.reg_write(UC_X86_REG_RDX, 0x77777777)
    mu.emu_start(RVA, RVA + LENGTH)
    return mu.reg_read(UC_X86_REG_R12) & 0xffffffff


def patch(data, levels=DEFAULT_LEVELS):
    off = rva_to_offset(data, RVA)
    cur = bytes(data[off:off + LENGTH])
    if cur != ORIG:
        raise RuntimeError('x86 mip cap: original bytes not found at RVA 0x%x (unsupported runtime build?)' % RVA)
    code = new_code(levels)
    bad = 0
    try:
        for w, h in [(0, 0), (1, 1), (2, 1), (16, 16), (64, 64), (512, 256), (1024, 1024), (2048, 2048), (4096, 2048), (4096, 4096), (3000, 5000)]:
            for lo in (MARK, MARK ^ 1, 0):
                bad += emulate(code, w, h, lo) != model(w, h, lo, levels)
        emulated = True
    except ImportError:
        emulated = False
    if bad:
        raise RuntimeError('x86 mip cap: emulation mismatch (%d cases)' % bad)
    data[off:off + LENGTH] = code
    return {'offset': off, 'levels': levels, 'emulated': emulated}


def main():
    args = sys.argv[1:]
    levels = DEFAULT_LEVELS
    if '--levels' in args:
        i = args.index('--levels')
        levels = int(args[i + 1])
        del args[i:i + 2]
    src, dst = args
    data = bytearray(open(src, 'rb').read())
    info = patch(data, levels)
    open(dst, 'wb').write(data)
    print('x86 mip cap: file offset 0x%x, %d levels for marked textures, emulation %s' %
          (info['offset'], info['levels'], 'passed' if info['emulated'] else 'skipped (unicorn not installed)'))


if __name__ == '__main__':
    main()
