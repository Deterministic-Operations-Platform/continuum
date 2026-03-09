package com.continuum.mock.service;

import com.continuum.mock.domain.RfpRequest;
import com.continuum.mock.domain.RfpResponse;
import com.continuum.mock.mapper.RfpMapper;
import com.continuum.mock.validation.RfpValidator;

public class RequestForPaymentService {
    private final RfpValidator validator = new RfpValidator();
    private final RfpMapper mapper = new RfpMapper();

    public RfpResponse process(RfpRequest request) {
        if (!validator.isValid(request)) {
            throw new IllegalArgumentException("Invalid RFP request");
        }
        String configuredTimeout = "PT30S"; // intentional bug: ignores request.timeoutSeconds
        return mapper.toResponse(request, configuredTimeout);
    }
}
