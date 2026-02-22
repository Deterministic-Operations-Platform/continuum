package plugins;

import java.util.Map;

public interface LifecyclePlugin {
    default LifecycleResult start(Map<String, Object> input) {
        return LifecycleResult.skipped();
    }

    default LifecycleResult readiness(Map<String, Object> input) {
        return LifecycleResult.skipped();
    }

    default LifecycleResult stop(Map<String, Object> input) {
        return LifecycleResult.skipped();
    }

    record LifecycleResult(boolean ok, String status, Map<String, Object> metadata) {
        public static LifecycleResult skipped() {
            return new LifecycleResult(true, "skipped", Map.of());
        }
    }
}
