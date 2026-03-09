package com.continuum.mock.validation;

import com.continuum.mock.domain.RfpRequest;

public class RfpValidator {
    public boolean isValid(RfpRequest request) {
        return request != null && request.timeoutSeconds() > 0;
    }
}
