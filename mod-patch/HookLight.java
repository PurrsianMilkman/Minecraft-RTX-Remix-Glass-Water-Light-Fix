import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import java.nio.file.*;

/**
 * At the head of LightManager.updateDistantLight(RemixLight, float[], float[], float) replaces the angular diameter
 * argument (local 4) with GlassContactFaces.skyDiameter(angularDiameter), so the sun and moon size can be scaled live.
 */
public class HookLight {
    static final String HELPER = "com/nvidia/rtxremix/minecraft/terrain/capture/GlassContactFaces";

    public static void main(String[] a) throws Exception {
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(Paths.get(a[0]))).accept(cn, 0);
        int hooks = 0;
        for (MethodNode m : cn.methods) {
            if (!m.name.equals("updateDistantLight")) continue;
            if (!m.desc.endsWith("[F[FF)Lcom/nvidia/rtxremix/minecraft/RemixLight;") && !m.desc.contains("[F[FF)")) {
                throw new IllegalStateException("unexpected updateDistantLight descriptor " + m.desc);
            }
            InsnList l = new InsnList();
            l.add(new VarInsnNode(Opcodes.FLOAD, 4));
            l.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "skyDiameter", "(F)F", false));
            l.add(new VarInsnNode(Opcodes.FSTORE, 4));
            m.instructions.insert(l);
            hooks++;
        }
        System.out.println("light hooks inserted: " + hooks + " (expect 1)");
        if (hooks != 1) System.exit(2);
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cn.accept(cw);
        Files.write(Paths.get(a[1]), cw.toByteArray());
    }
}
