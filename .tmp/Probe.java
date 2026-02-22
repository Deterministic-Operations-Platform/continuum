import core.runtime.ContinuumRuntime;
import java.nio.file.Path;

public class Probe {
  public static void main(String[] args) throws Exception {
    ContinuumRuntime rt = new ContinuumRuntime();
    rt.run(Path.of("scenarios/fednow/cam29/scenario.yaml"), Path.of("runs/sandbox"), "..\\escape-test");
  }
}
