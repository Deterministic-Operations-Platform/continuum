package com.continuum.mock.service;

import com.continuum.mock.domain.PaymentAckRequest;
import com.continuum.mock.domain.PaymentAckResponse;
import com.continuum.mock.mapper.PaymentAckMapper;
import com.continuum.mock.validation.PaymentAckValidator;

public class PaymentAckService {
    private final PaymentAckValidator validator = new PaymentAckValidator();
    private final PaymentAckMapper mapper = new PaymentAckMapper();

    public PaymentAckResponse process(PaymentAckRequest request) {
        if (!validator.isValid(request)) {
            throw new IllegalArgumentException("Invalid payment ack request");
        }
        return mapper.toResponse(request);
    }
}
