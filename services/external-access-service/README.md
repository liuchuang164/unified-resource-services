# External Access Service

Provider-neutral service for tenant-scoped third-party API access. Phase 1 enables only
Alibaba Farui through the `ALI_FARUI` provider adapter.

## Scope And Non-Goals

Scope:

- `/eag/*` Agent Tool entry contracts and execution conversion.
- `/external/*` unified external entry contracts and dispatch.
- `ALI_FARUI` provider adapter behind an `ExternalProviderPort`.
- Mock transport coverage for automated tests.

Non-goals:

- No other provider implementation.
- No frontend.
- No direct Agent-to-provider calls.
- No checked-in real provider credentials.

## Local Verification

```bash
cd services/external-access-service
python3 -m pytest
```

Real Alibaba Farui integration is gated by environment variables and is not run by default.
