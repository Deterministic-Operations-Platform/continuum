package com.continuum.mock.handler;

public final class HealthHandler {
    private HealthHandler() {}

    public static String health() {
        return "continuum-automation:ok";
    }
}
