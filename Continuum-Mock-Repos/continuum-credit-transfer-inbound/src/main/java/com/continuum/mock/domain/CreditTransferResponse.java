package com.continuum.mock.domain;

public record CreditTransferResponse(String paymentId, String sourceSystem, TransferStatus status) {
}
