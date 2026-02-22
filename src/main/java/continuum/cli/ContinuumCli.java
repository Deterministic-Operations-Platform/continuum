package continuum.cli;

import continuum.core.scenario.Scenario;
import continuum.core.scenario.ScenarioLoader;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
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
    }

    public static void main(String[] args) {
        if (args.length == 0) {
            printUsage();
            return;
        }

        String command = args[0];
        switch (command) {
            case "init" -> handleInit();
            case "run" -> handleRun(args);
            default -> printUsage();
        }
    }

    private static void handleInit() {
        System.out.println("Continuum initialized");
    }

    private static void handleRun(String[] args) {
        if (args.length < 2) {
            System.err.println("Missing scenario path");
            printUsage();
            return;
        }

        Path scenarioPath = Path.of(args[1]);
        ScenarioLoader loader = scenarioLoaderFactory.get();
        Scenario scenario = loader.load(scenarioPath);

        String runId = buildRunId();
        Path runDirectory = resolveRunDirectory(runId);
        try {
            Files.createDirectories(runDirectory);
            Files.copy(scenarioPath, runDirectory.resolve("scenario.yaml"), StandardCopyOption.REPLACE_EXISTING);

            String summaryJson = """
                    {
                      \"runId\": \"%s\",
                      \"scenarioName\": \"%s\",
                      \"status\": \"STARTED\"
                    }
                    """.formatted(escapeJson(runId), escapeJson(scenario.getName()));
            Files.writeString(runDirectory.resolve("summary.json"), summaryJson, StandardCharsets.UTF_8);
            Files.writeString(runDirectory.resolve("events.jsonl"), "", StandardCharsets.UTF_8);

            System.out.println("Scenario: " + scenario.getName());
            System.out.println("Run directory: " + runDirectory);
        } catch (IOException e) {
            throw new RuntimeException("Failed to initialize run directory", e);
        }
    }

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

    private static void printUsage() {
        System.out.println("Usage: ContinuumCli <init|run <scenarioPath>>");
    }
}
