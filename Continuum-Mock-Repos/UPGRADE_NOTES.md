# Continuum Mock Repos Upgrade Notes

## Repos with realistic domain flow classes
- `continuum-credit-transfer-inbound`
- `continuum-payment-return-outbound`
- `continuum-request-for-payment-inbound`
- `continuum-payment-ack-outbound`

Each of the above now includes a lightweight request/response model, mapper, validator, service, and handler/controller layer to better simulate enterprise event processing.

## Repos with intentional mock bugs
- `continuum-credit-transfer-inbound`
  - Wrong field mapping in `CreditTransferMapper`.
  - Null handling bug in `CreditTransferService`.
- `continuum-payment-return-outbound`
  - Incorrect enum/status mapping in `PaymentReturnMapper`.
- `continuum-request-for-payment-inbound`
  - Missing config usage in `RequestForPaymentService`.
- `continuum-payment-ack-outbound`
  - Broken validation rule in `PaymentAckValidator`.
  - Failing test expectation in `PaymentAckMapperTest`.

## Metadata format for task-to-repo mapping
All 15 repos now include `repo-metadata.yaml` with:
- repo
- domain
- event_type
- direction
- jira_labels
- keywords
- dependencies
- workflow_tags

## Mixed repo state simulation
- Workspace markers: `repo-states/*.state`
- Helper script: `tools/describe-repo-state.sh`
- Simulated states include `clean`, `dirty`, `behind`, `diverged`, and `misconfigured`.
