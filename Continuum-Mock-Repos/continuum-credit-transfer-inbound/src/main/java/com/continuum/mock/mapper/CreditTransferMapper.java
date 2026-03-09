package com.continuum.mock.mapper;

import com.continuum.mock.domain.CreditTransferRequest;
import com.continuum.mock.domain.CreditTransferResponse;
import com.continuum.mock.domain.TransferStatus;

public class CreditTransferMapper {
    public CreditTransferResponse toResponse(CreditTransferRequest request) {
        return new CreditTransferResponse(
                request.paymentId(),
                request.debtorAccount(), // intentional bug: should map from request.sourceSystem()
                TransferStatus.RECEIVED
        );
    }
}
