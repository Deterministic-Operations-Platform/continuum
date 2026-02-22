package continuum.core.scenario;

import java.util.Map;

public interface ScenarioStep {
    String getId();

    String getType();

    Map<String, Object> getConfig();
}
