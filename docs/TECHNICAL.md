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
SIG += sigma_i                      # sum of the sigma of every translucent hit
X   += k * s_i * t_i                # net path length inside translucent media (k = --k, 1.0 physical)
N   += k * s_i                      # net entries minus exits
n   += 1                            # hit count
per-hit factor = 1                  # the old constant tint is removed
after the loop:  attenuation *= min(exp(-(SIG / max(n,1)) * (X + max(-N, 0) * min(tMax, 1024))), 1)
```

(Until 2026-11-14 the sum was `A += k * s_i * sigma_i * t_i`, `C += k * s_i * sigma_i`, with every hit's own sigma. Ray-query candidates arrive
in arbitrary order and an entry face and its exit face can carry different material colours, so some channels got negative optical depth and the
sunlit floor under coloured glass showed the complement colour (magenta under green glass). Only the sun showed it, because its `tMax` cap is huge.
Taking the mean sigma times a path length that is common to all channels cannot invert the hue. For a single crossing of one glass it equals the old
formula; stacks of different colours are averaged, which matches the old result when the layers are about equally thick.)

* A paired entry/exit at t_in < t_out gives sigma * (t_out - t_in).
* A ray that **starts inside** a medium sees an unpaired exit: X = t_exit, which is correct with no extra term.
* A ray that **ends inside** sees an unpaired entry: X = -t_in and N = -1, so the `max(-N,0) * tMax` term adds the rest.
  The distant sun sits ~1e5 away, hence the `min(tMax, 1024)` cap (it keeps a missing face from producing inf or NaN).
* Light that starts inside glass and ends inside glass without any crossing is the one uncovered case.
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

* **Live channel.** The patched shaders read ONE value, `RaytraceArgs.viewDistanceArgs.noiseScale` (shipped 20, read by nothing else): `20 + m / 2^19` with
  `m = 512 + 64 * saturation% + p`, `p = pane depth% / 5` (0..63, pane depth K = p * 0.05). Every such value is an exact float. OFF is exactly 20, ON is
  anything above 20.0005. The shaders decode the saturation as `(noiseScale - 20.0009765625) * 81.92` (two instructions: the patched modules have almost no
  size slack; the pane step adds at most 0.009 to it) and the pane depth with integer operations (`(m - 512) & 63`). A value in `user.conf` outranks
  runtime writes, so keep the key out of it. Two earlier channels failed: `distanceFadeMin` is rewritten by the automatic view-distance layer whenever the
  render distance is below 32 chunks (pane depth silently died), and `hairCardRoughnessScale` is multiplied into the translucent colour scale by most
  stock shaders (glass turned white). Check every reader of an option before using it as a channel.
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
  scales them. The real sun gives a penumbra of about 1 cm per metre, which looks razor sharp at block scale. The slider defaults to 100% (the shipped
  size); larger values give softer shadow edges and, with the denoiser, a smearier sun.
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
* Download speed: GitHub release downloads can crawl on a single connection while a browser is fast. `installer/fastdl.py` (16 MB chunks over 8 connections, each chunk its own Range request, retries, resume) was the installer's way to fetch the mod jar. The installer no longer downloads the mod at all: it patches only the original jar that sits next to the `.bat`, matched by size and MD5. The helper is kept in the repository in case a download fallback comes back.

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

## The NEE cache and emissive light through glass and water (2026-11)

How the NEE cache works (read from `nee_cache.h`, `nee_cache_light.slangh`, `update_nee_cache.comp.slang`, `integrate_nee.comp.slang`, `integrator_indirect.slangh`):
* The world around the camera is a hashed log grid of cells (finer near the camera). Each cell holds candidates (emissive triangle ranges with a sampling probability, and analytic lights) and a
  few stored sample points (position, normal, raw emissive radiance, pdf).
* Learning: integrators call `cell.insertSlotTask(task, radiance)` with the light that SURVIVED their shadow ray, into a hash-slot buffer (atomic max / add, luminance quantised). The update pass
  (`update_nee_cache`) merges the slots with the old candidates, decays them (`learningRate`, `ageCullingSpeed`, `cullingThreshold`), explores neighbouring triangles, and writes the new
  candidate probabilities and sample points. **The update pass traces no rays**, so the cache itself never sees glass.
* Query: `integrate_nee` (first bounce, only when the primary surface is opaque and `enableOnFirstBounce`) and the indirect integrator (later bounces) pick a cell, draw a candidate, build the light
  sample, weight it by MIS against the BSDF sample and trace ONE visibility ray (`evalNEESecondary`), whose attenuation multiplies the accumulated light. The mask of that ray adds the translucent
  bit only with `rtx.enableIndirectTranslucentShadows` (true in NVIDIA's Minecraft `rtx.conf`, default false in Remix).

The leak: in the ReSTIR GI variant of `integrate_nee`, when the visibility ray was not blocked by an opaque surface (glass does not block), the sample is also stored in the ReSTIR GI initial
reservoir as `min(lightSample.radiance / lightSample.solidAnglePdf, float16 max)`, the raw emissive radiance. ReSTIR GI's final shading applies `reservoir.radiance * BRDF * avgWeight` with a final
visibility ray (`restirGI.useFinalVisibility`) whose mask is `OPAQUE | dynamic | ALPHA_BLEND` and whose mode lacks translucent materials, so it cannot see glass or water. The directly accumulated
NEE light was tinted, the redistributed copy was not: white light through coloured glass, untinted light through water. (The earlier workaround, switching the cache off on the first bounce,
removed the copy but also the noise reduction.)

Fix: `runtime-patch/nee_reservoir_patch.py` (`--nee-reservoir`) multiplies the reservoir radiance by the visibility attenuation, live-gated (`noiseScale > 20.0005`, otherwise the shipped value).
The attenuation vector is the one the shader multiplies into `diffuseLight` / `specularLight` (found structurally); the reservoir site is the `FDiv` by the pdf followed by the float16-max clamp. One
module, one site (the ReSTIR GI variant of `integrate_nee`); validated with spirv-val. The menu switch that was briefly added as a workaround for this was removed again.

## GI Spread and reach (2026-11)

A menu button (integer setting 0..3 shown by `CycleButton`, a `ButtonWidget` that steps the value and wraps; `LightTransformUi` uses it instead of a slider for `light.giReach`, default 2) that, with the
master switch on, writes two Remix options through the bridge:

| Level | `rtx.enableRussianRoulette` | `rtx.indirectRaySpreadAngleFactor` |
|---|---|---|
| Off (0) | True (Remix) | 0.05 (Remix) |
| Low (1) | False | 0.05 |
| Medium (2, default) | False | 0.025 |
| High (3) | False | 0.0 |

Russian roulette ends paths early at random and compensates by boosting the survivors; in practice indirect light then grows stronger the closer you get to a surface, because the termination
probability depends on the path throughput. The spread angle factor (Remix default 0.05, range 0-1) widens a ray's cone after an indirect BRDF sample to prefilter the lobe; smaller values keep
the lobe sharper. With the setting at Off, or the master switch off, the mod writes Remix's own defaults, so Off is the original rendering whatever an earlier Alt+X session left in `rtx.conf`.
A value pinned in `user.conf` outranks the mod's runtime writes, so keep both keys out of it. This replaced the first version, an on/off "Better GI" (Russian roulette off and 0.02).

## Bounce limit for water (2026-11)

Because `water_reflect_patch` makes water a real surface for bounce rays, a path through a water column refracts in, may reflect inside it and refracts out, and glass layers add more. With Remix's default
`rtx.pathMaxBounces = 4` such paths end before they reach the sky or a light and the reflection comes out **black** (seen after a settings reset removed an Alt+X-saved `pathMaxBounces = 8`). The mod
therefore writes `rtx.pathMaxBounces = 8` while the master switch is on and Remix's own 4 when it is off, so the fix does not depend on a hand-edited `user.conf`. A value pinned in `user.conf` outranks it.

## Indirect integration mode (2026-11)

Every patch here was built and tested with `rtx.integrateIndirectMode = 1` (ReSTIR GI); the NEE reservoir fix exists only in the ReSTIR GI variant of `integrate_nee`. Remix's own default is 3 (SHaRC, a
spatially hashed radiance cache whose paths stop early by looking up stored radiance), which is what a profile without that line gets. After a settings reset the reflection of water seen through glass
went black in mode 3. The mod therefore writes `rtx.integrateIndirectMode = 1` while the master switch is on and Remix's 3 when it is off, next to `rtx.pathMaxBounces = 8` / 4. A value pinned in `user.conf` outranks both.
