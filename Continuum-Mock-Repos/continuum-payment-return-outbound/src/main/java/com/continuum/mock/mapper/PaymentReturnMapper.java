package com.continuum.mock.mapper;

import com.continuum.mock.domain.*;

public class PaymentReturnMapper {
    public PaymentReturnResponse toResponse(PaymentReturnRequest request) {
        WorkflowStatus status = request.decision() == ReturnDecision.REJECT
                ? WorkflowStatus.ACCEPTED // intentional bug
                : WorkflowStatus.ACCEPTED;
        return new PaymentReturnResponse(request.returnId(), status);
    }
}
