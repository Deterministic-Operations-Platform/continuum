package com.continuum.mock;

import com.continuum.mock.handler.HealthHandler;
import com.continuum.mock.handler.WorkflowHandler;

public class Main {
    public static void main(String[] args) {
        System.out.println("[continuum-common] startup");
        System.out.println(HealthHandler.health());
        System.out.println(WorkflowHandler.route("sample-task"));
    }
}
