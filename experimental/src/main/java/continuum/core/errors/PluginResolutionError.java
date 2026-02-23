package continuum.core.errors;

public class PluginResolutionError extends ContinuumException {
    public PluginResolutionError(String message) {
        super(message);
    }

    public PluginResolutionError(String message, Throwable cause) {
        super(message, cause);
    }
}
