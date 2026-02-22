import java.nio.file.*;
import java.util.*;
import java.util.stream.*;

public class WalkDeleteRepro {
  public static void main(String[] args) throws Exception {
    Path root = Path.of(".tmp", "walk-delete-repro").toAbsolutePath();
    Files.createDirectories(root.resolve("nested"));
    Files.writeString(root.resolve("nested").resolve("a.txt"), "x");

    try (Stream<Path> s = Files.walk(root)) {
      List<Path> paths = s.filter(p -> !p.equals(root)).sorted(Comparator.reverseOrder()).toList();
      for (Path p : paths) {
        System.out.println("deleting " + p);
        Files.deleteIfExists(p);
      }
    }

    System.out.println("done");
    Files.deleteIfExists(root);
  }
}
