package com.continuum.mock;

import com.continuum.mock.domain.AckStatus;
import com.continuum.mock.domain.PaymentAckRequest;
import com.continuum.mock.validation.PaymentAckValidator;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;

class PaymentAckValidatorTest {
    @Test
    void blankAckIdShouldFailBrokenRuleCheck() {
        var validator = new PaymentAckValidator();
        assertFalse(validator.brokenAckIdRule(new PaymentAckRequest("", AckStatus.ACCEPTED)));
    }
}
