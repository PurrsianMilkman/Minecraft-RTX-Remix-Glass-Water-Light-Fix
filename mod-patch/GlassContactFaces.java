package com.nvidia.rtxremix.minecraft.terrain.capture;

import net.minecraft.class_1920;
import net.minecraft.class_2338;
import net.minecraft.class_2350;
import net.minecraft.class_2680;

/**
 * Keeps the faces of glass-like blocks that touch an opaque block. Vanilla culls them, which leaves the
 * glass with no exit face against the neighbour, so Remix cannot close the medium and the touching
 * surface is not tinted. The face is drawn and nudged a hair into the glass so it is never coplanar
 * with the neighbour's face. (Names are the compiled intermediary names; class_2680 = BlockState,
 * method_26225 = isOpaque, method_26216 = isOpaqueFullCube, method_8320 = getBlockState.)
 */
public final class GlassContactFaces {
    private static final float LIFT = 0.004f;

    private GlassContactFaces() {}

    private static boolean glassLike(class_2680 state) {
        String layer = BlockQuadEmitter.classifyBlockLayer(state);
        return "glass".equals(layer) || "translucent".equals(layer);
    }

    /** Called with vanilla's answer; returns true when the face must be drawn after all. */
    public static boolean force(boolean drawn, class_1920 world, class_2680 state, class_2350 side,
                                class_2680 neighbor, int nx, int ny, int nz) {
        if (drawn || state.method_26225() || !neighbor.method_26225()) {
            return drawn;
        }
        if (!glassLike(state)) {
            return false;
        }
        return neighbor.method_26216(world, new class_2338(nx, ny, nz));
    }

    private static boolean flat(float[] p, int axis, float value) {
        return p[axis] == value && p[axis + 3] == value && p[axis + 6] == value && p[axis + 9] == value;
    }

    private static void shift(float[] p, int axis, float delta) {
        p[axis] += delta;
        p[axis + 3] += delta;
        p[axis + 6] += delta;
        p[axis + 9] += delta;
    }

    /** p holds four xyz vertices already offset by (lx, ly, lz); pos is the block being emitted. */
    public static void lift(float[] p, float lx, float ly, float lz, class_1920 world, class_2680 state,
                            class_2338 pos) {
        if (state.method_26225()) {
            return;
        }
        float[] lo = {lx, ly, lz};
        int[] at = {pos.method_10263(), pos.method_10264(), pos.method_10260()};
        for (int axis = 0; axis < 3; axis++) {
            int dir;
            if (flat(p, axis, lo[axis])) {
                dir = -1;
            } else if (flat(p, axis, lo[axis] + 1.0f)) {
                dir = 1;
            } else {
                continue;
            }
            int x = at[0] + (axis == 0 ? dir : 0);
            int y = at[1] + (axis == 1 ? dir : 0);
            int z = at[2] + (axis == 2 ? dir : 0);
            class_2338 np = new class_2338(x, y, z);
            class_2680 neighbor = world.method_8320(np);
            if (neighbor.method_26225() && glassLike(state) && neighbor.method_26216(world, np)) {
                shift(p, axis, -dir * LIFT);
                return;
            }
        }
    }
}
