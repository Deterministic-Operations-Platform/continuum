package evidence.collector;

import core.scenario.Scenario;
import core.scenario.ScenarioStep;

import java.nio.file.Path;
import java.util.Map;

/**
 * Evidence collector contract for immutable run artifacts.
 */
public interface EvidenceCollector {
    void startRun(String runId, Scenario scenario, Path runDirectory);

    void recordStep(String runId, ScenarioStep step, Map<String, Object> event);

    void completeRun(String runId, Map<String, Object> summary);
}
