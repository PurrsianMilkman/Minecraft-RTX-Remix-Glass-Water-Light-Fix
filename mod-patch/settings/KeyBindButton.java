package com.nvidia.rtxremix.minecraft.settings;

import net.minecraft.class_124;
import net.minecraft.class_2561;
import net.minecraft.class_304;
import net.minecraft.class_310;
import net.minecraft.class_3675;
import net.minecraft.class_4185;

/**
 * A key assignment button that works like the game's Controls screen: click it (it shows "> key <"), then press the
 * key (or a mouse button) to assign it. Delete clears the binding; Escape clears it too when the screen lets it through
 * (the settings screen itself closes on Escape). Clicking anywhere else cancels. The binding is the game's own
 * KeyBinding, so it is also listed in Controls and saved in options.txt.
 * Intermediary names: class_4185 = ButtonWidget, class_304 = KeyBinding, class_3675 = InputUtil, method_25306 = onPress,
 * method_25404 = keyPressed, method_25402 = mouseClicked, method_25365 = setFocused, method_25355 = setMessage,
 * method_1422 = setBoundKey, method_1426 = updateKeysByCode, method_16007 = getBoundKeyLocalizedText.
 */
final class KeyBindButton extends class_4185 {
    private final class_304 binding;
    private boolean listening;

    KeyBindButton(class_304 binding, int width) {
        super(0, 0, width, 20, class_2561.method_43473(), (class_4185.class_4241) null, field_40754);
        this.binding = binding;
        refresh();
    }

    private void refresh() {
        class_2561 key = binding.method_16007();
        if (listening) {
            method_25355(class_2561.method_43470("> ").method_10852(key.method_27661().method_27692(class_124.field_1054))
                    .method_10852(class_2561.method_43470(" <")).method_27692(class_124.field_1054));
        } else {
            method_25355(key);
        }
    }

    private void assign(class_3675.class_306 key) {
        binding.method_1422(key);
        class_304.method_1426();
        try {
            class_310.method_1551().field_1690.method_1640();   // GameOptions.write: options.txt
        } catch (Throwable t) {
            // the binding still works this session
        }
        listening = false;
        refresh();
    }

    @Override
    public void method_25306() {
        listening = true;
        refresh();
    }

    @Override
    public boolean method_25402(double x, double y, int button) {
        if (listening && method_25367()) {
            // a second click on the button itself assigns that mouse button, as in Controls
            assign(class_3675.class_307.field_1672.method_1447(button));
            return true;
        }
        return super.method_25402(x, y, button);
    }

    @Override
    public boolean method_25404(int keyCode, int scanCode, int modifiers) {
        if (listening) {
            if (keyCode == 256 || keyCode == 261) {   // Escape / Delete: unbound
                assign(class_3675.field_16237);
            } else {
                assign(class_3675.method_15985(keyCode, scanCode));
            }
            return true;
        }
        return super.method_25404(keyCode, scanCode, modifiers);
    }

    @Override
    public void method_25365(boolean focused) {
        super.method_25365(focused);
        if (!focused && listening) {
            listening = false;
            refresh();
        }
    }
}
