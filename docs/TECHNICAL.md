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

## Supporting NVIDIA 0.1.1 (2026-11)

* NVIDIA's 0.1.1 runtime (`d3d9.dll` 309,016,064 bytes) contains the **same 647 SPIR-V shader modules** as 0.1.0, byte for byte; only the order of nine of them
  differs. So the shader patches need no changes, but they must find their targets by content. `build_runtime.py` therefore accepts both md5s, finds the
  composite shader by its names (`CompositeArgs_natural`, `PrimaryLinearViewZ`, `primaryMiss`) and anchors the sky-fade edit structurally (the `OpLogicalNot` of the
  `primaryMiss` load in the `distanceMode == 3` branch, and the view-Z-equals-sentinel comparison) instead of the numeric ids `%18556 / %1039 / %848`.
  Rebuilding the 0.1.0 DLL with the structural anchors gives the identical md5 (`f259180a...`).
* The class hooks (`HookEmitter`, `HookLight`, `HookSettings`, `HookCategoryScreen`, `HookMeasure`) apply to 0.1.1 unchanged (same hook counts); the three methods
  that `BlockQuadEmitter` hooks touch pass ASM's `SimpleVerifier` (`Verify2.java`). `NativeExtractor` still re-extracts the natives when the version marker changes.
* Download speed: GitHub release downloads can crawl on a single connection while a browser is fast. `installer/fastdl.py` downloads in 16 MB chunks over 8
  connections (each chunk is its own Range request against the original URL, so the short-lived redirect never expires), retries stalled chunks and resumes.

## Reflections through glass and water (2026-11)

Symptom (stock Remix too): the reflection on a water surface disappears when it is seen through glass, through water, or through any stack of them.
Alt+X shows that turning off `PSTR Secondary Incident Split Approximation` brings it back.

What the shader does (read from the primary-ray `gbuffer_psr_*` modules, 108 of the 647 modules read the option):
* A loop crosses each see-through interface (PSTR). A per-ray counter is compared with `psrrMaxBounces` / `pstrMaxBounces` (RaytraceArgs members 43 / 44).
  A flag bit tracks "inside a medium", toggled when a transmission is set up.
* When the ray ENTERS a medium (flag becomes set) the interface is replaced iff `enablePSTRSecondaryIncidentSplitApproximation` (member 132); when it
  leaves one, iff `enablePSTROutgoingSplitApproximation` (member 131) together with the transmission lobe. A replaced interface multiplies the throughput by
  (1 - Fresnel) and its reflection is not drawn.
* An interface that is not replaced ends the loop and becomes the visible surface, shaded normally (reflection included).

Attempts, in order:
1. Exempting "water" by a measurement-distance test: the value read (`%162261`) is not the measurement distance (it is multiplied into radiance and used as a mix
   weight); the patch did nothing. Lesson: check what an SSA value IS before gating on it.
2. Ending the replacement at every later entering interface (`counter > 1`): fixes one glass or one water layer, but in a stack the replacement ends at a wall or pane
   that still has layers behind it, which then lose their reflection, and a water wall drawn as a visible surface uses the bluer non-replacement path.
3. Later entering interface AND horizontal (`|N.y| > 0.7`, N = the value normalised and passed to `Refract`): fixed the stacks, but looking UP through glass at water above, the
   ray enters the water through its bottom face, which ended the replacement and drew the water too blue.
4. Later entering interface whose normal points UP (`N.y > 0.7`, signed). The first interface, walls, panes and bottom faces stay as shipped.
5. Current (v5): rule 4 plus a medium-state restore. The sample call flips the state's inside-medium flag by reference, and after the continuation decision the loop records the
   medium it just entered (`mediumMaterialIndex`) whether or not the ray continues (`geometry_resolver.slangh`, "Set the material medium index if a medium was entered or exited").
   Stopping the replacement at the water top therefore left the pixel marked as already INSIDE the water, and the water top was shaded as seen from underneath (total internal
   reflection of the sky: a royal-blue water top under a glass roof, only for water behind another see-through layer). The patch stores "the rule fired in this iteration" in a
   Function bool and, just before that bookkeeping, puts the flag bit back to its pre-interface value. The bookkeeping is found structurally (`OpLogicalNot old`, branch, load of
   the flags ushort, `& 2`), in all 108 modules (some have it more than 4000 lines after the rule, so the search spans the module). Per module it is all or nothing, and
   `build_runtime.py` prints "medium state restored at N of them".

Patch: `runtime-patch/psr_water_patch.py`, option `--psr-water` of `build_runtime.py` (in the installer's DLL arguments). Counter, normal and the option read are found
structurally per module (unique in all 108); each patched module is validated with spirv-val. Gate: `ViewDistanceArgs.noiseScale > 20.0005` (Master Switch).
Assumption: the interface normal is in a space where up is +Y (Minecraft); if not, stacks behave as stock.

Related observation: with PSR reflection and transmission switched off in Alt+X, water looks very blue. That is stock behaviour; the medium-state bug above does not explain it
(there the replacement never starts), and the cause is not isolated.

## Water seen by bounce rays (2026-11)

Symptom: a water column reflected by a water or glass surface and seen through glass was royal blue (cyan when looked at directly), and the bounce light under water was blue.

Mechanism (read from `resolve.slangh` and the compiled indirect-ray modules): with `rtx.enableTransmissionApproximationInIndirectRays` on (shipped; the mod keeps it), the indirect-ray
resolve does not return a hit for a translucent surface. It multiplies the throughput by the surface colour and sends the ray straight on ("translucent objects hit by indirect rays will
not alter ray direction"). A reflected ray that meets a water column flies through it, out of its top and into the sky: a tinted window, no refraction, no total internal reflection,
no absorption by depth. Stock Remix hides this because the same water seen directly is handled by the primary-ray replacement with distance based absorption.

Fix: `runtime-patch/water_reflect_patch.py` (`--water-reflect`) makes the approximation false for hits on WATER only: both tests of resolveMode bit 6
(`resolveModeTranslucencyTransmissionApprox`) ahead of the per-hit colour multiply become `approx && !(live && isWater)`. The water is then an ordinary hit and the integrator
refracts, reflects, tracks the medium and absorbs by distance, as stock does with the option off. Glass keeps the approximation. 152 indirect-ray modules (those that read the option;
the primary-ray modules have the mode constant false) are patched.

Detecting water: `MemoryPolymorphicSurfaceMaterial` is `uvec4 data[4]`; for a translucent material the refractive index is a half float in the high 16 bits of `data[1].y`
(`UnpackHalf2x16(...).y`) and the measurement distance in the high 16 bits of `data[0].w`. The mod's water has IOR 1.33, every glass-like material 1.52, so `1.1 < IOR < 1.425` is
water. **Versions 1 and 2 tested the animated-water surface flag** (bit 24 of surface word 3), which Remix sets only for instances in the AnimatedWater category (or textures listed in
`rtx.animatedWaterTextures`); this mod does neither, so those versions never fired and three user tests showed no change. Lesson: before building on a gate, find who sets it.
The earlier "water gate" in `bounce_tint_patch.py` used the same dead flag and was removed.

## Second set of shadows on subsurface materials (2026-11)

Symptom: seen through the surface of water, the floor showed a second, lighter, shifted set of shadows, about twice as refracted as it should be; from under the water only the right set.
Only blocks with a subsurface scattering profile (sand, sandstone, snow and similar, from the RTX Remix Materials pack) showed it, only with RTXDI on, and "Enable Diffusion Profile"
in Alt+X removed it.

Mechanism (`rtxcr_material.slangh`, `evalSssDiffusionProfile`, inlined into integrate_direct): each diffusion-profile sample point is lit with a light taken from the RTXDI reservoir of
`samplePixelCoordinate`, the screen pixel the sample's REAL world position projects to. For a pixel reached through water or glass (primary surface replacement) that pixel shows
another spot, so the lighting followed that spot's shadows. Stock only falls back to ordinary light selection when the sample projects off screen.

Fix: `runtime-patch/sss_psr_patch.py` (`--sss-psr`): the inside-screen test also requires that `GeometryFlags.performPSTR | performPSRR` (bits 7 and 8) are clear, live-gated. Two modules
(integrate_direct, ray-generation and compute variants), four sites.

## Better Colored Glass GI (2026-11)

A menu option (off by default) that, while the master switch is on, writes `rtx.neeCache.enableOnFirstBounce = False` through the Remix bridge (OFF or master switch off restores the value the
runtime started with). The NEE cache samples emissive blocks on the first bounce with a visibility ray that does not see glass, so lamp and sea-lantern light can stay white through coloured glass;
with the cache off on the first bounce that light is traced through the glass and takes its colour, at some cost in speed. It lives in `TranslucentFixToggle` (state and option write) and
`LightTransformSettings` (menu entry).
