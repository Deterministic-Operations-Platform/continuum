package com.continuum.mock;

import com.continuum.mock.domain.RfpRequest;
import com.continuum.mock.service.RequestForPaymentService;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class RequestForPaymentServiceTest {
    @Test
    void usesRequestTimeoutWhenBuildingResponse() {
        var service = new RequestForPaymentService();
        var response = service.process(new RfpRequest("rfp-1", 10));
        assertEquals("PT10S", response.effectiveTimeout());
    }
}
