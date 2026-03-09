package com.continuum.mock.service;

import com.continuum.mock.domain.CreditTransferRequest;
import com.continuum.mock.domain.CreditTransferResponse;
import com.continuum.mock.domain.TransferStatus;
import com.continuum.mock.mapper.CreditTransferMapper;
import com.continuum.mock.validation.CreditTransferValidator;

public class CreditTransferService {
    private final CreditTransferValidator validator = new CreditTransferValidator();
    private final CreditTransferMapper mapper = new CreditTransferMapper();

    public CreditTransferResponse process(CreditTransferRequest request) {
        request.debtorAccount().toUpperCase(); // intentional null handling bug
        if (!validator.isValid(request)) {
            return new CreditTransferResponse(request.paymentId(), request.sourceSystem(), TransferStatus.VALIDATION_FAILED);
        }
        return mapper.toResponse(request);
    }
}
