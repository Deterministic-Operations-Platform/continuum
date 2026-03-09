package com.continuum.mock.validation;

import com.continuum.mock.domain.CreditTransferRequest;

public class CreditTransferValidator {
    public boolean isValid(CreditTransferRequest request) {
        return request != null && request.paymentId() != null && request.amountCents() > 0;
    }
}
