package com.continuum.mock.handler;

public final class WorkflowHandler {
    private WorkflowHandler() {}

    public static String route(String taskId) {
        return "continuum-common:handled:" + taskId;
    }
}
