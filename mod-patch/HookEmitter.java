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
            } else if (m.name.equals("emitFluidQuads")) {
                // setPos4, setUv4, writeFluidQuad, setPos4, writeFluidQuad: the last call is the reversed duplicate
                java.util.List<MethodInsnNode> calls = new java.util.ArrayList<>();
                for (AbstractInsnNode n : m.instructions.toArray())
                    if (n instanceof MethodInsnNode mi) calls.add(mi);
                MethodInsnNode hit = null;
                for (int i = 0; i + 4 < calls.size(); i++) {
                    if (calls.get(i).name.equals("setPos4") && calls.get(i + 1).name.equals("setUv4")
                            && calls.get(i + 2).name.equals("writeFluidQuad") && calls.get(i + 3).name.equals("setPos4")
                            && calls.get(i + 4).name.equals("writeFluidQuad")) {
                        if (hit != null) throw new IllegalStateException("fluid quad pattern found twice");
                        hit = calls.get(i + 4);
                    }
                }
                if (hit == null) throw new IllegalStateException("fluid quad pattern not found");
                m.instructions.set(hit, new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "fluidQuadReversed",
                        "(L" + hit.owner + ";" + hit.desc.substring(1), false));
                hooks++;
                // water faces that touch glass: pull them a hair off the glass (GlassContactFaces.nudgeWater).
                // The writeFluidQuad calls of the method in order are 6 top faces (the reversed copy is now a helper
                // call), then bottom water, bottom lava, side water, side lava: the water bottom and side calls are
                // the 4th and 2nd from the end.
                java.util.List<MethodInsnNode> wq = new java.util.ArrayList<>();
                for (AbstractInsnNode n : m.instructions.toArray())
                    if (n instanceof MethodInsnNode mi && mi.name.equals("writeFluidQuad")) wq.add(mi);
                if (wq.size() != 9) throw new IllegalStateException("expected 9 writeFluidQuad calls left, found " + wq.size());
                // (the branches are "if water" on local 9 = !fluid.isIn(LAVA): water call first, lava call second.) Lava faces
                // flicker against glass the same way, so the lava bottom and side calls (3rd from the end, last) get the same helpers.
                MethodInsnNode bottomWater = wq.get(wq.size() - 4), bottomLava = wq.get(wq.size() - 3);
                MethodInsnNode sideWater = wq.get(wq.size() - 2), sideLava = wq.get(wq.size() - 1);
                for (MethodInsnNode bottom : new MethodInsnNode[] {bottomWater, bottomLava}) {
                    m.instructions.set(bottom, new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "fluidQuadBottom",
                            "(L" + bottom.owner + ";" + bottom.desc.substring(1), false));
                }
                for (MethodInsnNode side : new MethodInsnNode[] {sideWater, sideLava}) {
                    m.instructions.set(side, new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "fluidQuadSide",
                            "(L" + side.owner + ";" + side.desc.substring(1), false));
                }
                // entry: GlassContactFaces.enterFluid(world, baseX + lx, baseY + ly, baseZ + lz)
                InsnList enter = new InsnList();
                enter.add(new VarInsnNode(Opcodes.ALOAD, 1));
                enter.add(new VarInsnNode(Opcodes.ALOAD, 0));
                enter.add(new FieldInsnNode(Opcodes.GETFIELD, EMITTER, "baseX", "I"));
                enter.add(new VarInsnNode(Opcodes.ILOAD, 3));
                enter.add(new InsnNode(Opcodes.IADD));
                enter.add(new VarInsnNode(Opcodes.ALOAD, 0));
                enter.add(new FieldInsnNode(Opcodes.GETFIELD, EMITTER, "baseY", "I"));
                enter.add(new VarInsnNode(Opcodes.ILOAD, 4));
                enter.add(new InsnNode(Opcodes.IADD));
                enter.add(new VarInsnNode(Opcodes.ALOAD, 0));
                enter.add(new FieldInsnNode(Opcodes.GETFIELD, EMITTER, "baseZ", "I"));
                enter.add(new VarInsnNode(Opcodes.ILOAD, 5));
                enter.add(new InsnNode(Opcodes.IADD));
                enter.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HELPER, "enterFluid",
                        "(L" + WORLD + ";III)V", false));
                m.instructions.insert(enter);
                hooks += 5;
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
        System.out.println("hooks inserted: " + hooks + " (expect 10: 2 returns + stageBakedQuad + frapi + water top + 4 fluid-nudge + enterFluid)");
        if (hooks != 10) System.exit(2);
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cn.accept(cw);
        Files.write(Paths.get(a[1]), cw.toByteArray());
    }
}
