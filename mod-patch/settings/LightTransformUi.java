package com.nvidia.rtxremix.minecraft.settings;

import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.List;

import net.minecraft.class_124;
import net.minecraft.class_2561;
import net.minecraft.class_304;
import net.minecraft.class_310;
import net.minecraft.class_339;
import net.minecraft.class_353;
import net.minecraft.class_437;
import net.minecraft.class_7172;
import net.minecraft.class_7842;

/**
 * Lays out the "Light Transform Modifications" group of the RTX settings category screen: the toggles as the usual
 * two-column buttons, then the glass saturation slider as a row with its name on the left and the slider on the right.
 * RtxSettingsCategoryScreen.addOptions calls {@link #groupFor} in place of RtxSettings.group(group); for this group
 * the rows are added here and an empty list is returned so the screen adds nothing more, for every other group the
 * list comes back untouched. Any failure falls back to the screen's own rendering of the group.
 * (class_353 = OptionListWidget, class_437 = Screen, class_7842 = TextWidget, class_7172 = SimpleOption.)
 */
public final class LightTransformUi {
    private LightTransformUi() {}

    public static List<RtxSetting<?>> groupFor(RtxSettings settings, SettingGroup group, class_437 screen) {
        List<RtxSetting<?>> list = settings.group(group);
        if (group != SettingGroup.LIGHT_TRANSFORM || list.isEmpty()) {
            return list;
        }
        try {
            class_353 body = bodyOf(screen);
            class_7842 header = new class_7842(310, 20,
                    class_2561.method_43471(group.labelKey()).method_27692(class_124.field_1067), class_310.method_1551().field_1772);
            List<class_7172<?>> toggles = new ArrayList<>();
            List<RtxSetting<Integer>> sliders = new ArrayList<>();
            for (RtxSetting<?> s : list) {
                if (s.kind() == RtxSetting.Kind.INT) {
                    @SuppressWarnings("unchecked")
                    RtxSetting<Integer> sat = (RtxSetting<Integer>) s;
                    sliders.add(sat);
                } else {
                    toggles.add(RtxOptionFactory.toOption(s));
                }
            }
            List<class_7842> names = new ArrayList<>();
            List<class_339> widgets = new ArrayList<>();
            for (RtxSetting<Integer> s : sliders) {
                class_7842 name = new class_7842(150, 20, class_2561.method_43471(s.labelKey()), class_310.method_1551().field_1772);
                name.method_48596();   // align left
                name.method_47400(net.minecraft.class_7919.method_47407(class_2561.method_43471(s.tooltipKey())));
                names.add(name);
                if ("light.giReach".equals(s.id())) {
                    widgets.add(new CycleButton(s, 150, (int) s.min(), (int) s.max()));
                } else {
                    widgets.add(new PercentSlider(s, 150, (int) s.min(), (int) s.max(), s.step()));
                }
            }
            // everything built: now add (so a failure above cannot leave half a group behind)
            body.method_20407(header, null);
            if (!toggles.isEmpty()) {
                body.method_20408(toggles.toArray(new class_7172<?>[0]));
            }
            for (int i = 0; i < widgets.size(); i++) {
                body.method_20407(names.get(i), widgets.get(i));
            }
            addHotkeys(body);
            return List.of();
        } catch (Throwable t) {
            return list;
        }
    }

    /** The "Hotkeys" rows: a name and a click-then-press key button for each toggle in the toggle mod. Never fatal. */
    private static void addHotkeys(class_353 body) {
        try {
            Class<?> toggle = Class.forName("purrsian.translucentfix.TranslucentFixToggle", true,
                    LightTransformUi.class.getClassLoader());
            int n = (Integer) toggle.getMethod("hotkeyCount").invoke(null);
            java.lang.reflect.Method get = toggle.getMethod("getHotkey", int.class);
            List<class_7842> names = new ArrayList<>();
            List<KeyBindButton> buttons = new ArrayList<>();
            for (int i = 0; i < n; i++) {
                class_304 kb = (class_304) get.invoke(null, i);
                class_7842 name = new class_7842(150, 20, class_2561.method_43471("rtxremix.hotkey." + i), class_310.method_1551().field_1772);
                name.method_48596();
                names.add(name);
                buttons.add(new KeyBindButton(kb, 150));
            }
            body.method_20407(new class_7842(310, 20, class_2561.method_43471("rtxremix.hotkey.header").method_27692(class_124.field_1067),
                    class_310.method_1551().field_1772), null);
            for (int i = 0; i < n; i++) {
                body.method_20407(names.get(i), buttons.get(i));
            }
        } catch (Throwable t) {
            // no hotkey rows; the rest of the group is already there
        }
    }

    /** GameOptionsScreen.body (protected): found by its type. */
    private static class_353 bodyOf(class_437 screen) throws ReflectiveOperationException {
        for (Class<?> c = screen.getClass(); c != null; c = c.getSuperclass()) {
            for (Field f : c.getDeclaredFields()) {
                if (class_353.class.isAssignableFrom(f.getType())) {
                    f.setAccessible(true);
                    return (class_353) f.get(screen);
                }
            }
        }
        throw new NoSuchFieldException("option list");
    }
}
