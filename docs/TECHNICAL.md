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

## Later additions (2026-11)

* **Live channels.** The patched shaders read `RaytraceArgs.viewDistanceArgs`: `noiseScale` (shipped 20) is the on/off flag (`> 20.0005`) and carries the
  saturation (`20.001 + 0.0001 * percent`), `distanceFadeMin` (shipped 358.4) carries the pane depth (`358.4 + 0.00001 * percent`). A value in
  `user.conf` outranks runtime writes, so keep both keys out of it. The companion mod re-reads both once a second and rewrites them on drift.
* **Brightness lift is saturation weighted.** `scale = 1 + (CLEAR / max - 1) * (1 - min / max)` in `shadow_ray_patch.py` and `bounce_tint_patch.py`.
  The unweighted version (`scale = max(CLEAR / max, 1)`) turned black glass (linear 0.0097) into 0.9 per 0.35 m, i.e. almost clear.
* **Primary-ray miss branch** (`gbuf_patch.py`): a ray that hits nothing is treated as inside an infinite medium, so any absorbing medium gives black.
  Black sky behind glass or water means the ray still believes it is inside a medium (missing or coplanar faces), not that the sky is dark.
  `--miss-probe` draws that case pink (glass) or green (water) for diagnosis.
* **Coplanar faces.** Vanilla culls only the face between blocks of the same kind. Different glass colours (and glass against water) emit two faces
  on one plane; the hit order is then arbitrary per ray, which breaks medium tracking. `GlassContactFaces.lift` also pulls a glass face that touches
  another glass-like block 4 mm inward (`separateGlass`), leaving an 8 mm hairline of air between the two.
* **Material constants.** `HookMeasure.java` patches the two `ldc 0.35f` glass measurement distances and the water blue transmittance in
  `BlockTextureManager`; those materials are built once per resource load, so these settings apply after a reload or restart.
* **Sun size.** `LightManager.updateDistantLight` receives the sun (0.53 deg) and moon (0.52 deg) diameters as a parameter; `HookLight.java`
  scales them. The real sun gives a penumbra of about 1 cm per metre, which looks razor sharp at block scale.
* **Settings UI.** `KeyBindButton` extends `ButtonWidget` and uses the game's own `KeyBinding` objects (click, press a key); `patch_jar.py` copies each helper
  class as exactly one class file, so helper classes must not have nested classes or enums (lambdas are fine).
* **Building shaders without `spirv-val`.** `build_runtime.py` runs without it and only checks a disassembly round trip; a type or logic error would not be
  caught. Prefer a full SPIRV-Tools set.
* **Unexplained.** A violet/blue cast in skylit shade and under glass also appears with all of these mods off, so it is stock Remix behaviour.
  Measured on one screenshot, a white floor had r/g 1.17-1.24 and b/g 1.08-1.22 even in direct sun (green suppressed everywhere).
