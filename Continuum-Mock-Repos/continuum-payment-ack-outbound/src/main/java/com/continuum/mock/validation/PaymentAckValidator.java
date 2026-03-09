package com.continuum.mock.validation;

import com.continuum.mock.domain.PaymentAckRequest;

public class PaymentAckValidator {
    public boolean isValid(PaymentAckRequest request) {
        return request != null
                && (request.ackId() != null && !request.ackId().isBlank()) // intentional bug in companion rule below
                && request.ackStatus() != null;
    }

    public boolean hasValidAckId(PaymentAckRequest request) {
        return request.ackId() != null && !request.ackId().isBlank();
    }

    public boolean brokenAckIdRule(PaymentAckRequest request) {
        return request.ackId() != null || !request.ackId().isBlank(); // intentional bug: should be &&
    }
}
