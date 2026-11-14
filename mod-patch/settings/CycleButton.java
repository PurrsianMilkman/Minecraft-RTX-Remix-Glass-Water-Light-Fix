package com.nvidia.rtxremix.minecraft.settings;

import net.minecraft.class_2561;
import net.minecraft.class_4185;
import net.minecraft.class_7919;

/**
 * A button that steps an integer setting through min..max on each click and wraps around (used for "GI Spread and reach":
 * Off, Low, Medium, High). Its text is the language entry "<label key>.<value>"; the setting's tooltip is shown on hover.
 * Written against intermediary names: class_4185 = ButtonWidget, method_25306 = onPress, method_25355 = setMessage,
 * field_40754 = DEFAULT_NARRATION_SUPPLIER.
 */
final class CycleButton extends class_4185 {
    private final RtxSetting<Integer> setting;
    private final int min;
    private final int max;

    CycleButton(RtxSetting<Integer> setting, int width, int min, int max) {
        super(0, 0, width, 20, class_2561.method_43473(), (class_4185.class_4241) null, field_40754);
        this.setting = setting;
        this.min = min;
        this.max = max;
        method_47400(class_7919.method_47407(class_2561.method_43471(setting.tooltipKey())));
        refresh();
    }

    private void refresh() {
        method_25355(class_2561.method_43471(setting.labelKey() + "." + setting.get()));
    }

    @Override
    public void method_25306() {
        int value = setting.get();
        setting.apply(value >= max ? min : value + 1);
        refresh();
    }
}
