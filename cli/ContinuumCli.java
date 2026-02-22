package cli;

import core.runtime.ContinuumRuntime;
import core.scenario.Scenario;

import java.io.IOException;
import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Objects;

/**
 * Deterministic CLI entrypoint for continuum runs.
 */
public final class ContinuumCli {
    @FunctionalInterface
    public interface ScenarioLoader {
        Scenario load(Path scenarioPath) throws IOException;
    }

    @FunctionalInterface
    public interface RunIdGenerator {
        String nextRunId();
    }

    private static final class SequentialRunIdGenerator implements RunIdGenerator {
        private int next = 1;

        @Override
        public synchronized String nextRunId() {
            String runId = String.format("run-fixed-%03d", next);
            next += 1;
            return runId;
        }
    }

    private final ContinuumRuntime runtime;
    private final ScenarioLoader scenarioLoader;
    private final RunIdGenerator runIdGenerator;
    private final Path scenariosRoot;
    private final Path runsRoot;
    private final PrintStream out;
    private final PrintStream err;

    public ContinuumCli() {
        this(
                new ContinuumRuntime(),
                Scenario::load,
                new SequentialRunIdGenerator(),
                Path.of("scenarios"),
                Path.of("runs"),
                System.out,
                System.err
        );
    }

    public ContinuumCli(ScenarioLoader scenarioLoader) {
        this(
                new ContinuumRuntime(),
                scenarioLoader,
                new SequentialRunIdGenerator(),
                Path.of("scenarios"),
                Path.of("runs"),
                System.out,
                System.err
        );
    }

    public ContinuumCli(
            ContinuumRuntime runtime,
            ScenarioLoader scenarioLoader,
            RunIdGenerator runIdGenerator,
            Path scenariosRoot,
            Path runsRoot,
            PrintStream out,
            PrintStream err
    ) {
        this.runtime = Objects.requireNonNull(runtime, "runtime");
        this.scenarioLoader = Objects.requireNonNull(scenarioLoader, "scenarioLoader");
        this.runIdGenerator = Objects.requireNonNull(runIdGenerator, "runIdGenerator");
        this.scenariosRoot = Objects.requireNonNull(scenariosRoot, "scenariosRoot");
        this.runsRoot = Objects.requireNonNull(runsRoot, "runsRoot");
        this.out = Objects.requireNonNull(out, "out");
        this.err = Objects.requireNonNull(err, "err");
    }

    public static void main(String[] args) {
        int exitCode = new ContinuumCli().execute(args);
        if (exitCode != 0) {
            System.exit(exitCode);
        }
    }

    public int execute(String[] args) {
        if (args == null || args.length == 0) {
            printUsage();
            return 2;
        }

        String command = args[0];
        try {
            return switch (command) {
                case "init" -> init();
                case "run" -> run(args);
                default -> {
                    printUsage();
                    yield 2;
                }
            };
        } catch (IOException ex) {
            err.println("Run failed: " + ex.getMessage());
            return 1;
        } catch (RuntimeException ex) {
            err.println("Run failed: " + ex.getMessage());
            return 1;
        }
    }

    private int init() throws IOException {
        Files.createDirectories(scenariosRoot);
        Files.createDirectories(runsRoot);
        out.println("Initialized continuum workspace: " + scenariosRoot + " and " + runsRoot);
        return 0;
    }

    private int run(String[] args) throws IOException {
        if (args.length < 2) {
            err.println("Missing scenario path. Usage: continuum run <scenario-path>");
            return 2;
        }

        Path scenarioPath = Path.of(args[1]).toAbsolutePath().normalize();
        Scenario scenario = scenarioLoader.load(scenarioPath);
        String runId = runIdGenerator.nextRunId();
        Path effectiveRunsRoot = resolveRunsRootForScenario(scenarioPath);
        ContinuumRuntime.RunSummary summary = runtime.run(scenario, scenarioPath, effectiveRunsRoot, runId);

        out.println("Run complete: " + summary.runId());
        out.println("Summary: " + effectiveRunsRoot.resolve(summary.runId()).resolve("summary.json"));
        return 0;
    }

    private Path resolveRunsRootForScenario(Path scenarioPath) {
        if (runsRoot.isAbsolute()) {
            return runsRoot.normalize();
        }

        Path currentDirectory = Path.of("").toAbsolutePath().normalize();
        if (scenarioPath.startsWith(currentDirectory)) {
            return currentDirectory.resolve(runsRoot).normalize();
        }

        Path scenarioParent = scenarioPath.getParent();
        if (scenarioParent == null) {
            return currentDirectory.resolve(runsRoot).normalize();
        }

        return scenarioParent.resolve(runsRoot).normalize();
    }

    private void printUsage() {
        out.println("continuum <command>");
        out.println("  init                Initialize local scaffold directories");
        out.println("  run <scenario-path> Load scenario and write deterministic run artifacts");
    }
}
