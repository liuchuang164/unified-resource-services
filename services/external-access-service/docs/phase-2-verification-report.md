# External Access Service Phase 2 Verification Report

## Scope

Phase 2 adds production-governance building blocks while preserving the two-layer External
Access Service architecture:

- trusted context resolution from authentication headers with legacy body compatibility;
- HMAC capability-token verification for Agent Tool calls;
- persistent audit repository contract with query APIs;
- usage and cost metering;
- policy and quota governance services;
- credential provider abstraction for secret-source replacement;
- secret and request-body redaction hardening.

## Non-Goals

- No real Alibaba Farui integration call was run.
- No provider other than `ALI_FARUI` was added.
- No distributed rate limiter, complete circuit breaker, Kafka/EventBus, Kubernetes, or frontend
  work was added.

## Persistence

`migrations/002_external_access_governance.sql` defines PostgreSQL tables:

- `external_access_audit`
- `external_usage_record`

The automated test environment uses repository adapters with the same record/query behavior and
does not store sensitive request bodies, capability tokens, authorization headers, signatures, or
provider secrets.

## Real Alibaba Farui Gate

Status: `NOT_RUN`

Reason: Phase 2 explicitly forbids real Alibaba Farui integration. Provider behavior remains
covered through `httpx.MockTransport`.
