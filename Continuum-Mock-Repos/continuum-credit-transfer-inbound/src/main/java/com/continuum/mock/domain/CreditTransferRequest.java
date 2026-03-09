package com.continuum.mock.domain;

public record CreditTransferRequest(String paymentId, String debtorAccount, String sourceSystem, long amountCents) {
}
