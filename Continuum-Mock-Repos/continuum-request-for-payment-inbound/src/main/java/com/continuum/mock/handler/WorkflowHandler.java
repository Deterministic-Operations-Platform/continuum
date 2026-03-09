package com.continuum.mock.handler;

public final class WorkflowHandler {
    private WorkflowHandler() {}

    public static String route(String taskId) {
        return "continuum-request-for-payment-inbound:handled:" + taskId;
    }
}
