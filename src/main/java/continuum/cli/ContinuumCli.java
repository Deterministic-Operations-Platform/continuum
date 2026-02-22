package continuum.cli;

import continuum.core.scenario.Scenario;
import continuum.core.scenario.ScenarioLoader;
import continuum.evidence.collector.EvidenceCollector;
import continuum.evidence.collector.FileEvidenceCollector;

import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
<<<<<<< Updated upstream
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.util.Objects;
import java.util.UUID;
import java.util.function.Supplier;

public class ContinuumCli {
    private static Supplier<ScenarioLoader> scenarioLoaderFactory = ScenarioLoader::new;

    static void setScenarioLoaderFactoryForTests(Supplier<ScenarioLoader> factory) {
        scenarioLoaderFactory = Objects.requireNonNull(factory, "factory");
    }

    static void resetTestOverrides() {
        scenarioLoaderFactory = ScenarioLoader::new;
=======
import java.util.List;
import java.util.Objects;

public class ContinuumCli {
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

    private static final List<String> MANIFEST_FILES = List.of(
            "scenario.yaml",
            "summary.json",
            "events.log",
            "manifest.json"
    );

    private final ScenarioLoader scenarioLoader;
    private final RunIdGenerator runIdGenerator;
    private final Path runsRoot;
    private final PrintStream out;
    private final PrintStream err;

    public ContinuumCli() {
        this(new ScenarioLoader(), new SequentialRunIdGenerator(), Path.of("runs"), System.out, System.err);
    }

    public ContinuumCli(ScenarioLoader scenarioLoader) {
        this(scenarioLoader, new SequentialRunIdGenerator(), Path.of("runs"), System.out, System.err);
    }

    public ContinuumCli(
            ScenarioLoader scenarioLoader,
            RunIdGenerator runIdGenerator,
            Path runsRoot,
            PrintStream out,
            PrintStream err
    ) {
        this.scenarioLoader = Objects.requireNonNull(scenarioLoader, "scenarioLoader");
        this.runIdGenerator = Objects.requireNonNull(runIdGenerator, "runIdGenerator");
        this.runsRoot = Objects.requireNonNull(runsRoot, "runsRoot");
        this.out = Objects.requireNonNull(out, "out");
        this.err = Objects.requireNonNull(err, "err");
>>>>>>> Stashed changes
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
        return switch (command) {
            case "init" -> handleInit();
            case "run" -> handleRun(args);
            default -> {
                printUsage();
                yield 2;
            }
        };
    }

    private int handleInit() {
        out.println("Continuum initialized");
        return 0;
    }

    private int handleRun(String[] args) {
        if (args.length < 2) {
            err.println("Missing scenario path");
            printUsage();
            return 2;
        }

<<<<<<< Updated upstream
        Path scenarioPath = Path.of(args[1]);
        ScenarioLoader loader = scenarioLoaderFactory.get();
        Scenario scenario = loader.load(scenarioPath);

        String runId = buildRunId();
        Path runDirectory = resolveRunDirectory(runId);
=======
>>>>>>> Stashed changes
        try {
            Path scenarioPath = Path.of(args[1]).toAbsolutePath().normalize();
            Scenario scenario = scenarioLoader.load(scenarioPath);
            String runId = runIdGenerator.nextRunId();
            Path runDirectory = resolveRunsRootForScenario(scenarioPath).resolve(runId);
            EvidenceCollector collector = new FileEvidenceCollector();

<<<<<<< Updated upstream
            String summaryJson = """
                    {
                      \"runId\": \"%s\",
                      \"scenarioName\": \"%s\",
                      \"status\": \"STARTED\"
                    }
                    """.formatted(escapeJson(runId), escapeJson(scenario.getName()));
            Files.writeString(runDirectory.resolve("summary.json"), summaryJson, StandardCharsets.UTF_8);
            Files.writeString(runDirectory.resolve("events.jsonl"), "", StandardCharsets.UTF_8);
=======
            try {
                collector.initialize(runDirectory);
                collector.collect("scenario.yaml", buildScenarioSnapshot(scenarioPath, scenario));
                collector.collect("summary.json", buildSummary(runId, scenario, scenarioPath));
                collector.collect("events.log", new byte[0]);
                collector.collect("manifest.json", buildManifest(runId));
            } catch (IOException ex) {
                err.println("Run failed: Unable to create run artifacts in " + runDirectory);
                return 1;
            }
>>>>>>> Stashed changes

            out.println("Scenario: " + scenario.getName());
            out.println("Run directory: " + runDirectory);
            return 0;
        } catch (RuntimeException ex) {
            err.println("Run failed: " + ex.getMessage());
            return 1;
        }
    }

<<<<<<< Updated upstream
    private static String buildRunId() {
        String fixedRunId = firstNonBlank(
                System.getProperty("continuum.runId"),
                System.getenv("CONTINUUM_RUN_ID"),
                System.getenv("CONTINUUM_FIXED_RUN_ID")
        );
        if (fixedRunId != null) {
            return fixedRunId;
        }

        String timestamp = DateTimeFormatter.ISO_INSTANT.format(Instant.now())
                .replace(":", "")
                .replace("-", "");
        return timestamp + "-" + UUID.randomUUID().toString().substring(0, 8);
=======
    private byte[] buildScenarioSnapshot(Path scenarioPath, Scenario scenario) throws IOException {
        if (Files.exists(scenarioPath)) {
            return Files.readAllBytes(scenarioPath);
        }

        String fallback = "name: " + scenario.getName() + System.lineSeparator() + "steps: []" + System.lineSeparator();
        return fallback.getBytes(StandardCharsets.UTF_8);
    }

    private byte[] buildSummary(String runId, Scenario scenario, Path scenarioPath) {
        String summaryJson = """
                {
                  "runId": "%s",
                  "scenarioName": "%s",
                  "scenarioPath": "%s",
                  "status": "STARTED"
                }
                """.formatted(escapeJson(runId), escapeJson(scenario.getName()), escapeJson(scenarioPath.toString()));
        return summaryJson.getBytes(StandardCharsets.UTF_8);
    }

    private byte[] buildManifest(String runId) {
        String manifestJson = """
                {
                  "runId": "%s",
                  "artifacts": [
                    "%s",
                    "%s",
                    "%s",
                    "%s"
                  ]
                }
                """.formatted(
                escapeJson(runId),
                MANIFEST_FILES.get(0),
                MANIFEST_FILES.get(1),
                MANIFEST_FILES.get(2),
                MANIFEST_FILES.get(3)
        );
        return manifestJson.getBytes(StandardCharsets.UTF_8);
>>>>>>> Stashed changes
    }

    private static Path resolveRunDirectory(String runId) {
        String configuredRunsDir = firstNonBlank(
                System.getProperty("continuum.runsDir"),
                System.getenv("CONTINUUM_RUNS_DIR")
        );

        Path runsRoot = configuredRunsDir == null
                ? Path.of("runs")
                : Path.of(configuredRunsDir.replace('\\', '/'));

        return runsRoot.resolve(runId);
    }

    private static String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return null;
    }

    private static String escapeJson(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
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
        out.println("Usage: ContinuumCli <init|run <scenarioPath>>");
    }
}
