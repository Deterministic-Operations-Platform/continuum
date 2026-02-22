package continuum.core.errors;

public class ContinuumException extends RuntimeException {
    public ContinuumException(String message) {
        super(message);
    }

    public ContinuumException(String message, Throwable cause) {
        super(message, cause);
    }
}
