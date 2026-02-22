package core.errors;

public class LifecycleException extends ContinuumException {
    public LifecycleException(String message) {
        super("lifecycle", message);
    }

    public LifecycleException(String message, Throwable cause) {
        super("lifecycle", message, cause);
    }
}
