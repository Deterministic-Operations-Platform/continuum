package com.continuum.mock.handler;

public class HealthHandler {
    private final String serviceName;

    public HealthHandler(String serviceName) {
        this.serviceName = serviceName;
    }

    public String handle() {
        return "HEALTHY:" + serviceName;
    }
}
