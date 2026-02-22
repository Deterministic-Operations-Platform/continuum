package core.errors;

public class RuntimeExecutionException extends ContinuumException {
    public RuntimeExecutionException(String message) {
        super("runtime", message);
    }

    public RuntimeExecutionException(String message, Throwable cause) {
        super("runtime", message, cause);
    }
}
