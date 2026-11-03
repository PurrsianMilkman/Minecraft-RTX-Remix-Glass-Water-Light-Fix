import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.tree.analysis.*;
import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.util.*;
public class Verify2 {
    public static void main(String[] a) throws Exception {
        List<URL> urls = new ArrayList<>();
        for (int i = 1; i < a.length; i++) {
            File f = new File(a[i]);
            if (f.isDirectory() && a[i].endsWith("jars")) for (File j : f.listFiles()) urls.add(j.toURI().toURL());
            else urls.add(f.toURI().toURL());
        }
        ClassLoader cl = new URLClassLoader(urls.toArray(new URL[0]), null);
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(Paths.get(a[0]))).accept(cn, 0);
        Set<String> mine = Set.of("shouldDrawBlockSide", "stageBakedQuad", "emitFrapiBlock");
        for (MethodNode m : cn.methods) {
            if (!mine.contains(m.name)) continue;
            Analyzer<BasicValue> an = new Analyzer<>(new SimpleVerifier(Opcodes.ASM9, Type.getObjectType(cn.name),
                    Type.getObjectType(cn.superName), null, false) {
                @Override protected Class<?> getClass(Type t) {
                    try { return Class.forName(t.getClassName(), false, cl); } catch (ClassNotFoundException e) { throw new TypeNotPresentException(t.getClassName(), e); }
                }
            });
            try { an.analyze(cn.name, m); System.out.println("OK   " + m.name + " (maxStack=" + m.maxStack + ")"); }
            catch (Exception e) { System.out.println("FAIL " + m.name + ": " + e); }
        }
    }
}
