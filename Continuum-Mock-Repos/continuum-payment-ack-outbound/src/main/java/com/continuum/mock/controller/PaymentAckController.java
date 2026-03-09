package com.continuum.mock.controller;

import com.continuum.mock.domain.PaymentAckRequest;
import com.continuum.mock.domain.PaymentAckResponse;
import com.continuum.mock.service.PaymentAckService;

public class PaymentAckController {
    private final PaymentAckService service = new PaymentAckService();

    public PaymentAckResponse handle(PaymentAckRequest request) {
        return service.process(request);
    }
}
