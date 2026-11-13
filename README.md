# RTX Remix for Minecraft: coloured light through water and glass

Fixes and settings for [NVIDIA's RTX Remix for Minecraft](https://github.com/NVIDIAGameWorks/rtx-remix-minecraft) (Fabric, 1.21.1) where
**water and glass did not colour the light that passes through them**: light from torches, sea lanterns and the sun, and the
sky seen through glass. Nothing is thin-walled, glass keeps refracting and water keeps its look.

This repository contains **patch scripts and a small companion mod only**. It ships no NVIDIA binaries, no shader dumps and no game
assets: the scripts patch *your own* copy of the mod jar and runtime DLL, and refuse to run on anything but the exact builds listed
below. Not affiliated with NVIDIA, Mojang or Microsoft. Use at your own risk and keep backups (see "Restore").

## Easy install (one file)

To install and use:

1. Download the original mod from NVIDIA: https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/releases/download/v0.1.1/rtx-remix-renderer-0.1.1-202611060211-7d2ba9f.jar
2. Download the patch: https://github.com/PurrsianMilkman/Minecraft-RTX-Remix-Glass-Water-Light-Fix/releases/download/installer-v1.0.0-rc1/Make-Patched-RTX-Remix-Glass-Fix.bat
3. Put both the jar file and the bat file in the same folder and run the bat file. The bat file will give you the patched jar file.
4. Put the patched jar file in your mods folder, just like other mods.
5. Remove the original jar file if it is still there.

## Status (honest version)

| Item | State |
|---|---|
| Sky seen through glass/water was untinted: cause found | **Confirmed in game** (turning the distance fade off made the tint appear) |
| Sky fade patch (keeps the fade, stops it overwriting tinted sky) | Installed, not yet confirmed with the fade on |
| Light through glass/water absorbed by distance travelled (shadow rays) | Installed; light comes out tinted, a bit dim through red glass, hence the `--k` knob |
| Glass touching an opaque block gets a real exit face | **Confirmed in game** |
| Master switch: shipped rendering restored when off | Works live in game; one report of wrong sunlight after switching off then on is still being investigated |
| Glass colour saturation slider, glass pane depth slider | Installed, in use |
| Dark glass stays dark (the brightness lift only applies to saturated glass) | Confirmed in game (built without `spirv-val`, see below) |
| Glass Layer Gap (touching glass/water faces pulled 4 mm apart) | Confirmed in game: black sky behind glass plus water is fixed. Glass-under-water flicker and 3+ layer mixing not yet reported |
| Reflection of a water surface seen through glass or water, including reflected water seen through glass | **Confirmed in game** (stock Remix hides these reflections) |
| Sun Size slider (softer sun/moon shadow edges) | Installed, **untested in game** |
| Glass Block Depth, Water Blue sliders | Installed, **untested in game**; apply when the materials are rebuilt (resource reload or restart) |
| Hotkey assignment buttons in the settings menu | Installed, **untested in game** |
| Water Surface Underside, Water Off Glass (test switches) | Installed, optional. Underside is **off by default**: the reversed copy of the water top stays dropped while the master switch is on |
| White light through coloured glass, and untinted light through water, from lamps and sea lanterns (the NEE cache feeding ReSTIR GI) | **Confirmed fixed in game** (item 12 below) |
| Distant violet/blue skylight tint | Went away once the profile's config matched a stock instance (a main-profile setting, not our shaders); the exact setting was not isolated. A user.conf that pins `rtx.viewDistance.noiseScale` / `distanceFadeMin` silently disables the Master Switch: never save from the Alt+X menu |
| Royal-blue water top under glass, and blue bounce light under water or in reflected water | **Confirmed fixed in game.** Two causes (items 9 and 10 below): the reflection patch left the ray marked as already inside the water, and bounce rays flew straight through water to the sky |
| Better GI (Russian roulette off, indirect ray spread angle 0.02; on by default): GI no longer gets stronger up close | **Confirmed in game** |
| Second, over-refracted set of shadows on sand, sandstone, snow (subsurface materials) seen through water | **Confirmed fixed in game** (item 11 below) |
| With the primary-ray replacement switched off in Alt+X (PSR off), water drawn as an ordinary visible surface looks very blue | Stock Remix behaviour; not explained by the fixes above |

## Supported builds (the scripts check this)

| NVIDIA release | Jar (pristine md5) | Runtime `d3d9.dll` (pristine md5) |
|---|---|---|
| **0.1.1** (latest, `7d2ba9f`) | `rtx-remix-renderer-0.1.1-202611060211-7d2ba9f.jar`, `0b9c4d5f272fc4627d48ba6c636f2ef5` | `1ae89b5ebcd2a4dad175d96b1806d5f0`, 309,016,064 bytes |
| 0.1.0 (`170197a`) | `rtx-remix-renderer-0.1.0-202610230634-170197a.jar`, `c4551ac851988aa6ec5b6299c8cbd259` | `cbe2d49f543b608a7ac45d6b2c6631ae`, 309,009,920 bytes (`remix-main+71a581da`, API 0.16.0) |

The 647 shader modules inside the two runtimes are byte-identical (only the order of nine of them differs), so the same shader patches apply to both;
they are found by content, not by offset.
The runtime is an internal NVIDIA build whose source is not public (the mod's `CONTRIBUTING.md` says so), and public
`dxvk-remix` speaks a different API version, so the fix is a **size-preserving patch of the SPIR-V shaders embedded in the DLL**.
The patched DLL reads two Remix options as live channels, so the companion mod can switch and tune the fix without a restart.

## What was wrong, and what we changed

1. **Block light and sunlight ignored the glass's thickness.** The shipped shaders multiply a shadow ray by the material colour
   once per surface it crosses, whatever the thickness. `runtime-patch/shadow_ray_patch.py` rewrites every ray-query visibility
   loop (149 shader modules, 162 sites) to accumulate a signed distance: entering a thick translucent surface counts -t, leaving it
   counts +t, and the ray is attenuated by `exp(-sigma * distance)`, with `sigma = -ln(T)/measurementDistance` from the material.
   It is order independent, handles rays that start or end inside glass or water, and keeps glass refracting. `--k` scales the
   absorption seen by light only (1.0 physical, 0.5 used here).
2. **The sky looked untinted through glass.** The composite pass blended distant surfaces into the sky; a ray that passed through glass
   and then hit sky carried a huge placeholder distance, so the blend overwrote the tinted sky. One condition in the composite shader
   changes (`!primaryMiss` becomes `!(primaryMiss || viewZ == missSentinel)`).
3. **Glass sitting on a block had no exit face.** Vanilla culls the glass face that touches an opaque block. `mod-patch/GlassContactFaces.java`
   keeps those faces for glass-like blocks (clear, stained, tinted, ice, slime, honey) and nudges them 4 mm into the glass.
4. **Water's top face was emitted twice**; with distance-based absorption the two hits cancel, so the reversed copy is removed
   (optionally kept with the Water Surface Underside switch).
5. **Bounce rays (indirect light)** get the same tint treatment (`runtime-patch/bounce_tint_patch.py`), and the NEE-cache shadow mask
   includes alpha-blended glass.
6. **Brightness lift for coloured glass, but not for dark glass.** The material colour of a stained pane is a hue, not a transmittance, so
   after the runtime's gamma step a red pane is about (0.33, 0.006, 0.006). Both light paths raise the brightest channel to `--glass-clear` /
   `--bounce-clear` (0.9 per measurement distance) keeping the hue. The lift is weighted by saturation (`1 - min/max`), so neutral dark glass
   (black, grey) is **not** brightened and keeps blocking light. (Before this, black glass passed about 74% of the sun through a 1 m block.)
7. **Thin glass seen directly looks pale** (a pane is 2/16 thick). `runtime-patch/gbuf_patch.py` makes the primary-ray distance
   `max(T, K * measurementDistance)` for glass, with K read live (Glass Pane Depth Effect).
8. **Coplanar faces between different glass-like blocks** (vanilla only culls the face between two blocks of the same kind): with
   Glass Layer Gap on, glass faces that touch another glass or water block are pulled 4 mm into their own block.

9. **Reflections of water (or glass) seen through another see-through layer** (`runtime-patch/psr_water_patch.py`). Stock Remix drops them: the
   primary-ray shader crosses each interface with primary surface transmission replacement (PSTR) and, for an interface the ray enters,
   `enablePSTRSecondaryIncidentSplitApproximation` crosses it as pure transmission and drops its reflection. Turning that option off restores the
   reflection but also changes the first layer. The patch leaves the first interface and every wall or pane as shipped and turns the approximation off
   only for a later interface whose normal points up (`N.y > 0.7`: the top face of a water surface or glass floor/roof, seen from above), using the shader's own
   interface counter, so that surface is drawn as a visible surface and reflects. A bottom face (looking up through glass at water above) stays as shipped. Live-gated like the other patches.
   Stopping the replacement there is not enough: stock has already recorded "the ray entered the water" for that interface, so without a second step the water top is
   shaded as if the camera were underwater (royal blue). The patch restores the medium state when it stops the replacement. See `docs/TECHNICAL.md`.
10. **Water seen by bounce rays** (`runtime-patch/water_reflect_patch.py`, `--water-reflect`). With the shipped `enableTransmissionApproximationInIndirectRays` a bounce ray crossing
    a translucent surface is not a hit: it is tinted and flies straight on, so a water column in a reflection becomes a window onto the sky (blue, no refraction, no
    absorption by depth). The patch switches that approximation off for **water only** (recognised by its refractive index, 1.33 against 1.52 for glass, read from the
    material the shader has just loaded), so water refracts, reflects and absorbs by depth as it does in stock Remix with the option off. Glass keeps the approximation.
11. **Second set of shadows on subsurface materials seen through water** (`runtime-patch/sss_psr_patch.py`, `--sss-psr`). The RTX Remix Materials pack gives sand, sandstone,
    snow and similar blocks a subsurface scattering profile. The diffusion profile lights points around the shaded point and, with RTXDI on, takes each point's light from the
    reservoir of the screen pixel that the point's real position projects to. Through water that pixel shows a different spot, so the surface also followed that spot's shadows
    (a second, lighter, shifted set). For pixels reached through a see-through surface (PSTR/PSRR) the patch makes the lookup use the ordinary light selection instead.
12. **Emissive light (sea lanterns, lamps) stayed white through coloured glass and untinted through water** (`runtime-patch/nee_reservoir_patch.py`, `--nee-reservoir`).
    The NEE cache's first-bounce pass traces one shadow ray to its chosen glowing triangle and multiplies the directly accumulated light by the glass/water tint. The same
    sample is also written into the ReSTIR GI buffer, but with the RAW emissive radiance, and ReSTIR GI's final shading applies it with a visibility test whose ray mask has no
    translucent bit. Light redistributed that way therefore arrived white. The patch multiplies the stored radiance by the shadow ray's attenuation, so the cache stays on
    (no extra noise or cost) and no menu switch is needed.

## The companion mod and the settings menu

`toggle-mod/` is a small Fabric mod (`TranslucentFixToggle`). Together with the patched renderer jar it adds a
**Light Transform Modifications** page to the RTX Remix settings menu:

| Setting | Effect |
|---|---|
| Light Transform Mods (Master Switch) | Off = the shipped rendering exactly (shaders, geometry, options); sliders keep their values |
| Better GI | On by default, with the master switch: turns Russian roulette off and sets the indirect ray spread angle factor to 0.02 (Remix: 0.05), so GI no longer gets stronger the closer you get and is cleaner. Off restores Remix's own values (on, 0.05) |
| Glass Color Saturation | scales the saturation of glass tint for light (25-200%) |
| Glass Pane Depth Effect | how strongly panes tint what you see (0-280%) |
| Glass Block Depth | block tint strength; **applies after a resource reload or restart** (75-400%) |
| Glass Layer Gap | separates touching glass/water faces (on by default) |
| Water Blue | blue transmittance of water; **applies after a resource reload or restart** (25-150%) |
| Sun Size | apparent size of sun and moon (100-2000%); larger = softer shadow edges |
| Water Surface Underside, Water Off Glass | geometry test switches (Underside is off by default) |
| Hotkeys + four key buttons | click a button, press a key (Delete clears); master switch defaults to Numpad 1, debug markers Numpad 2 |

The mod writes `rtx.viewDistance.noiseScale` (on/off flag and saturation) and `rtx.viewDistance.distanceFadeMin` (pane depth) through the
Remix bridge, checks once a second that the runtime still holds them, and rebuilds the loaded terrain only after the options are written.

## What this touches on your machine

| File | Change |
|---|---|
| `<profile>/remix-sdk/d3d9.dll` | replaced by the patched copy (back up the original) |
| `<profile>/mods/rtx-remix-renderer-....jar` | several classes modified or added, everything else byte-identical |
| `<profile>/mods/translucent-light-fix-toggle-1.0.0.jar` | the companion mod you build from `toggle-mod/` |
| `<profile>/javaw.dxvk-cache` | delete after changing the DLL so shaders are rebuilt |

Do **not** change `.rtx-remix-version` or the jar version: the mod re-extracts `remix-sdk/` and `rtx.conf` when they differ.
Do not keep our keys (`noiseScale`, `distanceFadeMin`) in `user.conf`: a value there outranks the mod's live writes.

## Build and install

Requirements: Python 3.10+, `spirv-as` and `spirv-dis` from [SPIRV-Tools](https://github.com/KhronosGroup/SPIRV-Tools) and, strongly
recommended, `spirv-val` (without it the build only checks a disassembly round trip and warns), a JDK 21+, the ASM 9.x jars
(`asm`, `asm-tree`), and for the companion mod the Fabric loader, Fabric API (lifecycle events, key binding, screen API) and brigadier jars.
Close Minecraft first and build from the **pristine** files, not from files you already patched.

```
python runtime-patch/build_runtime.py --dll <pristine d3d9.dll> --out d3d9.patched.dll --spirv-tools <folder> \
       --k 0.5 --glass-clear 0.9 --bounce-clear 0.9 --live-flag --sat-slider --pane-depth \
       --psr-water --water-reflect --sss-psr --nee-reservoir

python mod-patch/patch_jar.py --jar <pristine renderer jar> --out patched.jar \
       --intermediary <profile>/.fabric/remappedJars/minecraft-1.21.1-<loader>/client-intermediary.jar \
       --asm <asm folder> --jdk <JDK folder> --extra-cp <brigadier jar>
```

The companion mod is plain Java: compile `toggle-mod/src/**` against the Minecraft intermediary jar, Fabric loader, the Fabric API modules
above and brigadier (`javac --release 21`), add `toggle-mod/assets` and `toggle-mod/fabric.mod.json`, and `jar` it.

Back up the originals, copy the outputs over them, delete `javaw.dxvk-cache`, check the md5 of the DLL you copied in. Build time is about
a minute; the first launch is slower while shaders are rebuilt. The DLL build above produced md5 `f259180a499791e87b9a13987c0fa05f` for the 0.1.0 runtime and
`68af47616690009975f252030d0bd25f` for the 0.1.1 runtime (both built without `spirv-val`, with the older flag set). With all the flags above (built with `spirv-val`,
every module validated) the 0.1.1 runtime comes out as md5 `8ca11e36b667ec10ec6ed44603d95551`.

## Restore

Put the original `d3d9.dll` and the original renderer jar back, remove the companion mod jar, delete `javaw.dxvk-cache`.

## Checking it works (with controls)

* Torch 2 blocks from a white wall: nothing between, then red stained glass, then clear glass. Red glass should cast clearly red light.
* Black glass over a room: the room should be dark; coloured glass should look as bright as before.
* Lake floors at 1, 5 and 15 blocks deep under open sky: the floor should get bluer and darker with depth.
* Look up through stained glass with the distance fade **on**: the sky should be tinted.
* Red glass next to blue glass: the sky behind both should not go black; three or more different glasses in a row should all show in the mix.
* Fault sign: light *brighter* behind glass than without means entering and leaving are swapped (see `docs/TECHNICAL.md`).

## Known gaps

* The distant violet/blue skylight tint is unexplained and also happens with the mods off.
* Glass Block Depth and Water Blue cannot be live: they change materials the mod builds once.
* Only the builds above are supported. A new NVIDIA release needs its jar and runtime md5 added (the shader modules may or may not have changed; see `docs/TECHNICAL.md`).
* The right long-term fix is in the runtime source; this should become an upstream issue or PR once the runtime branch is public.

Developed with Claude Code. Investigation details, derivations and gotchas: [docs/TECHNICAL.md](docs/TECHNICAL.md).
Licence: Apache-2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE).
