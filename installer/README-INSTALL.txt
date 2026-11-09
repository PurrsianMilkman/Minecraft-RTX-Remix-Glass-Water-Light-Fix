RTX Remix for Minecraft - glass and water light fix: one-click patcher
========================================================================

What you need: Windows 10/11 64-bit, internet, about 4.5 GB free disk space, and RTX Remix for Minecraft 0.1.0
(Fabric 1.21.1). Nothing else: Python and the shader tools are downloaded into a private "work" folder.

1. Extract this whole zip to a folder (do not run the .bat from inside the zip).
2. Double-click Make-Patched-Mod.bat.
   It downloads NVIDIA's original mod from NVIDIA's own GitHub release (about 1 GB), patches it and puts ONE jar into the
   "output" folder. Nothing of NVIDIA's is included in this zip.
3. Close Minecraft. In your profile's mods folder delete the original rtx-remix-renderer jar and copy the new jar from "output" in.
   (Both jars at once will not work: they are the same mod.)
4. Start the game. The first start takes longer. Settings: RTX Remix settings > "Light Transform Modifications".

To go back: delete the patched jar and put NVIDIA's original jar back (it is in work\pristine, or download it from
https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/releases/tag/v0.1.0 ).
Only version 0.1.0 is supported. Newer NVIDIA releases need this project to be updated first.
Not affiliated with NVIDIA, Mojang or Microsoft. Use at your own risk. Source and notes: see the project page.
