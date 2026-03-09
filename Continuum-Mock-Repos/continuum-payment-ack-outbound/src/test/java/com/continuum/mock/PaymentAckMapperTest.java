package com.continuum.mock;

import com.continuum.mock.domain.AckStatus;
import com.continuum.mock.domain.PaymentAckRequest;
import com.continuum.mock.mapper.PaymentAckMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class PaymentAckMapperTest {
    @Test
    void rejectedAckStillReturnsAckOkCode() {
        var mapper = new PaymentAckMapper();
        var response = mapper.toResponse(new PaymentAckRequest("ack-1", AckStatus.REJECTED));
        assertEquals("ACK_OK", response.code()); // intentional failing expectation
    }
}
