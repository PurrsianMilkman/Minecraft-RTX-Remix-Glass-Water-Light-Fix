RTX Remix for Minecraft - glass and water light fix: one-click patcher
========================================================================

What you need: Windows 10/11 64-bit, internet (for two small helper tools), about 4.5 GB free disk space, and NVIDIA's original
RTX Remix for Minecraft mod jar, version 0.1.1 (Fabric 1.21.1). Python and the shader tools are downloaded into a private
"work" folder. The mod jar is NOT downloaded: you put it next to the .bat yourself.

1. Extract this whole zip to a folder (do not run the .bat from inside the zip).
2. Put NVIDIA's original mod jar (rtx-remix-renderer-0.1.1-...jar, any file name) in the SAME folder as Make-Patched-Mod.bat,
   then double-click the .bat. It looks only at the jars in that folder and nowhere else on your PC. A jar is recognised by its hash, not its
   name: a 0.1.1 jar gets the patch, and anything else is refused with a message (an already patched jar,
   another version or a damaged download do not match). It patches the jar and puts ONE jar, named ...-LightFix.jar, into the "output" folder.
   Nothing of NVIDIA's is included in this zip.
3. Close Minecraft. In your profile's mods folder delete the original rtx-remix-renderer jar and copy the new ...-LightFix.jar from "output" in.
   (Both jars at once will not work: they are the same mod.) If you had the old separate translucent-light-fix-toggle jar, delete it:
   the new jar already contains it.
4. Start the game. The first start takes longer. Settings: RTX Remix settings > "Light Transform Modifications".

To go back: delete the patched jar and put NVIDIA's original jar back (the one you put next to the .bat is untouched, or download it from
https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/releases ).
Supported: NVIDIA's 0.1.1 only. When NVIDIA releases a newer version this project is updated and the older one is dropped.
Not affiliated with NVIDIA, Mojang or Microsoft. Use at your own risk. Source and notes: see the project page.
