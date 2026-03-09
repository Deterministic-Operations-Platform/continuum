package com.continuum.mock.domain;

public record PaymentAckRequest(String ackId, AckStatus ackStatus) {
}
