package core.runtime;

import core.scenario.Scenario;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.UUID;

/**
 * v0.1 runtime shell: load scenario and write deterministic run summary.
 */
public class ContinuumRuntime {

    public RunSummary run(Path scenarioPath, Path runsRoot) throws IOException {
        Scenario scenario = Scenario.load(scenarioPath);
        String runId = UUID.randomUUID().toString();
        Instant startedAt = Instant.now();

        Path runDir = runsRoot.resolve(runId);
        Files.createDirectories(runDir);

        Instant endedAt = Instant.now();
        RunSummary summary = new RunSummary(
                runId,
                scenario.name(),
                scenario.rail(),
                scenarioPath.toString(),
                "passed",
                startedAt.toString(),
                endedAt.toString()
        );

        Files.writeString(runDir.resolve("summary.json"), summary.toJson(), StandardCharsets.UTF_8);
        return summary;
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
