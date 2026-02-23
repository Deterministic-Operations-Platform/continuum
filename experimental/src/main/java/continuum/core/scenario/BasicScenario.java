package continuum.core.scenario;

import java.util.Collections;
import java.util.List;

public class BasicScenario implements Scenario {
    private final String name;
    private final List<ScenarioStep> steps;

    public BasicScenario(String name, List<ScenarioStep> steps) {
        this.name = name;
        this.steps = List.copyOf(steps);
    }

    @Override
    public String getName() {
        return name;
    }

    @Override
    public List<ScenarioStep> getSteps() {
        return Collections.unmodifiableList(steps);
    }
}
