package continuum.plugins;

import java.util.Map;

public interface VerificationPlugin {
    String getName();

    boolean verify(Map<String, Object> context);
}
