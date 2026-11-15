import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import java.nio.file.*;

/**
 * Texture blend/horizon fix: in RemixTexture.doCreate(RemixAPI, long hash) the hash stored into TextureFromMemoryInfo.hash becomes
 * GlassContactFaces.texHash(hash, width, height, purpose), which marks large atlas textures so the patched runtime caps their mip chain.
 */
public class HookTexture {
    static final String HELPER = "com/nvidia/rtxremix/minecraft/terrain/capture/GlassContactFaces";
    static final String OWNER = "com/nvidia/rtxremix/minecraft/asset/RemixTexture";
    static final String INFO = "com/nvidia/rtxremix/TextureFromMemoryInfo";

    public static void main(String[] a) throws Exception {
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(Paths.get(a[0]))).accept(cn, 0);
        int hooks = 0;
        for (MethodNode m : cn.methods) {
            if (!m.name.equals("doCreate") || !m.desc.equals("(Lcom/nvidia/rtxremix/RemixAPI;J)J")) continue;
            for (AbstractInsnNode n = m.instructions.getFirst(); n != null; n = n.getNext()) {
                if (n.getOpcode() != Opcodes.LLOAD || ((VarInsnNode) n).var != 2) continue;
                AbstractInsnNode next = n.getNext();
                if (!(next instanceof FieldInsnNode)) continue;
                FieldInsnNode f = (FieldInsnNode) next;
                if (f.getOpcode() != Opcodes.PUTFIELD || !f.owner.equals(INFO) || !f.name.equals("hash")) continue;
                InsnList l = new InsnList();
                for (String field : new String[] {"width", "height", "purpose"}) {
                    l.add(new VarInsnNode(Opcodes.ALOAD, 0));
                    l.add(new FieldInsnNode(Opcodes.GETFIELD, OWNER, field, "I"));
                }
                l.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "texHash", "(JIII)J", false));
                m.instructions.insert(n, l);
                hooks++;
            }
        }
        System.out.println("texture hash hooks inserted: " + hooks + " (expect 1)");
        if (hooks != 1) System.exit(2);
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cn.accept(cw);
        Files.write(Paths.get(a[1]), cw.toByteArray());
    }
}
