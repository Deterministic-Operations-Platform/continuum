package com.continuum.mock.mapper;

import com.continuum.mock.domain.RfpRequest;
import com.continuum.mock.domain.RfpResponse;

public class RfpMapper {
    public RfpResponse toResponse(RfpRequest request, String timeout) {
        return new RfpResponse(request.requestId(), timeout);
    }
}
