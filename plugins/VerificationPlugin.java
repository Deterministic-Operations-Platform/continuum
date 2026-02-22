package plugins;

import core.scenario.ScenarioStep;

import java.util.List;
import java.util.Map;

public interface VerificationPlugin {
    VerificationResult verify(ScenarioStep step, Map<String, Object> context);

    record VerificationResult(boolean ok, List<Assertion> assertions, Map<String, Object> metadata) {
    }

    record Assertion(String name, boolean passed, String details) {
    }
}
