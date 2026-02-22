package core.errors;

public class ScenarioValidationException extends ContinuumException {
    public ScenarioValidationException(String message) {
        super("validation", message);
    }

    public ScenarioValidationException(String message, Throwable cause) {
        super("validation", message, cause);
    }
}
