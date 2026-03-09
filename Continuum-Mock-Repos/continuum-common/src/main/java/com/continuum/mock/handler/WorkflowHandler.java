package com.continuum.mock.handler;

public class WorkflowHandler {
    public String handle(String workItemId) {
        return "WORKFLOW_ACCEPTED:" + workItemId;
    }
}
