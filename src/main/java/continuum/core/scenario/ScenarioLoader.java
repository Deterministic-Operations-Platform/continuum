package continuum.core.scenario;

import continuum.core.errors.ScenarioValidationError;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

public class ScenarioLoader {
    private final SimpleYamlParser yamlParser;

    public ScenarioLoader() {
        this.yamlParser = new SimpleYamlParser();
    }

    public Scenario load(Path scenarioPath) {
        try {
            String content = Files.readString(scenarioPath, StandardCharsets.UTF_8);
            Map<String, Object> data = yamlParser.parse(content);

            String name = asString(data.get("name"));
            if (name == null || name.isBlank()) {
                throw new ScenarioValidationError("Scenario name is required");
            }

            List<ScenarioStep> steps = new ArrayList<>();
            Object stepsRaw = data.get("steps");
            if (stepsRaw instanceof List<?> list) {
                for (int i = 0; i < list.size(); i++) {
                    Object item = list.get(i);
                    if (!(item instanceof Map<?, ?> stepMap)) {
                        throw new ScenarioValidationError("Invalid step format at index " + i);
                    }

                    String id = asString(stepMap.get("id"));
                    String type = asString(stepMap.get("type"));
                    if (id == null || id.isBlank()) {
                        id = "step-" + (i + 1);
                    }
                    if (type == null || type.isBlank()) {
                        type = "unknown";
                    }

                    steps.add(new BasicScenarioStep(id, type, Map.of()));
                }
            }

            return new BasicScenario(name, steps);
        } catch (IOException e) {
            throw new ScenarioValidationError("Unable to load scenario from " + scenarioPath, e);
        }
    }

    private String asString(Object value) {
        return value == null ? null : String.valueOf(value);
    }
}
