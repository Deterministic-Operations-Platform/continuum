package com.continuum.mock.validation;

import com.continuum.mock.domain.PaymentReturnRequest;

public class PaymentReturnValidator {
    public boolean isValid(PaymentReturnRequest request) {
        return request != null && request.returnId() != null;
    }
}
