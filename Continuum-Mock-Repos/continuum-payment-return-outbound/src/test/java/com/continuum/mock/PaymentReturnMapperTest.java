package com.continuum.mock;

import com.continuum.mock.domain.PaymentReturnRequest;
import com.continuum.mock.domain.ReturnDecision;
import com.continuum.mock.domain.WorkflowStatus;
import com.continuum.mock.mapper.PaymentReturnMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class PaymentReturnMapperTest {
    @Test
    void mapsRejectToDeclinedStatus() {
        var mapper = new PaymentReturnMapper();
        var response = mapper.toResponse(new PaymentReturnRequest("ret-1", ReturnDecision.REJECT));
        assertEquals(WorkflowStatus.DECLINED, response.workflowStatus());
    }
}
