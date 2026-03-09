package com.continuum.mock.service;

import com.continuum.mock.domain.PaymentReturnRequest;
import com.continuum.mock.domain.PaymentReturnResponse;
import com.continuum.mock.mapper.PaymentReturnMapper;
import com.continuum.mock.validation.PaymentReturnValidator;

public class PaymentReturnService {
    private final PaymentReturnValidator validator = new PaymentReturnValidator();
    private final PaymentReturnMapper mapper = new PaymentReturnMapper();

    public PaymentReturnResponse process(PaymentReturnRequest request) {
        if (!validator.isValid(request)) {
            throw new IllegalArgumentException("Invalid return request");
        }
        return mapper.toResponse(request);
    }
}
