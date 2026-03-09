package com.continuum.mock;

import com.continuum.mock.handler.HealthHandler;
import com.continuum.mock.handler.WorkflowHandler;

public class Main {
    public static void main(String[] args) {
        String serviceName = "continuum-credit-transfer-inbound";
        System.out.println("Starting mock service: " + serviceName);
        System.out.println(new HealthHandler(serviceName).handle());
        System.out.println(new WorkflowHandler().handle("sample-work-item"));
    }
}
