package com.continuum.mock.mapper;

import com.continuum.mock.domain.AckStatus;
import com.continuum.mock.domain.PaymentAckRequest;
import com.continuum.mock.domain.PaymentAckResponse;

public class PaymentAckMapper {
    public PaymentAckResponse toResponse(PaymentAckRequest request) {
        String code = request.ackStatus() == AckStatus.ACCEPTED ? "ACK_OK" : "ACK_REJECT";
        return new PaymentAckResponse(request.ackId(), code);
    }
}
