import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import java.nio.file.*;

/**
 * In BlockTextureManager.buildAtlasTransMaterialInfo (stained glass) and createAtlasGlassMaterial (clear glass) the glass
 * transmittance measurement distance is the constant 0.35f. Each such constant is followed by
 * GlassContactFaces.glassMeasure(F)F so the glass block depth can be scaled when the materials are built.
 */
public class HookMeasure {
    static final String HELPER = "com/nvidia/rtxremix/minecraft/terrain/capture/GlassContactFaces";

    public static void main(String[] a) throws Exception {
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(Paths.get(a[0]))).accept(cn, 0);
        int hooks = 0;
        for (MethodNode m : cn.methods) {
            if (m.name.equals("buildWaterMaterials")) {
                for (AbstractInsnNode n : m.instructions.toArray()) {
                    if (n instanceof FieldInsnNode && n.getOpcode() == Opcodes.GETFIELD
                            && ((FieldInsnNode) n).name.equals("waterTransmittanceB")) {
                        m.instructions.insert(n, new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "waterBlue", "(F)F", false));
                        hooks++;
                    }
                }
                continue;
            }
            if (!m.name.equals("buildAtlasTransMaterialInfo") && !m.name.equals("createAtlasGlassMaterial")) continue;
            for (AbstractInsnNode n : m.instructions.toArray()) {
                if (n instanceof LdcInsnNode && ((LdcInsnNode) n).cst instanceof Float && (Float) ((LdcInsnNode) n).cst == 0.35f) {
                    m.instructions.insert(n, new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "glassMeasure", "(F)F", false));
                    hooks++;
                }
            }
        }
        System.out.println("measure hooks inserted: " + hooks + " (expect 4)");
        if (hooks != 4) System.exit(2);
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cn.accept(cw);
        Files.write(Paths.get(a[1]), cw.toByteArray());
    }
}
