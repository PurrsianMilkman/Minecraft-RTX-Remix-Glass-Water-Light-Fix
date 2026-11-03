# RTX Remix for Minecraft: coloured light through water and glass

Fixes for [NVIDIA's RTX Remix for Minecraft](https://github.com/NVIDIAGameWorks/rtx-remix-minecraft) (Fabric, 1.21.1) where
**water and glass did not colour the light that passes through them**: light from torches, sea lanterns and the sun, and the
sky seen through glass. Nothing is thin-walled, glass keeps refracting and water keeps its look.

This repository contains **patch scripts only**. It ships no NVIDIA binaries, no shader dumps and no game assets: the scripts
patch *your own* copy of the mod jar and runtime DLL, and refuse to run on anything but the exact builds listed below.
Not affiliated with NVIDIA, Mojang or Microsoft. Use at your own risk and keep backups (see "Restore").

## Status (honest version)

| Fix | State |
|---|---|
| Sky seen through glass/water was untinted: cause found | **Confirmed in game** (turning the distance fade off made the tint appear) |
| Sky fade patch (keeps the fade, stops it overwriting tinted sky) | Installed, not yet confirmed with the fade on |
| Light through glass/water absorbed by distance travelled (shadow rays) | Installed. In game the light came out tinted but a bit dim through red glass, hence the `--k` knob |
| Glass touching an opaque block gets a real exit face | **Confirmed in game** |
| Water top face emitted once instead of twice | Installed, untested on its own |
| Skylight bounces refract and absorb by depth (`user.conf` setting) | Installed, costs some FPS |

## Supported builds (the scripts check this)

* Mod: `rtx-remix-renderer-0.1.0-202610230634-170197a.jar` (source commit `170197a`)
* Runtime: `remix-sdk/d3d9.dll`, md5 `cbe2d49f543b608a7ac45d6b2c6631ae`, 309,009,920 bytes (`remix-main+71a581da`, API 0.16.0)

The runtime is an internal NVIDIA build whose source is not public (the mod's `CONTRIBUTING.md` says so), and public
`dxvk-remix` speaks a different API version, so the fix is a **size-preserving patch of the SPIR-V shaders embedded in the DLL**.

## What was wrong, and what we changed

1. **Block light and sunlight ignored the glass's thickness.** The shipped shaders multiply a shadow ray by the material colour
   once per surface it crosses, whatever the thickness. So a 15-block-deep lake floor was tinted like a puddle, and the shadow of
   a glass block did not get stronger inside thicker glass. `runtime-patch/shadow_ray_patch.py` rewrites every ray-query visibility
   loop (149 shader modules, 162 sites) to accumulate a signed distance: entering a thick translucent surface counts -t, leaving it
   counts +t, and the ray is attenuated by `exp(-sigma * distance)`, with `sigma = -ln(T)/measurementDistance` from the material.
   It is order independent, handles rays that start or end inside glass or water, and keeps glass refracting. `--k` scales the
   absorption seen by light only (1.0 physical, 0.5 used here), so the glass looks the same to the eye.
2. **The sky looked untinted through glass.** The composite pass blends distant surfaces into the sky when
   `rtx.viewDistance.distanceMode = 3` (the mod's default). A ray that passed through glass and then hit sky is not counted as a plain
   sky miss, and its stored distance is a huge placeholder, so the blend was 100% and it overwrote the tinted sky with raw sky.
   `runtime-patch/build_runtime.py` changes one condition in the composite shader (`!primaryMiss` becomes
   `!(primaryMiss || viewZ == missSentinel)`).
3. **Glass sitting on a block had no exit face.** Vanilla culls the glass face that touches an opaque block, so the medium was never
   closed and the surface under the glass stayed pale (a block floating one block above stone looked right, touching it did not).
   `mod-patch/GlassContactFaces.java` keeps those faces for glass-like blocks (clear, stained, tinted, ice, slime, honey) and nudges
   them 4 mm into the glass so they never fight with the neighbour's face. It is hooked into `BlockQuadEmitter` with ASM.
4. **Water's top face was emitted twice** (an up-facing quad plus a reversed copy). With distance-based absorption the two hits
   cancel each other, so the reversed copy is removed (`mod-patch/water_quad_patch.py`, 92 bytes NOPed).
5. **Config:** `rtx.enableTransmissionApproximationInIndirectRays = False` in the profile's `user.conf`, so bounce rays refract and use
   Remix's exact depth-based absorption instead of one flat tint per surface (see `config/`).

## What this touches on your machine

| File | Change |
|---|---|
| `<profile>/remix-sdk/d3d9.dll` | replaced by the patched copy (back up the original) |
| `<profile>/mods/rtx-remix-renderer-....jar` | `BlockQuadEmitter.class` modified, `GlassContactFaces.class` added, everything else byte-identical |
| `<profile>/user.conf` | one line changed (see above) |
| `<profile>/javaw.dxvk-cache` | delete after changing the DLL so shaders are rebuilt |

Do **not** change `.rtx-remix-version` or the jar version: the mod re-extracts `remix-sdk/` and `rtx.conf` when they differ.

## Build and install

Requirements: Python 3.10+, [SPIRV-Tools](https://github.com/KhronosGroup/SPIRV-Tools) (`spirv-as`, `spirv-dis`, `spirv-val`),
a JDK 21+, and the ASM 9.x jars (the Modrinth launcher ships them under `meta/libraries/org/ow2/asm`). Close Minecraft first.

```
python runtime-patch/build_runtime.py --dll <profile>/remix-sdk/d3d9.dll --out d3d9.patched.dll \
       --spirv-tools <folder> --k 0.5

python mod-patch/patch_jar.py --jar <profile>/mods/rtx-remix-renderer-0.1.0-202610230634-170197a.jar --out patched.jar \
       --intermediary <profile>/.fabric/remappedJars/minecraft-1.21.1-<loader>/client-intermediary.jar \
       --asm <asm folder> --jdk <JDK folder>
```

Back up the originals, copy the two outputs over the originals, apply `config/user.conf.snippet`, delete `javaw.dxvk-cache`,
then check the md5 of the DLL you copied in. Build time is about a minute; the first launch is slower while shaders are rebuilt.
With `--k 0.5` the DLL comes out with md5 `9a5055f8717f5c760d3899b40724d331`, which is how the scripts were checked against the
author's installed files.

## Restore

Put the original `d3d9.dll`, the original jar and your old `user.conf` back and delete `javaw.dxvk-cache`.

## Checking it works (with controls)

* Torch 2 blocks from a white wall: nothing between, then red stained glass, then clear glass. Red glass should cast clearly red light.
* Lake floors at 1, 5 and 15 blocks deep under open sky: the floor should get bluer and darker with depth (it used to be identical).
* Look up through stained glass with the distance fade **on**: the sky should be tinted.
* The same glass block floating one block above stone and sitting on it should look alike (uniform colour, no pale half).
* Fault sign: light *brighter* behind glass than without means entering and leaving are swapped (see `docs/TECHNICAL.md`).

## Known gaps

* Water above an opaque block has the same missing bottom face; not changed yet.
* The 4 mm nudge could show a thin bright line at a glass/stone edge. `LIFT` in `GlassContactFaces.java` is the knob.
* Only the builds above are supported. New mod or runtime versions need the anchors re-found (`docs/TECHNICAL.md`).
* The right long-term fix is in the runtime source; this should become an upstream issue or PR once the runtime branch is public.

Developed with Claude Code. Investigation details, derivations and gotchas: [docs/TECHNICAL.md](docs/TECHNICAL.md).
Licence: Apache-2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE).
