package com.continuum.mock.controller;

import com.continuum.mock.domain.PaymentReturnRequest;
import com.continuum.mock.domain.PaymentReturnResponse;
import com.continuum.mock.service.PaymentReturnService;

public class PaymentReturnController {
    private final PaymentReturnService service = new PaymentReturnService();

    public PaymentReturnResponse handle(PaymentReturnRequest request) {
        return service.process(request);
    }
}
