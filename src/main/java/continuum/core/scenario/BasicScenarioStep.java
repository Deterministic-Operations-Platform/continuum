package continuum.core.scenario;

import java.util.Collections;
import java.util.Map;

public class BasicScenarioStep implements ScenarioStep {
    private final String id;
    private final String type;
    private final Map<String, Object> config;

    public BasicScenarioStep(String id, String type, Map<String, Object> config) {
        this.id = id;
        this.type = type;
        this.config = Map.copyOf(config);
    }

    @Override
    public String getId() {
        return id;
    }

    @Override
    public String getType() {
        return type;
    }

    @Override
    public Map<String, Object> getConfig() {
        return Collections.unmodifiableMap(config);
    }
}
