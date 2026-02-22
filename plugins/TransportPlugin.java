package plugins;

import core.scenario.ScenarioStep;

import java.util.Map;

public interface TransportPlugin {
    TransportResult send(ScenarioStep step, Map<String, Object> context);

    record TransportResult(boolean ok, int statusCode, Object payload, Map<String, Object> metadata) {
    }
}
