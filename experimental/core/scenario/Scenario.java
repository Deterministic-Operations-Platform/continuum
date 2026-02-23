package core.scenario;

import core.errors.ScenarioValidationException;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.List;

/**
 * Data contract for scenario-as-data execution.
 */
public record Scenario(
        String name,
        String rail,
        List<ScenarioStep> steps,
        String rawDefinition
) {
    public static Scenario load(Path path) throws IOException {
        if (!Files.exists(path)) {
            throw new ScenarioValidationException("Scenario file does not exist: " + path);
        }

        String raw = Files.readString(path, StandardCharsets.UTF_8);
        String scenarioName = extractScalar(raw, "name", path.getFileName().toString());
        String rail = extractScalar(raw, "rail", "unknown");

        return new Scenario(scenarioName, rail, Collections.emptyList(), raw);
    }

    private static String extractScalar(String source, String key, String fallback) {
        String prefix = key + ":";
        for (String line : source.split("\\R")) {
            String trimmed = line.trim();
            if (trimmed.startsWith(prefix)) {
                String value = trimmed.substring(prefix.length()).trim();
                if (!value.isEmpty()) {
                    return value.replace("\"", "").replace("'", "");
                }
            }
        }
        return fallback;
    }
}
