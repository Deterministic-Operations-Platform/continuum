package continuum.plugins;

import java.util.Map;

public interface TransportPlugin {
    String getName();

    Map<String, Object> send(Map<String, Object> request);
}
