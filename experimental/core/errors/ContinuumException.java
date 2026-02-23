package core.errors;

/**
 * Base exception for Continuum runtime failures.
 */
public class ContinuumException extends RuntimeException {
    private final String code;

    public ContinuumException(String code, String message) {
        super(message);
        this.code = code;
    }

    public ContinuumException(String code, String message, Throwable cause) {
        super(message, cause);
        this.code = code;
    }

    public String code() {
        return code;
    }
}
