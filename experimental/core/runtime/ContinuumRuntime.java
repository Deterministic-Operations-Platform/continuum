package core.runtime;

import core.scenario.Scenario;
import evidence.collector.EvidenceCollector;
import evidence.collector.FileEvidenceCollector;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.zip.CRC32;

/**
 * Deterministic runtime shell that emits evidence for every run.
 */
public class ContinuumRuntime {
    private static final String FIXED_TIMESTAMP = "1970-01-01T00:00:00Z";
    private final EvidenceCollector evidenceCollector;

    public ContinuumRuntime() {
        this(new FileEvidenceCollector());
    }

    public ContinuumRuntime(EvidenceCollector evidenceCollector) {
        this.evidenceCollector = Objects.requireNonNull(evidenceCollector, "evidenceCollector");
    }

    public RunSummary run(Path scenarioPath, Path runsRoot) throws IOException {
        Scenario scenario = Scenario.load(scenarioPath);
        String runId = deterministicRunId(scenario, scenarioPath);
        return run(scenario, scenarioPath, runsRoot, runId);
    }

    public RunSummary run(Path scenarioPath, Path runsRoot, String runId) throws IOException {
        Scenario scenario = Scenario.load(scenarioPath);
        return run(scenario, scenarioPath, runsRoot, runId);
    }

    public RunSummary run(Scenario scenario, Path scenarioPath, Path runsRoot, String runId) throws IOException {
        Objects.requireNonNull(scenario, "scenario");
        Objects.requireNonNull(scenarioPath, "scenarioPath");
        Objects.requireNonNull(runsRoot, "runsRoot");
        Objects.requireNonNull(runId, "runId");

        Path normalizedRunsRoot = runsRoot.toAbsolutePath().normalize();
        Files.createDirectories(normalizedRunsRoot);
        Path runDir = normalizedRunsRoot.resolve(runId);
        RunSummary summary = new RunSummary(
                runId,
                scenario.name(),
                scenario.rail(),
                scenarioPath.toString(),
                "passed",
                FIXED_TIMESTAMP,
                FIXED_TIMESTAMP
        );

        try {
            evidenceCollector.startRun(runId, scenario, runDir);
            evidenceCollector.completeRun(runId, summary.toMap());
        } catch (RuntimeException ex) {
            throw new IOException("Unable to create run artifacts in " + runDir, ex);
        }

        return summary;
    }

    private String deterministicRunId(Scenario scenario, Path scenarioPath) {
        String seed = scenario.name() + "|" + scenarioPath.toAbsolutePath().normalize() + "|" + scenario.rawDefinition();
        CRC32 crc = new CRC32();
        crc.update(seed.getBytes(StandardCharsets.UTF_8));
        return "run-" + String.format("%08x", crc.getValue());
    }

    public record RunSummary(
            String runId,
            String scenarioName,
            String rail,
            String scenarioPath,
            String status,
            String startedAt,
            String endedAt
    ) {
        public Map<String, Object> toMap() {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("runId", runId);
            payload.put("scenarioName", scenarioName);
            payload.put("rail", rail);
            payload.put("scenarioPath", scenarioPath);
            payload.put("status", status);
            payload.put("startedAt", startedAt);
            payload.put("endedAt", endedAt);
            return payload;
        }

        public String toJson() {
            return """
                    {
                      "runId": "%s",
                      "scenarioName": "%s",
                      "rail": "%s",
                      "scenarioPath": "%s",
                      "status": "%s",
                      "startedAt": "%s",
                      "endedAt": "%s"
                    }
                    """.formatted(escape(runId), escape(scenarioName), escape(rail), escape(scenarioPath), escape(status), escape(startedAt), escape(endedAt));
        }

        private static String escape(String input) {
            return input.replace("\\", "\\\\").replace("\"", "\\\"");
        }
    }
}
