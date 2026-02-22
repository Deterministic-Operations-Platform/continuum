package continuum.core.errors;

public class ScenarioValidationError extends ContinuumException {
    public ScenarioValidationError(String message) {
        super(message);
    }

    public ScenarioValidationError(String message, Throwable cause) {
        super(message, cause);
    }
}
