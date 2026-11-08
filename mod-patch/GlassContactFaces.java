package com.nvidia.rtxremix.minecraft.terrain.capture;

import com.nvidia.rtxremix.minecraft.terrain.capture.DirectQuadWriter;
import com.nvidia.rtxremix.minecraft.texture.BlockTextureManager;
import net.minecraft.class_1920;
import net.minecraft.class_2338;
import net.minecraft.class_2350;
import net.minecraft.class_2680;
import net.minecraft.class_2960;

/**
 * Keeps the faces of glass-like blocks that touch an opaque block. Vanilla culls them, which leaves the
 * glass with no exit face against the neighbour, so Remix cannot close the medium and the touching
 * surface is not tinted. The face is drawn and nudged a hair into the glass so it is never coplanar
 * with the neighbour's face. (Names are the compiled intermediary names; class_2680 = BlockState,
 * method_26225 = isOpaque, method_26216 = isOpaqueFullCube, method_8320 = getBlockState.)
 */
public final class GlassContactFaces {
    private static final float LIFT = 0.004f;

    /** On unless -Dtranslucentfix.enabled=false; the toggle mod flips it at runtime (then rebuilds the terrain). */
    public static volatile boolean enabled = !"false".equals(System.getProperty("translucentfix.enabled"));

    /**
     * Keep the reversed (downward-facing) copy of the water top face even while the fix is on. A camera ray that
     * comes up through water, for example from inside a glass room under a lake, meets the surface from below,
     * where only the reversed copy faces it. Off by default (the fix drops the copy); -Dtranslucentfix.waterUnderside=true
     * or the toggle mod's setting turns it on.
     */
    public static volatile boolean keepWaterUnderside = "true".equals(System.getProperty("translucentfix.waterUnderside"));

    /**
     * Pull water bottom and side faces that touch a glass-like block a hair off the glass, so the glass back face and
     * the water face are never coplanar and a view ray crosses glass, then a hairline of air, then water in a defined order.
     * Off by default; -Dtranslucentfix.waterNudge=true or the toggle mod setting turns it on.
     */
    public static volatile boolean nudgeWater = "true".equals(System.getProperty("translucentfix.waterNudge"));

    /**
     * Pull the faces of a glass-like block that touch ANOTHER glass-like block (a different colour of glass, water) a hair
     * into their own block, exactly as faces against opaque blocks are. Without it the two blocks draw coplanar faces on
     * the shared plane (vanilla only culls the face between two blocks of the SAME kind), so a ray meets the pair at one
     * distance, in an order that varies with the camera: the medium the ray thinks it is in goes wrong (black sky behind
     * two glasses, middle blocks of a stack missing from the colour mix, glass under water flickering). With a 8 mm
     * hairline of air between them the order is fixed. On unless -Dtranslucentfix.glassGap=false.
     */
    public static volatile boolean separateGlass = !"false".equals(System.getProperty("translucentfix.glassGap"));

    /**
     * The fluid block being emitted on this thread (set by enterFluid at the top of emitFluidQuads): the world and the
     * block position. No nested class on purpose: the jar patcher copies exactly one class file for this helper.
     */
    private static final ThreadLocal<class_1920[]> FLUID_WORLD = ThreadLocal.withInitial(() -> new class_1920[1]);
    private static final ThreadLocal<int[]> FLUID_POS = ThreadLocal.withInitial(() -> new int[3]);

    /**
     * Sun and moon apparent size as a multiple of the shipped 0.53 / 0.52 degrees (1.0 = shipped). A bigger disc gives wider,
     * softer shadow edges; the total brightness is not meant to change. Applied only while the fix is on.
     */
    public static volatile float skySizeScale = 1.0f;

    /** Glass block depth in percent (100 = shipped). Read when the block materials are built (resource load). */
    public static volatile int glassDepthPercent = 100;

    /** Water blue transmittance scale in percent (100 = shipped 0.89). Read when the water materials are built. */
    public static volatile int waterBluePercent = 100;

    private GlassContactFaces() {}

    /** Blue transmittance of water (shipped 0.89): b^(100/percent), so less than 100 removes blue (greener), more adds it. */
    public static float waterBlue(float shipped) {
        if (!enabled || waterBluePercent == 100) {
            return shipped;
        }
        return (float) Math.pow(shipped, 100.0 / Math.max(10, waterBluePercent));
    }

    /** The glass transmittance measurement distance (shipped 0.35 m): a smaller distance makes a thick glass block absorb more. */
    public static float glassMeasure(float shipped) {
        if (!enabled || glassDepthPercent == 100) {
            return shipped;
        }
        // stays under 0.5 so the patched shaders still treat it as glass
        return Math.min(0.49f, shipped * 100.0f / Math.max(25, glassDepthPercent));
    }

    /** LightManager.updateDistantLight(..., angularDiameterDegrees): the sun (0.53f) and the moon (0.52f) get scaled. */
    public static float skyDiameter(float degrees) {
        if (enabled && (degrees == 0.53f || degrees == 0.52f)) {
            return degrees * skySizeScale;
        }
        return degrees;
    }

    public static void enterFluid(class_1920 world, int x, int y, int z) {
        FLUID_WORLD.get()[0] = world;
        int[] p = FLUID_POS.get();
        p[0] = x;
        p[1] = y;
        p[2] = z;
    }

    private static void nudge(float[] pos, float nx, float ny, float nz, int dx, int dy, int dz) {
        if (!enabled || !nudgeWater) {
            return;
        }
        class_1920 world = FLUID_WORLD.get()[0];
        if (world == null) {
            return;
        }
        int[] p = FLUID_POS.get();
        class_2680 neighbour = world.method_8320(new class_2338(p[0] + dx, p[1] + dy, p[2] + dz));
        if (!glassLike(neighbour)) {
            return;
        }
        for (int i = 0; i < 4; i++) {   // inwards: against the outward normal
            pos[i * 3] -= nx * LIFT;
            pos[i * 3 + 1] -= ny * LIFT;
            pos[i * 3 + 2] -= nz * LIFT;
        }
    }

    /** Stands in for the water bottom face writeFluidQuad. */
    public static void fluidQuadBottom(DirectQuadWriter w, float[] pos, float[] uv, float a, float b, float c,
                                       int d, class_2960 id, float e, float f, float g, float h, String s,
                                       BlockTextureManager tm) {
        nudge(pos, a, b, c, 0, -1, 0);
        w.writeFluidQuad(pos, uv, a, b, c, d, id, e, f, g, h, s, tm);
    }

    /** Stands in for the water side faces writeFluidQuad (the outward normal is the neighbour direction). */
    public static void fluidQuadSide(DirectQuadWriter w, float[] pos, float[] uv, float a, float b, float c,
                                     int d, class_2960 id, float e, float f, float g, float h, String s,
                                     BlockTextureManager tm) {
        nudge(pos, a, b, c, Math.round(a), 0, Math.round(c));
        w.writeFluidQuad(pos, uv, a, b, c, d, id, e, f, g, h, s, tm);
    }

    /**
     * Stands in for the second writeFluidQuad call of the water top face, the reversed copy that sits
     * coplanar with the first. Skipped while the fix is on (unless keepWaterUnderside); the shipped call otherwise.
     */
    public static void fluidQuadReversed(DirectQuadWriter w, float[] pos, float[] uv, float a, float b, float c,
                                         int d, class_2960 id, float e, float f, float g, float h, String s,
                                         BlockTextureManager tm) {
        if (!enabled || keepWaterUnderside) {
            w.writeFluidQuad(pos, uv, a, b, c, d, id, e, f, g, h, s, tm);
        }
    }

    private static boolean glassLike(class_2680 state) {
        String layer = BlockQuadEmitter.classifyBlockLayer(state);
        return "glass".equals(layer) || "translucent".equals(layer);
    }

    /** Called with vanilla's answer; returns true when the face must be drawn after all. */
    public static boolean force(boolean drawn, class_1920 world, class_2680 state, class_2350 side,
                                class_2680 neighbor, int nx, int ny, int nz) {
        if (!enabled || drawn || state.method_26225() || !neighbor.method_26225()) {
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
        if (!enabled || state.method_26225()) {
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
            if (glassLike(state) && ((neighbor.method_26225() && neighbor.method_26216(world, np))
                    || (separateGlass && glassLike(neighbor)))) {
                shift(p, axis, -dir * LIFT);
                return;
            }
        }
    }
}
