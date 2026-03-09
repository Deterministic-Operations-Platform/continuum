package com.continuum.mock.controller;

import com.continuum.mock.domain.CreditTransferRequest;
import com.continuum.mock.domain.CreditTransferResponse;
import com.continuum.mock.service.CreditTransferService;

public class CreditTransferHandler {
    private final CreditTransferService service = new CreditTransferService();

    public CreditTransferResponse handle(CreditTransferRequest request) {
        return service.process(request);
    }
}
