RTX Remix for Minecraft - glass and water light fix: one-click patcher
========================================================================

What you need: Windows 10/11 64-bit, internet, about 4.5 GB free disk space, and RTX Remix for Minecraft 0.1.1 (latest) or 0.1.0
(Fabric 1.21.1). Nothing else: Python and the shader tools are downloaded into a private "work" folder.

1. Extract this whole zip to a folder (do not run the .bat from inside the zip).
2. Double-click Make-Patched-Mod.bat. (Faster and download-free: first put NVIDIA's mod jar in the same folder as the .bat; it is used first.)
   It uses NVIDIA's original mod if it is already on your PC (Modrinth, Prism, CurseForge, .minecraft mods, Downloads). If not, it
   downloads the latest from NVIDIA's own GitHub (about 1 GB, over several connections like a browser, resumable), patches it and
   puts ONE jar, named ...-LightFix.jar, into the "output" folder. Nothing of NVIDIA's is included in this zip.
3. Close Minecraft. In your profile's mods folder delete the original rtx-remix-renderer jar and copy the new ...-LightFix.jar from "output" in.
   (Both jars at once will not work: they are the same mod.) If you had the old separate translucent-light-fix-toggle jar, delete it:
   the new jar already contains it.
4. Start the game. The first start takes longer. Settings: RTX Remix settings > "Light Transform Modifications".

To go back: delete the patched jar and put NVIDIA's original jar back (it is in the "work" folder, or download it from
https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/releases ).
Supported: NVIDIA's 0.1.1 and 0.1.0. Newer NVIDIA releases need this project to be updated first.
Not affiliated with NVIDIA, Mojang or Microsoft. Use at your own risk. Source and notes: see the project page.
