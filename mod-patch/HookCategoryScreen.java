import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import java.nio.file.*;

/**
 * In RtxSettingsCategoryScreen.addOptions (intermediary name method_60325) replaces the call
 * RtxSettings.group(SettingGroup) with LightTransformUi.groupFor(RtxSettings, SettingGroup, Screen), passing the
 * screen (aload_0) as the extra argument.
 */
public class HookCategoryScreen {
    static final String SETTINGS = "com/nvidia/rtxremix/minecraft/settings/RtxSettings";
    static final String GROUP = "com/nvidia/rtxremix/minecraft/settings/SettingGroup";
    static final String UI = "com/nvidia/rtxremix/minecraft/settings/LightTransformUi";

    public static void main(String[] a) throws Exception {
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(Paths.get(a[0]))).accept(cn, 0);
        int hooks = 0;
        for (MethodNode m : cn.methods) {
            if (!m.name.equals("method_60325")) continue;
            for (AbstractInsnNode n : m.instructions.toArray()) {
                if (n instanceof MethodInsnNode mi && mi.getOpcode() == Opcodes.INVOKEVIRTUAL && mi.owner.equals(SETTINGS)
                        && mi.name.equals("group") && mi.desc.equals("(L" + GROUP + ";)Ljava/util/List;")) {
                    m.instructions.insertBefore(n, new VarInsnNode(Opcodes.ALOAD, 0));
                    m.instructions.set(n, new MethodInsnNode(Opcodes.INVOKESTATIC, UI, "groupFor",
                            "(L" + SETTINGS + ";L" + GROUP + ";Lnet/minecraft/class_437;)Ljava/util/List;", false));
                    hooks++;
                }
            }
        }
        System.out.println("category screen hooks inserted: " + hooks + " (expect 1)");
        if (hooks != 1) System.exit(2);
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cn.accept(cw);
        Files.write(Paths.get(a[1]), cw.toByteArray());
    }
}
