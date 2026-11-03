# Technical notes

## How the problem was found

* The mod builds water, stained glass and clear glass as Remix **Translucent** materials (`BlockTextureManager.java`: IOR 1.33 / 1.52,
  transmittance 0.6,0.9,0.89 for water, albedo-atlas transmittance texture for stained glass, a constant 0.97 grey for clear glass,
  measurement distance 0.35 m for glass and 1 m for water). None is thin-walled; nothing in the mod calls `thinWall(...)`.
* **Do not trust the public dxvk-remix source for this runtime.** Public `visibility.slangh` returns `vec3(1)` for thick translucents on
  shadow rays, so the first diagnosis was "no tint at all". Disassembling the embedded SPIR-V of the shipped build showed the opposite:
  the thick branch multiplies the ray by `exp(-sigma * d)` with `sigma = -ln(T)/d` and `d` the measurement distance, which collapses to
  exactly `T`, once per hit, independent of depth.
* The shipped DLL has no shader hot-reload (it is behind `REMIX_DEVELOPMENT`) and no public source exists at API 0.16 (the mod's
  `packman` pin points at a binary-only build), so the route is a binary patch of the shaders.

## The DLL

* 647 raw SPIR-V 1.5 modules sit in `.rdata`. Each is referenced from `.text` by a `lea` plus a `mov r32, <word count>`: sizes are baked
  in, so every patched module is reassembled to **exactly** its original size. The builder strips `OpName`/`OpMemberName` debug info
  (nothing in dxvk reads it) and pads with one `OpModuleProcessed` string.
* A module's real length is found by walking instructions to the last `OpFunctionEnd`. Do not use the distance to the next module.
* Candidate shadow-ray modules are found by anchor, not by name: a `Log` whose operand is a clamped transmittance, divided by a
  vector built from one scalar that is also compared `< 0` shortly before (the thin-walled test), inside a ray-query `Proceed` loop that
  also reads `OpRayQueryGetIntersectionTypeKHR ... %uint_0`. The RTXDI reuse and ReSTIR-GI modules have loops but no translucent
  evaluation, so they are left alone.
* Pipeline cache: `javaw.dxvk-cache` is keyed by shader hash. Patched shaders simply miss it; delete the file anyway.

## Shadow-ray absorption

For each candidate hit `i` of a visibility ray with material coefficient `sigma_i = -ln(T_i) / d_i` (T is lerp(constant, texture) and
gamma corrected by the runtime; `T` is clamped to >= 1/1024 before the log):

```
s_i = frontFace ? -1 : +1          # raw hardware facing (OpRayQueryGetIntersectionFrontFaceKHR), not the view-flipped normal
A  += k * s_i * sigma_i * t_i       # k = --k, 1.0 physical
C  += k * s_i * sigma_i
per-hit factor = 1                  # the old constant tint is removed
after the loop:  attenuation *= exp(-(A + max(-C, 0) * min(tMax, 1024)))
```

* A paired entry/exit at t_in < t_out gives sigma * (t_out - t_in).
* A ray that **starts inside** a medium sees an unpaired exit: A = sigma * t_exit, which is correct with no extra term.
* A ray that **ends inside** sees an unpaired entry: A = -sigma * t_in and C = -sigma, so the `max(-C,0) * tMax` term adds the rest.
  The distant sun sits ~1e5 away, hence the `min(tMax, 1024)` cap (it keeps a missing face from producing inf or NaN).
* Mixed media work because each hit carries its own sigma. Light that starts inside glass and ends inside glass without any crossing
  is the one uncovered case.
* Coplanar duplicate surfaces cancel exactly, which is why the water's reversed top quad has to go.
* Fault sign: if front/back polarity is wrong, paired crossings give `exp(+sigma L)`, i.e. *brighter* behind glass than without it.

## Sky through glass

Primary rays through glass/water go through Remix's "primary surface transmission replacement". When such a ray ends in sky the
resolver adds `sky * radianceAttenuation` correctly, but in `composite.comp` the distance fade (`viewDistanceModeCoherentNoiseSmoothPrimary`)
runs for every pixel that is not `primaryMiss`, and a replaced pixel's stored view Z is the NRD miss sentinel (`denoisingRangeLimit + 1`), far past
the fade end. The fade then lerps to untinted sky at 100%. The patch makes the guard `!(primaryMiss || viewZ == missSentinel)`.
(Public source shows the same structure; the runtime build was patched by disassembly anchors `%18556`, `%1039`, `%848`.)

## The mod jar

* Vanilla's `Block.shouldDrawSide` hides the glass face against an opaque block. `GlassContactFaces.force` is called with vanilla's answer
  before both `return`s of `shouldDrawBlockSide` and flips it to "draw" when the block is glass-like (`classifyBlockLayer` is `glass` or
  `translucent`) and the neighbour is an opaque full cube. `GlassContactFaces.lift` is called in `stageBakedQuad` and `emitFrapiBlock` and moves a
  quad lying exactly on a block face with an opaque neighbour by 4 mm inward.
* Compiled names are intermediary (`class_2680` = BlockState, `method_26225` = isOpaque, `method_26216` = isOpaqueFullCube, `method_8320` =
  getBlockState); the helper is compiled against `client-intermediary.jar` and hooked by ASM. The three edited methods were type-checked with
  `Verify2.java` (ASM `SimpleVerifier`). Insertion points are straight-line, so stack-map frames stay valid and only max stack is recomputed.
* `water_quad_patch.py` finds `setPos4, setUv4, writeFluidQuad, setPos4, writeFluidQuad` in `emitFluidQuads` and NOPs the second quad statement,
  refusing to run if a branch or stack-map target lands inside the range.

## Gotchas

* Close Minecraft before copying anything in; a running game leaves the old files without an error. Check the md5 after copying.
* The mod re-extracts the runtime when `.rtx-remix-version` differs from the jar version.
* Remix's own UI rewrites `rtx.conf`; keep your overrides in `user.conf`.

## Open questions

* The internal runtime may still differ from what the anchors assume outside the matched sites; the patch was only run against the build above.
* Water over an opaque block lacks the bottom face as well. The same helper idea applies to the fluid emitter.
* Everything here should be an upstream change: a runtime change to absorb by travelled distance for thick translucents on shadow rays, a fix for the fade on
  replaced pixels, and a mod change to keep contact faces and emit one water top quad.
