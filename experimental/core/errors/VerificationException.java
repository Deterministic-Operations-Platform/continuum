package core.errors;

public class VerificationException extends ContinuumException {
    public VerificationException(String message) {
        super("verification", message);
    }

    public VerificationException(String message, Throwable cause) {
        super("verification", message, cause);
    }
}
