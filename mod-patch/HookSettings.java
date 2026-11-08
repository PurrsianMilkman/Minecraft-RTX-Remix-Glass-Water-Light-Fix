import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import java.nio.file.*;

/** Calls LightTransformSettings.contribute(list) just before RtxSettingsFactory.build wraps its list in RtxSettings. */
public class HookSettings {
    static final String SETTINGS = "com/nvidia/rtxremix/minecraft/settings/RtxSettings";
    static final String HELPER = "com/nvidia/rtxremix/minecraft/settings/LightTransformSettings";

    public static void main(String[] a) throws Exception {
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(Paths.get(a[0]))).accept(cn, 0);
        int hooks = 0;
        for (MethodNode m : cn.methods) {
            if (!m.name.equals("build")) continue;
            for (AbstractInsnNode n : m.instructions.toArray()) {
                if (n instanceof TypeInsnNode t && t.getOpcode() == Opcodes.NEW && t.desc.equals(SETTINGS)) {
                    InsnList l = new InsnList();
                    l.add(new VarInsnNode(Opcodes.ALOAD, 1));   // the List<RtxSetting<?>> built so far
                    l.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "contribute", "(Ljava/util/List;)V", false));
                    m.instructions.insertBefore(n, l);
                    hooks++;
                }
            }
        }
        System.out.println("settings hooks inserted: " + hooks + " (expect 1)");
        if (hooks != 1) System.exit(2);
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cn.accept(cw);
        Files.write(Paths.get(a[1]), cw.toByteArray());
    }
}
