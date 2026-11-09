# RTX Remix for Minecraft: coloured light through water and glass

Fixes and settings for [NVIDIA's RTX Remix for Minecraft](https://github.com/NVIDIAGameWorks/rtx-remix-minecraft) (Fabric, 1.21.1) where
**water and glass did not colour the light that passes through them**: light from torches, sea lanterns and the sun, and the
sky seen through glass. Nothing is thin-walled, glass keeps refracting and water keeps its look.

This repository contains **patch scripts and a small companion mod only**. It ships no NVIDIA binaries, no shader dumps and no game
assets: the scripts patch *your own* copy of the mod jar and runtime DLL, and refuse to run on anything but the exact builds listed
below. Not affiliated with NVIDIA, Mojang or Microsoft. Use at your own risk and keep backups (see "Restore").

## Easy install (one file)

Download **`Make-Patched-RTX-Remix-Glass-Fix.bat`** from the Releases page (one file, no zip) and double-click it. Windows may warn
that it is from the internet: it is a plain text batch file, open it in Notepad to read it, then choose "Run anyway".
It downloads NVIDIA's own RTX Remix for Minecraft 0.1.0 release (about 1 GB), patches it, and writes **one jar** next to the `.bat`.
Close Minecraft, delete the original `rtx-remix-renderer` jar from your profile's `mods` folder, and copy the new jar in
(same file name, it replaces the original; the companion mod is merged into it, so there is nothing else to install).
The installer needs only Windows 10/11 and about 4.5 GB of free disk space. The `.bat` carries our scripts and the changed classes inside itself
(about 170 KB); it unpacks them into a `RemixGlassFix-files` folder beside it, downloads a portable Python and the SPIR-V tools into that folder
(pinned versions, SHA-256 checked), and you can delete that folder afterwards. Nothing of NVIDIA's is inside the `.bat`.
Only 0.1.0 is supported, not 0.1.1. The first start with the new jar is slower: the mod unpacks its runtime again
(the jar's version carries a `+glassfix1` suffix for that). `tools/make_release.py --bat` builds the single-file installer; a zip version
(`Make-Patched-Mod.bat` inside `RemixGlassFix-Installer.zip`) is built from the same sources. The manual build below is for developers.

## Status (honest version)

| Item | State |
|---|---|
| Sky seen through glass/water was untinted: cause found | **Confirmed in game** (turning the distance fade off made the tint appear) |
| Sky fade patch (keeps the fade, stops it overwriting tinted sky) | Installed, not yet confirmed with the fade on |
| Light through glass/water absorbed by distance travelled (shadow rays) | Installed; light comes out tinted, a bit dim through red glass, hence the `--k` knob |
| Glass touching an opaque block gets a real exit face | **Confirmed in game** |
| Master switch: shipped rendering restored when off | Works live in game; one report of wrong sunlight after switching off then on is still being investigated |
| Glass colour saturation slider, glass pane depth slider | Installed, in use |
| Dark glass stays dark (the brightness lift only applies to saturated glass) | Installed, **untested in game** (built without `spirv-val`, see below) |
| Glass Layer Gap (touching glass/water faces pulled 4 mm apart) | Installed, **untested in game**; hypothesis: removes black sky behind two glasses, missing middle blocks, glass-under-water flicker |
| Sun Size slider (softer sun/moon shadow edges) | Installed, **untested in game** |
| Glass Block Depth, Water Blue sliders | Installed, **untested in game**; apply when the materials are rebuilt (resource reload or restart) |
| Hotkey assignment buttons in the settings menu | Installed, **untested in game** |
| Water Surface Underside, Water Off Glass (test switches) | Installed, optional, results not reported |
| Distant violet/blue skylight tint | **Not solved.** Present with these mods off too (stock Remix) |

## Supported builds (the scripts check this)

* Mod: `rtx-remix-renderer-0.1.0-202610230634-170197a.jar` (source commit `170197a`), md5 `c4551ac851988aa6ec5b6299c8cbd259` (pristine)
* Runtime: pristine `remix-sdk/d3d9.dll`, md5 `cbe2d49f543b608a7ac45d6b2c6631ae`, 309,009,920 bytes (`remix-main+71a581da`, API 0.16.0)

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

## The companion mod and the settings menu

`toggle-mod/` is a small Fabric mod (`TranslucentFixToggle`). Together with the patched renderer jar it adds a
**Light Transform Modifications** page to the RTX Remix settings menu:

| Setting | Effect |
|---|---|
| Light Transform Mods (Master Switch) | Off = the shipped rendering exactly (shaders, geometry, options); sliders keep their values |
| Glass Color Saturation | scales the saturation of glass tint for light (25-200%) |
| Glass Pane Depth Effect | how strongly panes tint what you see (0-280%) |
| Glass Block Depth | block tint strength; **applies after a resource reload or restart** (75-400%) |
| Glass Layer Gap | separates touching glass/water faces (on by default) |
| Water Blue | blue transmittance of water; **applies after a resource reload or restart** (25-150%) |
| Sun Size | apparent size of sun and moon (100-2000%); larger = softer shadow edges |
| Water Surface Underside, Water Off Glass | geometry test switches |
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
       --k 0.5 --glass-clear 0.9 --bounce-clear 0.9 --live-flag --sat-slider --pane-depth

python mod-patch/patch_jar.py --jar <pristine renderer jar> --out patched.jar \
       --intermediary <profile>/.fabric/remappedJars/minecraft-1.21.1-<loader>/client-intermediary.jar \
       --asm <asm folder> --jdk <JDK folder> --extra-cp <brigadier jar>
```

The companion mod is plain Java: compile `toggle-mod/src/**` against the Minecraft intermediary jar, Fabric loader, the Fabric API modules
above and brigadier (`javac --release 21`), add `toggle-mod/assets` and `toggle-mod/fabric.mod.json`, and `jar` it.

Back up the originals, copy the outputs over them, delete `javaw.dxvk-cache`, check the md5 of the DLL you copied in. Build time is about
a minute; the first launch is slower while shaders are rebuilt. The DLL build above produced md5 `f259180a499791e87b9a13987c0fa05f`
(built without `spirv-val`).

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
* Only the builds above are supported. New mod or runtime versions need the anchors re-found (`docs/TECHNICAL.md`).
* The right long-term fix is in the runtime source; this should become an upstream issue or PR once the runtime branch is public.

Developed with Claude Code. Investigation details, derivations and gotchas: [docs/TECHNICAL.md](docs/TECHNICAL.md).
Licence: Apache-2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE).
