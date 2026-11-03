import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import java.nio.file.*;

public class HookEmitter {
    static final String HELPER = "com/nvidia/rtxremix/minecraft/terrain/capture/GlassContactFaces";
    static final String EMITTER = "com/nvidia/rtxremix/minecraft/terrain/capture/BlockQuadEmitter";
    static final String WORLD = "net/minecraft/class_1920", STATE = "net/minecraft/class_2680",
            DIR = "net/minecraft/class_2350", POS = "net/minecraft/class_2338";

    public static void main(String[] a) throws Exception {
        byte[] in = Files.readAllBytes(Paths.get(a[0]));
        ClassNode cn = new ClassNode();
        new ClassReader(in).accept(cn, 0);
        int hooks = 0;
        for (MethodNode m : cn.methods) {
            if (m.name.equals("shouldDrawBlockSide")) {
                for (AbstractInsnNode n : m.instructions.toArray()) {
                    if (n.getOpcode() == Opcodes.IRETURN) {
                        InsnList l = new InsnList();
                        l.add(new VarInsnNode(Opcodes.ALOAD, 1));
                        l.add(new VarInsnNode(Opcodes.ALOAD, 2));
                        l.add(new VarInsnNode(Opcodes.ALOAD, 3));
                        l.add(new VarInsnNode(Opcodes.ALOAD, 7));
                        l.add(new VarInsnNode(Opcodes.ILOAD, 4));
                        l.add(new VarInsnNode(Opcodes.ILOAD, 5));
                        l.add(new VarInsnNode(Opcodes.ILOAD, 6));
                        l.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "force",
                                "(ZL" + WORLD + ";L" + STATE + ";L" + DIR + ";L" + STATE + ";III)Z", false));
                        m.instructions.insertBefore(n, l);
                        hooks++;
                    }
                }
            } else if (m.name.equals("stageBakedQuad")) {
                // insert before "aload vd; bipush 7; iaload" (int packedNormal = vd[7])
                AbstractInsnNode target = null;
                for (AbstractInsnNode n : m.instructions.toArray()) {
                    if (n.getOpcode() == Opcodes.BIPUSH && ((IntInsnNode) n).operand == 7
                            && n.getNext() != null && n.getNext().getOpcode() == Opcodes.IALOAD
                            && n.getPrevious() != null && n.getPrevious().getOpcode() == Opcodes.ALOAD) {
                        target = n.getPrevious();
                        break;
                    }
                }
                if (target == null) throw new IllegalStateException("stageBakedQuad anchor not found");
                InsnList l = new InsnList();
                l.add(new VarInsnNode(Opcodes.ALOAD, 0));
                l.add(new FieldInsnNode(Opcodes.GETFIELD, EMITTER, "tempPositions", "[F"));
                l.add(new VarInsnNode(Opcodes.FLOAD, 5));
                l.add(new VarInsnNode(Opcodes.FLOAD, 6));
                l.add(new VarInsnNode(Opcodes.FLOAD, 7));
                l.add(new VarInsnNode(Opcodes.ALOAD, 4));
                l.add(new VarInsnNode(Opcodes.ALOAD, 3));
                l.add(new VarInsnNode(Opcodes.ALOAD, 0));
                l.add(new FieldInsnNode(Opcodes.GETFIELD, EMITTER, "mutablePos", "Lnet/minecraft/class_2338$class_2339;"));
                l.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "lift",
                        "([FFFFL" + WORLD + ";L" + STATE + ";L" + POS + ";)V", false));
                m.instructions.insertBefore(target, l);
                hooks++;
            } else if (m.name.equals("emitFrapiBlock")) {
                MethodInsnNode call = null;
                for (AbstractInsnNode n : m.instructions.toArray())
                    if (n instanceof MethodInsnNode mi && mi.name.equals("stageQuad")) { call = mi; break; }
                if (call == null) throw new IllegalStateException("stageQuad call not found");
                AbstractInsnNode w = call;
                while (w != null && !(w instanceof FieldInsnNode f && f.name.equals("writer"))) w = w.getPrevious();
                if (w == null) throw new IllegalStateException("writer field not found");
                AbstractInsnNode target = w.getPrevious();   // the aload_0 feeding getfield writer
                if (target.getOpcode() != Opcodes.ALOAD) throw new IllegalStateException("unexpected receiver load");
                InsnList l = new InsnList();
                l.add(new VarInsnNode(Opcodes.ALOAD, 0));
                l.add(new FieldInsnNode(Opcodes.GETFIELD, EMITTER, "tempPositions", "[F"));
                l.add(new VarInsnNode(Opcodes.FLOAD, 6));
                l.add(new VarInsnNode(Opcodes.FLOAD, 7));
                l.add(new VarInsnNode(Opcodes.FLOAD, 8));
                l.add(new VarInsnNode(Opcodes.ALOAD, 1));
                l.add(new VarInsnNode(Opcodes.ALOAD, 2));
                l.add(new VarInsnNode(Opcodes.ALOAD, 0));
                l.add(new FieldInsnNode(Opcodes.GETFIELD, EMITTER, "mutablePos", "Lnet/minecraft/class_2338$class_2339;"));
                l.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "lift",
                        "([FFFFL" + WORLD + ";L" + STATE + ";L" + POS + ";)V", false));
                m.instructions.insertBefore(target, l);
                hooks++;
            }
        }
        System.out.println("hooks inserted: " + hooks + " (expect 4: 2 returns + stageBakedQuad + frapi)");
        if (hooks != 4) System.exit(2);
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cn.accept(cw);
        Files.write(Paths.get(a[1]), cw.toByteArray());
    }
}
