package core.scenario;

import java.util.Map;

/**
 * Declarative unit of work in a scenario.
 */
public record ScenarioStep(
        String id,
        String name,
        String type,
        String plugin,
        Map<String, Object> input,
        Integer timeoutMs,
        Integer retries
) {
}
