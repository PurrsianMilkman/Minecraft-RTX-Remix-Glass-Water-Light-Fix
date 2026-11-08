package purrsian.translucentfix;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.class_2561;
import net.minecraft.class_304;
import net.minecraft.class_310;

/**
 * Live A/B switch for the translucent light fix, shown in the RTX Remix settings menu under
 * "Light Transform Modifications" (the settings themselves are added by the renderer jar's
 * LightTransformSettings, which calls the public static methods below, so the menu's own save,
 * Reset and Reset all apply to them).
 *
 * The patched runtime (remix-sdk/d3d9.dll built with --live-flag) runs the fixed shader code only while
 * rtx.viewDistance.noiseScale is above 20.0005, and the shipped code while it is exactly the shipped 20. ON
 * writes 20.001 (the fade noise scale, a difference nobody can see), OFF writes 20. The fix also keeps
 * rtx.enableTransmissionApproximationInIndirectRays at its shipped True, sets the first-bounce NEE cache off
 * (OFF restores the value the runtime started with), switches the glass-contact and water-quad changes inside
 * the renderer jar and rebuilds the loaded terrain, so OFF is the shipped behaviour and the change shows at once.
 * The debug markers (red = glass on a shadow ray, green = glass on a bounce ray) need a telltale build of the DLL
 * and are off by default. Hotkeys: Numpad 1 fix on/off, Numpad 2 debug markers on/off, both disabled by the
 * "Hotkeys" setting.
 * (Names are the compiled intermediary names; class_304 = KeyBinding, class_310 = MinecraftClient.)
 */
public final class TranslucentFixToggle implements ClientModInitializer {
    private static final String NOISE_SCALE = "rtx.viewDistance.noiseScale";
    private static final String FADE_MIN = "rtx.viewDistance.distanceFadeMin";
    private static final String TRANSMISSION_APPROX = "rtx.enableTransmissionApproximationInIndirectRays";
    /** The NEE cache samples emissive blocks (sea lantern, lantern) on the first bounce with a visibility ray that never sees glass. */
    private static final String NEE_FIRST_BOUNCE = "rtx.neeCache.enableOnFirstBounce";
    /** Cache NEE shadow rays use the INDIRECT shadow mask; alpha-blended instances are only in it when this is on. */
    private static final String INDIRECT_ALPHA_SHADOWS = "rtx.enableIndirectAlphaBlendShadows";
    /** The old workaround for untinted emissive light (cache off on the first bounce). Off while the mask fix is tested. */
    private static final boolean DISABLE_FIRST_BOUNCE_CACHE = false;

    static {
        // The renderer mod's server light snapshot (ServerLightSnapshot) can throw 'published light snapshot is
        // read-only' on world join when a lower sky-light section loads after its last flatten. The exception kills
        // the server's light task for good, so chunks stop loading and exiting hangs on the saving screen. The mod's
        // own switch makes the engines clone their maps as vanilla does. It is read once, when the policy class loads,
        // which turned out to be BEFORE this class initialises, so the effective setter is TranslucentFixPreLaunch
        // (a preLaunch entrypoint); this copy is only a fallback. An explicit -D on the command line wins.
        if (System.getProperty("rtxremix.light.vanillaSnapshot") == null) {
            System.setProperty("rtxremix.light.vanillaSnapshot", "true");
        }
    }

    private static volatile boolean enabled = true;
    private static volatile boolean diagRed = false;
    private static volatile boolean hotkeys = true;
    private static volatile int saturationPercent = 100;
    private static volatile int paneDepthPercent = 150;
    private static volatile boolean waterUnderside = false;
    private static volatile boolean waterNudge = false;
    private static volatile boolean glassGap = true;
    private static volatile int glassDepthPercent = 100;
    private static volatile int waterBluePercent = 100;
    private static volatile int sunSizePercent = 400;
    private static volatile boolean optionApplied;
    private static volatile boolean rebuildPending;
    /** The runtime's value of NEE_FIRST_BOUNCE before this mod wrote it, so OFF restores it exactly. */
    private static String neeFirstBounceDefault;
    private static String indirectAlphaDefault;
    private static class_304 toggleKey;
    private static class_304 diagKey;
    private static class_304 undersideKey;
    private static class_304 nudgeKey;

    // ---- state, read and written by the RTX settings menu (LightTransformSettings) ----

    public static boolean isFixEnabled() {
        return enabled;
    }

    public static void setFixEnabled(boolean on) {
        if (on == enabled) {
            return;
        }
        enabled = on;
        setContactFaces(on);
        optionApplied = false;
        // The terrain is rebuilt only AFTER the runtime options are written (see the tick handler): instances created while the
        // old options were still live could keep the old shadow mask and the old fix state until they are captured again.
        rebuildPending = true;
    }

    public static boolean isDiagnostic() {
        return diagRed;
    }

    public static void setDiagnostic(boolean on) {
        if (on != diagRed) {
            diagRed = on;
            optionApplied = false;
        }
    }

    /** Glass colour saturation in percent (25..200, 100 = the glass colours as shipped), read live by the patched shaders. */
    public static int getSaturation() {
        return saturationPercent;
    }

    public static void setSaturation(int percent) {
        int p = Math.max(25, Math.min(200, percent));
        if (p != saturationPercent) {
            saturationPercent = p;
            optionApplied = false;
        }
    }

    /**
     * Strength of the depth effect for thin glass (panes) seen directly, in percent (0..280): K = percent / 100, a pane absorbs as
     * if it were K * 0.35 thick (150 = 0.525, a head-on pane shows its colour to the power 1.5). 0 = the shipped look.
     */
    public static int getPaneDepth() {
        return paneDepthPercent;
    }

    public static void setPaneDepth(int percent) {
        int p = Math.max(0, Math.min(280, percent));
        if (p != paneDepthPercent) {
            paneDepthPercent = p;
            optionApplied = false;
        }
    }

    /** Keep the downward-facing copy of the water top face with the fix on (see GlassContactFaces.keepWaterUnderside). */
    public static boolean isWaterUnderside() {
        return waterUnderside;
    }

    public static void setWaterUnderside(boolean on) {
        if (on == waterUnderside) {
            return;
        }
        waterUnderside = on;
        setWaterUndersideField(on);
        if (enabled) {
            rebuildTerrain();
        }
    }

    /** Pull water faces that touch glass a hair off it (see GlassContactFaces.nudgeWater). */
    public static boolean isWaterNudge() {
        return waterNudge;
    }

    public static void setWaterNudge(boolean on) {
        if (on == waterNudge) {
            return;
        }
        waterNudge = on;
        try {
            game("com.nvidia.rtxremix.minecraft.terrain.capture.GlassContactFaces").getField("nudgeWater").setBoolean(null, on);
        } catch (Throwable t) {
            System.err.println("[translucent-fix] water nudge switch unavailable: " + t);
        }
        if (enabled) {
            rebuildTerrain();
        }
    }

    /** Glass block depth in percent (100 = shipped); read when the block materials are built, so it applies after a resource reload. */
    public static int getGlassDepth() {
        return glassDepthPercent;
    }

    public static void setGlassDepth(int percent) {
        int p = Math.max(75, Math.min(400, percent));
        glassDepthPercent = p;
        applyGlassDepth();
    }

    private static void applyGlassDepth() {
        try {
            game("com.nvidia.rtxremix.minecraft.terrain.capture.GlassContactFaces").getField("glassDepthPercent")
                    .setInt(null, glassDepthPercent);
        } catch (Throwable t) {
            // renderer jar without the helper: nothing to apply
        }
    }

    /** Water blue transmittance in percent (100 = shipped); read when the water material is built (resource reload). */
    public static int getWaterBlue() {
        return waterBluePercent;
    }

    public static void setWaterBlue(int percent) {
        waterBluePercent = Math.max(25, Math.min(150, percent));
        applyWaterBlue();
    }

    private static void applyWaterBlue() {
        try {
            game("com.nvidia.rtxremix.minecraft.terrain.capture.GlassContactFaces").getField("waterBluePercent")
                    .setInt(null, waterBluePercent);
        } catch (Throwable t) {
            // renderer jar without the helper: nothing to apply
        }
    }

    /** Separate glass-like blocks that touch each other (other colours of glass, water) by a hairline of air. */
    public static boolean isGlassGap() {
        return glassGap;
    }

    public static void setGlassGap(boolean on) {
        if (on == glassGap) {
            return;
        }
        glassGap = on;
        try {
            game("com.nvidia.rtxremix.minecraft.terrain.capture.GlassContactFaces").getField("separateGlass").setBoolean(null, on);
        } catch (Throwable t) {
            System.err.println("[translucent-fix] glass gap switch unavailable: " + t);
        }
        if (enabled) {
            rebuildTerrain();
        }
    }

    /** Sun and moon apparent size in percent of the shipped size (100 = shipped); bigger = softer shadow edges. */
    public static int getSunSize() {
        return sunSizePercent;
    }

    public static void setSunSize(int percent) {
        int p = Math.max(100, Math.min(2000, percent));
        sunSizePercent = p;
        applySunSize();
    }

    private static void applySunSize() {
        try {
            game("com.nvidia.rtxremix.minecraft.terrain.capture.GlassContactFaces").getField("skySizeScale")
                    .setFloat(null, sunSizePercent / 100.0f);
        } catch (Throwable t) {
            // renderer jar without the helper (or not loaded yet): the value is applied again on the next change
        }
    }

    /** The assignable hotkeys, in the order the settings menu lists them: master switch, debug markers, water underside, water off glass. */
    public static int hotkeyCount() {
        return 4;
    }

    public static class_304 getHotkey(int i) {
        return i == 0 ? toggleKey : i == 1 ? diagKey : i == 2 ? undersideKey : nudgeKey;
    }

    public static boolean isHotkeys() {
        return hotkeys;
    }

    public static void setHotkeys(boolean on) {
        hotkeys = on;
    }

    // ---- hotkeys and applying the options to the runtime ----

    @Override
    public void onInitializeClient() {
        // Numpad 1 / Numpad 2 by default (GLFW_KEY_KP_1 = 321, GLFW_KEY_KP_2 = 322), rebindable in Controls.
        applySunSize();
        applyGlassDepth();
        applyWaterBlue();
        toggleKey = KeyBindingHelper.registerKeyBinding(
                new class_304("key.translucentfix.toggle", 321, "key.categories.misc"));
        diagKey = KeyBindingHelper.registerKeyBinding(
                new class_304("key.translucentfix.diagnostic", 322, "key.categories.misc"));
        // unbound by default (GLFW_KEY_UNKNOWN = -1); assign them in the RTX settings menu or in Controls
        undersideKey = KeyBindingHelper.registerKeyBinding(
                new class_304("key.translucentfix.waterUnderside", -1, "key.categories.misc"));
        nudgeKey = KeyBindingHelper.registerKeyBinding(
                new class_304("key.translucentfix.waterNudge", -1, "key.categories.misc"));
        ClientTickEvents.END_CLIENT_TICK.register(client -> {
            while (toggleKey.method_1436()) {
                if (hotkeys) {
                    setFixEnabled(!enabled);
                    announce(client, "Translucent Light Fix: " + (enabled ? "ON" : "OFF"));
                    saveSettings();
                }
            }
            while (diagKey.method_1436()) {
                if (hotkeys) {
                    setDiagnostic(!diagRed);
                    announce(client, "Light Fix debug markers: " + (diagRed ? "ON" : "OFF"));
                    saveSettings();
                }
            }
            while (undersideKey.method_1436()) {
                if (hotkeys) {
                    setWaterUnderside(!waterUnderside);
                    announce(client, "Water Surface Underside: " + (waterUnderside ? "ON" : "OFF"));
                    saveSettings();
                }
            }
            while (nudgeKey.method_1436()) {
                if (hotkeys) {
                    setWaterNudge(!waterNudge);
                    announce(client, "Water Off Glass: " + (waterNudge ? "ON" : "OFF"));
                    saveSettings();
                }
            }
            verifyOptions();
            // The Remix bridge is not up at client init, so keep trying each tick until the writes are accepted.
            if (!optionApplied) {
                optionApplied = writeOptions();
                if (optionApplied && rebuildPending) {
                    rebuildPending = false;
                    rebuildTerrain();
                }
                if (optionApplied) {
                    System.out.println("[translucent-fix] light fix " + (enabled ? "ON" : "OFF"));
                }
            }
        });
    }

    private static void announce(class_310 client, String text) {
        if (client.field_1724 != null) {
            client.field_1724.method_7353(class_2561.method_43470(text), true);
        }
    }

    private static Class<?> game(String name) throws ClassNotFoundException {
        return Class.forName(name, true, TranslucentFixToggle.class.getClassLoader());
    }

    /** The value the shaders' live flag and saturation are read from: ON 20.001 + 0.0001 * saturation%, OFF exactly the shipped 20. */
    private static String desiredNoise() {
        return enabled ? String.format(java.util.Locale.ROOT, "%.5f", 20.001 + 0.0001 * saturationPercent) : "20";
    }

    /** distanceFadeMin: ON 358.4 + 0.00001 * pane depth%, OFF (or depth 0) exactly the shipped 358.4. */
    private static String desiredFade() {
        return enabled && paneDepthPercent > 0
                ? String.format(java.util.Locale.ROOT, "%.5f", 358.4 + 0.00001 * paneDepthPercent) : "358.4";
    }

    /** Current value of a Remix option, or null when it cannot be read. */
    private static Float readFloat(String key) {
        try {
            Method m = game("com.nvidia.rtxremix.RemixBridge").getMethod("getConfigVariableResolved", String.class, byte[].class);
            byte[] out = new byte[256];
            if ((Integer) m.invoke(null, key, out) != 0) {
                return null;
            }
            int n = 0;
            while (n < out.length && out[n] != 0) {
                n++;
            }
            return Float.parseFloat(new String(out, 0, n, StandardCharsets.UTF_8).trim());
        } catch (Throwable t) {
            return null;
        }
    }

    private static boolean near(Float actual, String wanted) {
        return actual != null && Math.abs(actual - Float.parseFloat(wanted)) < 0.00002f;
    }

    private static int verifyTicks;
    private static boolean mismatchLogged;

    /**
     * Every second: the runtime must still hold the values this mod wrote (another writer, a settings save or a config reload
     * could change them, and the patched shaders read the fix state from them). A mismatch is logged and the values are written again.
     */
    private static void verifyOptions() {
        if (!optionApplied || ++verifyTicks < 20) {
            return;
        }
        verifyTicks = 0;
        Float noise = readFloat(NOISE_SCALE);
        Float fade = readFloat(FADE_MIN);
        if (noise == null || fade == null) {
            return;
        }
        if (!near(noise, desiredNoise()) || !near(fade, desiredFade())) {
            System.out.println("[translucent-fix] runtime options drifted (noiseScale=" + noise + " wanted " + desiredNoise()
                    + ", distanceFadeMin=" + fade + " wanted " + desiredFade() + "); writing them again");
            optionApplied = false;
            mismatchLogged = true;
        }
    }

    private static boolean writeOptions() {
        try {
            Method m = game("com.nvidia.rtxremix.RemixBridge").getMethod("setConfigVariable", String.class, String.class);
            boolean on = enabled;
            // ON: 20.001 + 0.01 * saturation (the patched shaders decode the glass colour saturation from it,
            // 20.011 = 100%); OFF: exactly the shipped 20.
            int a = (Integer) m.invoke(null, NOISE_SCALE, desiredNoise());
            // shipped value in both states: with it False the bounce-ray resolve applies no glass colour at all
            int b = (Integer) m.invoke(null, TRANSMISSION_APPROX, "True");
            // 358.4 is the shipped fade minimum. ON: 358.4 + 0.001 * K (K = pane depth percent / 100), which the patched
            // gbuffer shaders decode as the pane depth effect strength (a shift of at most 0.003 m of the distance fade).
            int c = (Integer) m.invoke(null, FADE_MIN, desiredFade());
            if (neeFirstBounceDefault == null) {
                neeFirstBounceDefault = readResolved(NEE_FIRST_BOUNCE);
            }
            if (indirectAlphaDefault == null) {
                indirectAlphaDefault = readResolved(INDIRECT_ALPHA_SHADOWS);
            }
            int d = (Integer) m.invoke(null, NEE_FIRST_BOUNCE,
                    on && DISABLE_FIRST_BOUNCE_CACHE ? "False" : neeFirstBounceDefault);
            int e = (Integer) m.invoke(null, INDIRECT_ALPHA_SHADOWS, on ? "True" : indirectAlphaDefault);
            boolean ok = a == 0 && b == 0 && c == 0 && d == 0 && e == 0;
            if (ok) {
                System.out.println("[translucent-fix] options written: noiseScale " + desiredNoise() + " (runtime now " + readFloat(NOISE_SCALE)
                        + "), distanceFadeMin " + desiredFade() + " (runtime now " + readFloat(FADE_MIN) + ")");
            }
            return ok;
        } catch (Throwable t) {
            return false;
        }
    }

    /** Current resolved value of a Remix option as text; "True" if it cannot be read (the shipped default). */
    private static String readResolved(String key) {
        try {
            Method m = game("com.nvidia.rtxremix.RemixBridge").getMethod("getConfigVariableResolved", String.class, byte[].class);
            byte[] out = new byte[256];
            if ((Integer) m.invoke(null, key, out) == 0) {
                int n = 0;
                while (n < out.length && out[n] != 0) {
                    n++;
                }
                String v = new String(out, 0, n, StandardCharsets.UTF_8).trim();
                if (!v.isEmpty()) {
                    return v;
                }
            }
        } catch (Throwable t) {
            // fall through
        }
        return "True";
    }

    private static void setContactFaces(boolean on) {
        try {
            Field f = game("com.nvidia.rtxremix.minecraft.terrain.capture.GlassContactFaces").getField("enabled");
            f.setBoolean(null, on);
        } catch (Throwable t) {
            System.err.println("[translucent-fix] glass-contact switch unavailable: " + t);
        }
    }

    private static void setWaterUndersideField(boolean on) {
        try {
            Field f = game("com.nvidia.rtxremix.minecraft.terrain.capture.GlassContactFaces").getField("keepWaterUnderside");
            f.setBoolean(null, on);
        } catch (Throwable t) {
            System.err.println("[translucent-fix] water underside switch unavailable: " + t);
        }
    }

    private static void rebuildTerrain() {
        try {
            game("com.nvidia.rtxremix.minecraft.RtxRemixMod").getMethod("rebuildLoadedTerrain").invoke(null);
        } catch (Throwable t) {
            // no world or renderer yet (settings are applied at startup): the terrain is built with the new value
        }
    }

    /** Saves the RTX settings file, so a hotkey change survives a restart like a menu change does. */
    private static void saveSettings() {
        try {
            game("com.nvidia.rtxremix.minecraft.RtxRemixMod").getMethod("saveRtxSettings").invoke(null);
        } catch (Throwable t) {
            System.err.println("[translucent-fix] could not save the settings: " + t);
        }
    }
}
