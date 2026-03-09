package com.continuum.mock.controller;

import com.continuum.mock.domain.RfpRequest;
import com.continuum.mock.domain.RfpResponse;
import com.continuum.mock.service.RequestForPaymentService;

public class RequestForPaymentHandler {
    private final RequestForPaymentService service = new RequestForPaymentService();

    public RfpResponse handle(RfpRequest request) {
        return service.process(request);
    }
}
