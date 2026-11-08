package com.nvidia.rtxremix.minecraft.settings;

import java.lang.reflect.Method;
import java.util.List;

/**
 * Adds the "Light Transform Modifications" settings to the RTX Remix settings menu. They live in the toggle mod
 * (purrsian.translucentfix.TranslucentFixToggle), which holds the state; this class only exposes it as RtxSettings,
 * so the menu's own save, per-category Reset and Reset all apply to them. Nothing is added if the toggle mod is absent.
 */
public final class LightTransformSettings {
    private static final String TOGGLE = "purrsian.translucentfix.TranslucentFixToggle";

    private LightTransformSettings() {}

    /** Called at the end of RtxSettingsFactory.build with the list that becomes the registry. */
    public static void contribute(List<RtxSetting<?>> list) {
        Class<?> toggle;
        try {
            toggle = Class.forName(TOGGLE, true, LightTransformSettings.class.getClassLoader());
        } catch (Throwable t) {
            return;
        }
        list.add(RtxSetting.ofBool("light.fix", SettingGroup.LIGHT_TRANSFORM,
                "rtxremix.setting.light.fix", "rtxremix.setting.light.fix.tip",
                true, () -> get(toggle, "isFixEnabled", true), v -> set(toggle, "setFixEnabled", v)));
        list.add(RtxSetting.ofBool("light.debugMarkers", SettingGroup.LIGHT_TRANSFORM,
                "rtxremix.setting.light.debugMarkers", "rtxremix.setting.light.debugMarkers.tip",
                false, () -> get(toggle, "isDiagnostic", false), v -> set(toggle, "setDiagnostic", v)));
        list.add(RtxSetting.ofInt("light.saturation", SettingGroup.LIGHT_TRANSFORM,
                "rtxremix.setting.light.saturation", "rtxremix.setting.light.saturation.tip",
                25, 200, 100, () -> getInt(toggle, "getSaturation", 100), v -> setInt(toggle, "setSaturation", v))
                .withStep(5));
        list.add(RtxSetting.ofInt("light.paneDepth", SettingGroup.LIGHT_TRANSFORM,
                "rtxremix.setting.light.paneDepth", "rtxremix.setting.light.paneDepth.tip",
                0, 280, 150, () -> getInt(toggle, "getPaneDepth", 150), v -> setInt(toggle, "setPaneDepth", v))
                .withStep(10));
        list.add(RtxSetting.ofInt("light.glassDepth", SettingGroup.LIGHT_TRANSFORM,
                "rtxremix.setting.light.glassDepth", "rtxremix.setting.light.glassDepth.tip",
                75, 400, 100, () -> getInt(toggle, "getGlassDepth", 100), v -> setInt(toggle, "setGlassDepth", v))
                .withStep(25));
        list.add(RtxSetting.ofInt("light.waterBlue", SettingGroup.LIGHT_TRANSFORM,
                "rtxremix.setting.light.waterBlue", "rtxremix.setting.light.waterBlue.tip",
                25, 150, 100, () -> getInt(toggle, "getWaterBlue", 100), v -> setInt(toggle, "setWaterBlue", v))
                .withStep(5));
        list.add(RtxSetting.ofBool("light.glassGap", SettingGroup.LIGHT_TRANSFORM,
                "rtxremix.setting.light.glassGap", "rtxremix.setting.light.glassGap.tip",
                true, () -> get(toggle, "isGlassGap", true), v -> set(toggle, "setGlassGap", v)));
        list.add(RtxSetting.ofBool("light.waterUnderside", SettingGroup.LIGHT_TRANSFORM,
                "rtxremix.setting.light.waterUnderside", "rtxremix.setting.light.waterUnderside.tip",
                false, () -> get(toggle, "isWaterUnderside", false), v -> set(toggle, "setWaterUnderside", v)));
        list.add(RtxSetting.ofBool("light.waterNudge", SettingGroup.LIGHT_TRANSFORM,
                "rtxremix.setting.light.waterNudge", "rtxremix.setting.light.waterNudge.tip",
                false, () -> get(toggle, "isWaterNudge", false), v -> set(toggle, "setWaterNudge", v)));
        list.add(RtxSetting.ofInt("light.sunSize", SettingGroup.LIGHT_TRANSFORM,
                "rtxremix.setting.light.sunSize", "rtxremix.setting.light.sunSize.tip",
                100, 2000, 400, () -> getInt(toggle, "getSunSize", 400), v -> setInt(toggle, "setSunSize", v))
                .withStep(50));
        list.add(RtxSetting.ofBool("light.hotkeys", SettingGroup.LIGHT_TRANSFORM,
                "rtxremix.setting.light.hotkeys", "rtxremix.setting.light.hotkeys.tip",
                true, () -> get(toggle, "isHotkeys", true), v -> set(toggle, "setHotkeys", v)));
    }

    private static boolean get(Class<?> toggle, String name, boolean fallback) {
        try {
            return (Boolean) toggle.getMethod(name).invoke(null);
        } catch (Throwable t) {
            return fallback;
        }
    }

    private static int getInt(Class<?> toggle, String name, int fallback) {
        try {
            return (Integer) toggle.getMethod(name).invoke(null);
        } catch (Throwable t) {
            return fallback;
        }
    }

    private static void setInt(Class<?> toggle, String name, int value) {
        try {
            toggle.getMethod(name, int.class).invoke(null, value);
        } catch (Throwable t) {
            // the toggle mod is the only writer; a failure leaves the previous state
        }
    }

    private static void set(Class<?> toggle, String name, boolean value) {
        try {
            Method m = toggle.getMethod(name, boolean.class);
            m.invoke(null, value);
        } catch (Throwable t) {
            // the toggle mod is the only writer; a failure leaves the previous state
        }
    }
}
