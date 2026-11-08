package com.nvidia.rtxremix.minecraft.settings;

import net.minecraft.class_2561;
import net.minecraft.class_357;
import net.minecraft.class_7919;

/**
 * A percent slider shown beside its name (the same two-column pattern as the block-light table), used for the glass
 * colour saturation and the glass pane depth effect. Whole steps between min and max; the handle snaps to the step,
 * the left/right keys move one step, and the value is applied while dragging so the change shows live. Written against
 * intermediary names: class_357 = SliderWidget, field_22753 = its 0..1 position, method_25346 = updateMessage,
 * method_25344 = applyValue, method_25404 = keyPressed.
 */
final class PercentSlider extends class_357 {
    private final RtxSetting<Integer> setting;
    private final int min;
    private final int max;
    private final int step;

    PercentSlider(RtxSetting<Integer> setting, int width, int min, int max, int step) {
        super(0, 0, width, 20, class_2561.method_43473(), position(setting.get(), min, max));
        this.setting = setting;
        this.min = min;
        this.max = max;
        this.step = step;
        method_47400(class_7919.method_47407(class_2561.method_43471(setting.tooltipKey())));
        method_25346();
    }

    static int percent(double position, int min, int max, int step) {
        int steps = (int) Math.round(position * (max - min) / (double) step);
        return Math.max(min, Math.min(max, min + steps * step));
    }

    static double position(int percent, int min, int max) {
        int p = Math.max(min, Math.min(max, percent));
        return (p - min) / (double) (max - min);
    }

    @Override
    protected void method_25346() {
        method_25355(class_2561.method_43470(percent(field_22753, min, max, step) + "%"));
    }

    @Override
    protected void method_25344() {
        int p = percent(field_22753, min, max, step);
        field_22753 = position(p, min, max);          // snap the handle to the step
        setting.apply(p);
    }

    @Override
    public boolean method_25404(int keyCode, int scanCode, int modifiers) {
        if (keyCode == 263 || keyCode == 262) {   // GLFW_KEY_LEFT / GLFW_KEY_RIGHT
            int p = Math.max(min, Math.min(max, percent(field_22753, min, max, step) + (keyCode == 263 ? -step : step)));
            field_22753 = position(p, min, max);
            method_25344();
            method_25346();
            return true;
        }
        return super.method_25404(keyCode, scanCode, modifiers);
    }
}
