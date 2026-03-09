# Intentional Mock Bugs

These defects are intentionally seeded for fix-assist and diff/review workflow testing.

1. **continuum-credit-transfer-inbound**
   - `CreditTransferMapper` maps `sourceSystem` from `debtorAccount` instead of `sourceSystem` (wrong field mapping).
   - `CreditTransferService` dereferences nullable `debtorAccount` without null guard (null handling bug).
2. **continuum-payment-return-outbound**
   - `PaymentReturnMapper` maps `ReturnDecision.REJECT` to `WorkflowStatus.ACCEPTED` (incorrect enum/status mapping).
3. **continuum-request-for-payment-inbound**
   - `RequestForPaymentService` ignores configured timeout and hard-codes `PT30S` (missing config usage).
4. **continuum-payment-ack-outbound**
   - `PaymentAckValidator` allows blank `ackId` because the condition uses `&&` instead of `||` (broken validation rule).
5. **continuum-payment-ack-outbound test**
   - `PaymentAckMapperTest` intentionally expects a success code for rejected acknowledgements (failing test expectation).
