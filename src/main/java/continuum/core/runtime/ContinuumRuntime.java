package continuum.core.runtime;

import continuum.core.errors.ContinuumException;
import continuum.core.scenario.Scenario;

public interface ContinuumRuntime {
    void runScenario(Scenario scenario) throws ContinuumException;
}
