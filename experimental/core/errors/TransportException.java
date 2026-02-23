package core.errors;

public class TransportException extends ContinuumException {
    public TransportException(String message) {
        super("transport", message);
    }

    public TransportException(String message, Throwable cause) {
        super("transport", message, cause);
    }
}
