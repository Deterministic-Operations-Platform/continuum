package continuum.core.scenario;

import java.util.List;

public interface Scenario {
    String getName();

    List<ScenarioStep> getSteps();
}
