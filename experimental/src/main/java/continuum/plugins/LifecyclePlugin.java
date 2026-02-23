package continuum.plugins;

public interface LifecyclePlugin {
    String getName();

    void start();

    boolean healthcheck();

    void stop();
}
