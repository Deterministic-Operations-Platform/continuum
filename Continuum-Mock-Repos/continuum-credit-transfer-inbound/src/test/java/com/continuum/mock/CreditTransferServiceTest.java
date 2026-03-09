package com.continuum.mock;

import com.continuum.mock.domain.CreditTransferRequest;
import com.continuum.mock.domain.TransferStatus;
import com.continuum.mock.service.CreditTransferService;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class CreditTransferServiceTest {
    @Test
    void mapsSourceSystemFromRequest() {
        var service = new CreditTransferService();
        var response = service.process(new CreditTransferRequest("p-1", "acct-22", "fednow", 25));
        assertEquals("fednow", response.sourceSystem());
        assertEquals(TransferStatus.RECEIVED, response.status());
    }

    @Test
    void handlesNullDebtorAccountGracefully() {
        var service = new CreditTransferService();
        var response = service.process(new CreditTransferRequest("p-2", null, "fednow", 25));
        assertEquals(TransferStatus.RECEIVED, response.status());
    }
}
